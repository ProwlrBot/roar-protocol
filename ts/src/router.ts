/**
 * ROAR Protocol — HTTP router adding SSE, WebSocket, and rate-limited message
 * handling to an existing http.Server or ROARServer.
 *
 * Mirrors python/src/roar_sdk/router.py.
 * Uses Node.js 18+ built-ins only — no external dependencies.
 *
 * Usage:
 *   const router = createROARRouter(roarServer, { rateLimit: 20 });
 *   router.attach(httpServer);  // before httpServer.listen()
 */

import * as http from "http";
import * as net from "net";
import * as crypto from "crypto";
import { ROARServer } from "./server.js";
import { StreamEventType } from "./types.js";
import { messageFromWire, messageToWire } from "./types.js";
import { IdempotencyGuard } from "./dedup.js";

// ---------------------------------------------------------------------------
// TokenBucket — sliding-window rate limiter
// ---------------------------------------------------------------------------

class TokenBucket {
  private _tokens: number;
  private _lastRefill: number;

  /**
   * @param capacity   max burst (tokens)
   * @param refillRate tokens per second (same as capacity for a 1-second window)
   */
  constructor(
    private readonly _capacity: number,
    private readonly _refillRate: number,
  ) {
    this._tokens = _capacity;
    this._lastRefill = Date.now() / 1000;
  }

  /** Attempt to consume one token. Returns false if the bucket is empty. */
  consume(): boolean {
    const now = Date.now() / 1000;
    const elapsed = now - this._lastRefill;
    this._tokens = Math.min(
      this._capacity,
      this._tokens + elapsed * this._refillRate,
    );
    this._lastRefill = now;
    if (this._tokens < 1) return false;
    this._tokens -= 1;
    return true;
  }
}

// ---------------------------------------------------------------------------
// Server-side WebSocket helpers (send UNMASKED frames — RFC 6455 §5.1)
// ---------------------------------------------------------------------------

function wsSendText(socket: net.Socket, text: string): void {
  const payload = Buffer.from(text, "utf-8");
  const len = payload.length;

  let header: Buffer;
  if (len < 126) {
    header = Buffer.alloc(2);
    header[0] = 0x81; // FIN + text opcode
    header[1] = len;  // no MASK bit
  } else if (len < 65536) {
    header = Buffer.alloc(4);
    header[0] = 0x81;
    header[1] = 126;
    header.writeUInt16BE(len, 2);
  } else {
    header = Buffer.alloc(10);
    header[0] = 0x81;
    header[1] = 127;
    header.writeUInt32BE(0, 2);
    header.writeUInt32BE(len, 6);
  }
  socket.write(Buffer.concat([header, payload]));
}

function wsSendClose(socket: net.Socket): void {
  const frame = Buffer.alloc(2);
  frame[0] = 0x88; // FIN + close opcode
  frame[1] = 0x00;
  try { socket.write(frame); } catch { /* ignore */ }
  socket.destroy();
}

/** Maximum WebSocket payload we accept (1 MiB). Prevents memory exhaustion DoS. */
const MAX_WS_PAYLOAD = 1 * 1024 * 1024;

/** Parse complete frames from a buffer. Returns [parsedFrames, remainder]. */
function parseWsFrames(buf: Buffer): [string[], Buffer] {
  const texts: string[] = [];
  let offset = 0;

  while (offset + 2 <= buf.length) {
    const b0 = buf[offset];
    const b1 = buf[offset + 1];

    const opcode = b0 & 0x0f;
    const masked = (b1 & 0x80) !== 0;
    let payloadLen = b1 & 0x7f;
    let hdrEnd = offset + 2;

    if (payloadLen === 126) {
      if (buf.length < hdrEnd + 2) break;
      payloadLen = buf.readUInt16BE(hdrEnd);
      hdrEnd += 2;
    } else if (payloadLen === 127) {
      if (buf.length < hdrEnd + 8) break;
      // RFC 6455: high 32 bits must be zero. Non-zero = frame >4 GB, reject.
      const high = buf.readUInt32BE(hdrEnd);
      if (high !== 0) {
        texts.push("\x00CLOSE");
        break;
      }
      payloadLen = buf.readUInt32BE(hdrEnd + 4);
      hdrEnd += 8;
    }

    // Reject oversized frames before allocating any buffer for them.
    if (payloadLen > MAX_WS_PAYLOAD) {
      texts.push("\x00CLOSE");
      break;
    }

    const maskLen = masked ? 4 : 0;
    const frameEnd = hdrEnd + maskLen + payloadLen;
    if (buf.length < frameEnd) break;

    let payload = buf.slice(hdrEnd + maskLen, frameEnd);
    if (masked) {
      const mask = buf.slice(hdrEnd, hdrEnd + 4);
      payload = Buffer.from(payload);
      for (let i = 0; i < payload.length; i++) {
        payload[i] ^= mask[i % 4];
      }
    }

    offset = frameEnd;

    if (opcode === 0x1 || opcode === 0x2) {
      // Text or binary — ROAR JSON
      texts.push(payload.toString("utf-8"));
    } else if (opcode === 0x8) {
      // Close frame — signal with sentinel
      texts.push("\x00CLOSE");
      break;
    }
    // Ping (0x9) / pong (0xA) ignored
  }

  return [texts, buf.slice(offset)];
}

// ---------------------------------------------------------------------------
// ROARRouter public interface
// ---------------------------------------------------------------------------

export interface ROARRouterOptions {
  /** Max requests per second per source IP. 0 = unlimited (default). */
  rateLimit?: number;
  /** Bearer token required in Authorization header or WS auth frame. Empty = no auth. */
  authToken?: string;
  /** Maximum simultaneous SSE connections. Default 100. */
  maxSseConnections?: number;
  /**
   * Trust X-Forwarded-For header for rate-limit IP bucketing.
   * Only enable when running behind a trusted reverse proxy (nginx, fly.io, etc.).
   * Default false — uses socket.remoteAddress, which cannot be spoofed.
   */
  trustProxy?: boolean;
}

export interface ROARRouter {
  /**
   * Handle an HTTP request. Returns true if the path was handled, false if
   * the caller should try its own routes.
   */
  handleRequest(req: http.IncomingMessage, res: http.ServerResponse): boolean;
  /**
   * Handle a WebSocket upgrade (pass from http.Server 'upgrade' event).
   * Returns true if the upgrade was accepted.
   */
  handleUpgrade(req: http.IncomingMessage, socket: net.Socket, head: Buffer): boolean;
  /**
   * Convenience: attach request + upgrade listeners to an existing http.Server.
   * Call before server.listen().
   */
  attach(httpServer: http.Server): void;
}

// ---------------------------------------------------------------------------
// createROARRouter
// ---------------------------------------------------------------------------

export function createROARRouter(
  server: ROARServer,
  opts: ROARRouterOptions = {},
): ROARRouter {
  const rateLimit = opts.rateLimit ?? 0;
  const authToken = opts.authToken ?? "";
  const maxSse = opts.maxSseConnections ?? 100;
  const trustProxy = opts.trustProxy ?? false;

  // Per-IP token buckets (rate limiter)
  const _buckets = new Map<string, TokenBucket>();
  // Replay guard
  const _dedup = new IdempotencyGuard();
  // Active SSE connection count
  let _sseCount = 0;

  function _getIp(req: http.IncomingMessage): string {
    if (trustProxy) {
      const forwarded = req.headers["x-forwarded-for"];
      if (typeof forwarded === "string") return forwarded.split(",")[0].trim();
    }
    return req.socket?.remoteAddress ?? "unknown";
  }

  function _checkRate(ip: string): boolean {
    if (rateLimit <= 0) return true;
    let bucket = _buckets.get(ip);
    if (!bucket) {
      bucket = new TokenBucket(rateLimit, rateLimit);
      _buckets.set(ip, bucket);
    }
    return bucket.consume();
  }

  function _checkAuth(req: http.IncomingMessage): boolean {
    if (!authToken) return true;
    const authHeader = req.headers["authorization"] ?? "";
    const expected = `Bearer ${authToken}`;
    // Use timingSafeEqual to prevent timing oracle attacks on the secret token.
    // Pad/truncate both sides to the same length so the comparison is always
    // constant-time regardless of prefix match length.
    try {
      const a = Buffer.from(authHeader);
      const b = Buffer.from(expected);
      if (a.length !== b.length) return false;
      return crypto.timingSafeEqual(a, b);
    } catch {
      return false;
    }
  }

  // ── HTTP request handler ──────────────────────────────────────────────────

  function handleRequest(
    req: http.IncomingMessage,
    res: http.ServerResponse,
  ): boolean {
    const url = req.url ?? "/";
    const ip = _getIp(req);

    // GET /roar/health
    if (req.method === "GET" && url === "/roar/health") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ status: "ok", protocol: "roar/1.0" }));
      return true;
    }

    // GET /roar/events — Server-Sent Events
    if (req.method === "GET" && url.startsWith("/roar/events")) {
      if (!_checkAuth(req)) {
        res.writeHead(401, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "unauthorized" }));
        return true;
      }
      if (_sseCount >= maxSse) {
        res.writeHead(503, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "too_many_connections" }));
        return true;
      }

      // Parse optional filter query params
      const qIdx = url.indexOf("?");
      const params = qIdx >= 0
        ? new URLSearchParams(url.slice(qIdx + 1))
        : new URLSearchParams();

      const sessionId = params.get("session_id") ?? undefined;
      const eventType = params.get("event_type") ?? undefined;
      const sourceDid = params.get("source_did") ?? undefined;

      res.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
      });
      res.flushHeaders?.();

      // Subscribe to the server's event bus
      const filterSpec: Record<string, string[]> = {};
      if (sessionId) filterSpec.session_ids = [sessionId];
      if (eventType) filterSpec.event_types = [eventType as StreamEventType];
      if (sourceDid) filterSpec.source_dids = [sourceDid];

      _sseCount++;
      const sub = server.eventBus.subscribe(
        Object.keys(filterSpec).length > 0 ? filterSpec : undefined,
      );

      // Push events to client
      (async () => {
        for await (const event of sub) {
          if (res.destroyed) break;
          try {
            res.write(`data: ${JSON.stringify(event)}\n\n`);
          } catch {
            break;
          }
        }
      })().catch(() => {});

      req.on("close", () => {
        sub.close();
        _sseCount--;
      });

      return true;
    }

    // POST /roar/message
    if (req.method === "POST" && url === "/roar/message") {
      if (!_checkAuth(req)) {
        res.writeHead(401, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "unauthorized" }));
        return true;
      }
      if (!_checkRate(ip)) {
        res.writeHead(429, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "rate_limit_exceeded" }));
        return true;
      }

      let body = "";
      req.on("data", (chunk: Buffer | string) => (body += chunk.toString()));
      req.on("end", async () => {
        try {
          const raw = JSON.parse(body) as Record<string, unknown>;
          const msg = messageFromWire(raw);

          if (_dedup.is_duplicate(msg.id)) {
            res.writeHead(409, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ error: "duplicate_message_id" }));
            return;
          }

          const response = await server.handleMessage(msg);
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify(messageToWire(response)));
        } catch (err) {
          res.writeHead(400, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: "invalid_message", detail: String(err) }));
        }
      });
      return true;
    }

    return false; // not our route
  }

  // ── WebSocket upgrade handler ─────────────────────────────────────────────

  function handleUpgrade(
    req: http.IncomingMessage,
    socket: net.Socket,
    _head: Buffer,
  ): boolean {
    if (req.url !== "/roar/ws") return false;

    // RFC 6455 handshake
    const wsKey = req.headers["sec-websocket-key"];
    if (!wsKey) {
      socket.destroy();
      return true;
    }
    const acceptKey = crypto
      .createHash("sha1")
      .update(wsKey + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")
      .digest("base64");

    socket.write(
      "HTTP/1.1 101 Switching Protocols\r\n" +
        "Upgrade: websocket\r\n" +
        "Connection: Upgrade\r\n" +
        `Sec-WebSocket-Accept: ${acceptKey}\r\n` +
        "\r\n",
    );

    let rxBuf: Buffer = Buffer.alloc(0);
    let authenticated = !authToken; // if no token required, already auth'd
    const ip = _getIp(req);

    socket.on("data", async (chunk: Buffer | string) => {
      rxBuf = Buffer.concat([rxBuf, Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)]);
      const [frames, remaining] = parseWsFrames(rxBuf);
      rxBuf = remaining;

      for (const text of frames) {
        if (text === "\x00CLOSE") {
          wsSendClose(socket);
          return;
        }

        let raw: Record<string, unknown>;
        try {
          raw = JSON.parse(text) as Record<string, unknown>;
        } catch {
          continue; // non-JSON — ignore
        }

        // Auth frame: {"type": "auth", "token": "..."}
        if (!authenticated) {
          // Use timingSafeEqual to prevent timing oracle attacks on the secret.
          const supplied = typeof raw["token"] === "string" ? raw["token"] as string : "";
          let tokenMatch = false;
          try {
            const a = Buffer.from(supplied);
            const b = Buffer.from(authToken);
            tokenMatch = a.length === b.length && crypto.timingSafeEqual(a, b);
          } catch {
            tokenMatch = false;
          }
          if (raw["type"] === "auth" && tokenMatch) {
            authenticated = true;
            wsSendText(socket, JSON.stringify({ type: "auth_ok" }));
          } else {
            wsSendText(socket, JSON.stringify({ type: "error", message: "unauthorized" }));
            wsSendClose(socket);
          }
          return;
        }

        // Rate limit
        if (!_checkRate(ip)) {
          wsSendText(socket, JSON.stringify({ type: "error", message: "rate_limit_exceeded" }));
          continue;
        }

        // Parse ROAR message
        if (!raw["intent"]) continue; // not a ROAR message (e.g. ping frame)

        try {
          const msg = messageFromWire(raw);

          // Replay protection
          if (_dedup.is_duplicate(msg.id)) {
            wsSendText(socket, JSON.stringify({ type: "error", message: "duplicate_message_id" }));
            continue;
          }

          const response = await server.handleMessage(msg);
          wsSendText(socket, JSON.stringify(messageToWire(response)));
        } catch (err) {
          wsSendText(socket, JSON.stringify({ type: "error", message: String(err) }));
        }
      }
    });

    socket.on("error", () => socket.destroy());

    return true;
  }

  // ── attach convenience ────────────────────────────────────────────────────

  function attach(httpServer: http.Server): void {
    httpServer.on("request", (req, res) => handleRequest(req, res));
    httpServer.on("upgrade", (req, socket, head) =>
      handleUpgrade(req, socket as net.Socket, head),
    );
  }

  return { handleRequest, handleUpgrade, attach };
}

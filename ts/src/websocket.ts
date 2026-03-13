/**
 * ROAR Protocol — WebSocket transport for bidirectional agent communication.
 *
 * Mirrors Python's roar_sdk/transports/websocket.py.
 * Uses Node.js built-in `net` + HTTP upgrade — no external dependencies.
 *
 * Usage:
 *   const ws = await ROARWebSocket.connect("ws://localhost:8089");
 *   ws.onMessage((msg) => console.log(msg.intent));
 *   await ws.send(myMessage);
 *   ws.close();
 */

import * as http from "http";
import * as https from "https";
import * as net from "net";
import * as crypto from "crypto";
import { ROARMessage, messageFromWire, messageToWire } from "./types.js";

type MessageHandler = (msg: ROARMessage) => void | Promise<void>;
type ErrorHandler = (err: Error) => void;
type CloseHandler = () => void;

export class ROARWebSocket {
  private _socket: net.Socket;
  private _messageHandlers: MessageHandler[] = [];
  private _errorHandlers: ErrorHandler[] = [];
  private _closeHandlers: CloseHandler[] = [];
  private _buffer: Buffer = Buffer.alloc(0);
  private _closed = false;

  private constructor(socket: net.Socket) {
    this._socket = socket;
    socket.on("data", (chunk: Buffer | string) => this._onData(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)));
    socket.on("close", () => {
      this._closed = true;
      this._closeHandlers.forEach((h) => h());
    });
    socket.on("error", (err) => {
      this._errorHandlers.forEach((h) => h(err));
    });
  }

  /**
   * Open a WebSocket connection to a ROAR server.
   *
   * @param url   WebSocket URL — ws:// or wss://
   * @param opts  Optional auth token (sent as first frame if provided)
   */
  static async connect(
    url: string,
    opts: { authToken?: string; timeoutMs?: number } = {},
  ): Promise<ROARWebSocket> {
    const parsed = new URL(url);
    const isSecure = parsed.protocol === "wss:";
    const port = parsed.port
      ? parseInt(parsed.port)
      : isSecure
        ? 443
        : 80;
    const host = parsed.hostname;
    const path = parsed.pathname || "/";

    // WebSocket handshake key
    const key = crypto.randomBytes(16).toString("base64");

    return new Promise((resolve, reject) => {
      const timeout = opts.timeoutMs ?? 10000;
      const transport = isSecure ? https : http;

      const req = transport.request({
        hostname: host,
        port,
        path,
        method: "GET",
        headers: {
          "Upgrade": "websocket",
          "Connection": "Upgrade",
          "Sec-WebSocket-Key": key,
          "Sec-WebSocket-Version": "13",
        },
      });

      const timer = setTimeout(() => {
        req.destroy(new Error(`WebSocket connect to ${url} timed out`));
      }, timeout);

      req.on("upgrade", (res, socket) => {
        clearTimeout(timer);

        // Validate server's Sec-WebSocket-Accept
        const expectedAccept = crypto
          .createHash("sha1")
          .update(key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")
          .digest("base64");
        const serverAccept = res.headers["sec-websocket-accept"];
        if (serverAccept !== expectedAccept) {
          socket.destroy();
          reject(new Error("WebSocket handshake failed: invalid Sec-WebSocket-Accept"));
          return;
        }

        const ws = new ROARWebSocket(socket);

        // If auth token provided, send auth frame first
        if (opts.authToken) {
          ws._sendRaw(JSON.stringify({ type: "auth", token: opts.authToken }));
        }

        resolve(ws);
      });

      req.on("error", (err) => {
        clearTimeout(timer);
        reject(err);
      });

      req.end();
    });
  }

  /** Send a ROARMessage over the WebSocket. */
  async send(msg: ROARMessage): Promise<void> {
    if (this._closed) throw new Error("WebSocket is closed");
    this._sendRaw(JSON.stringify(messageToWire(msg)));
  }

  /** Register a handler called for every incoming ROARMessage. */
  onMessage(handler: MessageHandler): this {
    this._messageHandlers.push(handler);
    return this;
  }

  /** Register a handler called on socket errors. */
  onError(handler: ErrorHandler): this {
    this._errorHandlers.push(handler);
    return this;
  }

  /** Register a handler called when the connection closes. */
  onClose(handler: CloseHandler): this {
    this._closeHandlers.push(handler);
    return this;
  }

  /** Close the WebSocket connection. */
  close(): void {
    if (this._closed) return;
    this._closed = true;
    // Send WebSocket close frame (opcode 0x8)
    const frame = Buffer.alloc(2);
    frame[0] = 0x88; // FIN + close opcode
    frame[1] = 0x00; // no payload
    try {
      this._socket.write(frame);
    } finally {
      this._socket.destroy();
    }
  }

  get closed(): boolean {
    return this._closed;
  }

  // ── WebSocket frame parsing ────────────────────────────────────────────────

  private _onData(chunk: Buffer): void {
    this._buffer = Buffer.concat([this._buffer, chunk]);
    this._parseFrames();
  }

  private _parseFrames(): void {
    while (this._buffer.length >= 2) {
      const b0 = this._buffer[0];
      const b1 = this._buffer[1];

      const opcode = b0 & 0x0f;
      const masked = (b1 & 0x80) !== 0;
      let payloadLen = b1 & 0x7f;
      let offset = 2;

      if (payloadLen === 126) {
        if (this._buffer.length < 4) return; // wait for more data
        payloadLen = this._buffer.readUInt16BE(2);
        offset = 4;
      } else if (payloadLen === 127) {
        if (this._buffer.length < 10) return;
        // High 32 bits must be zero — non-zero means frame >4 GB, close.
        const high = this._buffer.readUInt32BE(2);
        if (high !== 0) { this.close(); return; }
        payloadLen = this._buffer.readUInt32BE(6);
        offset = 10;
      }

      // Reject oversized frames (1 MiB cap) to prevent memory exhaustion.
      if (payloadLen > 1 * 1024 * 1024) { this.close(); return; }

      const maskLen = masked ? 4 : 0;
      const totalLen = offset + maskLen + payloadLen;
      if (this._buffer.length < totalLen) return; // incomplete frame

      let payload = this._buffer.slice(offset + maskLen, totalLen);
      if (masked) {
        const mask = this._buffer.slice(offset, offset + 4);
        payload = Buffer.from(payload);
        for (let i = 0; i < payload.length; i++) {
          payload[i] ^= mask[i % 4];
        }
      }

      this._buffer = this._buffer.slice(totalLen);

      if (opcode === 0x1 || opcode === 0x2) {
        // Text or binary frame — parse as ROAR message
        this._handleTextFrame(payload.toString("utf8"));
      } else if (opcode === 0x8) {
        // Close frame
        this.close();
        return;
      }
      // Ping/pong (0x9/0xA) ignored — servers handle keep-alive
    }
  }

  private _handleTextFrame(text: string): void {
    try {
      const raw = JSON.parse(text) as Record<string, unknown>;
      // Skip auth_ok or error frames that aren't ROARMessages
      if (!raw["intent"]) return;
      const msg = messageFromWire(raw);
      this._messageHandlers.forEach((h) => h(msg));
    } catch {
      // Non-JSON or non-ROAR frame — ignore
    }
  }

  private _sendRaw(text: string): void {
    const payload = Buffer.from(text, "utf8");
    const len = payload.length;

    // Client frames must be masked (RFC 6455 §5.1)
    const mask = crypto.randomBytes(4);
    const masked = Buffer.from(payload);
    for (let i = 0; i < masked.length; i++) {
      masked[i] ^= mask[i % 4];
    }

    let header: Buffer;
    if (len < 126) {
      header = Buffer.alloc(6);
      header[0] = 0x81; // FIN + text opcode
      header[1] = 0x80 | len; // MASK bit + length
      mask.copy(header, 2);
    } else if (len < 65536) {
      header = Buffer.alloc(8);
      header[0] = 0x81;
      header[1] = 0x80 | 126;
      header.writeUInt16BE(len, 2);
      mask.copy(header, 4);
    } else {
      header = Buffer.alloc(14);
      header[0] = 0x81;
      header[1] = 0x80 | 127;
      header.writeUInt32BE(0, 2);
      header.writeUInt32BE(len, 6);
      mask.copy(header, 10);
    }

    this._socket.write(Buffer.concat([header, masked]));
  }
}

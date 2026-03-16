/**
 * ROAR Protocol — HTTP server for receiving and dispatching ROAR messages.
 *
 * Mirrors Python's roar_sdk/server.py.
 * Uses Node.js built-in http module — no external dependencies.
 */

import * as http from "http";
import {
  AgentCard,
  AgentDirectory,
  AgentIdentity,
  DiscoveryEntry,
  MessageIntent,
  ROARMessage,
  messageFromWire,
  messageToWire,
} from "./types.js";
import { createMessage, verifyMessage } from "./message.js";
import { EventBus } from "./streaming.js";
import { StreamEvent } from "./types.js";
import {
  DelegationToken,
  isTokenValid,
  verifyToken,
} from "./delegation.js";

type HandlerFunc = (
  msg: ROARMessage,
) => ROARMessage | Promise<ROARMessage>;

export interface ROARServerOptions {
  host?: string;
  port?: number;
  signingSecret?: string;
  description?: string;
  skills?: string[];
  channels?: string[];
}

export class ROARServer {
  private _identity: AgentIdentity;
  private _host: string;
  private _port: number;
  private _signingSecret: string;
  private _description: string;
  private _skills: string[];
  private _channels: string[];
  private _handlers = new Map<MessageIntent, HandlerFunc>();
  private _eventBus = new EventBus();
  private _httpServer: http.Server | null = null;
  // Server-authoritative use counts keyed by token_id.
  // The delegate's claimed use_count in the wire payload is ignored;
  // this map is the only source of truth for max_uses enforcement.
  // NOTE: _tokenUseCounts is in-process memory. Multi-worker deployments
  // will have per-worker counters — see Python SDK comment for guidance.
  private _tokenUseCounts = new Map<string, number>();

  constructor(identity: AgentIdentity, opts: ROARServerOptions = {}) {
    this._identity = identity;
    this._host = opts.host ?? "127.0.0.1";
    this._port = opts.port ?? 8089;
    this._signingSecret = opts.signingSecret ?? "";
    this._description = opts.description ?? "";
    this._skills = opts.skills ?? [];
    this._channels = opts.channels ?? [];
  }

  get identity(): AgentIdentity {
    return this._identity;
  }

  get host(): string {
    return this._host;
  }

  get port(): number {
    return this._port;
  }

  get eventBus(): EventBus {
    return this._eventBus;
  }

  emit(event: StreamEvent): number {
    return this._eventBus.publish(event);
  }

  /** Register an intent handler. Returns this for chaining. */
  on(intent: MessageIntent, handler: HandlerFunc): this {
    this._handlers.set(intent, handler);
    return this;
  }

  async handleMessage(msg: ROARMessage): Promise<ROARMessage> {
    // Delegation token enforcement (mirrors Python ROARServer.handle_message)
    const rawToken = msg.context["delegation_token"] as Record<string, unknown> | undefined;
    if (rawToken) {
      let token: DelegationToken;
      try {
        token = rawToken as unknown as DelegationToken;
        if (
          typeof token.token_id !== "string" ||
          typeof token.delegator_did !== "string" ||
          typeof token.delegate_did !== "string" ||
          !Array.isArray(token.capabilities)
        ) {
          throw new Error("missing required fields");
        }
      } catch {
        return createMessage(
          this._identity,
          msg.from_identity,
          MessageIntent.RESPOND,
          { error: "invalid_delegation_token", message: "Malformed delegation token." },
          { in_reply_to: msg.id },
        );
      }

      // Override delegate-supplied use_count with the server-authoritative value.
      token.use_count = this._tokenUseCounts.get(token.token_id) ?? 0;

      if (!isTokenValid(token)) {
        return createMessage(
          this._identity,
          msg.from_identity,
          MessageIntent.RESPOND,
          { error: "delegation_token_exhausted", message: "Token expired or use limit reached." },
          { in_reply_to: msg.id },
        );
      }

      // Verify Ed25519 signature when a delegator public key is available.
      // If not available (C-3: no DID resolver yet), skip gracefully.
      const delegatorPublicKey: string | undefined =
        msg.from_identity.did === token.delegator_did
          ? (msg.from_identity.public_key ?? undefined)
          : (msg.context["delegator_public_key"] as string | undefined);

      if (delegatorPublicKey) {
        if (!verifyToken(token, delegatorPublicKey)) {
          return createMessage(
            this._identity,
            msg.from_identity,
            MessageIntent.RESPOND,
            { error: "invalid_delegation_signature", message: "Delegation token signature verification failed." },
            { in_reply_to: msg.id },
          );
        }
      }
      // else: no public key resolvable (C-3: no DID resolver yet) — skip gracefully

      // Increment server-authoritative use count.
      this._tokenUseCounts.set(token.token_id, token.use_count + 1);
    }

    const handler = this._handlers.get(msg.intent);
    if (!handler) {
      return createMessage(
        this._identity,
        msg.from_identity,
        MessageIntent.RESPOND,
        {
          error: "unhandled_intent",
          message: `No handler registered for intent '${msg.intent}'`,
        },
        { in_reply_to: msg.id },
      );
    }
    return handler(msg);
  }

  getCard(): AgentCard {
    return {
      identity: this._identity,
      description: this._description,
      skills: this._skills,
      channels: this._channels,
      endpoints: { http: `http://${this._host}:${this._port}` },
      declared_capabilities: [],
      metadata: {},
    };
  }

  registerWithDirectory(directory: AgentDirectory): DiscoveryEntry {
    return directory.register(this.getCard());
  }

  /** Start the HTTP server. Returns a Promise that resolves when listening. */
  serve(): Promise<void> {
    return new Promise((resolve) => {
      this._httpServer = http.createServer(async (req, res) => {
        if (req.method === "GET" && req.url === "/roar/health") {
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ status: "ok", protocol: "roar/1.0" }));
          return;
        }

        if (req.method === "GET" && req.url === "/roar/agents") {
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ agents: [this.getCard()] }));
          return;
        }

        if (req.method !== "POST" || req.url !== "/roar/message") {
          res.writeHead(404, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: "not_found" }));
          return;
        }

        /** 1 MiB cap — prevents unbounded memory growth from oversized POST bodies. */
        const MAX_BODY_BYTES = 1 * 1024 * 1024;
        let body = "";
        let bodyBytes = 0;
        let bodySizeExceeded = false;
        req.on("data", (chunk: Buffer | string) => {
          const chunkStr = typeof chunk === "string" ? chunk : chunk.toString();
          bodyBytes += Buffer.byteLength(chunkStr);
          if (bodyBytes > MAX_BODY_BYTES) {
            bodySizeExceeded = true;
            req.destroy();
            return;
          }
          body += chunkStr;
        });
        req.on("end", async () => {
          if (bodySizeExceeded) {
            res.writeHead(413, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ error: "request_too_large" }));
            return;
          }
          try {
            const raw = JSON.parse(body) as Record<string, unknown>;
            const msg = messageFromWire(raw);

            if (this._signingSecret && msg.auth) {
              if (!verifyMessage(msg, this._signingSecret, 300)) {
                res.writeHead(401, { "Content-Type": "application/json" });
                res.end(
                  JSON.stringify({
                    error: "invalid_signature",
                    message: "HMAC verification failed",
                  }),
                );
                return;
              }
            }

            const response = await this.handleMessage(msg);
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify(messageToWire(response)));
          } catch (err) {
            res.writeHead(400, { "Content-Type": "application/json" });
            res.end(
              JSON.stringify({ error: "invalid_message", detail: String(err) }),
            );
          }
        });
      });

      this._httpServer.listen(this._port, this._host, () => resolve());
    });
  }

  stop(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (!this._httpServer) return resolve();
      this._httpServer.close((err) => (err ? reject(err) : resolve()));
    });
  }
}

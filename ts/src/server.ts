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
import { DIDResolutionError, resolveDidToPublicKey } from "./did_resolver.js";
import { InMemoryTokenStore, TokenStore } from "./token_store.js";
import { DelegationToken, verifyToken } from "./delegation.js";

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
  tokenStore?: TokenStore;
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
  // Server-authoritative token use-count store.
  // The delegate's claimed use_count in the wire payload is ignored;
  // this store is the only source of truth for max_uses enforcement.
  // Use RedisTokenStore for multi-worker deployments (see token_store.ts).
  private _tokenStore: TokenStore;

  constructor(identity: AgentIdentity, opts: ROARServerOptions = {}) {
    this._identity = identity;
    this._host = opts.host ?? "127.0.0.1";
    this._port = opts.port ?? 8089;
    this._signingSecret = opts.signingSecret ?? "";
    this._description = opts.description ?? "";
    this._skills = opts.skills ?? [];
    this._channels = opts.channels ?? [];
    this._tokenStore = opts.tokenStore ?? new InMemoryTokenStore();
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

      // SECURITY INVARIANT 1: bind check MUST run before signature verification.
      // Ensures the token was issued to this exact sender — prevents token theft.
      if (token.delegate_did !== msg.from_identity.did) {
        return createMessage(
          this._identity,
          msg.from_identity,
          MessageIntent.RESPOND,
          { error: "delegation_token_unauthorized", message: "Token was not issued to this agent." },
          { in_reply_to: msg.id },
        );
      }

      // Expiry check (before consuming a use from the store)
      if (token.expires_at !== null && Date.now() / 1000 > token.expires_at) {
        return createMessage(
          this._identity,
          msg.from_identity,
          MessageIntent.RESPOND,
          { error: "delegation_token_exhausted", message: "Token expired or use limit reached." },
          { in_reply_to: msg.id },
        );
      }

      // Atomic use-count check + increment via the configured store.
      const allowed = await this._tokenStore.getAndIncrement(token.token_id, token.max_uses);
      if (!allowed) {
        return createMessage(
          this._identity,
          msg.from_identity,
          MessageIntent.RESPOND,
          { error: "delegation_token_exhausted", message: "Token expired or use limit reached." },
          { in_reply_to: msg.id },
        );
      }

      // Determine the delegator's public key for signature verification.
      // SECURITY INVARIANT 2: NEVER use context["delegator_public_key"] —
      // that field is attacker-controlled and accepting it would allow a
      // confused-deputy attack.
      let delegatorPublicKey: string;
      if (msg.from_identity.did === token.delegator_did) {
        // Same-party delegation: sender IS the delegator, use their key directly.
        const pk = msg.from_identity.public_key ?? undefined;
        if (!pk) {
          return createMessage(
            this._identity,
            msg.from_identity,
            MessageIntent.RESPOND,
            { error: "delegation_unverifiable", message: "No public key available for delegator DID." },
            { in_reply_to: msg.id },
          );
        }
        delegatorPublicKey = pk;
      } else {
        // 3-party delegation: resolve the delegator's DID to get their key.
        // SECURITY INVARIANT 3: fail closed on resolution failure.
        try {
          delegatorPublicKey = await resolveDidToPublicKey(token.delegator_did);
        } catch (e) {
          if (e instanceof DIDResolutionError) {
            return createMessage(
              this._identity,
              msg.from_identity,
              MessageIntent.RESPOND,
              {
                error: "delegation_unverifiable",
                message: `Could not resolve delegator DID: ${e.message}`,
              },
              { in_reply_to: msg.id },
            );
          }
          throw e;
        }
      }

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

            // C-1 fix: check signingSecret alone — empty auth must not bypass HMAC.
            if (this._signingSecret) {
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
          } catch {
            // Do not surface parse/validation details — they may expose schema info.
            res.writeHead(400, { "Content-Type": "application/json" });
            res.end(
              JSON.stringify({ error: "invalid_message", detail: "Request body is not a valid ROAR message." }),
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

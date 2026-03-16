/**
 * ROAR Protocol — Hub server with federation support (TypeScript).
 * Mirrors python/src/roar_sdk/hub.py.
 *
 * Provides discovery registration, lookup, search and federation sync/export.
 *
 * Security properties:
 * - Challenge-response proof-of-possession registration (no TOFU)
 * - Challenge is one-time use (consume deletes) and expires quickly
 * - Body size cap (256 KiB)
 * - Fail-closed when identity cannot be verified
 */

import * as http from "http";
import * as crypto from "crypto";

import { AgentDirectory } from "./types.js";
import type { AgentCard, DiscoveryEntry } from "./types.js";
import { ChallengeStore } from "./hub_auth.js";

const MAX_BODY_BYTES = 256 * 1024;

function parseDiscoveryEntry(raw: unknown): DiscoveryEntry | null {
  if (typeof raw !== "object" || raw === null) return null;
  const e = raw as Record<string, unknown>;
  const card = e["agent_card"];
  if (typeof card !== "object" || card === null) return null;
  const identity = (card as Record<string, unknown>)["identity"];
  if (typeof identity !== "object" || identity === null) return null;
  if (typeof (identity as Record<string, unknown>)["did"] !== "string") return null;
  return {
    agent_card: card as AgentCard,
    registered_at: typeof e["registered_at"] === "number" ? e["registered_at"] : Date.now() / 1000,
    last_seen: typeof e["last_seen"] === "number" ? e["last_seen"] : Date.now() / 1000,
    hub_url: typeof e["hub_url"] === "string" ? e["hub_url"] : "",
  };
}

function json(res: http.ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}

async function readBoundedJson(req: http.IncomingMessage): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    let body = "";
    let bytes = 0;

    req.on("data", (chunk: Buffer | string) => {
      const s = typeof chunk === "string" ? chunk : chunk.toString("utf8");
      bytes += Buffer.byteLength(s);
      if (bytes > MAX_BODY_BYTES) {
        req.destroy();
        reject(new Error("body_too_large"));
        return;
      }
      body += s;
    });

    req.on("end", () => {
      try {
        const parsed = JSON.parse(body || "{}") as Record<string, unknown>;
        resolve(parsed);
      } catch {
        reject(new Error("invalid_json"));
      }
    });
  });
}

function validateAgentCard(raw: unknown): AgentCard | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const card = raw as any;
  if (typeof card.identity !== "object" || card.identity === null || Array.isArray(card.identity)) return null;
  if (typeof card.identity.did !== "string" || !card.identity.did) return null;
  // public_key may be null on some cards, but for hub registration we require one.
  if (typeof card.identity.public_key !== "string" || !card.identity.public_key) return null;
  if (!Array.isArray(card.identity.capabilities)) card.identity.capabilities = [];
  if (typeof card.description !== "string") card.description = "";
  if (!Array.isArray(card.skills)) card.skills = [];
  if (!Array.isArray(card.channels)) card.channels = [];
  if (typeof card.endpoints !== "object" || card.endpoints === null || Array.isArray(card.endpoints)) card.endpoints = {};
  if (!Array.isArray(card.declared_capabilities)) card.declared_capabilities = [];
  if (typeof card.metadata !== "object" || card.metadata === null || Array.isArray(card.metadata)) card.metadata = {};
  return card as AgentCard;
}

function verifyEd25519Nonce(publicKeyHex: string, signature: string, nonce: string): boolean {
  if (!signature.startsWith("ed25519:")) return false;
  try {
    const b64 = signature.slice("ed25519:".length);
    const rawSig = Buffer.from(b64, "base64url");

    const rawPub = Buffer.from(publicKeyHex, "hex");
    // SPKI DER wrapper for Ed25519 public key
    const spkiHeader = Buffer.from("302a300506032b6570032100", "hex");
    const der = Buffer.concat([spkiHeader, rawPub]);
    const pubKey = crypto.createPublicKey({ key: der, format: "der", type: "spki" });

    return crypto.verify(null, Buffer.from(nonce, "utf8"), pubKey, rawSig);
  } catch {
    return false;
  }
}

export interface ROARHubOptions {
  host?: string;
  port?: number;
  hub_id?: string;
  peer_urls?: string[];
}

export class ROARHub {
  private _host: string;
  private _port: number;
  private _hubUrl: string;
  private _directory: AgentDirectory;
  private _peers: string[];
  private _challenges: ChallengeStore;
  private _httpServer: http.Server | null = null;

  constructor(opts: ROARHubOptions = {}) {
    this._host = opts.host ?? "0.0.0.0";
    this._port = opts.port ?? 8090;
    this._hubUrl = opts.hub_id ?? `http://${this._host}:${this._port}`;
    this._directory = new AgentDirectory();
    this._peers = [...(opts.peer_urls ?? [])];
    this._challenges = new ChallengeStore();
  }

  get directory(): AgentDirectory {
    return this._directory;
  }

  addPeer(url: string): void {
    if (!this._peers.includes(url)) this._peers.push(url);
  }

  serve(): Promise<void> {
    return new Promise((resolve) => {
      this._httpServer = http.createServer(async (req, res) => {
        const method = req.method ?? "GET";
        const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);

        // GET /roar/health
        if (method === "GET" && url.pathname === "/roar/health") {
          json(res, 200, {
            status: "ok",
            protocol: "roar/1.0",
            hub_url: this._hubUrl,
            agents: this._directory.listAll().length,
            peers: this._peers.length,
          });
          return;
        }

        // POST /roar/agents/register
        if (method === "POST" && url.pathname === "/roar/agents/register") {
          try {
            const body = await readBoundedJson(req);
            const did = body["did"];
            const public_key = body["public_key"];
            const card = body["card"];

            if (typeof did !== "string" || !did) {
              json(res, 400, { error: "did is required" });
              return;
            }
            if (typeof public_key !== "string" || !public_key) {
              json(res, 400, { error: "public_key is required — cannot verify identity without key" });
              return;
            }
            if (typeof card !== "object" || card === null) {
              json(res, 400, { error: "card is required" });
              return;
            }

            let ch;
            try {
              ch = this._challenges.issue(did, public_key, card as Record<string, unknown>);
            } catch (e) {
              json(res, 503, { error: (e as Error).message });
              return;
            }

            json(res, 200, {
              challenge_id: ch.challenge_id,
              nonce: ch.nonce,
              expires_at: ch.expires_at,
            });
            return;
          } catch (e) {
            const msg = (e as Error).message;
            if (msg === "body_too_large") {
              json(res, 413, { error: "Request body too large" });
              return;
            }
            json(res, 400, { error: "Invalid JSON body" });
            return;
          }
        }

        // POST /roar/agents/challenge
        if (method === "POST" && url.pathname === "/roar/agents/challenge") {
          try {
            const body = await readBoundedJson(req);
            const challenge_id = body["challenge_id"];
            const signature = body["signature"];

            if (typeof challenge_id !== "string" || !challenge_id) {
              json(res, 400, { error: "challenge_id is required" });
              return;
            }
            if (typeof signature !== "string" || !signature) {
              json(res, 400, { error: "signature is required" });
              return;
            }

            const ch = this._challenges.consume(challenge_id);
            if (!ch) {
              json(res, 401, { error: "challenge_expired" });
              return;
            }

            const ok = verifyEd25519Nonce(ch.public_key, signature, ch.nonce);
            if (!ok) {
              json(res, 401, { error: "invalid_signature" });
              return;
            }

            // Register agent card (fail closed if invalid)
            const card = validateAgentCard(ch.card);
            if (!card) {
              json(res, 400, { error: "invalid card" });
              return;
            }

            const entry = this._directory.register(card);
            entry.hub_url = this._hubUrl;
            json(res, 200, { registered: true });
            return;
          } catch (e) {
            const msg = (e as Error).message;
            if (msg === "body_too_large") {
              json(res, 413, { error: "Request body too large" });
              return;
            }
            json(res, 400, { error: "Invalid JSON body" });
            return;
          }
        }

        // GET /roar/agents (optional capability)
        if (method === "GET" && url.pathname === "/roar/agents") {
          const capability = url.searchParams.get("capability");
          const entries = capability ? this._directory.search(capability) : this._directory.listAll();
          json(res, 200, { agents: entries.map((e) => e) });
          return;
        }

        // GET /roar/agents/search?capability=X
        if (method === "GET" && url.pathname === "/roar/agents/search") {
          const cap = url.searchParams.get("capability") ?? "";
          if (!cap) {
            json(res, 400, { error: "capability is required" });
            return;
          }
          json(res, 200, { agents: this._directory.search(cap) });
          return;
        }

        // GET /roar/agents/:did
        if (method === "GET" && url.pathname.startsWith("/roar/agents/")) {
          const did = decodeURIComponent(url.pathname.slice("/roar/agents/".length));
          if (!did) {
            json(res, 400, { error: "did is required" });
            return;
          }
          const entry = this._directory.lookup(did);
          if (!entry) {
            json(res, 404, { error: "Agent not found" });
            return;
          }
          json(res, 200, entry);
          return;
        }

        // POST /roar/federation/sync
        if (method === "POST" && url.pathname === "/roar/federation/sync") {
          try {
            const body = await readBoundedJson(req);
            const entriesRaw = body["entries"];
            if (!Array.isArray(entriesRaw)) {
              json(res, 400, { error: "entries must be a list" });
              return;
            }

            let imported = 0;
            for (const raw of entriesRaw) {
              try {
                const entry = parseDiscoveryEntry(raw);
                if (!entry) continue;
                const did = entry.agent_card.identity.did;
                // Don't overwrite locally-registered agents
                if (!this._directory.lookup(did)) {
                  // @ts-expect-error internal store access matches python behavior
                  this._directory._agents[did] = entry;
                  imported += 1;
                }
              } catch {
                // Skip invalid entries (fail closed per-entry)
              }
            }

            json(res, 200, { imported, total: entriesRaw.length });
            return;
          } catch (e) {
            const msg = (e as Error).message;
            if (msg === "body_too_large") {
              json(res, 413, { error: "Request body too large" });
              return;
            }
            json(res, 400, { error: "Invalid JSON body" });
            return;
          }
        }

        // GET /roar/federation/export
        if (method === "GET" && url.pathname === "/roar/federation/export") {
          const entries = this._directory.listAll();
          json(res, 200, {
            hub_url: this._hubUrl,
            exported_at: Date.now() / 1000,
            entries,
          });
          return;
        }

        json(res, 404, { error: "not_found" });
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

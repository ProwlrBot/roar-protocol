/**
 * ROAR Protocol — SQLite-backed agent directory (Layer 2 — Discovery).
 *
 * Mirrors python/src/roar_sdk/sqlite_directory.py exactly.
 * Uses Node.js built-in `node:sqlite` (Node 22.5+) — no external deps.
 *
 * Default path: ~/.roar/roar_directory.db
 *
 * Usage:
 *   const dir = new SqliteAgentDirectory();
 *   dir.register(card);
 *   const entry = dir.lookup("did:roar:agent:planner-abc12345");
 *   dir.close();
 */

import { DatabaseSync } from "node:sqlite";
import { homedir } from "node:os";
import { mkdirSync } from "node:fs";
import { join, dirname, resolve } from "node:path";
import { AgentCard, DiscoveryEntry } from "./types.js";

const DEFAULT_DB_PATH = join(homedir(), ".roar", "roar_directory.db");

export class SqliteAgentDirectory {
  private readonly _db: DatabaseSync;

  constructor(dbPath: string = DEFAULT_DB_PATH) {
    const resolvedPath = resolve(dbPath);
    mkdirSync(dirname(resolvedPath), { recursive: true });
    this._db = new DatabaseSync(resolvedPath);
    this._createTables();
  }

  private _createTables(): void {
    this._db.prepare(`
      CREATE TABLE IF NOT EXISTS agents (
        did TEXT PRIMARY KEY,
        card_json TEXT NOT NULL,
        registered_at REAL NOT NULL,
        last_seen REAL NOT NULL,
        hub_url TEXT NOT NULL DEFAULT ''
      )
    `).run();
  }

  /** Register (or re-register) an agent card. Returns the DiscoveryEntry. */
  register(card: AgentCard): DiscoveryEntry {
    const now = Date.now() / 1000;
    this._db.prepare(`
      INSERT OR REPLACE INTO agents (did, card_json, registered_at, last_seen, hub_url)
      VALUES (?, ?, ?, ?, ?)
    `).run(card.identity.did, JSON.stringify(card), now, now, "");
    return { agent_card: card, registered_at: now, last_seen: now, hub_url: "" };
  }

  /** Look up an agent by DID. Returns undefined if not found (matches AgentDirectory). */
  lookup(did: string): DiscoveryEntry | undefined {
    const row = this._db.prepare(
      "SELECT card_json, registered_at, last_seen, hub_url FROM agents WHERE did = ?",
    ).get(did) as
      | { card_json: string; registered_at: number; last_seen: number; hub_url: string }
      | undefined;
    if (!row) return undefined;
    return this._rowToEntry(row);
  }

  /** Find agents with a specific capability string. */
  search(capability: string): DiscoveryEntry[] {
    const rows = this._db.prepare(
      "SELECT card_json, registered_at, last_seen, hub_url FROM agents",
    ).all() as Array<{ card_json: string; registered_at: number; last_seen: number; hub_url: string }>;
    return rows
      .map((r) => this._rowToEntry(r))
      .filter((e) => e.agent_card.identity.capabilities.includes(capability));
  }

  /** List all registered agents. */
  listAll(): DiscoveryEntry[] {
    const rows = this._db.prepare(
      "SELECT card_json, registered_at, last_seen, hub_url FROM agents",
    ).all() as Array<{ card_json: string; registered_at: number; last_seen: number; hub_url: string }>;
    return rows.map((r) => this._rowToEntry(r));
  }

  /** Remove an agent by DID. Returns true if it existed. */
  unregister(did: string): boolean {
    const result = this._db.prepare("DELETE FROM agents WHERE did = ?").run(did) as { changes: number };
    return result.changes > 0;
  }

  /** Close the database connection. */
  close(): void {
    this._db.close();
  }

  /**
   * Explicit resource management support (ES2023 `using` keyword).
   * `using dir = new SqliteAgentDirectory()` auto-closes on scope exit.
   */
  [Symbol.dispose](): void {
    this.close();
  }

  private _rowToEntry(row: {
    card_json: string;
    registered_at: number;
    last_seen: number;
    hub_url: string;
  }): DiscoveryEntry {
    let agent_card: AgentCard;
    try {
      agent_card = JSON.parse(row.card_json) as AgentCard;
    } catch {
      throw new Error(`SqliteAgentDirectory: corrupt card_json in database row`);
    }
    return { agent_card, registered_at: row.registered_at, last_seen: row.last_seen, hub_url: row.hub_url };
  }
}

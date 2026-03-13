/**
 * ROAR Protocol — Idempotency guard for replay protection.
 *
 * Mirrors python/src/roar_sdk/dedup.py exactly.
 * Zero external dependencies.
 *
 * Usage:
 *   const guard = new IdempotencyGuard();
 *   if (guard.is_duplicate(msg.id)) { drop it; }
 */

// ---------------------------------------------------------------------------
// IdempotencyGuard
// ---------------------------------------------------------------------------

/**
 * Bounded TTL cache that tracks whether a key has been seen before.
 *
 * - `is_duplicate(key)` returns false on first call (and records it),
 *   true on all subsequent calls within the TTL window.
 * - Evicts entries older than `ttl_seconds` lazily on each `is_duplicate` call.
 * - Caps at `max_keys` using FIFO eviction when the limit is hit.
 */
export class IdempotencyGuard {
  private readonly _maxKeys: number;
  private readonly _ttlSeconds: number;
  // Map preserves insertion order (ES2015) — we sweep from the front.
  private readonly _seen: Map<string, number> = new Map();

  constructor(maxKeys = 10_000, ttlSeconds = 300.0) {
    this._maxKeys = maxKeys;
    this._ttlSeconds = ttlSeconds;
  }

  /**
   * Returns true if this key has been seen before (replay detected).
   * Returns false on first encounter (and records the key as seen).
   */
  is_duplicate(key: string): boolean {
    this._evict_expired();
    if (this._seen.has(key)) return true;
    this.mark_seen(key);
    return false;
  }

  /**
   * Unconditionally record a key as seen (without checking for duplicates).
   * Evicts the oldest entry if the map is full.
   */
  mark_seen(key: string): void {
    // If already present, refresh the timestamp by deleting + re-inserting
    // (so it moves to the back of insertion order)
    if (this._seen.has(key)) {
      this._seen.delete(key);
    }
    // Evict oldest (first entry) if at capacity
    if (this._seen.size >= this._maxKeys) {
      const oldest = this._seen.keys().next().value;
      if (oldest !== undefined) this._seen.delete(oldest);
    }
    this._seen.set(key, Date.now() / 1000);
  }

  /**
   * Remove entries whose recorded timestamp is older than `ttl_seconds`.
   * Because Map is insertion-ordered, entries at the front are oldest.
   */
  _evict_expired(): void {
    const cutoff = Date.now() / 1000 - this._ttlSeconds;
    for (const [key, ts] of this._seen) {
      if (ts < cutoff) {
        this._seen.delete(key);
      } else {
        // Map is insertion-ordered: once we hit a fresh entry, stop
        break;
      }
    }
  }

  /** Number of currently tracked keys. */
  get size(): number {
    return this._seen.size;
  }

  /** Clear all tracked keys. */
  clear(): void {
    this._seen.clear();
  }
}

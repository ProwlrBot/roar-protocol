/**
 * DiscoveryCache — TTL + LRU cache for DiscoveryEntry objects.
 *
 * Mirrors Python roar_sdk/discovery_cache.py exactly.
 * Uses a Map (insertion-order preserved in JS) to implement LRU:
 *   - On hit:  delete + re-insert (moves to end / most-recent)
 *   - On evict: remove via Map.keys().next() (removes front / least-recent)
 */

import type { DiscoveryEntry } from "./types.js";

// ---------------------------------------------------------------------------
// Internal cache entry (not exported)
// ---------------------------------------------------------------------------

interface _CacheEntry {
  entry: DiscoveryEntry;
  cached_at: number; // unix timestamp (seconds, float)
  ttl: number;       // seconds
}

function _isExpired(e: _CacheEntry): boolean {
  return Date.now() / 1000 - e.cached_at > e.ttl;
}

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface DiscoveryCacheStats {
  size: number;
  max_entries: number;
  hits: number;
  misses: number;
  hit_rate: number;
}

// ---------------------------------------------------------------------------
// DiscoveryCache
// ---------------------------------------------------------------------------

export class DiscoveryCache {
  private _cache: Map<string, _CacheEntry>;
  private _max_entries: number;
  private _default_ttl: number;
  private _hits: number;
  private _misses: number;

  constructor(max_entries = 1000, default_ttl = 300.0) {
    this._cache = new Map();
    this._max_entries = max_entries;
    this._default_ttl = default_ttl;
    this._hits = 0;
    this._misses = 0;
  }

  /** Look up a DiscoveryEntry by DID. Returns undefined on miss or expiry. */
  get(did: string): DiscoveryEntry | undefined {
    const e = this._cache.get(did);
    if (e === undefined || _isExpired(e)) {
      this._misses++;
      if (e !== undefined) {
        // expired — remove it
        this._cache.delete(did);
      }
      return undefined;
    }
    // LRU: move to end (most-recently used)
    this._cache.delete(did);
    this._cache.set(did, e);
    this._hits++;
    return e.entry;
  }

  /** Insert or update a DiscoveryEntry in the cache. */
  put(entry: DiscoveryEntry, ttl?: number): void {
    const did = entry.agent_card.identity.did;
    const resolvedTtl = ttl !== undefined ? ttl : this._default_ttl;

    // If key already present, remove first so re-insert lands at the end
    this._cache.delete(did);
    this._cache.set(did, {
      entry,
      cached_at: Date.now() / 1000,
      ttl: resolvedTtl,
    });

    // Evict LRU entries (front of Map) while over capacity
    while (this._cache.size > this._max_entries) {
      const oldest = this._cache.keys().next().value;
      if (oldest !== undefined) {
        this._cache.delete(oldest);
      }
    }
  }

  /** Remove a single entry. Returns true if it existed. */
  invalidate(did: string): boolean {
    return this._cache.delete(did);
  }

  /** Remove all cached entries. Stats counters are preserved (matches Python). */
  clear(): void {
    this._cache.clear();
  }

  /**
   * Search for entries that advertise a given capability.
   * Checks both agent_card.identity.capabilities and agent_card.skills.
   * Expired entries are evicted before searching.
   */
  search(capability: string): DiscoveryEntry[] {
    this._evict_expired();
    const results: DiscoveryEntry[] = [];
    for (const e of this._cache.values()) {
      const card = e.entry.agent_card;
      if (
        card.identity.capabilities.includes(capability) ||
        card.skills.includes(capability)
      ) {
        results.push(e.entry);
      }
    }
    return results;
  }

  /** Number of entries currently in the cache. */
  get size(): number {
    return this._cache.size;
  }

  /** Cache statistics snapshot. */
  get stats(): DiscoveryCacheStats {
    const total = this._hits + this._misses;
    return {
      size: this._cache.size,
      max_entries: this._max_entries,
      hits: this._hits,
      misses: this._misses,
      hit_rate: total === 0 ? 0.0 : this._hits / total,
    };
  }

  /** Remove all expired entries from the cache. */
  private _evict_expired(): void {
    for (const [did, e] of this._cache.entries()) {
      if (_isExpired(e)) {
        this._cache.delete(did);
      }
    }
  }
}

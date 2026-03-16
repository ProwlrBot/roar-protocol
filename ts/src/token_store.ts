/**
 * ROAR Protocol — Abstract token use-count store for delegation token enforcement.
 *
 * The default InMemoryTokenStore is safe for single-worker deployments.
 * For multi-worker production, use RedisTokenStore (requires ioredis package).
 *
 * Both stores are safe against race conditions within their scope:
 * - InMemoryTokenStore: JS single-threaded event loop (single process)
 * - RedisTokenStore: INCR is atomic on the Redis server (across processes)
 *
 * Mirrors python/src/roar_sdk/token_store.py exactly.
 */

// ---------------------------------------------------------------------------
// Abstract interface
// ---------------------------------------------------------------------------

export interface TokenStore {
  /**
   * Atomically increment use count.
   * Returns true if within limit, false if exhausted.
   * If maxUses is null (unlimited), always returns true and increments.
   */
  getAndIncrement(tokenId: string, maxUses: number | null): Promise<boolean>;

  /** Return current use count for a token. */
  getCount(tokenId: string): Promise<number>;
}

// ---------------------------------------------------------------------------
// In-memory store (single-process)
// ---------------------------------------------------------------------------

export class InMemoryTokenStore implements TokenStore {
  private _counts = new Map<string, number>();

  async getAndIncrement(tokenId: string, maxUses: number | null): Promise<boolean> {
    const current = this._counts.get(tokenId) ?? 0;
    if (maxUses !== null && current >= maxUses) {
      return false;
    }
    this._counts.set(tokenId, current + 1);
    return true;
  }

  async getCount(tokenId: string): Promise<number> {
    return this._counts.get(tokenId) ?? 0;
  }
}

// ---------------------------------------------------------------------------
// Redis store (multi-worker)
// ---------------------------------------------------------------------------

/**
 * Multi-worker safe token store using Redis INCR.
 *
 * Redis INCR is atomic — safe across multiple Node.js worker processes.
 * Keys are set to expire after 24 hours to prevent unbounded growth.
 *
 * Requires: npm install ioredis
 * ioredis is a dynamic import so the package is optional at module load time.
 */
export class RedisTokenStore implements TokenStore {
  private _redisUrl: string;
  private _keyPrefix: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private _client: any | null = null;

  constructor(
    redisUrl = "redis://localhost:6379/0",
    keyPrefix = "roar:tok:",
  ) {
    this._redisUrl = redisUrl;
    this._keyPrefix = keyPrefix;
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private async getClient(): Promise<any> {
    if (this._client) return this._client;
    let Redis: { new(url: string): unknown };
    try {
      // Dynamic import keeps ioredis optional
      const mod = await import("ioredis");
      Redis = mod.default ?? mod;
    } catch {
      throw new Error(
        "RedisTokenStore requires the 'ioredis' package. Install: npm install ioredis",
      );
    }
    this._client = new (Redis as { new(url: string): unknown })(this._redisUrl);
    return this._client;
  }

  async getAndIncrement(tokenId: string, maxUses: number | null): Promise<boolean> {
    const redis = await this.getClient();
    const key = `${this._keyPrefix}${tokenId}`;
    // INCR is atomic; compare AFTER increment to decide if within limit
    const newCount: number = await redis.incr(key);
    // Set TTL on first use (24h default)
    if (newCount === 1) {
      await redis.expire(key, 86400);
    }
    if (maxUses !== null && newCount > maxUses) {
      return false;
    }
    return true;
  }

  async getCount(tokenId: string): Promise<number> {
    const redis = await this.getClient();
    const val: string | null = await redis.get(`${this._keyPrefix}${tokenId}`);
    return val ? parseInt(val, 10) : 0;
  }
}

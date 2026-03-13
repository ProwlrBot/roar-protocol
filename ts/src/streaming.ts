/**
 * ROAR Protocol — in-process EventBus for Layer 5 streaming.
 *
 * Mirrors Python's roar_sdk/streaming.py.
 * Zero external dependencies — uses Node.js built-in EventEmitter as a signal only.
 */

import { EventEmitter } from "events";
import { StreamEvent, StreamEventType } from "./types.js";

// ---------------------------------------------------------------------------
// StreamFilter
// ---------------------------------------------------------------------------

export interface StreamFilterSpec {
  event_types?: StreamEventType[];
  source_dids?: string[];
  session_ids?: string[];
}

export class StreamFilter {
  readonly event_types: StreamEventType[];
  readonly source_dids: string[];
  readonly session_ids: string[];

  constructor(spec: StreamFilterSpec = {}) {
    this.event_types = spec.event_types ?? [];
    this.source_dids = spec.source_dids ?? [];
    this.session_ids = spec.session_ids ?? [];
  }

  matches(event: StreamEvent): boolean {
    if (this.event_types.length > 0 && !this.event_types.includes(event.type))
      return false;
    if (this.source_dids.length > 0 && !this.source_dids.includes(event.source))
      return false;
    if (
      this.session_ids.length > 0 &&
      !this.session_ids.includes(event.session_id)
    )
      return false;
    return true;
  }
}

// ---------------------------------------------------------------------------
// Subscription
// ---------------------------------------------------------------------------

export class Subscription implements AsyncIterable<StreamEvent> {
  readonly id: string;
  readonly filter: StreamFilter;

  private _buffer: StreamEvent[] = [];
  private _closed = false;
  private _resolve: ((e: StreamEvent) => void) | null = null;
  private _bus: EventBus;

  eventsReceived = 0;
  eventsDropped = 0;

  // AIMD capacity: floats between 1 and maxBuffer
  private _capacity: number;

  constructor(
    id: string,
    filter: StreamFilter,
    bus: EventBus,
    private readonly maxBuffer: number,
  ) {
    this.id = id;
    this.filter = filter;
    this._bus = bus;
    this._capacity = maxBuffer;
  }

  /** AIMD effective limit (floor of floating capacity). */
  get effectiveLimit(): number {
    return Math.floor(this._capacity);
  }

  /** @internal — called by EventBus.publish */
  _deliver(event: StreamEvent): boolean {
    if (this._closed) return false;
    if (this._resolve) {
      // Waiting consumer — deliver directly; additive increase
      const resolve = this._resolve;
      this._resolve = null;
      this._capacity = Math.min(this.maxBuffer, this._capacity + 1);
      this.eventsReceived++;
      resolve(event);
      return true;
    }
    if (this._buffer.length >= this.effectiveLimit) {
      // Backpressure: multiplicative decrease, drop oldest
      this._capacity = Math.max(1, this._capacity * 0.5);
      this._buffer.shift();
      this.eventsDropped++;
    } else {
      // Buffered without drop: additive increase
      this._capacity = Math.min(this.maxBuffer, this._capacity + 1);
    }
    this._buffer.push(event);
    return true;
  }

  /** Get the next event, or undefined after timeout (ms). */
  async get(timeoutMs = 5000): Promise<StreamEvent | undefined> {
    if (this._closed) return undefined;
    if (this._buffer.length > 0) {
      this.eventsReceived++;
      return this._buffer.shift()!;
    }
    return new Promise<StreamEvent | undefined>((resolve) => {
      this._resolve = (e) => resolve(e);
      setTimeout(() => {
        if (this._resolve === resolve) {
          this._resolve = null;
          resolve(undefined);
        }
      }, timeoutMs);
    });
  }

  close(): void {
    if (!this._closed) {
      this._closed = true;
      this._resolve?.(undefined as unknown as StreamEvent);
      this._resolve = null;
      this._bus._unsubscribe(this.id);
    }
  }

  get closed(): boolean {
    return this._closed;
  }

  async *[Symbol.asyncIterator](): AsyncGenerator<StreamEvent> {
    while (!this._closed) {
      const event = await this.get(1000);
      if (event !== undefined) yield event;
    }
  }
}

// ---------------------------------------------------------------------------
// EventBus
// ---------------------------------------------------------------------------

export class EventBus {
  private _subscriptions = new Map<string, Subscription>();
  private _replayBuffer: StreamEvent[] = [];
  private _eventCount = 0;
  private _counter = 0;

  constructor(
    private readonly maxBuffer = 1000,
    private readonly replaySize = 100,
  ) {}

  get subscriberCount(): number {
    return this._subscriptions.size;
  }

  get eventCount(): number {
    return this._eventCount;
  }

  subscribe(
    filterSpec?: StreamFilterSpec,
    bufferSize?: number,
    replay = false,
  ): Subscription {
    const id = `sub-${(++this._counter).toString(16).padStart(12, "0")}`;
    const filter = new StreamFilter(filterSpec);
    const sub = new Subscription(id, filter, this, bufferSize ?? this.maxBuffer);

    if (replay) {
      for (const event of this._replayBuffer) {
        if (filter.matches(event)) sub._deliver(event);
      }
    }

    this._subscriptions.set(id, sub);
    return sub;
  }

  /** Publish an event to all matching subscribers. Returns delivery count. */
  publish(event: StreamEvent): number {
    this._eventCount++;
    this._replayBuffer.push(event);
    if (this._replayBuffer.length > this.replaySize) {
      this._replayBuffer.shift();
    }

    let delivered = 0;
    for (const sub of this._subscriptions.values()) {
      if (!sub.closed && sub.filter.matches(event)) {
        if (sub._deliver(event)) delivered++;
      }
    }
    return delivered;
  }

  _unsubscribe(id: string): void {
    this._subscriptions.delete(id);
  }

  closeAll(): void {
    for (const sub of this._subscriptions.values()) {
      sub.close();
    }
    this._subscriptions.clear();
  }
}

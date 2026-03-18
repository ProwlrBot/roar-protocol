#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ROAR Protocol Performance Benchmark Suite.

Measures message throughput, signing overhead, discovery lookup,
hub registration, serialization speed, and memory usage.

Usage:
    python benchmarks/benchmark_suite.py [--iterations 1000] [--warmup 100] [--output results.json]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import tracemalloc
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python", "src"))

from roar_sdk.types import (  # noqa: E402
    AgentIdentity,
    DelegationToken,
    ROARMessage,
    StreamEvent,
    StreamEventType,
)
from roar_sdk.signing import sign_message, verify_message  # noqa: E402
from roar_sdk.hub import ROARHub  # noqa: E402
from roar_sdk.streaming import EventBus, StreamFilter  # noqa: E402


@dataclass
class BenchmarkResult:
    name: str
    iterations: int
    total_ms: float
    ops_per_sec: float
    p50_us: float
    p95_us: float
    p99_us: float
    memory_peak_kb: float
    memory_delta_kb: float


def _percentile(data: List[float], p: float) -> float:
    if not data:
        return 0.0
    k = (len(data) - 1) * (p / 100.0)
    f, c = int(k), int(k) + 1
    if c >= len(data):
        return data[f]
    return data[f] + (data[c] - data[f]) * (k - f)


def run_benchmark(
    name: str,
    fn: Callable[[], Any],
    iterations: int = 1000,
    warmup: int = 100,
) -> BenchmarkResult:
    """Run a benchmark function and collect metrics."""
    # Warmup
    for _ in range(warmup):
        fn()

    # Measure
    tracemalloc.start()
    mem_before = tracemalloc.get_traced_memory()[0]
    latencies: List[float] = []

    start_total = time.perf_counter()
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        fn()
        t1 = time.perf_counter_ns()
        latencies.append((t1 - t0) / 1000.0)  # microseconds
    end_total = time.perf_counter()

    mem_after, mem_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    total_ms = (end_total - start_total) * 1000.0
    latencies.sort()

    return BenchmarkResult(
        name=name,
        iterations=iterations,
        total_ms=round(total_ms, 2),
        ops_per_sec=round(iterations / (total_ms / 1000.0), 1),
        p50_us=round(_percentile(latencies, 50), 2),
        p95_us=round(_percentile(latencies, 95), 2),
        p99_us=round(_percentile(latencies, 99), 2),
        memory_peak_kb=round(mem_peak / 1024, 1),
        memory_delta_kb=round((mem_after - mem_before) / 1024, 1),
    )


# ---------------------------------------------------------------------------
# Benchmark functions
# ---------------------------------------------------------------------------

_alice = AgentIdentity(did="did:roar:agent:alice-bench01", display_name="Alice")
_bob = AgentIdentity(did="did:roar:agent:bob-bench02", display_name="Bob")
_secret = "benchmark-secret-key-for-hmac"


def bench_message_creation() -> None:
    ROARMessage(from_identity=_alice, to_identity=_bob, intent="ask", payload={"q": "ping"})


def bench_hmac_signing() -> None:
    msg = ROARMessage(from_identity=_alice, to_identity=_bob, intent="ask", payload={"q": "ping"})
    sign_message(msg, _secret)


def bench_hmac_sign_verify() -> None:
    msg = ROARMessage(from_identity=_alice, to_identity=_bob, intent="ask", payload={"q": "ping"})
    sign_message(msg, _secret)
    verify_message(msg, _secret)


def bench_message_serialization() -> None:
    msg = ROARMessage(from_identity=_alice, to_identity=_bob, intent="ask", payload={"q": "ping"})
    data = msg.model_dump_json()
    ROARMessage.model_validate_json(data)


def bench_canonical_json() -> None:
    msg = ROARMessage(
        from_identity=_alice,
        to_identity=_bob,
        intent="execute",
        payload={"command": "run", "args": [1, 2, 3], "nested": {"key": "value"}},
    )
    json.dumps(
        {
            "id": msg.id,
            "from": msg.from_identity.did,
            "to": msg.to_identity.did,
            "intent": msg.intent,
            "payload": msg.payload,
            "context": msg.context,
            "timestamp": msg.timestamp,
        },
        sort_keys=True,
        separators=(", ", ": "),
    )


# Hub benchmarks — use a shared hub instance
_hub = ROARHub.__new__(ROARHub)
_hub._directory = {}
_hub._peers = []
_hub._federation_secret = ""

_cards_registered: List[str] = []


def _setup_hub(n: int) -> None:
    """Pre-populate hub with n agents."""
    from roar_sdk.types import AgentCard

    _hub._directory = {}
    for i in range(n):
        did = f"did:roar:agent:bench-{i:06d}"
        card = AgentCard(
            identity=AgentIdentity(
                did=did,
                display_name=f"Agent-{i}",
                capabilities=[f"skill-{i % 10}", f"group-{i % 50}"],
            ),
            description=f"Benchmark agent {i}",
        )
        _hub._directory[did] = card


def bench_hub_register_lookup() -> None:
    from roar_sdk.types import AgentCard

    did = f"did:roar:agent:reg-{time.perf_counter_ns()}"
    card = AgentCard(
        identity=AgentIdentity(did=did, display_name="Reg-Test"),
        description="test",
    )
    _hub._directory[did] = card
    _ = _hub._directory.get(did)
    del _hub._directory[did]


def bench_hub_search_100() -> None:
    results = [c for c in _hub._directory.values() if "skill-5" in c.identity.capabilities]
    _ = len(results)


def bench_hub_search_1000() -> None:
    results = [c for c in _hub._directory.values() if "skill-5" in c.identity.capabilities]
    _ = len(results)


def bench_hub_search_10000() -> None:
    results = [c for c in _hub._directory.values() if "skill-5" in c.identity.capabilities]
    _ = len(results)


# Replay detection benchmark
_seen: dict = {}
_seen_order: list = []
_MAX_SEEN = 10_000


def bench_replay_detection() -> None:
    msg_id = f"msg_{time.perf_counter_ns()}"
    if msg_id in _seen:
        return
    _seen[msg_id] = True
    _seen_order.append(msg_id)
    while len(_seen_order) > _MAX_SEEN:
        oldest = _seen_order.pop(0)
        _seen.pop(oldest, None)


# Stream benchmark
import asyncio

_bus = EventBus()


def bench_stream_publish() -> None:
    event = StreamEvent(
        type=StreamEventType.TASK_UPDATE,
        source="did:roar:agent:bench",
        session_id="s1",
        data={"progress": 0.5},
    )
    loop = asyncio.new_event_loop()
    loop.run_until_complete(_bus.publish(event))
    loop.close()


# Delegation token benchmark
def bench_delegation_token_create() -> None:
    token = DelegationToken(
        delegator_did=_alice.did,
        delegate_did=_bob.did,
        capabilities=["execute", "ask"],
    )
    _ = token.model_dump_json()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="ROAR Protocol Benchmark Suite")
    parser.add_argument("--iterations", "-n", type=int, default=1000)
    parser.add_argument("--warmup", "-w", type=int, default=100)
    parser.add_argument("--output", "-o", type=str, default="")
    args = parser.parse_args()

    n = args.iterations
    w = args.warmup

    print(f"ROAR Protocol Benchmark Suite — {n} iterations, {w} warmup\n")
    print(f"{'Benchmark':<40} {'ops/sec':>10} {'P50 µs':>10} {'P95 µs':>10} {'P99 µs':>10}")
    print("-" * 85)

    results: List[BenchmarkResult] = []

    benchmarks = [
        ("Message Creation", bench_message_creation),
        ("HMAC-SHA256 Signing", bench_hmac_signing),
        ("HMAC Sign+Verify Cycle", bench_hmac_sign_verify),
        ("Message Serialization (JSON)", bench_message_serialization),
        ("Canonical JSON Generation", bench_canonical_json),
        ("Hub Register+Lookup", bench_hub_register_lookup),
        ("Replay Detection (10K cache)", bench_replay_detection),
        ("Delegation Token Create", bench_delegation_token_create),
    ]

    for name, fn in benchmarks:
        r = run_benchmark(name, fn, n, w)
        results.append(r)
        print(f"{r.name:<40} {r.ops_per_sec:>10,.0f} {r.p50_us:>10.1f} {r.p95_us:>10.1f} {r.p99_us:>10.1f}")

    # Hub search benchmarks at different scales
    for scale, bench_fn in [
        (100, bench_hub_search_100),
        (1000, bench_hub_search_1000),
        (10000, bench_hub_search_10000),
    ]:
        _setup_hub(scale)
        r = run_benchmark(f"Hub Search ({scale} agents)", bench_fn, min(n, 500), w)
        results.append(r)
        print(f"{r.name:<40} {r.ops_per_sec:>10,.0f} {r.p50_us:>10.1f} {r.p95_us:>10.1f} {r.p99_us:>10.1f}")

    print()
    print("Memory Usage:")
    for r in results:
        if r.memory_delta_kb > 0:
            print(f"  {r.name}: peak={r.memory_peak_kb:.0f}KB, delta={r.memory_delta_kb:.0f}KB")

    if args.output:
        output = {
            "suite": "roar-protocol-benchmarks",
            "timestamp": time.time(),
            "iterations": n,
            "warmup": w,
            "results": [asdict(r) for r in results],
        }
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()

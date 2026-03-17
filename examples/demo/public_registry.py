#!/usr/bin/env python3
"""ROAR Protocol Demo — Public Agent Discovery Registry.

Starts a public registry on port 8095 that aggregates agents from one or
more ROAR hubs and makes them searchable.

Prerequisites:
    1. Start a hub first:  python examples/demo/hub.py   (port 8090)
    2. Register some agents with the hub (e.g. run agent_a.py / agent_b.py)
    3. Then run this script:  python examples/demo/public_registry.py

The registry will pull agents from the local hub and expose them via:

    GET  /registry/agents           — paginated agent list
    GET  /registry/agents/{did}     — single agent lookup
    GET  /registry/search?q=<text>  — full-text search
    GET  /registry/hubs             — registered hubs
    GET  /registry/stats            — statistics
    GET  /registry/health           — health check
    GET  /.well-known/roar-registry.json — machine-readable metadata
"""
import sys
import io

# ── Windows encoding fix ─────────────────────────────────────────────────
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import asyncio
import json

from roar_sdk.registry import PublicRegistry


async def main() -> None:
    print("""
+==============================================================+
|              ROAR PUBLIC AGENT DISCOVERY REGISTRY             |
|                                                               |
|  Aggregates agents from multiple hubs into one searchable     |
|  directory.  Anyone on the internet can query it.             |
|                                                               |
|  Endpoints:                                                   |
|    GET  /registry/agents           - list agents              |
|    GET  /registry/agents/{did}     - lookup agent             |
|    GET  /registry/search?q=<text>  - full-text search         |
|    GET  /registry/hubs             - list hubs                |
|    POST /registry/hubs             - add hub (admin)          |
|    GET  /registry/stats            - statistics               |
|    GET  /registry/health           - health check             |
|    GET  /.well-known/roar-registry.json - metadata            |
|                                                               |
|  Listening on http://127.0.0.1:8095                           |
+==============================================================+
""")

    # Create the registry
    registry = PublicRegistry(
        host="127.0.0.1",
        port=8095,
        registry_name="ROAR Demo Registry",
        admin_api_key="demo-admin-key",
    )

    # Register the local hub as a source
    local_hub = "http://127.0.0.1:8090"
    registry.register_hub(local_hub)
    print(f"[registry] Registered hub: {local_hub}")

    # Pull agents from the hub
    print(f"[registry] Pulling agents from {local_hub} ...")
    try:
        results = await registry.pull_from_hubs()
        for hub_url, result in results.items():
            if "error" in result:
                print(f"[registry]   {hub_url}: ERROR - {result['error']}")
                print(f"[registry]   (Is the hub running? Start it with: python examples/demo/hub.py)")
            else:
                print(f"[registry]   {hub_url}: imported {result['imported']} agents")
    except ImportError:
        print("[registry]   httpx not installed - skipping pull.")
        print("[registry]   Install with: pip install httpx")

    # Show current stats
    stats = registry.get_stats()
    print(f"\n[registry] Stats:")
    print(f"  Total agents: {stats['total_agents']}")
    print(f"  Total hubs:   {stats['total_hubs']}")
    if stats["by_capability"]:
        print(f"  By capability: {json.dumps(stats['by_capability'], indent=4)}")
    if stats["by_protocol"]:
        print(f"  By protocol:   {json.dumps(stats['by_protocol'], indent=4)}")

    # Show search results if there are agents
    if stats["total_agents"] > 0:
        print(f"\n[registry] All agents:")
        for entry in registry.search(limit=50):
            card = entry.agent_card
            print(f"  - {card.identity.display_name} ({card.identity.did})")
            print(f"    Hub: {entry.hub_url}")
            print(f"    Capabilities: {card.identity.capabilities}")
            print(f"    Protocols: {entry.protocols_supported}")

    # Show well-known metadata
    meta = registry.well_known_metadata()
    print(f"\n[registry] Well-known metadata:")
    print(f"  {json.dumps(meta, indent=2)}")

    # Start the server (blocking)
    print("\n[registry] Starting HTTP server ...\n")
    registry.serve()


if __name__ == "__main__":
    asyncio.run(main())

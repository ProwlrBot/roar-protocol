#!/usr/bin/env python3
"""ROAR Protocol Demo — Hub (Discovery Server).

Run this FIRST in Terminal 1. The hub lets agents register and find each other.

Usage:
    python examples/demo/hub.py

Then run agent_a.py and agent_b.py in separate terminals.
"""
import sys, io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from roar_sdk import ROARHub

print("""
╔══════════════════════════════════════════════════════════════╗
║                    ROAR DISCOVERY HUB                       ║
║                                                             ║
║  Agents register here, then discover each other.            ║
║                                                             ║
║  Endpoints:                                                 ║
║    POST /roar/agents/register   — begin registration        ║
║    POST /roar/agents/challenge  — complete registration     ║
║    GET  /roar/agents            — list all agents           ║
║    GET  /roar/agents/search?capability=X — search           ║
║    GET  /roar/health            — health check              ║
║                                                             ║
║  Listening on http://127.0.0.1:8090                         ║
╚══════════════════════════════════════════════════════════════╝
""")

hub = ROARHub(host="127.0.0.1", port=8090)
hub.serve()

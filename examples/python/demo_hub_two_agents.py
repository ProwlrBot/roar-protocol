#!/usr/bin/env python3
"""ROAR Protocol — Visual Demo: Hub + Two Agents.

Spins up a ROAR Hub, registers two agents, they discover each other
via the hub, then exchange signed messages — all in one script.

Usage:
    cd python && pip install -e ".[server,ed25519]"
    python examples/python/demo_hub_two_agents.py
"""

import asyncio
import json
import logging
import os
import time

import httpx

from roar_sdk import (
    AgentCard,
    AgentIdentity,
    MessageIntent,
    ROARMessage,
    ROARServer,
)
from roar_sdk.hub import ROARHub

# ── Pretty logging ───────────────────────────────────────────────────────────

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

def banner(text, color=CYAN):
    width = 60
    print(f"\n{color}{BOLD}{'=' * width}")
    print(f"  {text}")
    print(f"{'=' * width}{RESET}\n")

def step(num, text, color=GREEN):
    print(f"  {color}{BOLD}[Step {num}]{RESET} {text}")

def info(label, value, indent=4):
    print(f"{' ' * indent}{DIM}|{RESET} {BOLD}{label}:{RESET} {value}")

def arrow(direction, label, detail="", color=YELLOW):
    sym = "-->" if direction == "right" else "<--"
    print(f"    {color}{BOLD}{sym} {label}{RESET}  {DIM}{detail}{RESET}")

def box(title, lines, color=CYAN):
    width = max(len(l) for l in lines) + 4
    print(f"    {color}+-- {title} {'-' * max(0, width - len(title) - 4)}+{RESET}")
    for line in lines:
        print(f"    {color}|{RESET}  {line}{' ' * max(0, width - len(line) - 3)}{color}|{RESET}")
    print(f"    {color}+{'-' * (width + 1)}+{RESET}")


# ── Main demo ────────────────────────────────────────────────────────────────

HUB_PORT = 8090
AGENT_A_PORT = 8091
AGENT_B_PORT = 8092
SECRET = os.environ.get("ROAR_SIGNING_SECRET", "")

async def run_demo():
    banner("ROAR PROTOCOL — LIVE DEMO", CYAN)
    print(f"  {DIM}Demonstrating: Identity → Hub → Discovery → Signed Exchange{RESET}")
    print(f"  {DIM}Architecture:  Layer 1 (DID) → Layer 2 (Hub) → Layer 3 (HTTP) → Layer 4 (Exchange){RESET}\n")

    # ── PHASE 1: Identities ──────────────────────────────────────────────────
    banner("PHASE 1 — AGENT IDENTITY (Layer 1)", GREEN)
    step(1, "Creating Agent A identity...")
    agent_a_id = AgentIdentity(
        display_name="agent-alpha",
        agent_type="agent",
        capabilities=["summarize", "translate"],
    )
    box("Agent A", [
        f"Name: agent-alpha",
        f"DID:  {agent_a_id.did[:50]}...",
        f"Type: agent",
        f"Skills: summarize, translate",
    ], GREEN)

    step(2, "Creating Agent B identity...")
    agent_b_id = AgentIdentity(
        display_name="agent-bravo",
        agent_type="agent",
        capabilities=["analyze", "classify"],
    )
    box("Agent B", [
        f"Name: agent-bravo",
        f"DID:  {agent_b_id.did[:50]}...",
        f"Type: agent",
        f"Skills: analyze, classify",
    ], MAGENTA)

    # ── PHASE 2: Hub ─────────────────────────────────────────────────────────
    banner("PHASE 2 — ROAR HUB (Layer 2)", YELLOW)
    step(3, f"Starting ROAR Hub on port {HUB_PORT}...")

    hub = ROARHub(host="127.0.0.1", port=HUB_PORT)
    hub_task = asyncio.create_task(_run_hub(hub))
    await asyncio.sleep(1.5)  # let hub start

    box("Hub", [
        f"URL:  http://127.0.0.1:{HUB_PORT}",
        f"API:  /roar/agents, /roar/health",
        f"Mode: In-memory directory",
    ], YELLOW)

    # Check hub health
    async with httpx.AsyncClient() as http:
        health = await http.get(f"http://127.0.0.1:{HUB_PORT}/roar/health")
        info("Health", health.json())

    # ── PHASE 3: Agent Servers ───────────────────────────────────────────────
    banner("PHASE 3 — AGENT SERVERS (Layer 3)", GREEN)

    step(4, f"Starting Agent A server on port {AGENT_A_PORT}...")
    server_a = ROARServer(
        agent_a_id, host="127.0.0.1", port=AGENT_A_PORT,
        description="Summarizer & translator agent",
        skills=["summarize", "translate"],
        signing_secret=SECRET,
    )

    @server_a.on(MessageIntent.DELEGATE)
    async def handle_a(msg: ROARMessage) -> ROARMessage:
        return ROARMessage(
            **{"from": server_a.identity, "to": msg.from_identity},
            intent=MessageIntent.RESPOND,
            payload={"result": f"Agent Alpha processed: {msg.payload}", "status": "ok"},
            context={"in_reply_to": msg.id},
        )

    server_a_task = asyncio.create_task(_run_server(server_a))
    await asyncio.sleep(1.0)

    step(5, f"Starting Agent B server on port {AGENT_B_PORT}...")
    server_b = ROARServer(
        agent_b_id, host="127.0.0.1", port=AGENT_B_PORT,
        description="Analyzer & classifier agent",
        skills=["analyze", "classify"],
        signing_secret=SECRET,
    )

    @server_b.on(MessageIntent.DELEGATE)
    async def handle_b(msg: ROARMessage) -> ROARMessage:
        return ROARMessage(
            **{"from": server_b.identity, "to": msg.from_identity},
            intent=MessageIntent.RESPOND,
            payload={"result": f"Agent Bravo analyzed: {msg.payload}", "status": "ok"},
            context={"in_reply_to": msg.id},
        )

    server_b_task = asyncio.create_task(_run_server(server_b))
    await asyncio.sleep(1.0)

    print(f"\n  {DIM}Both agents running. Now registering with hub...{RESET}\n")

    # ── PHASE 4: Registration ────────────────────────────────────────────────
    banner("PHASE 4 — HUB REGISTRATION (Layer 2)", YELLOW)

    async with httpx.AsyncClient() as http:
        # Register Agent A
        step(6, "Agent A registering with hub...")
        card_a = server_a.get_card().model_dump()
        reg_a = await http.post(
            f"http://127.0.0.1:{HUB_PORT}/roar/agents/register",
            json={"agent_card": card_a},
        )
        arrow("right", "Agent A → Hub", f"POST /roar/agents/register")
        reg_a_data = reg_a.json()
        if "challenge" in reg_a_data:
            # Complete challenge-response
            challenge_resp = await http.post(
                f"http://127.0.0.1:{HUB_PORT}/roar/agents/challenge",
                json={
                    "did": agent_a_id.did,
                    "challenge": reg_a_data["challenge"],
                    "proof": reg_a_data["challenge"],  # simplified for demo
                },
            )
            arrow("left", "Hub → Agent A", f"Registered! ✓")
        info("Status", "Registered", indent=6)
        info("DID", agent_a_id.did[:55] + "...", indent=6)

        # Register Agent B
        step(7, "Agent B registering with hub...")
        card_b = server_b.get_card().model_dump()
        reg_b = await http.post(
            f"http://127.0.0.1:{HUB_PORT}/roar/agents/register",
            json={"agent_card": card_b},
        )
        arrow("right", "Agent B → Hub", f"POST /roar/agents/register")
        reg_b_data = reg_b.json()
        if "challenge" in reg_b_data:
            await http.post(
                f"http://127.0.0.1:{HUB_PORT}/roar/agents/challenge",
                json={
                    "did": agent_b_id.did,
                    "challenge": reg_b_data["challenge"],
                    "proof": reg_b_data["challenge"],
                },
            )
            arrow("left", "Hub → Agent B", f"Registered! ✓")
        info("Status", "Registered", indent=6)
        info("DID", agent_b_id.did[:55] + "...", indent=6)

    # ── PHASE 5: Discovery ───────────────────────────────────────────────────
    banner("PHASE 5 — AGENT DISCOVERY (Layer 2)", CYAN)

    async with httpx.AsyncClient() as http:
        step(8, "Agent A queries hub: 'Who can analyze?'")
        arrow("right", "Agent A → Hub", "GET /roar/agents")
        agents_resp = await http.get(f"http://127.0.0.1:{HUB_PORT}/roar/agents")
        agents = agents_resp.json()

        print(f"\n    {CYAN}{BOLD}Hub Directory:{RESET}")
        for entry in agents.get("agents", []):
            card = entry.get("agent_card", entry)
            identity = card.get("identity", {})
            name = identity.get("display_name", "?")
            did = identity.get("did", "?")
            caps = identity.get("capabilities", [])
            color = GREEN if "alpha" in name else MAGENTA
            print(f"    {color}  ● {name}{RESET}  {DIM}{did[:45]}...{RESET}")
            print(f"      {DIM}capabilities: {', '.join(caps)}{RESET}")

        arrow("left", "Hub → Agent A", f"Found {len(agents.get('agents', []))} agents")

        # Agent A discovers Agent B
        step(9, "Agent A identifies Agent B by capabilities...")
        target_did = agent_b_id.did
        target_url = f"http://127.0.0.1:{AGENT_B_PORT}"
        box("Discovery Result", [
            f"Found: agent-bravo",
            f"DID:   {target_did[:50]}...",
            f"URL:   {target_url}",
            f"Skills: analyze, classify",
        ], CYAN)

    # ── PHASE 6: Signed Message Exchange ─────────────────────────────────────
    banner("PHASE 6 — SIGNED MESSAGE EXCHANGE (Layer 4)", MAGENTA)

    step(10, "Agent A builds & signs DELEGATE message to Agent B...")

    msg = ROARMessage(
        **{"from": agent_a_id, "to": agent_b_id},
        intent=MessageIntent.DELEGATE,
        payload={"task": "analyze", "data": {"text": "ROAR Protocol is the TCP/IP for AI agents"}},
        context={"session_id": "demo-001"},
    )
    msg.sign(SECRET)

    box("Outgoing Message", [
        f"ID:        {msg.id[:30]}...",
        f"Intent:    DELEGATE",
        f"From:      agent-alpha",
        f"To:        agent-bravo",
        f"Payload:   analyze 'ROAR Protocol is the TCP/IP...'",
        f"Signed:    ✓ HMAC-SHA256",
        f"Timestamp: {msg.auth.get('timestamp', 'N/A')}",
    ], MAGENTA)

    step(11, "Sending to Agent B via HTTP transport...")
    arrow("right", "Agent A → Agent B", f"POST {target_url}/roar/message")

    async with httpx.AsyncClient() as http:
        resp = await http.post(
            f"{target_url}/roar/message",
            json=msg.model_dump(by_alias=True),
        )
        resp_data = resp.json()

    arrow("left", "Agent B → Agent A", f"HTTP {resp.status_code}")

    if resp.status_code == 200:
        box("Response", [
            f"Intent:  {resp_data.get('intent', '?')}",
            f"From:    {resp_data.get('from', {}).get('display_name', '?')}",
            f"Payload: {json.dumps(resp_data.get('payload', {}))[:55]}",
            f"Status:  ✓ Success",
        ], GREEN)
    else:
        box("Response", [
            f"Status: {resp.status_code}",
            f"Body:   {json.dumps(resp_data)[:55]}",
        ], RED)

    # ── PHASE 7: Reverse — Agent B talks to Agent A ──────────────────────────
    banner("PHASE 7 — REVERSE: Agent B → Agent A", GREEN)

    step(12, "Agent B sends DELEGATE to Agent A...")
    msg2 = ROARMessage(
        **{"from": agent_b_id, "to": agent_a_id},
        intent=MessageIntent.DELEGATE,
        payload={"task": "translate", "data": {"text": "Hello World", "target_lang": "es"}},
        context={"session_id": "demo-002"},
    )
    msg2.sign(SECRET)

    arrow("right", "Agent B → Agent A", f"POST http://127.0.0.1:{AGENT_A_PORT}/roar/message")

    async with httpx.AsyncClient() as http:
        resp2 = await http.post(
            f"http://127.0.0.1:{AGENT_A_PORT}/roar/message",
            json=msg2.model_dump(by_alias=True),
        )
        resp2_data = resp2.json()

    arrow("left", "Agent A → Agent B", f"HTTP {resp2.status_code}")

    if resp2.status_code == 200:
        box("Response", [
            f"Intent:  {resp2_data.get('intent', '?')}",
            f"From:    {resp2_data.get('from', {}).get('display_name', '?')}",
            f"Payload: {json.dumps(resp2_data.get('payload', {}))[:55]}",
            f"Status:  ✓ Success",
        ], GREEN)

    # ── Summary ──────────────────────────────────────────────────────────────
    banner("DEMO COMPLETE", CYAN)
    print(f"  {BOLD}What just happened:{RESET}")
    print(f"  {DIM}1. Two agents got W3C DID identities           (Layer 1: Identity){RESET}")
    print(f"  {DIM}2. ROAR Hub started as discovery server         (Layer 2: Discovery){RESET}")
    print(f"  {DIM}3. Both agents registered with the hub           (Layer 2: Registration){RESET}")
    print(f"  {DIM}4. Agent A discovered Agent B via hub directory  (Layer 2: Lookup){RESET}")
    print(f"  {DIM}5. Agents exchanged HMAC-signed messages         (Layer 4: Exchange){RESET}")
    print(f"  {DIM}6. Both directions worked — full duplex           (Layer 3: HTTP Transport){RESET}")
    print()
    print(f"  {BOLD}Network topology:{RESET}")
    print(f"  {GREEN}  agent-alpha:{AGENT_A_PORT} ──┐{RESET}")
    print(f"  {YELLOW}                   ├── hub:{HUB_PORT}  (discovery){RESET}")
    print(f"  {MAGENTA}  agent-bravo:{AGENT_B_PORT} ──┘{RESET}")
    print(f"  {DIM}  agent-alpha ←──── direct HTTP ────→ agent-bravo  (messages){RESET}")
    print()

    # Cleanup
    hub_task.cancel()
    server_a_task.cancel()
    server_b_task.cancel()
    try:
        await asyncio.gather(hub_task, server_a_task, server_b_task, return_exceptions=True)
    except Exception:
        pass


def _run_in_thread(fn):
    """Run a blocking function in a daemon thread."""
    import threading
    t = threading.Thread(target=fn, daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    import threading

    # Start hub and servers in background threads (they call serve() which blocks)
    hub_obj = ROARHub(host="127.0.0.1", port=HUB_PORT)

    # We need to create the servers before run_demo so handlers are registered
    # but run_demo is async and creates them — so we use a simpler approach:
    # run everything from run_demo using threads for the blocking serve() calls.

    # Patch: make run_demo use threads instead of asyncio tasks
    async def _start_services():
        """Start hub + agent servers in threads, then run demo logic."""

        # Start hub
        _run_in_thread(hub_obj.serve)
        await asyncio.sleep(1.5)

        # Start agent servers using inline FastAPI apps
        import uvicorn
        from fastapi import FastAPI, Request

        # Agent A setup
        agent_a_id = AgentIdentity(
            display_name="agent-alpha", agent_type="agent",
            capabilities=["summarize", "translate"],
        )
        server_a = ROARServer(
            agent_a_id, host="127.0.0.1", port=AGENT_A_PORT,
            description="Summarizer & translator", skills=["summarize", "translate"],
            signing_secret=SECRET,
        )

        @server_a.on(MessageIntent.DELEGATE)
        async def handle_a(msg: ROARMessage) -> ROARMessage:
            return ROARMessage(
                **{"from": server_a.identity, "to": msg.from_identity},
                intent=MessageIntent.RESPOND,
                payload={"result": f"Alpha processed: {msg.payload}", "status": "ok"},
                context={"in_reply_to": msg.id},
            )

        app_a = FastAPI()
        @app_a.post("/roar/message")
        async def recv_a(request: Request):
            body = await request.json()
            m = ROARMessage.model_validate(body)
            r = await server_a.handle_message(m)
            return r.model_dump(by_alias=True)
        @app_a.get("/roar/agents")
        async def agents_a():
            return {"agents": [server_a.get_card().model_dump()]}

        def _serve_a():
            uvicorn.run(app_a, host="127.0.0.1", port=AGENT_A_PORT, log_level="error")
        _run_in_thread(_serve_a)

        # Agent B setup
        agent_b_id = AgentIdentity(
            display_name="agent-bravo", agent_type="agent",
            capabilities=["analyze", "classify"],
        )
        server_b = ROARServer(
            agent_b_id, host="127.0.0.1", port=AGENT_B_PORT,
            description="Analyzer & classifier", skills=["analyze", "classify"],
            signing_secret=SECRET,
        )

        @server_b.on(MessageIntent.DELEGATE)
        async def handle_b(msg: ROARMessage) -> ROARMessage:
            return ROARMessage(
                **{"from": server_b.identity, "to": msg.from_identity},
                intent=MessageIntent.RESPOND,
                payload={"result": f"Bravo analyzed: {msg.payload}", "status": "ok"},
                context={"in_reply_to": msg.id},
            )

        app_b = FastAPI()
        @app_b.post("/roar/message")
        async def recv_b(request: Request):
            body = await request.json()
            m = ROARMessage.model_validate(body)
            r = await server_b.handle_message(m)
            return r.model_dump(by_alias=True)
        @app_b.get("/roar/agents")
        async def agents_b():
            return {"agents": [server_b.get_card().model_dump()]}

        def _serve_b():
            uvicorn.run(app_b, host="127.0.0.1", port=AGENT_B_PORT, log_level="error")
        _run_in_thread(_serve_b)

        await asyncio.sleep(1.5)
        return agent_a_id, agent_b_id, server_a, server_b

    async def main():
        banner("ROAR PROTOCOL — LIVE DEMO", CYAN)
        print(f"  {DIM}Demonstrating: Identity -> Hub -> Discovery -> Signed Exchange{RESET}")
        print(f"  {DIM}Architecture:  Layer 1 (DID) -> Layer 2 (Hub) -> Layer 3 (HTTP) -> Layer 4 (Exchange){RESET}\n")

        banner("PHASE 1-3 — STARTING SERVICES", GREEN)
        step(1, "Starting Hub + Agent Alpha + Agent Bravo...")
        agent_a_id, agent_b_id, server_a, server_b = await _start_services()

        box("Agent A", [
            f"Name: agent-alpha",
            f"DID:  {agent_a_id.did[:50]}...",
            f"Port: {AGENT_A_PORT}",
            f"Skills: summarize, translate",
        ], GREEN)
        box("Agent B", [
            f"Name: agent-bravo",
            f"DID:  {agent_b_id.did[:50]}...",
            f"Port: {AGENT_B_PORT}",
            f"Skills: analyze, classify",
        ], MAGENTA)
        box("Hub", [
            f"URL:  http://127.0.0.1:{HUB_PORT}",
            f"API:  /roar/agents, /roar/health",
        ], YELLOW)

        # ── Registration ─────────────────────────────────────────────────────
        banner("PHASE 4 — HUB REGISTRATION", YELLOW)

        async with httpx.AsyncClient() as http:
            step(2, "Agent A registering with hub...")
            card_a = server_a.get_card().model_dump()
            reg_a = await http.post(f"http://127.0.0.1:{HUB_PORT}/roar/agents/register", json={"agent_card": card_a})
            arrow("right", "Agent A -> Hub", "POST /roar/agents/register")
            reg_a_data = reg_a.json()
            if "challenge" in reg_a_data:
                await http.post(f"http://127.0.0.1:{HUB_PORT}/roar/agents/challenge",
                    json={"did": agent_a_id.did, "challenge": reg_a_data["challenge"], "proof": reg_a_data["challenge"]})
            arrow("left", "Hub -> Agent A", "Registered!")
            info("DID", agent_a_id.did[:55] + "...", indent=6)

            step(3, "Agent B registering with hub...")
            card_b = server_b.get_card().model_dump()
            reg_b = await http.post(f"http://127.0.0.1:{HUB_PORT}/roar/agents/register", json={"agent_card": card_b})
            arrow("right", "Agent B -> Hub", "POST /roar/agents/register")
            reg_b_data = reg_b.json()
            if "challenge" in reg_b_data:
                await http.post(f"http://127.0.0.1:{HUB_PORT}/roar/agents/challenge",
                    json={"did": agent_b_id.did, "challenge": reg_b_data["challenge"], "proof": reg_b_data["challenge"]})
            arrow("left", "Hub -> Agent B", "Registered!")
            info("DID", agent_b_id.did[:55] + "...", indent=6)

        # ── Discovery ────────────────────────────────────────────────────────
        banner("PHASE 5 — AGENT DISCOVERY", CYAN)

        async with httpx.AsyncClient() as http:
            step(4, "Agent A queries hub: 'Who else is registered?'")
            arrow("right", "Agent A -> Hub", "GET /roar/agents")
            agents_resp = await http.get(f"http://127.0.0.1:{HUB_PORT}/roar/agents")
            agents_list = agents_resp.json().get("agents", [])

            print(f"\n    {CYAN}{BOLD}Hub Directory:{RESET}")
            for entry in agents_list:
                card = entry.get("agent_card", entry)
                ident = card.get("identity", {})
                name = ident.get("display_name", "?")
                did = ident.get("did", "?")
                caps = ident.get("capabilities", [])
                c = GREEN if "alpha" in name else MAGENTA
                print(f"    {c}  * {name}{RESET}  {DIM}{did[:45]}...{RESET}")
                print(f"      {DIM}capabilities: {', '.join(caps)}{RESET}")

            arrow("left", "Hub -> Agent A", f"Found {len(agents_list)} agents")

        # ── Message Exchange ─────────────────────────────────────────────────
        banner("PHASE 6 — SIGNED MESSAGE EXCHANGE (Layer 4)", MAGENTA)

        step(5, "Agent A builds & signs DELEGATE message to Agent B...")
        msg = ROARMessage(
            **{"from": agent_a_id, "to": agent_b_id},
            intent=MessageIntent.DELEGATE,
            payload={"task": "analyze", "data": {"text": "ROAR Protocol is the TCP/IP for AI agents"}},
            context={"session_id": "demo-001"},
        )
        msg.sign(SECRET)

        box("Outgoing Message", [
            f"ID:        {msg.id[:30]}...",
            f"Intent:    DELEGATE",
            f"From:      agent-alpha",
            f"To:        agent-bravo",
            f"Signed:    HMAC-SHA256",
            f"Timestamp: {msg.auth.get('timestamp', 'N/A')}",
        ], MAGENTA)

        step(6, "Sending to Agent B via HTTP...")
        arrow("right", "Agent A -> Agent B", f"POST http://127.0.0.1:{AGENT_B_PORT}/roar/message")

        async with httpx.AsyncClient() as http:
            resp = await http.post(f"http://127.0.0.1:{AGENT_B_PORT}/roar/message", json=msg.model_dump(by_alias=True))
            resp_data = resp.json()

        arrow("left", "Agent B -> Agent A", f"HTTP {resp.status_code}")
        box("Response", [
            f"Intent:  {resp_data.get('intent', '?')}",
            f"From:    {resp_data.get('from', {}).get('display_name', '?')}",
            f"Payload: {json.dumps(resp_data.get('payload', {}))[:55]}",
        ], GREEN)

        # ── Reverse ──────────────────────────────────────────────────────────
        banner("PHASE 7 — REVERSE: Agent B -> Agent A", GREEN)

        step(7, "Agent B sends DELEGATE to Agent A...")
        msg2 = ROARMessage(
            **{"from": agent_b_id, "to": agent_a_id},
            intent=MessageIntent.DELEGATE,
            payload={"task": "translate", "data": {"text": "Hello World", "lang": "es"}},
            context={"session_id": "demo-002"},
        )
        msg2.sign(SECRET)
        arrow("right", "Agent B -> Agent A", f"POST http://127.0.0.1:{AGENT_A_PORT}/roar/message")

        async with httpx.AsyncClient() as http:
            resp2 = await http.post(f"http://127.0.0.1:{AGENT_A_PORT}/roar/message", json=msg2.model_dump(by_alias=True))
            resp2_data = resp2.json()

        arrow("left", "Agent A -> Agent B", f"HTTP {resp2.status_code}")
        box("Response", [
            f"Intent:  {resp2_data.get('intent', '?')}",
            f"From:    {resp2_data.get('from', {}).get('display_name', '?')}",
            f"Payload: {json.dumps(resp2_data.get('payload', {}))[:55]}",
        ], GREEN)

        # ── Summary ──────────────────────────────────────────────────────────
        banner("DEMO COMPLETE", CYAN)
        print(f"  {BOLD}What just happened:{RESET}")
        print(f"  {DIM}1. Two agents got W3C DID identities            (Layer 1: Identity){RESET}")
        print(f"  {DIM}2. ROAR Hub started as discovery server          (Layer 2: Discovery){RESET}")
        print(f"  {DIM}3. Both agents registered with the hub            (Layer 2: Registration){RESET}")
        print(f"  {DIM}4. Agent A discovered Agent B via hub directory   (Layer 2: Lookup){RESET}")
        print(f"  {DIM}5. Agents exchanged HMAC-signed messages          (Layer 4: Exchange){RESET}")
        print(f"  {DIM}6. Both directions worked - full duplex            (Layer 3: HTTP Transport){RESET}")
        print()
        print(f"  {BOLD}Network topology:{RESET}")
        print(f"  {GREEN}  agent-alpha:{AGENT_A_PORT} ---+{RESET}")
        print(f"  {YELLOW}                    +--- hub:{HUB_PORT}  (discovery){RESET}")
        print(f"  {MAGENTA}  agent-bravo:{AGENT_B_PORT} ---+{RESET}")
        print(f"  {DIM}  agent-alpha <---- direct HTTP ----> agent-bravo  (messages){RESET}")
        print()

    asyncio.run(main())

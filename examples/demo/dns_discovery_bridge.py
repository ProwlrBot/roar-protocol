#!/usr/bin/env python3
"""ROAR Protocol Demo — DNS Discovery + Protocol Bridge.

Simulates the full flow: DNS-AID lookup, DID Document resolution,
hub discovery, agent discovery, and a bridged A2A-to-ROAR exchange.
No HTTP servers or DNS queries — shows what each layer looks like.

Usage:
    python examples/demo/dns_discovery_bridge.py
"""
import sys, io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import json
from roar_sdk import (
    AgentIdentity, AgentCard, AgentCapability,
    MessageIntent, ROARMessage, A2AAdapter,
    DIDDocument, VerificationMethod, ServiceEndpoint,
)
from roar_sdk.adapters.detect import detect_protocol, ProtocolType

# ── Identities ────────────────────────────────────────────────────────────
agent_a = AgentIdentity(
    did="did:web:agents.example.com:agent-a",
    display_name="agent-a-coder", agent_type="agent",
    capabilities=["code-review", "python", "debugging"],
)
agent_b = AgentIdentity(
    did="did:web:tools.example.org:agent-b",
    display_name="agent-b-tester", agent_type="agent",
    capabilities=["testing", "qa"],
)
hub_identity = AgentIdentity(
    did="did:web:hub.example.com",
    display_name="roar-hub", agent_type="agent",
    capabilities=["discovery", "routing"],
)

def section(title: str) -> None:
    print(f"\n{'─' * 64}")
    print(f"  {title}")
    print(f"{'─' * 64}")

def show_json(label: str, obj: object) -> None:
    print(f"  {label}:")
    for line in json.dumps(obj, indent=2).splitlines():
        print(f"    {line}")

def show_text(label: str, text: str) -> None:
    print(f"  {label}:")
    for line in text.strip().splitlines():
        print(f"    {line}")

# ══════════════════════════════════════════════════════════════════════════
print("""
╔══════════════════════════════════════════════════════════════╗
║   ROAR DEMO: DNS Discovery ──► Protocol Bridge ──► Response  ║
║                                                              ║
║  Full stack: DNS-AID → DID Document → Hub → Agent → Bridge   ║
╚══════════════════════════════════════════════════════════════╝""")

# ── Step 1: DNS-AID Zone File ────────────────────────────────────────────
section("STEP 1 ── DNS-AID Zone File (published by hub.example.com)")

dns_zone = """\
; DNS-AID records for ROAR hub discovery
; Published in the hub.example.com zone file
;
$ORIGIN hub.example.com.

; Agent Identity Document pointer — tells clients where the DID doc lives
_did.hub.example.com.      300  IN  TXT  "did=did:web:hub.example.com"

; ROAR hub service record — how to find the hub
_roar._tcp.hub.example.com. 300  IN  SRV  0 0 8090 hub.example.com.
_roar._tcp.hub.example.com. 300  IN  TXT  "proto=roar" "version=1.0" "path=/roar"

; A2A compatibility endpoint
_a2a._tcp.hub.example.com.  300  IN  SRV  0 0 8090 hub.example.com.
_a2a._tcp.hub.example.com.  300  IN  TXT  "proto=a2a" "version=0.2"

; Agent A is registered at this hub
_agent.agent-a.hub.example.com. 300 IN TXT "did=did:web:agents.example.com:agent-a" "cap=code-review,python"\
"""
show_text("DNS zone records", dns_zone)

# ── Step 2: DID Document at /.well-known/did.json ────────────────────────
section("STEP 2 ── DID Document (https://hub.example.com/.well-known/did.json)")

did_doc = DIDDocument(
    id="did:web:hub.example.com",
    verification_methods=[
        VerificationMethod(
            id="did:web:hub.example.com#key-1",
            type="Ed25519VerificationKey2020",
            controller="did:web:hub.example.com",
            public_key_multibase="z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK",
        ),
    ],
    authentication=["did:web:hub.example.com#key-1"],
    services=[
        ServiceEndpoint(
            id="did:web:hub.example.com#roar-hub",
            type="ROARHub",
            service_endpoint="https://hub.example.com:8090/roar",
        ),
        ServiceEndpoint(
            id="did:web:hub.example.com#a2a",
            type="A2AEndpoint",
            service_endpoint="https://hub.example.com:8090/a2a",
        ),
    ],
)
show_json("DID Document", did_doc.to_dict())

# ── Step 3: Agent B does DNS lookup ──────────────────────────────────────
section("STEP 3 ── Agent B performs DNS discovery")

print("  1. Agent B wants to find a code-review agent")
print("  2. Query: dig TXT _roar._tcp.hub.example.com")
print("     → proto=roar, version=1.0, path=/roar")
print("  3. Query: dig SRV _roar._tcp.hub.example.com")
print("     → hub.example.com:8090")
print("  4. Resolve DID: GET https://hub.example.com/.well-known/did.json")
print("     → Service endpoint: https://hub.example.com:8090/roar")
print("  ✓ Hub discovered at https://hub.example.com:8090/roar")

# ── Step 4: Agent B queries hub for code-review agents ───────────────────
section("STEP 4 ── Agent B queries hub for 'code-review' agents")

# Simulated hub response
hub_search_response = {
    "agents": [{
        "agent_card": AgentCard(
            identity=agent_a,
            description="Coder agent — reviews code and debugs issues",
            skills=["code-review", "python", "debugging"],
            channels=["http", "roar"],
            endpoints={
                "roar": "https://agents.example.com:8091/roar",
                "http": "https://agents.example.com:8091",
            },
            declared_capabilities=[
                AgentCapability(name="code-review", description="Reviews code for bugs and style"),
                AgentCapability(name="python", description="Writes and analyzes Python code"),
            ],
        ).model_dump(),
        "registered_at": 1710000000.0,
    }],
}
print(f"  GET /roar/agents?capability=code-review")
print(f"  Found {len(hub_search_response['agents'])} agent(s):")
card = hub_search_response["agents"][0]["agent_card"]
print(f"    Name: {card['identity']['display_name']}")
print(f"    DID:  {card['identity']['did']}")
print(f"    Caps: {card['identity']['capabilities']}")
print(f"    Endpoint: {card['endpoints'].get('roar', card['endpoints'].get('http'))}")

# ── Step 5: Agent B sends A2A tasks/send ─────────────────────────────────
section("STEP 5 ── Agent B sends A2A tasks/send to hub")

a2a_request = {
    "jsonrpc": "2.0",
    "id": "b-req-001",
    "method": "tasks/send",
    "params": {
        "id": "review-task-42",
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": "Review PR #42: refactor auth middleware to use JWT"}],
        },
        "metadata": {
            "target_did": agent_a.did,
            "urgency": "high",
        },
    },
}
show_json("A2A tasks/send request", a2a_request)

detected = detect_protocol(a2a_request)
print(f"  detect_protocol() → {detected.value!r}")
assert detected == ProtocolType.A2A

# ── Step 6: Hub translates A2A → ROAR and routes to Agent A ─────────────
section("STEP 6 ── Hub translates A2A → ROAR, routes to Agent A")

a2a_task_payload = {
    "task_id": a2a_request["params"]["id"],
    "content": a2a_request["params"]["message"]["parts"][0]["text"],
    "urgency": a2a_request["params"]["metadata"]["urgency"],
}
roar_msg = A2AAdapter.a2a_task_to_roar(
    a2a_task_payload, from_agent=agent_b, to_agent=agent_a,
)
print(f"  ROARMessage.id     = {roar_msg.id}")
print(f"  intent             = {roar_msg.intent}")
print(f"  from               = {agent_b.display_name} ({agent_b.did})")
print(f"  to                 = {agent_a.display_name} ({agent_a.did})")
show_json("payload", roar_msg.payload)
print("  → Forwarded to Agent A's ROAR endpoint (native ROAR, no translation needed)")

# ── Step 7: Agent A processes and responds (ROAR native) ─────────────────
section("STEP 7 ── Agent A processes (ROAR native) and responds")

roar_response = ROARMessage(
    **{"from": agent_a, "to": agent_b},
    intent=MessageIntent.RESPOND,
    payload={
        "review": {
            "verdict": "approved_with_comments",
            "summary": "JWT refactor looks solid. Two minor suggestions.",
            "comments": [
                {"file": "auth/middleware.py", "line": 23, "text": "Consider using PyJWT's decode with options={'verify_exp': True}"},
                {"file": "auth/middleware.py", "line": 67, "text": "Token refresh logic should handle clock skew (leeway=30s)"},
            ],
            "stats": {"files_reviewed": 3, "issues": 0, "suggestions": 2},
        },
        "reviewer": agent_a.display_name,
    },
    context={"in_reply_to": roar_msg.id, "protocol": "roar"},
)
print(f"  ROARMessage.id     = {roar_response.id}")
print(f"  intent             = {roar_response.intent}")
show_json("payload", roar_response.payload)

# ── Step 8: Hub translates ROAR response → A2A for Agent B ──────────────
section("STEP 8 ── Hub translates ROAR response → A2A task result")

review_text = (
    f"Verdict: {roar_response.payload['review']['verdict']}\n"
    f"{roar_response.payload['review']['summary']}\n"
)
for c in roar_response.payload["review"]["comments"]:
    review_text += f"  - {c['file']}:{c['line']}: {c['text']}\n"

a2a_result = {
    "jsonrpc": "2.0",
    "id": "b-req-001",
    "result": {
        "id": "review-task-42",
        "status": {"state": "completed"},
        "artifacts": [{
            "parts": [{"type": "text", "text": review_text.strip()}],
        }],
    },
}
show_json("A2A task result (back to Agent B)", a2a_result)

# ── Summary ──────────────────────────────────────────────────────────────
print("""
╔══════════════════════════════════════════════════════════════╗
║                   FULL FLOW COMPLETE                         ║
║                                                              ║
║  Layer 1 — DNS-AID: _roar._tcp SRV/TXT records              ║
║  Layer 2 — DID Doc: /.well-known/did.json with services      ║
║  Layer 3 — Hub discovery: GET /roar/agents?capability=X      ║
║  Layer 4 — A2A tasks/send → ROARMessage(DELEGATE) → ROAR     ║
║  Layer 5 — Agent A processes natively, responds              ║
║  Layer 6 — ROARMessage(RESPOND) → A2A task artifact          ║
║                                                              ║
║  Agent B spoke A2A the entire time.                          ║
║  Agent A spoke ROAR the entire time.                         ║
║  The hub bridged transparently between them.                 ║
╚══════════════════════════════════════════════════════════════╝
""")

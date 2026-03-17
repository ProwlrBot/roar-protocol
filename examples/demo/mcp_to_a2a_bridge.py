#!/usr/bin/env python3
"""ROAR Protocol Demo — MCP-to-A2A Bridge.

Simulates an MCP client sending a tools/call request that gets bridged
through ROAR to an A2A-speaking agent, then translates the response back
to MCP result format.  No HTTP servers — pure data transformation.

Usage:
    python examples/demo/mcp_to_a2a_bridge.py
"""
import sys, io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import json
from roar_sdk import AgentIdentity, MessageIntent, ROARMessage, MCPAdapter, A2AAdapter
from roar_sdk.adapters.detect import detect_protocol, ProtocolType

# ── Identities ────────────────────────────────────────────────────────────
mcp_client = AgentIdentity(display_name="vscode-copilot", agent_type="ide",
                           capabilities=["mcp-client"])
roar_hub = AgentIdentity(display_name="roar-hub", agent_type="agent",
                         capabilities=["routing", "translation"])
a2a_agent = AgentIdentity(display_name="code-review-agent", agent_type="agent",
                          capabilities=["code-review", "python"])

def section(title: str) -> None:
    print(f"\n{'─' * 64}")
    print(f"  {title}")
    print(f"{'─' * 64}")

def show_json(label: str, obj: object) -> None:
    print(f"  {label}:")
    for line in json.dumps(obj, indent=2).splitlines():
        print(f"    {line}")

# ══════════════════════════════════════════════════════════════════════════
print("""
╔══════════════════════════════════════════════════════════════╗
║        ROAR BRIDGE DEMO: MCP  ──►  ROAR  ──►  A2A          ║
║                                                              ║
║  An MCP tools/call becomes a ROAR DELEGATE, routed to an    ║
║  A2A agent, and the response is translated back to MCP.     ║
╚══════════════════════════════════════════════════════════════╝""")

# ── Step 1: MCP client sends a JSON-RPC tools/call ───────────────────────
section("STEP 1 ── MCP Client sends tools/call")

mcp_request = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "name": "code-review",
        "arguments": {"file": "main.py", "mode": "thorough"},
    },
}
show_json("MCP JSON-RPC request", mcp_request)

# ── Step 2: Hub detects the protocol ─────────────────────────────────────
section("STEP 2 ── ROAR Hub detects protocol")

detected = detect_protocol(mcp_request)
print(f"  detect_protocol() → {detected.value!r}")
assert detected == ProtocolType.MCP, f"Expected MCP, got {detected}"
print("  ✓ Identified as MCP (JSON-RPC 2.0, method=tools/call)")

# ── Step 3: Translate MCP → ROAR ─────────────────────────────────────────
section("STEP 3 ── Translate MCP → ROARMessage")

tool_name = mcp_request["params"]["name"]
tool_args = mcp_request["params"]["arguments"]
roar_msg = MCPAdapter.mcp_to_roar(tool_name, tool_args, from_agent=mcp_client)
roar_msg.context["source_protocol"] = "mcp"
roar_msg.context["jsonrpc_id"] = mcp_request["id"]

print(f"  ROARMessage.id     = {roar_msg.id}")
print(f"  intent             = {roar_msg.intent}")
print(f"  from               = {roar_msg.from_identity.display_name} ({roar_msg.from_identity.did[:40]}...)")
print(f"  to                 = {roar_msg.to_identity.display_name}")
show_json("payload", roar_msg.payload)

# ── Step 4: Hub re-targets to A2A agent ──────────────────────────────────
section("STEP 4 ── Hub routes to A2A agent (re-target)")

# Hub changes intent from EXECUTE (tool call) to DELEGATE (agent task)
# and sets the real destination agent.
delegated = ROARMessage(
    **{"from": mcp_client, "to": a2a_agent},
    intent=MessageIntent.DELEGATE,
    payload={
        "task": tool_name,
        "params": tool_args,
        "source_tool": tool_name,
    },
    context={
        "source_protocol": "mcp",
        "target_protocol": "a2a",
        "jsonrpc_id": mcp_request["id"],
    },
)
print(f"  Re-targeted message:")
print(f"    intent  = {delegated.intent}")
print(f"    to      = {a2a_agent.display_name} (preferred_protocol=a2a)")
show_json("payload", delegated.payload)

# ── Step 5: Translate ROAR → A2A task ────────────────────────────────────
section("STEP 5 ── Translate ROARMessage → A2A tasks/send")

a2a_task_send = {
    "jsonrpc": "2.0",
    "id": "a2a-req-001",
    "method": "tasks/send",
    "params": {
        "id": delegated.id,
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": f"Review file {tool_args['file']} ({tool_args.get('mode', 'standard')} mode)"}],
        },
    },
}
show_json("A2A tasks/send (outbound to agent)", a2a_task_send)

# Verify detection sees A2A
assert detect_protocol(a2a_task_send) == ProtocolType.A2A
print("  ✓ detect_protocol() confirms A2A format")

# ── Step 6: A2A agent processes and responds ─────────────────────────────
section("STEP 6 ── A2A Agent processes task and responds")

a2a_response = {
    "jsonrpc": "2.0",
    "id": "a2a-req-001",
    "result": {
        "id": delegated.id,
        "status": {"state": "completed"},
        "artifacts": [{
            "parts": [{"type": "text", "text": "Code review complete. main.py: 2 issues found.\n1. Line 42: unused import 'os'\n2. Line 87: bare except clause"}],
        }],
    },
}
show_json("A2A task response", a2a_response)

# ── Step 7: Translate A2A response → ROAR ────────────────────────────────
section("STEP 7 ── Translate A2A response → ROARMessage")

artifact_text = a2a_response["result"]["artifacts"][0]["parts"][0]["text"]
a2a_task_for_roar = {
    "task_id": a2a_response["result"]["id"],
    "status": a2a_response["result"]["status"]["state"],
    "result": artifact_text,
}
roar_response = A2AAdapter.a2a_task_to_roar(
    a2a_task_for_roar, from_agent=a2a_agent, to_agent=mcp_client,
)
# Override intent to RESPOND since the task is complete
roar_response.intent = MessageIntent.RESPOND

print(f"  ROARMessage.id     = {roar_response.id}")
print(f"  intent             = {roar_response.intent}")
print(f"  from               = {roar_response.from_identity.display_name}")
print(f"  to                 = {roar_response.to_identity.display_name}")
show_json("payload", roar_response.payload)

# ── Step 8: Translate ROAR → MCP tool result ─────────────────────────────
section("STEP 8 ── Translate ROARMessage → MCP tool result")

mcp_response = {
    "jsonrpc": "2.0",
    "id": mcp_request["id"],
    "result": {
        "content": [
            {"type": "text", "text": artifact_text},
        ],
        "isError": False,
    },
}
show_json("MCP tools/call result (back to IDE)", mcp_response)

# ── Summary ──────────────────────────────────────────────────────────────
print("""
╔══════════════════════════════════════════════════════════════╗
║                    BRIDGE COMPLETE                           ║
║                                                              ║
║  MCP tools/call ──► ROARMessage(EXECUTE) ──► DELEGATE        ║
║       ──► A2A tasks/send ──► A2A result                      ║
║       ──► ROARMessage(RESPOND) ──► MCP tool result           ║
║                                                              ║
║  The IDE never knew it was talking to an A2A agent.          ║
║  The A2A agent never knew the request came from MCP.         ║
║  ROAR bridged both protocols transparently.                  ║
╚══════════════════════════════════════════════════════════════╝
""")

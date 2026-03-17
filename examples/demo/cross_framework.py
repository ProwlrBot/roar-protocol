#!/usr/bin/env python3
"""ROAR Protocol Demo — Cross-Framework Bridge (CrewAI ↔ LangGraph).

Simulates a CrewAI "researcher" agent communicating with a LangGraph
"analyst" agent through ROAR.  No framework dependencies required —
this shows the data transformations at each hop.

Usage:
    python examples/demo/cross_framework.py
"""
import sys, io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import json
from roar_sdk import AgentIdentity, MessageIntent, ROARMessage, A2AAdapter
from roar_sdk.adapters.crewai import CrewAIAdapter
from roar_sdk.adapters.langgraph import LangGraphAdapter
from roar_sdk.adapters.detect import detect_protocol, ProtocolType

# ── Identities ────────────────────────────────────────────────────────────
crewai_researcher = AgentIdentity(
    display_name="crewai-researcher", agent_type="agent",
    capabilities=["research", "web-search", "summarization"],
)
roar_hub = AgentIdentity(
    display_name="roar-hub", agent_type="agent",
    capabilities=["routing", "translation"],
)
langgraph_analyst = AgentIdentity(
    display_name="langgraph-analyst", agent_type="agent",
    capabilities=["data-analysis", "statistics", "visualization"],
)

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
║     ROAR BRIDGE DEMO: CrewAI  ──►  ROAR  ──►  LangGraph    ║
║                                                              ║
║  Two incompatible frameworks communicate transparently       ║
║  through the ROAR universal protocol bridge.                 ║
╚══════════════════════════════════════════════════════════════╝""")

# ── Step 1: CrewAI researcher creates a task ─────────────────────────────
section("STEP 1 ── CrewAI Researcher creates task")

crewai_task = {
    "description": "Analyze Q4 sales data and identify the top 3 growth regions",
    "expected_output": "A ranked list of regions with growth percentages and trends",
    "agent": "data-analyst",
    "tools": ["sql_query", "chart_generator"],
    "context": ["Q4 revenue was $4.2M, up 18% YoY"],
}
show_json("CrewAI task object", crewai_task)

detected = detect_protocol(crewai_task)
print(f"  detect_protocol() → {detected.value!r}")
assert detected == ProtocolType.CREWAI
print("  ✓ Identified as CrewAI format (description + expected_output)")

# ── Step 2: CrewAI wraps task in A2A tasks/send for transport ────────────
section("STEP 2 ── CrewAI sends as A2A tasks/send (wire format)")

a2a_outbound = {
    "jsonrpc": "2.0",
    "id": "crew-req-001",
    "method": "tasks/send",
    "params": {
        "id": "task-q4-analysis",
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": crewai_task["description"]}],
        },
        "metadata": {
            "framework": "crewai",
            "expected_output": crewai_task["expected_output"],
            "tools": crewai_task["tools"],
        },
    },
}
show_json("A2A tasks/send (on the wire)", a2a_outbound)

# ── Step 3: Hub receives, detects A2A, translates to ROAR ───────────────
section("STEP 3 ── ROAR Hub receives and translates A2A → ROAR")

wire_detected = detect_protocol(a2a_outbound)
print(f"  detect_protocol() → {wire_detected.value!r}")
assert wire_detected == ProtocolType.A2A

# Use CrewAI adapter since we know the origin framework
roar_msg = CrewAIAdapter.crewai_task_to_roar(
    crewai_task, from_agent=crewai_researcher, to_agent=langgraph_analyst,
)
print(f"  ROARMessage.id     = {roar_msg.id}")
print(f"  intent             = {roar_msg.intent}")
print(f"  from               = {crewai_researcher.display_name}")
print(f"  to                 = {langgraph_analyst.display_name}")
show_json("payload", roar_msg.payload)
show_json("context", roar_msg.context)

# ── Step 4: Hub translates ROAR → LangGraph state for analyst ────────────
section("STEP 4 ── Translate ROAR → LangGraph invocation")

lg_state = LangGraphAdapter.roar_to_langgraph_state(roar_msg)
# Enrich with the original task info for the graph
lg_state["messages"] = [
    {"role": "user", "content": roar_msg.payload["task"]},
]
lg_state["next"] = "analyst"
lg_state["metadata"] = {
    "expected_output": roar_msg.payload.get("expected_output", ""),
    "tools": roar_msg.payload.get("tools", []),
    "roar_message_id": roar_msg.id,
}

show_json("LangGraph state (input to graph)", lg_state)

lg_detected = detect_protocol(lg_state)
print(f"  detect_protocol() → {lg_detected.value!r}")
assert lg_detected == ProtocolType.LANGGRAPH
print("  ✓ Identified as LangGraph format (messages + next)")

# ── Step 5: LangGraph analyst processes (simulated) ──────────────────────
section("STEP 5 ── LangGraph Analyst processes (simulated graph execution)")

print("  analyst node → running sql_query tool...")
print("  analyst node → running chart_generator tool...")
print("  analyst node → composing final output...")

lg_result_state = {
    "messages": [
        {"role": "user", "content": roar_msg.payload["task"]},
        {"role": "assistant", "content": (
            "Q4 Growth Analysis - Top 3 Regions:\n"
            "1. APAC: +32% ($1.1M) — driven by enterprise expansion\n"
            "2. EMEA: +24% ($890K) — new partnerships in DACH region\n"
            "3. LATAM: +19% ($420K) — first full quarter post-launch\n\n"
            "Overall: $4.2M revenue, 18% YoY growth."
        )},
    ],
    "next": None,  # graph complete
    "metadata": {"steps_executed": 3, "tools_used": ["sql_query", "chart_generator"]},
}
show_json("LangGraph final state", lg_result_state)

# ── Step 6: Translate LangGraph response → ROAR ─────────────────────────
section("STEP 6 ── Translate LangGraph result → ROARMessage")

roar_response = LangGraphAdapter.langgraph_state_to_roar(
    lg_result_state, from_agent=langgraph_analyst, to_agent=crewai_researcher,
)
print(f"  ROARMessage.id     = {roar_response.id}")
print(f"  intent             = {roar_response.intent}")
assert roar_response.intent == MessageIntent.RESPOND, "next=None should map to RESPOND"
print("  ✓ next=None correctly mapped to RESPOND intent")
print(f"  from               = {roar_response.from_identity.display_name}")
print(f"  to                 = {roar_response.to_identity.display_name}")
show_json("payload", roar_response.payload)

# ── Step 7: Translate ROAR → CrewAI task result for researcher ───────────
section("STEP 7 ── Translate ROAR → CrewAI task result")

crewai_result = CrewAIAdapter.roar_to_crewai_result(roar_response)
show_json("CrewAI task result (back to researcher)", crewai_result)

# Also show the A2A wire format that would be sent back
a2a_response = {
    "jsonrpc": "2.0",
    "id": "crew-req-001",
    "result": {
        "id": "task-q4-analysis",
        "status": {"state": "completed"},
        "artifacts": [{
            "parts": [{"type": "text", "text": crewai_result["output"]}],
        }],
    },
}
show_json("A2A response (wire format back to CrewAI)", a2a_response)

# ── Summary ──────────────────────────────────────────────────────────────
print("""
╔══════════════════════════════════════════════════════════════╗
║                   BRIDGE COMPLETE                            ║
║                                                              ║
║  CrewAI task ──► A2A tasks/send ──► ROARMessage(DELEGATE)    ║
║       ──► LangGraph state ──► Graph execution                ║
║       ──► LangGraph result ──► ROARMessage(RESPOND)          ║
║       ──► CrewAI task result ──► A2A artifact                ║
║                                                              ║
║  CrewAI and LangGraph never spoke to each other directly.    ║
║  ROAR translated between their native formats seamlessly.    ║
╚══════════════════════════════════════════════════════════════╝
""")

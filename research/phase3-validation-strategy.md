# Phase 3: Validation Strategy & Forward-Looking Roadmap

**Project ROAR — Research Plan, Phase 3**
Version: 1.0 | Status: Draft

---

## Section 1: MCP/A2A Backward Compatibility

### Current State

The Python SDK ships two adapter classes in `python/src/roar_sdk/types.py`:

**MCPAdapter** — translates MCP tool calls into ROAR messages:
```python
MCPAdapter.mcp_to_roar(tool_name, params, from_agent)
  → ROARMessage(intent=EXECUTE, payload={"action": tool_name, "params": params})

MCPAdapter.roar_to_mcp(msg)
  → {"tool": msg.payload["action"], "params": msg.payload["params"]}
```

**A2AAdapter** — translates A2A tasks into ROAR messages:
```python
A2AAdapter.a2a_task_to_roar(task, from_agent, to_agent)
  → ROARMessage(intent=DELEGATE, payload=task, context={"protocol": "a2a"})

A2AAdapter.roar_to_a2a(msg)
  → {"task_id": msg.id, "from": ..., "to": ..., "payload": msg.payload}
```

### Gaps to Complete

| Gap | Priority | Description |
|---|---|---|
| MCP streaming → ROAR StreamEvent | High | MCP SSE token stream → `StreamEvent(type=TOOL_CALL)` |
| MCP error mapping | High | MCP `isError` result → `ROARMessage(intent=RESPOND, payload={"error": ...})` |
| A2A Agent Card → AgentCard | High | Map A2A `/.well-known/agent.json` → ROAR `AgentCard` with `AgentIdentity` |
| A2A task status → StreamEvent | Medium | A2A SSE status updates → `StreamEvent(type=TASK_UPDATE)` |
| A2A skill → AgentCapability | Medium | A2A `skills[]` → ROAR `AgentCapability` with `input_schema`/`output_schema` |
| MCP resource → ROAR payload | Low | MCP resource reads → `ROARMessage(intent=EXECUTE, payload={"resource": uri})` |
| A2A push notification → ROAR notify | Low | A2A webhook callbacks → `ROARMessage(intent=NOTIFY)` |

### Minimal Viable Adapter

The smallest adapter that lets a ROAR agent talk to a legacy MCP server:

```python
class MinimalMCPBridge:
    """Wrap any MCP server as a ROAR agent."""
    def __init__(self, mcp_server_url: str):
        self.identity = AgentIdentity(display_name="mcp-bridge", agent_type="tool")
        self.server_url = mcp_server_url

    async def handle(self, msg: ROARMessage) -> ROARMessage:
        if msg.intent == MessageIntent.EXECUTE:
            tool = msg.payload.get("action")
            params = msg.payload.get("params", {})
            # Call MCP server
            result = await self._call_mcp_tool(tool, params)
            return ROARMessage(
                **{"from": self.identity, "to": msg.from_identity},
                intent=MessageIntent.RESPOND,
                payload={"result": result},
            )
```

This is the pattern to formalize and ship in v0.3.0.

---

## Section 2: Governance & Standardization Roadmap

### Year 1 (2025–2026): Community Specification

**Goal:** Establish ROAR as a credible, well-documented open standard with reference implementations and a conformance test suite.

Milestones:
- ✅ v0.2.0: Spec published (5 layers, schemas, examples)
- ✅ Python SDK with golden conformance tests
- 🔄 TypeScript SDK aligned to Python canonical types (in progress)
- ⬜ Go SDK (community contribution target)
- ⬜ ROAR Hub reference server (federation + discovery)
- ⬜ Submit to GitHub open-source foundations for neutral hosting

**Governance:** Single maintainer (ProwlrBot) with public RFC process via GitHub issues. All spec changes require a `spec_change.md` issue. No votes required — maintainer has final say in Year 1 to keep velocity.

### Year 2 (2026–2027): Standards Body Engagement

**Goal:** Get ROAR acknowledged by at least one official body to build institutional credibility.

Options evaluated:

| Path | Time to result | Control retained | Credibility | Cost |
|---|---|---|---|---|
| **W3C Community Group** | 3–6 months | High | Medium | Low |
| **IETF Informational RFC** | 12–18 months | High | High | Medium |
| **Linux Foundation project** | 6–12 months | Medium | High | Low |
| **IEEE standard** | 3–5 years | Low | Very High | High |
| **AAIF (Agentic AI Foundation)** | 6–12 months | Low | Medium | Low |

**Recommendation:** Pursue **W3C Community Group** first (fastest path to legitimacy), simultaneously submit an **IETF Informational RFC** for Layer 4 (the Exchange message format is the most novel contribution). AAIF membership for ecosystem visibility.

The IETF BANDAID draft for DNS-based discovery is a natural collaboration partner — ROAR's Layer 2 should formally reference it.

### Year 3 (2027–2028): Formal Standardization

**Goal:** W3C Working Group Note or Recommendation for Layers 1–2 (Identity + Discovery). IETF Proposed Standard for Layer 4 message format.

Requirements to get here:
- 3+ independent interoperable implementations (Python, TypeScript, Go minimum)
- Real-world deployments at 2+ organizations
- Conformance test suite with automated certification
- At least one major AI platform (Anthropic, Google, or Microsoft) referencing ROAR in their agent documentation

---

## Section 3: Killer Use Cases

### Use Case 1: Multi-Agent Security Operations

**Problem:** A security team runs a fleet of autonomous agents — network scanner, vulnerability assessor, exploit researcher, report writer — each running in different environments (WSL, Mac, CI). Without coordination, they duplicate work, race-condition each other, and produce conflicting reports.

**ROAR Solution:**
- Layer 1: Each agent has a signed DID (`did:roar:agent:scanner-abc123`)
- Layer 2: All agents register with a shared ROAR Hub at scan start
- Layer 4: Scanner delegates to assessor: `ROARMessage(intent=DELEGATE, payload={"targets": [...]})`
- Layer 5: All agents stream `StreamEvent(type=TASK_UPDATE)` to a shared event bus
- Layer 4: Report writer sends `ROARMessage(intent=ASK)` to human for approval before publishing

**Layers used:** 1 (identity), 2 (discovery), 4 (delegation chain), 5 (live status stream)

**Example flow:**
```
scanner.did  →  DELEGATE  →  assessor.did   [payload: {targets: [10.0.0.0/24]}]
assessor.did →  DELEGATE  →  exploiter.did  [payload: {cves: ["CVE-2024-1234"]}]
exploiter.did → UPDATE    →  reporter.did   [payload: {findings: [...]}]
reporter.did  → ASK       →  human.did      [payload: {draft: "...", action: "approve?"}]
human.did     → RESPOND   →  reporter.did   [payload: {approved: true}]
reporter.did  → NOTIFY    →  *              [payload: {report_url: "..."}]  # broadcast
```

---

### Use Case 2: Human-in-the-Loop Approval Chains

**Problem:** An autonomous coding agent is about to push to production. It should pause, present its plan to a human, and only proceed after explicit approval. Existing protocols (MCP, A2A) have no standard way to model this as a verifiable, signed exchange.

**ROAR Solution:**
- The `ASK` intent is purpose-built for this: "I need a decision before I can continue"
- The human's `RESPOND` is signed with their DID, creating an auditable approval record
- The context chain (`in_reply_to`) links the approval to the original ask
- Any party can verify the chain: signed message from `did:roar:human:alice-...` approved task `msg_xxx`

**Layers used:** 1 (human identity), 4 (ASK/RESPOND intents)

**Example flow:**
```
agent.did  → ASK    → human.did  [payload: {plan: "Deploy v2.3 to prod", risk: "medium"}]
human.did  → RESPOND → agent.did  [payload: {approved: true, note: "go ahead, monitor closely"}]
agent.did  → EXECUTE → deploy-tool.did  [payload: {version: "2.3", env: "prod"}]
agent.did  → UPDATE  → monitor.did     [payload: {status: "deploying", trace_id: "..."}]
```

---

### Use Case 3: Cross-Platform Agent Discovery and Delegation

**Problem:** A Claude Code agent in a developer's terminal needs to find and use a specialized SQL optimization agent running on a remote server — without knowing its URL in advance, without trusting it blindly, and without manual configuration.

**ROAR Solution:**
- Layer 2: Developer's agent queries the ROAR Hub: "find agents with capability `sql-optimize`"
- Hub returns `DiscoveryEntry` with `AgentCard` including the agent's DID and endpoint
- Layer 1: Developer's agent verifies the DID signature before sending sensitive queries
- Layer 4: `ROARMessage(intent=DELEGATE, payload={"query": "SELECT ...", "dialect": "postgres"})`
- Layer 5: SQL agent streams `StreamEvent(type=REASONING)` events showing its optimization thinking

**Layers used:** 1 (identity verification), 2 (capability-based discovery), 4 (delegation), 5 (streaming reasoning)

**Example flow:**
```
claude.did  → DISCOVER  → hub.did     [payload: {capability: "sql-optimize"}]
hub.did     → RESPOND   → claude.did  [payload: {agents: [{did: "did:roar:...", endpoint: "..."}]}]
claude.did  → DELEGATE  → sqlagent.did [payload: {query: "...", dialect: "postgres"}]
sqlagent.did → STREAM    → claude.did  [StreamEvent(type=REASONING, data={step: "index scan..."})]
sqlagent.did → RESPOND   → claude.did  [payload: {optimized_query: "...", improvement: "40%"}]
```

---

## Summary

The three phases together establish ROAR as:
1. **Phase 1:** The most complete analysis of why existing protocols fail at interoperability
2. **Phase 2:** Evidence-based technology choices for each layer (DID, discovery, transport)
3. **Phase 3:** A clear path from community spec → international standard, with concrete use cases that justify the complexity

The killer application is the **multi-agent security operations** use case — it requires all five layers simultaneously and is a concrete, high-value workload that no single existing protocol can handle. This should be the reference scenario for the ROAR white paper.

---

*Generated: 2026-03-13 | See SDK-ROADMAP.md for implementation status*

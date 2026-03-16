# Layer 2: Discovery

> Decentralized agent directory, capability search, agent cards, matchmaking

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT",
"SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this
document are to be interpreted as described in RFC 2119.

---

## Overview

The Discovery layer enables agents to find each other based on capabilities, not hardcoded addresses. Agents register their capabilities via **Agent Cards**, and other agents search the directory to find collaborators.

The Discovery layer provides:
- **Agent Cards** — rich capability descriptors combining identity + skills + endpoints
- **Agent Directory** — in-memory registry for local discovery
- **Capability Search** — find agents that can perform specific tasks
- **Federation** — directories can sync across hubs for cross-machine discovery

---

## Agent Card

An Agent Card is the public-facing descriptor of an agent. Think of it as a business card that other agents can read to decide whether to collaborate.

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `identity` | AgentIdentity | REQUIRED | The agent's identity (Layer 1) |
| `description` | string | RECOMMENDED | What this agent does in plain English |
| `skills` | string[] | RECOMMENDED | Named skills this agent has installed |
| `channels` | string[] | OPTIONAL | Communication channels (console, discord, telegram) |
| `endpoints` | dict | OPTIONAL | Connection endpoints (`{"http": "http://...", "ws": "ws://..."}`) |
| `declared_capabilities` | AgentCapability[] | OPTIONAL | Formal capability declarations with schemas |
| `metadata` | dict | OPTIONAL | Arbitrary key-value metadata |

---

## Wire Format

### AgentCard

```json
{
  "identity": {
    "did": "did:roar:agent:architect-a1b2c3d4",
    "display_name": "architect",
    "agent_type": "agent",
    "capabilities": ["python", "api", "architecture"],
    "version": "1.0"
  },
  "description": "Backend architect specializing in API design and database schemas",
  "skills": ["code_review", "api_design", "db_migration"],
  "channels": ["console"],
  "endpoints": {
    "http": "http://localhost:8088/api/agent/architect"
  },
  "declared_capabilities": [
    {
      "name": "code_review",
      "description": "Review code for quality and security",
      "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}}},
      "output_schema": {"type": "object", "properties": {"issues": {"type": "array"}}}
    }
  ],
  "metadata": {
    "team": "backend",
    "timezone": "America/New_York"
  }
}
```

### DiscoveryEntry

```json
{
  "agent_card": { "...AgentCard..." },
  "registered_at": 1710000000.0,
  "last_seen": 1710003600.0,
  "hub_url": "http://localhost:8099"
}
```

---

## Examples

### Register an agent

```python
from prowlrbot.protocols.roar import AgentIdentity, AgentCard, AgentDirectory

directory = AgentDirectory()

card = AgentCard(
    identity=AgentIdentity(
        display_name="architect",
        capabilities=["python", "api", "architecture"],
    ),
    description="Backend architect",
    skills=["code_review", "api_design"],
)

entry = directory.register(card)
print(entry.agent_card.identity.did)
```

### Search by capability

```python
python_agents = directory.search("python")
for entry in python_agents:
    print(f"{entry.agent_card.identity.display_name}: {entry.agent_card.description}")
```

### Lookup by DID

```python
entry = directory.lookup("did:roar:agent:architect-a1b2c3d4")
if entry:
    print(entry.agent_card.description)
```

---

## Integration with ProwlrHub

ProwlrHub (the war room) maintains its own agent registry that maps to ROAR discovery:

| ProwlrHub Concept | ROAR Discovery Concept |
|-------------------|----------------------|
| Agent registration | Agent Card + Directory entry |
| `get_agents()` | `directory.list_all()` |
| Capabilities | `identity.capabilities` |
| Agent status | `entry.last_seen` + heartbeat |

When an agent connects to ProwlrHub via MCP, it's automatically registered in both the war room and the ROAR directory.

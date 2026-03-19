# Layer 1: Identity

> Agent registration, W3C DID-based identity, Ed25519 signing, capability tokens

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT",
"SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this
document are to be interpreted as described in RFC 2119.

---

## Overview

Every agent in the ROAR ecosystem has a unique identity based on the [W3C DID](https://www.w3.org/TR/did-core/) standard. Identities are self-sovereign — agents generate their own DIDs without a central authority.

The Identity layer provides:
- **Unique identification** via DID URIs
- **Capability declaration** — what an agent can do
- **Cryptographic signing** — Ed25519 public keys for message authentication
- **Type classification** — agent, tool, human, or IDE

---

## Agent Identity

### DID Format

```
did:roar:<agent_type>:<slug>-<unique_id>
```

Examples:
```
did:roar:agent:architect-a1b2c3d4
did:roar:tool:shell-executor-f5e6d7c8
did:roar:human:nunu-9a8b7c6d
did:roar:ide:claude-code-e1f2a3b4
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `did` | string | Auto-generated | W3C DID URI. MUST be generated from `agent_type` + `display_name` + random suffix if not provided |
| `display_name` | string | RECOMMENDED | Human-readable name (e.g., "architect", "frontend-dev") |
| `agent_type` | string | REQUIRED | MUST be one of: `agent`, `tool`, `human`, `ide` |
| `capabilities` | string[] | RECOMMENDED | What this agent can do (e.g., `["code", "review", "testing"]`) |
| `version` | string | REQUIRED | Protocol version (default: "1.0") |
| `public_key` | string | OPTIONAL | Ed25519 public key (hex-encoded) for message signing |

### DID Method: `did:roar` (Informative)

The `did:roar` method is a **private, application-specific DID method** used within the ROAR protocol ecosystem. It is NOT registered with the [W3C DID Method Registry](https://www.w3.org/TR/did-spec-registries/#did-methods) and SHOULD NOT be assumed to be resolvable outside of ROAR-aware systems.

**Properties:**

- **Self-issued:** Agents generate their own DIDs locally using cryptographic randomness. No central authority or blockchain is required.
- **Format:** `did:roar:<agent_type>:<slug>-<16-hex-chars>` where the suffix is 16 hex characters from a CSPRNG.
- **Not globally unique:** Uniqueness is probabilistic (2^64 collision resistance). For global uniqueness guarantees, use `did:key` or `did:web`.
- **No DID Document resolution:** `did:roar` DIDs do not resolve to DID Documents via the Universal Resolver. Public keys are exchanged during registration or via the hub directory.

**Migration path:** For production deployments requiring W3C-compliant identities, ROAR supports:

- `did:key` — deterministic DID derived from Ed25519 public key. Self-contained, no resolver needed.
- `did:web` — DNS-anchored DID resolvable via HTTPS. Suitable for organizational identities.

The identity migration toolkit (`roar_sdk.migration`) provides `migrate_did_method()` to transition between DID methods while preserving agent registrations and delegation chains.

Implementations MUST accept DIDs matching the pattern `^did:(roar|key|web):` in the `did` field. Implementations MAY support additional DID methods.

### Agent Types

| Type | Description | Examples |
|------|-------------|---------|
| `agent` | Autonomous AI agent | Claude Code terminal, ROAR agent |
| `tool` | Tool or service | Shell executor, file reader, MCP server |
| `human` | Human operator | Developer, admin |
| `ide` | IDE or editor | VS Code, Claude Code, Cursor |

---

## Wire Format

### AgentIdentity

```json
{
  "did": "did:roar:agent:architect-a1b2c3d4",
  "display_name": "architect",
  "agent_type": "agent",
  "capabilities": ["python", "api", "architecture"],
  "version": "1.0",
  "public_key": null
}
```

### AgentCapability

```json
{
  "name": "code_review",
  "description": "Review code for quality, security, and maintainability",
  "input_schema": {
    "type": "object",
    "properties": {
      "file_path": {"type": "string"},
      "review_type": {"type": "string", "enum": ["quality", "security", "performance"]}
    }
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "issues": {"type": "array"},
      "score": {"type": "number"}
    }
  }
}
```

---

## Examples

### Create an agent identity

```python
from roar_sdk import AgentIdentity

agent = AgentIdentity(
    display_name="backend-architect",
    agent_type="agent",
    capabilities=["python", "api", "database", "architecture"],
)

print(agent.did)       # did:roar:agent:backend-architect-a1b2c3d4
print(agent.version)   # 1.0
```

### Auto-generated DID

If no `did` is provided, one is generated from `agent_type` + `display_name` + random suffix:

```python
agent = AgentIdentity(display_name="my-agent")
# agent.did → "did:roar:agent:my-agent-f5e6d7c8"
```

### Identity with signing key

```python
agent = AgentIdentity(
    display_name="secure-agent",
    public_key="a1b2c3d4e5f6..."  # Ed25519 hex-encoded
)
```

---

## Security Considerations

- DIDs are **self-sovereign** — no central registry is REQUIRED for generation.
- The `public_key` field enables **message authentication** without shared secrets.
- Agent types constrain what actions are expected: tools SHOULD execute, agents SHOULD delegate.
- Capabilities are **advisory** — they declare intent but MUST NOT be treated as enforced access control by themselves.
- For access control, implementations MUST combine identity with the Connect layer's auth methods (HMAC, JWT, mTLS).

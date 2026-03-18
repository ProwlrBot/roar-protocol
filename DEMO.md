# ROAR Protocol — Live Demo (4 Terminals)

> Run all 4 terminals side-by-side for the full experience.
> Each terminal shows a different layer of the ROAR stack working together.

## Prerequisites

```bash
cd roar-protocol
pip install -e './python[cli,server,ed25519]'
```

---

## Terminal 1: Hub (The War Room)

**Title:** `ROAR Hub — Discovery & Federation`

```bash
# Generate keys for the hub
export ROAR_SIGNING_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
echo "Hub secret: $ROAR_SIGNING_SECRET"

# Start the hub
roar hub start --port 8090
```

What to show:
- Hub starts on port 8090
- Health endpoint: `curl http://127.0.0.1:8090/roar/health`
- Empty agent list: `roar hub agents`

---

## Terminal 2: Agent Alpha (Code Reviewer)

**Title:** `Agent Alpha — Code Review Specialist`

```bash
# Use the same secret as the hub
export ROAR_SIGNING_SECRET="<paste from terminal 1>"

# Generate Ed25519 identity
roar keygen --type ed25519

# Register with the hub
roar register http://127.0.0.1:8090 \
  --name "alpha-reviewer" \
  --capabilities "code-review,python,security" \
  --description "Reviews Python code for quality and security" \
  --endpoint "http://127.0.0.1:8091"
```

Then run the agent server:
```bash
python -c "
import os
from roar_sdk import AgentIdentity, ROARServer, ROARMessage, MessageIntent

identity = AgentIdentity(
    display_name='alpha-reviewer',
    agent_type='agent',
    capabilities=['code-review', 'python', 'security'],
)
print(f'Agent Alpha DID: {identity.did}')

server = ROARServer(
    identity=identity, port=8091,
    signing_secret=os.environ.get('ROAR_SIGNING_SECRET', ''),
    description='Reviews Python code for quality and security',
)

@server.on(MessageIntent.DELEGATE)
async def handle(msg: ROARMessage) -> ROARMessage:
    print(f'  Received task from {msg.from_identity.display_name}: {msg.payload}')
    return ROARMessage(
        **{'from': server.identity, 'to': msg.from_identity},
        intent=MessageIntent.RESPOND,
        payload={'status': 'reviewed', 'verdict': 'LGTM', 'issues': 0},
        context={'in_reply_to': msg.id},
    )

server.serve()
"
```

---

## Terminal 3: Agent Beta (Test Runner)

**Title:** `Agent Beta — Test Automation`

```bash
export ROAR_SIGNING_SECRET="<paste from terminal 1>"

roar register http://127.0.0.1:8090 \
  --name "beta-tester" \
  --capabilities "testing,pytest,ci" \
  --description "Runs test suites and reports results" \
  --endpoint "http://127.0.0.1:8092"
```

Then run:
```bash
python -c "
import os
from roar_sdk import AgentIdentity, ROARServer, ROARMessage, MessageIntent

identity = AgentIdentity(
    display_name='beta-tester',
    agent_type='agent',
    capabilities=['testing', 'pytest', 'ci'],
)
print(f'Agent Beta DID: {identity.did}')

server = ROARServer(
    identity=identity, port=8092,
    signing_secret=os.environ.get('ROAR_SIGNING_SECRET', ''),
    description='Runs test suites and reports results',
)

@server.on(MessageIntent.DELEGATE)
async def handle(msg: ROARMessage) -> ROARMessage:
    print(f'  Running tests for {msg.from_identity.display_name}...')
    return ROARMessage(
        **{'from': server.identity, 'to': msg.from_identity},
        intent=MessageIntent.RESPOND,
        payload={'status': 'passed', 'tests': 42, 'failures': 0, 'coverage': '94%'},
        context={'in_reply_to': msg.id},
    )

server.serve()
"
```

---

## Terminal 4: Orchestrator (The Conductor)

**Title:** `ROAR Orchestrator — Discovery, Delegation, Signing`

This terminal drives the demo. Run these commands one at a time for the video:

```bash
export ROAR_SIGNING_SECRET="<paste from terminal 1>"

# 1. Check hub health
echo "=== Hub Health ==="
roar hub health

# 2. Discover registered agents
echo "=== Registered Agents ==="
roar hub agents

# 3. Search by capability
echo "=== Find code reviewers ==="
roar hub search code-review

echo "=== Find testers ==="
roar hub search testing

# 4. Send a signed DELEGATE message to Alpha
echo "=== Delegating code review to Alpha ==="
roar send http://127.0.0.1:8091 did:roar:agent:alpha-reviewer-XXXX \
  '{"task": "review", "repo": "roar-protocol", "branch": "main"}' \
  --secret "$ROAR_SIGNING_SECRET"

# 5. Send a signed DELEGATE message to Beta
echo "=== Delegating test run to Beta ==="
roar send http://127.0.0.1:8092 did:roar:agent:beta-tester-XXXX \
  '{"task": "run-tests", "suite": "conformance", "target": "all"}' \
  --secret "$ROAR_SIGNING_SECRET"

# 6. Run conformance tests against the hub
echo "=== Conformance Check ==="
roar test http://127.0.0.1:8090 --secret "$ROAR_SIGNING_SECRET"

# 7. Generate new keys (show key management)
echo "=== Key Generation ==="
roar keygen --type both

# 8. Scaffold a new agent project
echo "=== Scaffold New Agent ==="
roar init my-new-agent --lang python
ls my-new-agent/
cat my-new-agent/agent.py
```

> Replace `XXXX` with the actual DID suffix from the agent registration output.

---

## Demo Flow (for video)

1. **Start hub** (Terminal 1) — show it's running, health check
2. **Register Alpha** (Terminal 2) — show Ed25519 key generation, hub registration
3. **Register Beta** (Terminal 3) — show second agent joining the network
4. **Discovery** (Terminal 4) — `roar hub agents` shows both agents, `roar hub search` finds by capability
5. **Delegation** (Terminal 4) — send signed messages, watch Terminal 2 & 3 respond
6. **Security** (Terminal 4) — `roar test` runs conformance checks, `roar keygen` shows key management
7. **Scaffolding** (Terminal 4) — `roar init` creates a ready-to-run agent project

## What This Demonstrates

| Feature | Where |
|:--------|:------|
| W3C DID identity (Layer 1) | Agent registration output |
| Federated discovery (Layer 2) | `roar hub agents` / `roar hub search` |
| HTTP transport (Layer 3) | Messages flowing between terminals |
| Signed messages (Layer 4) | `--secret` flag, signature in responses |
| Real-time events (Layer 5) | Agent logs showing received tasks |
| CLI toolkit | Every `roar` command |
| Ed25519 key management | `roar keygen` |
| Conformance testing | `roar test` |
| Project scaffolding | `roar init` |

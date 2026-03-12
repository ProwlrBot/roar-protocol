# ROAR Protocol — Installation

> ROAR is built into ProwlrBot. Install ProwlrBot to get the full ROAR SDK.

---

## Quick Start

```bash
git clone https://github.com/ProwlrBot/prowlrbot.git
cd prowlrbot
pip install -e .
```

That's it. The ROAR protocol types and SDK are now available:

```python
from prowlrbot.protocols.roar import (
    AgentIdentity,
    AgentCard,
    AgentDirectory,
    ROARMessage,
    MessageIntent,
    StreamEvent,
    MCPAdapter,
    A2AAdapter,
)
```

---

## Verify Installation

```python
python3 -c "
from prowlrbot.protocols.roar import AgentIdentity, ROARMessage, MessageIntent

agent = AgentIdentity(display_name='test-agent', capabilities=['code'])
print(f'Agent DID: {agent.did}')
print(f'Capabilities: {agent.capabilities}')
print('ROAR Protocol installed successfully!')
"
```

Expected output:
```
Agent DID: did:roar:agent:test-agent-xxxxxxxx
Capabilities: ['code']
ROAR Protocol installed successfully!
```

---

## Requirements

- Python 3.10+
- pydantic (installed with ProwlrBot)

No additional dependencies needed — ROAR uses only Pydantic and Python stdlib.

---

## Using with ProwlrHub (War Room)

ProwlrHub uses MCP transport with ROAR identity under the hood. To connect Claude Code terminals to a shared war room:

```bash
# Add to your project's .mcp.json
claude mcp add prowlr-hub -s local -e PYTHONPATH="$(pwd)/src" -- python3 -m prowlrbot.hub
```

See [ProwlrBot INSTALL.md](https://github.com/ProwlrBot/prowlrbot/blob/main/INSTALL.md) for the full war room setup guide.

---

## Using the SDK Directly

For building custom ROAR-based applications:

```python
# Client
from prowlrbot.protocols.sdk import ROARClient

# Server
from prowlrbot.protocols.sdk import ROARServer

# Router
from prowlrbot.protocols.sdk import ROARRouter

# Streaming
from prowlrbot.protocols.sdk import EventBus
```

See the [SDK documentation](https://github.com/ProwlrBot/prowlrbot/tree/main/src/prowlrbot/protocols/sdk) for detailed usage.

---

## Links

- [ROAR Protocol Specification](https://github.com/ProwlrBot/roar-protocol)
- [ProwlrBot Platform](https://github.com/ProwlrBot/prowlrbot)
- [Documentation](https://ProwlrBot.github.io/prowlr-docs)

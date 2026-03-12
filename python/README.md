# roar-sdk

**ROAR Protocol** — standalone Python SDK. 5-layer agent communication standard.

Design by [@kdairatchi](https://github.com/kdairatchi) — [ProwlrBot/roar-protocol](https://github.com/ProwlrBot/roar-protocol)

## Install

```bash
git clone https://github.com/ProwlrBot/roar-protocol.git
pip install -e ./python          # types + client + server (pydantic only)
pip install -e './python[http]'  # + httpx for HTTP transport
pip install -e './python[server]'  # + fastapi + uvicorn for serving
```

## Quick Start

```python
from roar_sdk import AgentIdentity, ROARMessage, MessageIntent, ROARClient, ROARServer

# Layer 1: identity
agent = AgentIdentity(display_name="my-agent", capabilities=["code"])

# Layer 4: message
msg = ROARMessage(
    **{"from": agent, "to": other},
    intent=MessageIntent.DELEGATE,
    payload={"task": "review"},
)
msg.sign("shared-secret")
```

See [examples/python/](https://github.com/ProwlrBot/roar-protocol/tree/main/examples/python) for runnable server + client.
See [ROAR-SPEC.md](https://github.com/ProwlrBot/roar-protocol/blob/main/ROAR-SPEC.md) for the full protocol specification.

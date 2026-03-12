# ROAR Protocol — Installation

The canonical Python SDK lives in this repo under `python/`. No external dependencies beyond Pydantic.

---

## Option A — Install from this repo (standalone)

```bash
git clone https://github.com/ProwlrBot/roar-protocol.git
cd roar-protocol
pip install -e ./python                  # types + client + server (pydantic only)
pip install -e './python[http]'          # + httpx for HTTP transport
pip install -e './python[server]'        # + fastapi + uvicorn to serve agents
```

### Verify install

```bash
python3 -c "
from roar_sdk import AgentIdentity, ROARMessage, MessageIntent
agent = AgentIdentity(display_name='test-agent', capabilities=['code'])
print('DID:', agent.did)
print('ROAR SDK', __import__('roar_sdk').__version__, 'installed successfully')
"
```

Expected output:
```
DID: did:roar:agent:test-agent-xxxxxxxxxxxxxxxx
ROAR SDK 0.2.0 installed successfully
```

### Run conformance tests

```bash
python3 tests/validate_golden.py
```

Expected output:
```
identity.json   ✅
message.json    ✅
stream-event.json ✅
signature.json  ✅

All 30 conformance checks passed. ✅
```

### Run the examples

```bash
# Terminal 1 — start the echo server
pip install -e './python[server]'
python3 examples/python/echo_server.py

# Terminal 2 — send it a message
pip install -e './python[http]'
python3 examples/python/client.py
```

---

## Option B — Install via ProwlrBot (full platform)

ProwlrBot includes the ROAR SDK plus the full platform (FastAPI app, channels, memory, CLI):

```bash
git clone https://github.com/ProwlrBot/prowlrbot.git
cd prowlrbot
pip install -e ".[dev]"
prowlr app   # starts on port 8088, ROAR endpoints at /roar/*
```

The ROAR types from the ProwlrBot repo are compatible with `roar-sdk` from this repo — same canonical types, same signing scheme.

---

## Package Structure

```
python/
├── pyproject.toml           # pip installable: pip install -e ./python
├── README.md
└── src/
    └── roar_sdk/
        ├── __init__.py      # Public API: from roar_sdk import *
        ├── types.py         # Canonical types — AgentIdentity, ROARMessage, StreamEvent, etc.
        ├── client.py        # ROARClient — send messages, discover agents
        ├── server.py        # ROARServer — receive and dispatch messages
        ├── streaming.py     # EventBus, StreamFilter, Subscription
        └── transports/
            ├── __init__.py  # Transport dispatcher
            └── http.py      # HTTP transport (httpx)
```

---

## Requirements

- Python 3.10+
- `pydantic>=2.0` (auto-installed with `pip install -e ./python`)
- `httpx>=0.25` for HTTP transport (optional extra: `[http]`)
- `fastapi>=0.104`, `uvicorn>=0.24` for serving (optional extra: `[server]`)

---

## Links

- [ROAR Protocol Specification](https://github.com/ProwlrBot/roar-protocol) — this repo
- [ProwlrBot Platform](https://github.com/ProwlrBot/prowlrbot) — reference implementation
- [SDK-ROADMAP.md](SDK-ROADMAP.md) — open tasks and Python/TS divergence tracker

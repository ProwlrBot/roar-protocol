# ROAR Python Examples

Two files. One runs a server, one runs a client.

---

## Requirements

```bash
git clone https://github.com/ProwlrBot/prowlrbot.git
cd prowlrbot
pip install -e ".[dev]"
pip install uvicorn httpx
```

---

## Option A: Echo Server + Client (self-contained)

The echo server is a tiny standalone ROAR agent. No ProwlrBot installation required beyond the pip install above.

**Terminal 1 — start the server:**

```bash
python3 examples/python/echo_server.py
```

Output:
```
INFO  Server DID: did:roar:agent:echo-server-a1b2c3d4...
INFO  Starting ROAR echo server on http://127.0.0.1:8089
INFO  Endpoints:
INFO    POST /roar/message  — receive a ROARMessage
INFO    GET  /roar/agents   — see this server's AgentCard
```

**Terminal 2 — run the client:**

```bash
python3 examples/python/client.py
```

Output:
```
INFO  Client DID: did:roar:agent:example-client-f5e6d7c8...
INFO  Sending DELEGATE to http://127.0.0.1:8089 ...
INFO  ✅ Response received:
INFO     intent  : respond
INFO     payload : {'echo': {'task': 'hello from ROAR client', 'data': [1, 2, 3]}, 'status': 'ok'}
INFO     from    : echo-server
INFO
INFO  Local message construction (no network):
INFO     id        : msg_...
INFO     intent    : notify
INFO     signed    : True
INFO     verify    : True
```

---

## Option B: Client talking to ProwlrBot

If you have ProwlrBot running (`prowlr app`), you can point the client at it instead. The ROAR router is mounted at port 8088 by default.

Edit `client.py`:

```python
SERVER_URL = "http://127.0.0.1:8088"
```

ProwlrBot exposes ROAR endpoints at `/roar/*`.

---

## What Each File Demonstrates

| File | Layers | Key concepts |
|:-----|:-------|:-------------|
| `echo_server.py` | 1, 2, 4, 5 | `ROARServer`, intent handler, `StreamEvent` emit, HTTP endpoint |
| `client.py` | 1, 2, 3, 4 | `ROARClient`, `AgentCard` registration, `send_remote`, HMAC verify |

---

## TypeScript Examples

TypeScript examples are pending SDK alignment. See [SDK-ROADMAP.md](../../SDK-ROADMAP.md) for status. Once the TS SDK field names are aligned to Python, a mirror of these examples will be added under `examples/ts/`.

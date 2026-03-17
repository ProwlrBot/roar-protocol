# ROAR Protocol — Installation

**Author:** [@kdairatchi](https://github.com/kdairatchi)

Pick your path — Docker for the fastest start, or install from source for development.

---

## Fastest Start — Docker

```bash
git clone https://github.com/ProwlrBot/roar-protocol.git
cd roar-protocol
docker compose up
```

Hub at `http://localhost:8090`, two demo agents at `:8091` and `:8092`. Done.

---

## Python SDK — Install from Source

```bash
git clone https://github.com/ProwlrBot/roar-protocol.git
cd roar-protocol

# Basic install (types + client + server)
pip install -e ./python

# With all bells and whistles
pip install -e './python[server,redis,cli,ed25519,monitoring]'
```

### Verify

```bash
python -c "
from roar_sdk import AgentIdentity, ROARMessage, MessageIntent
agent = AgentIdentity(display_name='test-agent', capabilities=['code'])
print('DID:', agent.did)
print('ROAR SDK installed successfully')
"
```

### Use the CLI

```bash
pip install -e './python[cli]'
roar hub start              # Start a discovery hub
roar hub health             # Check hub status
roar hub agents             # List registered agents
roar hub search code-review # Find agents by capability
```

### Run the Demo

```bash
# Terminal 1
python examples/demo/hub.py

# Terminal 2
python examples/demo/agent_a.py

# Terminal 3
python examples/demo/agent_b.py
```

### Run Tests

```bash
pip install -e './python[dev]'
python -m pytest tests/ -q
```

---

## TypeScript SDK

```bash
cd ts
npm ci
npm run build
npm test
```

---

## Go SDK

```bash
cd go
go build ./...
go test ./...
```

---

## Rust SDK

```bash
cd rust
cargo build
cargo test
```

---

## Browser/WASM SDK

For browser-based agent clients using the Web Crypto API:

```bash
cd ts/browser
npm install
```

Import directly in your browser app — uses `SubtleCrypto` for Ed25519.

---

## Production Deployment

See [docs/deployment/PRODUCTION_DEPLOYMENT.md](docs/deployment/PRODUCTION_DEPLOYMENT.md) for the full guide, or:

```bash
docker compose -f deployment/docker-compose.prod.yml up -d
```

This gives you the app + Redis + nginx with TLS.

---

## All Available Extras (Python)

```bash
pip install -e './python[server]'        # FastAPI + uvicorn + gunicorn
pip install -e './python[http]'          # httpx for HTTP transport
pip install -e './python[websocket]'     # websockets
pip install -e './python[redis]'         # Redis token store
pip install -e './python[ed25519]'       # Ed25519 signing (cryptography)
pip install -e './python[monitoring]'    # Prometheus metrics
pip install -e './python[cli]'           # CLI toolkit
pip install -e './python[dev]'           # Testing + linting tools
```

---

## Links

- [BUILD.md](BUILD.md) — Full build guide for all SDKs
- [ROAR-SPEC.md](ROAR-SPEC.md) — Protocol specification
- [SDK-ROADMAP.md](SDK-ROADMAP.md) — Feature status tracker
- [ProwlrBot](https://github.com/ProwlrBot/prowlrbot) — Reference platform implementation

---

*Built by [@kdairatchi](https://github.com/kdairatchi). The protocol should be invisible.*

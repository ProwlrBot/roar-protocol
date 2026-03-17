# ROAR Protocol — Build Guide

**Author:** [@kdairatchi](https://github.com/kdairatchi)
**Project:** [ProwlrBot/roar-protocol](https://github.com/ProwlrBot/roar-protocol)
**License:** MIT

This guide covers everything you need to build, test, deploy, and contribute to the ROAR Protocol from source. Whether you're hacking on the Python SDK, adding a feature to the Go implementation, or spinning up a production hub — this is your starting point.

---

## Prerequisites

You'll need at least one of these depending on which SDK you're working with:

| SDK | Requirement | Version |
|-----|-------------|---------|
| Python | Python | 3.10+ (3.12+ recommended) |
| TypeScript | Node.js | 22+ |
| Go | Go | 1.21+ |
| Rust | Rust + Cargo | 1.70+ |
| Docker | Docker + Compose | 24+ |

---

## Clone the Repo

```bash
git clone https://github.com/ProwlrBot/roar-protocol.git
cd roar-protocol
```

The project is a monorepo:

```
roar-protocol/
├── python/          # Python SDK (reference implementation)
├── ts/              # TypeScript SDK (Node.js)
├── ts/browser/      # TypeScript SDK (Browser/WASM — Web Crypto API)
├── go/              # Go SDK (types, signing, client)
├── rust/            # Rust SDK (types, signing, serde)
├── spec/            # Protocol specification + JSON schemas
├── tests/           # Cross-SDK conformance tests
├── examples/        # Runnable demos
├── deployment/      # Docker, nginx, monitoring configs
└── docs/            # Deployment guides, compliance, AAIF submission
```

---

## Building Each SDK

### Python SDK

The Python SDK is the reference implementation. It's the most feature-complete and is what the hub, server, and CLI are built on.

```bash
cd python

# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install with all extras
pip install -e ".[dev,server,redis,monitoring,cli,ed25519]"

# Verify the install
python -c "from roar_sdk import AgentIdentity; print(AgentIdentity(display_name='test').did)"
```

**Available extras:**

| Extra | What it adds |
|-------|-------------|
| `dev` | pytest, mypy, ruff, bandit, pip-audit |
| `server` | FastAPI, uvicorn, gunicorn, cryptography |
| `http` | httpx for HTTP transport |
| `websocket` | websockets for WS transport |
| `redis` | redis-py for multi-worker token store |
| `monitoring` | prometheus-fastapi-instrumentator |
| `cli` | httpx + cryptography for the `roar` CLI |
| `ed25519` | cryptography for Ed25519 signing |

### TypeScript SDK (Node.js)

```bash
cd ts
npm ci
npm run build        # Compiles to ts/dist/
npm run typecheck    # Type checking without emit
npm test             # Run test suite
```

### TypeScript SDK (Browser/WASM)

The browser SDK uses the Web Crypto API instead of Node.js `crypto`. It's designed for client-side applications.

```bash
cd ts/browser
npm install
# Build with esbuild (if configured) or use directly via import
```

### Go SDK

```bash
cd go
go build ./...       # Build all packages
go test ./...        # Run tests
go vet ./...         # Lint
```

### Rust SDK

```bash
cd rust
cargo build          # Build
cargo test           # Run tests
cargo clippy         # Lint
```

---

## Running the Tests

### Python Tests (full suite)

```bash
# From the repo root
python -m pytest tests/ --tb=short -q

# Just the fast unit tests (no network, no hanging)
python -m pytest tests/test_token_store.py tests/test_attestation.py \
    tests/test_negative.py tests/test_3party_delegation.py \
    tests/test_did_resolver.py tests/test_adapters.py \
    tests/test_framework_adapters.py tests/test_dns_discovery.py \
    tests/test_bridge.py tests/test_workflow.py tests/test_otel.py \
    tests/test_mcp_adapter.py tests/test_a2a_adapter.py -q
```

### Cross-SDK Conformance Tests

These verify that Python and TypeScript produce identical wire-format output:

```bash
# Requires both Python and Node.js
cd ts && npm ci && npm run build && cd ..
python -m pytest tests/test_cross_sdk_interop.py -v
```

### Go Tests

```bash
cd go && go test -v ./...
```

### Linting & Type Checking

```bash
# Python
cd python
ruff check src/roar_sdk/
mypy src/roar_sdk/ --ignore-missing-imports

# TypeScript
cd ts
npx tsc --noEmit
```

### Security Scanning

```bash
cd python
bandit -r src/roar_sdk/ -ll --skip B104,B107
pip-audit --desc
```

---

## Running the Demo

The fastest way to see ROAR in action is the 3-terminal demo:

```bash
# Terminal 1 — Start the discovery hub
python examples/demo/hub.py

# Terminal 2 — Start Agent A (the "coder")
python examples/demo/agent_a.py

# Terminal 3 — Run Agent B (the "tester") — discovers Agent A and talks to it
python examples/demo/agent_b.py
```

Or the single-script visual demo:

```bash
python examples/python/demo_hub_two_agents.py
```

---

## Docker Deployment

### One-Command Start

```bash
docker compose up
```

This starts:
- **Hub** on `http://localhost:8090`
- **Agent A** on `http://localhost:8091`
- **Agent B** on `http://localhost:8092`

### Production Deployment

```bash
# With Redis for multi-worker token store
docker compose -f deployment/docker-compose.prod.yml up -d
```

This starts the full production stack:
- ROAR app (Gunicorn + uvicorn workers)
- Redis (token store + rate limiting)
- nginx (TLS termination, rate limiting, security headers)

See [docs/deployment/PRODUCTION_DEPLOYMENT.md](docs/deployment/PRODUCTION_DEPLOYMENT.md) for the complete guide.

### CLI

```bash
pip install -e './python[cli]'
roar hub start --port 8090
roar hub health
roar hub agents
roar hub search code-review
roar register http://localhost:8090 --name my-agent --capabilities "code,review"
roar send http://localhost:8091 did:roar:agent:target '{"task":"hello"}'
```

---

## Project Architecture

```
Layer 5: Stream     → streaming.py, EventBus, SSE/WebSocket
Layer 4: Exchange   → types.py (ROARMessage), signing.py, verifier.py
Layer 3: Connect    → transports/ (HTTP, WebSocket, stdio, QUIC stub)
Layer 2: Discovery  → hub.py, directory, dns_discovery.py, well_known.py
Layer 1: Identity   → types.py (AgentIdentity, AgentCard), did_key.py, did_web.py
```

**Cross-cutting:**
- `adapters/` — MCP, A2A, ACP, AutoGen, CrewAI, LangGraph bridges
- `bridge.py` — BridgeRouter for protocol auto-detection and translation
- `workflow.py` — DAG-based workflow orchestration engine
- `otel.py` — OpenTelemetry span exporter for message tracing
- `middleware/` — Rate limiting, auth middleware
- `registry.py` — Public multi-hub agent discovery registry

---

## Security

All messages are signed by default. The protocol supports two signing schemes:

- **HMAC-SHA256** — shared secret, same-machine deployments
- **Ed25519** — asymmetric, cross-machine deployments

Production deployments should use:
- TLS termination via nginx (see `deployment/nginx/roar.conf`)
- `StrictMessageVerifier` for all message endpoints
- Redis-backed rate limiting
- CORS with explicit allowed origins (never `*`)

See [docs/deployment/SECURITY.md](docs/deployment/SECURITY.md) and [THREAT-MODEL.md](THREAT-MODEL.md).

---

## Contributing

1. Fork the repo
2. Create a feature branch
3. Make your changes with tests
4. Run the full test suite
5. Submit a PR

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

---

## Docs Reference

| Document | What's in it |
|----------|-------------|
| [ROAR-SPEC.md](ROAR-SPEC.md) | Full protocol specification |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design and layer breakdown |
| [INSTALL.md](INSTALL.md) | Quick installation guide |
| [SDK-ROADMAP.md](SDK-ROADMAP.md) | Feature status across all SDKs |
| [SECURITY.md](SECURITY.md) | Security policies and reporting |
| [THREAT-MODEL.md](THREAT-MODEL.md) | Threat analysis and mitigations |
| [CHANGELOG.md](CHANGELOG.md) | Release history |
| [docs/deployment/](docs/deployment/) | Production deployment, runbooks, security config |
| [docs/PRIVACY.md](docs/PRIVACY.md) | GDPR/SOC2/HIPAA compliance mapping |
| [docs/AAIF-SUBMISSION.md](docs/AAIF-SUBMISSION.md) | AAIF standards submission package |

---

*Built by [@kdairatchi](https://github.com/kdairatchi). Protocols are invisible when they work. That is the goal.*

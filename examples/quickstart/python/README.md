# ROAR Protocol — Python Quickstart

Get a ROAR agent running in under 5 minutes.

## Setup

```bash
pip install roar-sdk[server,ed25519]
# or from source: cd python && pip install -e ".[dev]"
```

## Examples

### 01: Hello Agent
Create an agent, register a message handler, start an HTTP server.
```bash
python 01_hello_agent.py
```

### 02: Discover and Talk
Register agents in a directory, search by capability, send signed messages.
```bash
python 02_discover_and_talk.py
```

### 03: Signed Messages
HMAC-SHA256 and Ed25519 signing with tamper detection.
```bash
python 03_signed_messages.py
```

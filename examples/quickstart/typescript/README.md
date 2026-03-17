# ROAR Protocol — TypeScript Quickstart

Get a ROAR agent running in under 5 minutes.

## Setup

```bash
npm install @roar-protocol/sdk
# or from source: cd ts && npm ci && npm run build
```

## Examples

### 01: Hello Agent
Create an agent, handle messages, start an HTTP server.
```bash
npx tsx 01_hello_agent.ts
```

### 02: Discover and Talk
Register agents in a directory, search by capability, send signed messages.
```bash
npx tsx 02_discover_and_talk.ts
```

### 03: Signed Messages
HMAC-SHA256 and Ed25519 signing with tamper detection.
```bash
npx tsx 03_signed_messages.ts
```

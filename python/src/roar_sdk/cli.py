#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ROAR Protocol — CLI Toolkit for hub and agent management.

Usage:
    roar init NAME              Scaffold a new agent project
    roar keygen                 Generate HMAC + Ed25519 keys
    roar test URL               Run conformance checks against a hub/agent

    roar hub start              Start a discovery hub
    roar hub health [URL]       Check hub health
    roar hub agents [URL]       List registered agents
    roar hub search CAP [URL]   Search agents by capability

    roar register URL           Register this agent with a hub
    roar send URL DID MSG       Send a DELEGATE message to an agent
    roar health URL             Check an agent server's health

Requires: pip install 'roar-sdk[cli]'
"""

import argparse
import asyncio
import base64
import json
import sys


def _hub_start(args: argparse.Namespace) -> None:
    from .hub import ROARHub
    hub = ROARHub(host=args.host, port=args.port)
    print(f"Starting ROAR Hub on http://{args.host}:{args.port}")
    hub.serve()


def _hub_health(args: argparse.Namespace) -> None:
    import httpx
    url = args.url.rstrip("/")
    try:
        r = httpx.get(f"{url}/roar/health", timeout=5)
        print(json.dumps(r.json(), indent=2))
    except httpx.ConnectError:
        print(f"Error: cannot connect to {url}", file=sys.stderr)
        sys.exit(1)


def _hub_agents(args: argparse.Namespace) -> None:
    import httpx
    url = args.url.rstrip("/")
    try:
        r = httpx.get(f"{url}/roar/agents", timeout=5)
        data = r.json()
        agents = data.get("agents", [])
        if not agents:
            print("No agents registered.")
            return
        for agent in agents:
            card = agent.get("agent_card", {})
            ident = card.get("identity", {})
            print(f"  {ident.get('display_name', '?')}")
            print(f"    DID:          {ident.get('did', '?')}")
            print(f"    Capabilities: {', '.join(ident.get('capabilities', []))}")
            endpoints = card.get("endpoints", {})
            if endpoints:
                print(f"    Endpoints:    {endpoints}")
            print()
    except httpx.ConnectError:
        print(f"Error: cannot connect to {url}", file=sys.stderr)
        sys.exit(1)


def _hub_search(args: argparse.Namespace) -> None:
    import httpx
    url = args.url.rstrip("/")
    try:
        r = httpx.get(f"{url}/roar/agents", params={"capability": args.capability}, timeout=5)
        data = r.json()
        agents = data.get("agents", [])
        print(f"Found {len(agents)} agent(s) with '{args.capability}':")
        for agent in agents:
            card = agent.get("agent_card", {})
            ident = card.get("identity", {})
            print(f"  - {ident.get('display_name', '?')} ({ident.get('did', '?')[:50]})")
    except httpx.ConnectError:
        print(f"Error: cannot connect to {url}", file=sys.stderr)
        sys.exit(1)


def _register(args: argparse.Namespace) -> None:
    from .types import AgentIdentity, AgentCard, AgentCapability
    from .signing import generate_keypair

    priv_key, pub_key = generate_keypair()
    identity = AgentIdentity(
        display_name=args.name,
        agent_type="agent",
        capabilities=args.capabilities.split(",") if args.capabilities else [],
        public_key=pub_key,
    )

    card = AgentCard(
        identity=identity,
        description=args.description or f"Agent: {args.name}",
        skills=identity.capabilities,
        channels=["http"],
        endpoints={"http": args.endpoint} if args.endpoint else {},
        declared_capabilities=[
            AgentCapability(name=c, description=c) for c in identity.capabilities
        ],
    )

    async def _do_register():
        import httpx
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        hub_url = args.hub_url.rstrip("/")
        async with httpx.AsyncClient() as client:
            # Step 1: Request challenge
            r = await client.post(f"{hub_url}/roar/agents/register", json={
                "did": identity.did,
                "public_key": pub_key,
                "card": card.model_dump(),
            })
            if r.status_code != 200:
                print(f"Error: {r.status_code} {r.text}", file=sys.stderr)
                sys.exit(1)
            challenge = r.json()
            print(f"Challenge received: {challenge['challenge_id'][:16]}...")

            # Step 2: Sign and complete
            private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(priv_key))
            sig_bytes = private.sign(challenge["nonce"].encode())
            sig_b64 = base64.urlsafe_b64encode(sig_bytes).decode().rstrip("=")

            r = await client.post(f"{hub_url}/roar/agents/challenge", json={
                "challenge_id": challenge["challenge_id"],
                "signature": f"ed25519:{sig_b64}",
            })
            result = r.json()
            if result.get("registered"):
                print("Registered successfully!")
                print(f"  DID: {identity.did}")
                print(f"  Name: {args.name}")
                print(f"  Private key (save this!): {priv_key}")
            else:
                print(f"Registration failed: {result}", file=sys.stderr)
                sys.exit(1)

    asyncio.run(_do_register())


def _send(args: argparse.Namespace) -> None:
    from .types import AgentIdentity, ROARMessage, MessageIntent

    sender = AgentIdentity(display_name="roar-cli")
    receiver = AgentIdentity(did=args.did, display_name="target")

    msg = ROARMessage(
        **{"from": sender, "to": receiver},  # type: ignore[arg-type]
        intent=MessageIntent.DELEGATE,
        payload=json.loads(args.payload) if args.payload.startswith("{") else {"task": args.payload},
    )
    if args.secret:
        msg.sign(args.secret)

    async def _do_send():
        import httpx
        url = args.url.rstrip("/")
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{url}/roar/message",
                json=msg.model_dump(by_alias=True),
                timeout=10,
            )
            print(f"Status: {r.status_code}")
            print(json.dumps(r.json(), indent=2))

    asyncio.run(_do_send())


def _health(args: argparse.Namespace) -> None:
    import httpx
    url = args.url.rstrip("/")
    try:
        r = httpx.get(f"{url}/roar/health", timeout=5)
        print(json.dumps(r.json(), indent=2))
    except httpx.ConnectError:
        print(f"Error: cannot connect to {url}", file=sys.stderr)
        sys.exit(1)


def _init_project(args: argparse.Namespace) -> None:
    import os
    name = args.name
    if os.path.exists(name):
        print(f"Error: directory '{name}' already exists", file=sys.stderr)
        sys.exit(1)

    os.makedirs(name)
    if args.lang == "python":
        with open(os.path.join(name, "agent.py"), "w") as f:
            f.write(f'''#!/usr/bin/env python3
"""ROAR agent: {name}"""
import os
from roar_sdk import AgentIdentity, ROARServer, ROARMessage, MessageIntent

identity = AgentIdentity(
    display_name="{name}",
    agent_type="agent",
    capabilities=["example"],
)

server = ROARServer(
    identity=identity,
    port=8089,
    signing_secret=os.environ.get("ROAR_SIGNING_SECRET", ""),
)

@server.on(MessageIntent.DELEGATE)
async def handle(msg: ROARMessage) -> ROARMessage:
    return ROARMessage(
        **{{"from": server.identity, "to": msg.from_identity}},
        intent=MessageIntent.RESPOND,
        payload={{"status": "ok"}},
        context={{"in_reply_to": msg.id}},
    )

if __name__ == "__main__":
    server.serve()
''')
        with open(os.path.join(name, ".env"), "w") as f:
            f.write("ROAR_SIGNING_SECRET=\n")
        with open(os.path.join(name, "requirements.txt"), "w") as f:
            f.write("roar-sdk[server]\n")
        print(f"Created '{name}/' with:")
        print("  agent.py         — ROAR agent server")
        print("  .env             — environment config (set your signing secret)")
        print("  requirements.txt — dependencies")
        print("\nNext steps:")
        print(f"  cd {name}")
        print("  roar keygen --type hmac  # generate a signing secret")
        print("  pip install -r requirements.txt")
        print("  python agent.py")
    else:
        with open(os.path.join(name, "agent.ts"), "w") as f:
            f.write(f'''import {{ AgentIdentity, ROARMessage, MessageIntent }} from "@roar-protocol/sdk";

const identity: AgentIdentity = {{
  did: "",
  display_name: "{name}",
  agent_type: "agent",
  capabilities: ["example"],
  version: "1.0",
}};

console.log("Agent DID:", identity.did);
''')
        with open(os.path.join(name, "package.json"), "w") as f:
            f.write(json.dumps({"name": name, "dependencies": {"@roar-protocol/sdk": "^0.3.0"}}, indent=2))
        print(f"Created '{name}/' with agent.ts and package.json")
        print("\nNext steps:")
        print(f"  cd {name} && npm install && npx ts-node agent.ts")


def _keygen(args: argparse.Namespace) -> None:
    import secrets
    output: list[str] = []

    if args.key_type in ("hmac", "both"):
        hmac_secret = secrets.token_urlsafe(32)
        output.append(f"ROAR_SIGNING_SECRET={hmac_secret}")

    if args.key_type in ("ed25519", "both"):
        from .signing import generate_keypair
        private_hex, public_hex = generate_keypair()
        output.append(f"ROAR_ED25519_PRIVATE_KEY={private_hex}")
        output.append(f"ROAR_ED25519_PUBLIC_KEY={public_hex}")

    text = "\n".join(output)
    if args.output:
        with open(args.output, "w") as f:
            f.write(text + "\n")
        print(f"Keys written to {args.output}")
    else:
        print(text)


def _test_endpoint(args: argparse.Namespace) -> None:
    import httpx
    url = args.url.rstrip("/")
    passed = 0
    failed = 0

    def _check(name: str, fn):
        nonlocal passed, failed
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1

    print(f"Testing {url} ...\n")

    def check_health():
        r = httpx.get(f"{url}/roar/health", timeout=5)
        assert r.status_code == 200, f"status {r.status_code}"
        data = r.json()
        assert "status" in data, "missing 'status' field"

    def check_agents():
        r = httpx.get(f"{url}/roar/agents", timeout=5)
        assert r.status_code == 200, f"status {r.status_code}"
        data = r.json()
        assert "agents" in data, "missing 'agents' field"

    def check_message_rejects_unsigned():
        from .types import AgentIdentity, ROARMessage, MessageIntent
        sender = AgentIdentity(display_name="test-cli")
        receiver = AgentIdentity(display_name="target")
        msg = ROARMessage(
            **{"from": sender, "to": receiver},
            intent=MessageIntent.DELEGATE,
            payload={"test": True},
        )
        r = httpx.post(f"{url}/roar/message", json=msg.model_dump(by_alias=True), timeout=5)
        assert r.status_code in (401, 403, 422), f"unsigned message accepted (status {r.status_code})"

    def check_message_signed():
        if not args.secret:
            raise AssertionError("skipped (no --secret provided)")
        from .types import AgentIdentity, ROARMessage, MessageIntent
        sender = AgentIdentity(display_name="test-cli")
        receiver = AgentIdentity(display_name="target")
        msg = ROARMessage(
            **{"from": sender, "to": receiver},
            intent=MessageIntent.DELEGATE,
            payload={"test": True},
        )
        msg.sign(args.secret)
        r = httpx.post(f"{url}/roar/message", json=msg.model_dump(by_alias=True), timeout=5)
        assert r.status_code == 200, f"signed message rejected (status {r.status_code})"

    _check("GET /roar/health returns 200", check_health)
    _check("GET /roar/agents returns 200", check_agents)
    _check("POST /roar/message rejects unsigned", check_message_rejects_unsigned)
    _check("POST /roar/message accepts signed", check_message_signed)

    print(f"\n{passed} passed, {failed} failed")
    if failed:
        sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="roar",
        description="ROAR Protocol CLI — manage hubs and agents",
    )
    sub = parser.add_subparsers(dest="command")

    # --- hub commands ---
    hub_parser = sub.add_parser("hub", help="Hub management")
    hub_sub = hub_parser.add_subparsers(dest="hub_command")

    start = hub_sub.add_parser("start", help="Start a discovery hub")
    start.add_argument("--host", default="127.0.0.1")
    start.add_argument("--port", type=int, default=8090)
    start.set_defaults(func=_hub_start)

    health = hub_sub.add_parser("health", help="Check hub health")
    health.add_argument("url", nargs="?", default="http://127.0.0.1:8090")
    health.set_defaults(func=_hub_health)

    agents = hub_sub.add_parser("agents", help="List registered agents")
    agents.add_argument("url", nargs="?", default="http://127.0.0.1:8090")
    agents.set_defaults(func=_hub_agents)

    search = hub_sub.add_parser("search", help="Search agents by capability")
    search.add_argument("capability", help="Capability to search for")
    search.add_argument("url", nargs="?", default="http://127.0.0.1:8090")
    search.set_defaults(func=_hub_search)

    # --- register command ---
    reg = sub.add_parser("register", help="Register agent with a hub")
    reg.add_argument("hub_url", help="Hub URL (e.g. http://127.0.0.1:8090)")
    reg.add_argument("--name", required=True, help="Agent display name")
    reg.add_argument("--capabilities", default="", help="Comma-separated capabilities")
    reg.add_argument("--description", default="", help="Agent description")
    reg.add_argument("--endpoint", default="", help="Agent HTTP endpoint URL")
    reg.set_defaults(func=_register)

    # --- send command ---
    snd = sub.add_parser("send", help="Send a message to an agent")
    snd.add_argument("url", help="Agent server URL")
    snd.add_argument("did", help="Target agent DID")
    snd.add_argument("payload", help="Message payload (JSON or plain text)")
    snd.add_argument("--secret", default="", help="HMAC signing secret")
    snd.set_defaults(func=_send)

    # --- health command ---
    hlth = sub.add_parser("health", help="Check agent/hub health")
    hlth.add_argument("url", help="URL to check")
    hlth.set_defaults(func=_health)

    # --- init command ---
    init_p = sub.add_parser("init", help="Scaffold a new ROAR agent project")
    init_p.add_argument("name", help="Agent project name")
    init_p.add_argument("--lang", choices=["python", "typescript"], default="python")
    init_p.set_defaults(func=_init_project)

    # --- keygen command ---
    kg = sub.add_parser("keygen", help="Generate signing keys")
    kg.add_argument("--type", choices=["hmac", "ed25519", "both"], default="both", dest="key_type")
    kg.add_argument("--output", default="", help="Write keys to file (default: stdout)")
    kg.set_defaults(func=_keygen)

    # --- test command ---
    tst = sub.add_parser("test", help="Run conformance checks against a hub or agent")
    tst.add_argument("url", help="Hub or agent URL to test")
    tst.add_argument("--secret", default="", help="HMAC secret for signed tests")
    tst.set_defaults(func=_test_endpoint)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        sys.exit(0)
    if args.command == "hub" and not getattr(args, "hub_command", None):
        hub_parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()

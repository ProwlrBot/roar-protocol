#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ROAR Protocol — CLI Toolkit for hub and agent management.

Usage:
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
                print(f"Registered successfully!")
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
        **{"from": sender, "to": receiver},
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

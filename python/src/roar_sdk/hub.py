# -*- coding: utf-8 -*-
"""ROAR Protocol — Hub server with federation support (Layer 2).

A ROAR Hub is a discovery server that:
  1. Maintains a registry of agent cards (AgentDirectory)
  2. Exposes a REST API for registration, lookup, and search
  3. Federates with other hubs by syncing entries (push/pull)

Hub API endpoints (mounted on a FastAPI app):

  POST /roar/agents/register   — begin challenge-response registration
  POST /roar/agents/challenge  — complete registration with signed proof
  DELETE /roar/agents/{did}    — unregister (requires signed proof)
  GET  /roar/agents            — list all agents
  GET  /roar/agents/{did}      — lookup single agent
  GET  /roar/agents/search?capability=X — search by capability
  POST /roar/federation/sync   — receive entries from a peer hub
  GET  /roar/federation/export — export all entries for a peer hub

Usage::

    from roar_sdk.hub import ROARHub

    hub = ROARHub(host="0.0.0.0", port=8090)
    hub.add_peer("https://hub2.example.com")
    hub.serve()
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any, List, Optional

from .hub_auth import ChallengeStore
from .types import AgentCard, AgentDirectory, DiscoveryEntry

# FastAPI / uvicorn are optional (server extra).  Import them at module level so
# that ``from __future__ import annotations`` does not turn type hints inside
# serve() into unresolvable forward-reference strings.
try:
    from fastapi import FastAPI, HTTPException, Request  # type: ignore[import]
    from fastapi.responses import JSONResponse  # type: ignore[import]
    import uvicorn  # type: ignore[import]
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False
    # Provide stubs so that type annotations inside serve() can still be written.
    # They are only evaluated at runtime when serve() is called, which will raise
    # ImportError before reaching the annotated functions anyway.
    Request = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# Maximum request body size: 256 KiB
_MAX_BODY_BYTES = 256 * 1024


class ROARHub:
    """A ROAR discovery hub with federation support.

    Requires: pip install 'roar-sdk[server]'
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8090,
        *,
        hub_id: str = "",
        peer_urls: Optional[List[str]] = None,
    ) -> None:
        self._host = host
        self._port = port
        self._hub_url = hub_id or f"http://{host}:{port}"
        self._directory = AgentDirectory()
        self._peers: List[str] = list(peer_urls or [])
        self._challenge_store = ChallengeStore()

    @property
    def directory(self) -> AgentDirectory:
        return self._directory

    def add_peer(self, hub_url: str) -> None:
        if hub_url not in self._peers:
            self._peers.append(hub_url)

    def serve(self) -> None:
        """Start the hub HTTP server.

        Requires: pip install 'roar-sdk[server]'
        """
        if not _FASTAPI_AVAILABLE:
            raise ImportError(
                "Hub server requires fastapi and uvicorn. "
                "Install them: pip install 'roar-sdk[server]'"
            )

        app = FastAPI(title=f"ROAR Hub — {self._hub_url}")
        hub = self

        # ── Helpers ───────────────────────────────────────────────────────

        async def _read_bounded_json(request: Request) -> dict:
            """Read request body with a 256 KiB cap, then parse as JSON."""
            body = await request.body()
            if len(body) > _MAX_BODY_BYTES:
                raise HTTPException(status_code=413, detail="Request body too large")
            import json as _json
            try:
                return _json.loads(body)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid JSON body")

        def _verify_ed25519(public_key_hex: str, signature_str: str, message: str) -> bool:
            """Verify an Ed25519 signature.

            *signature_str* must be of the form ``ed25519:<base64url>``.
            *message* is the UTF-8 plaintext that was signed.

            Raises ``ImportError`` if the cryptography package is absent.
            Raises ``ValueError`` for malformed inputs.
            Returns True on success, False on bad signature.
            """
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            from cryptography.exceptions import InvalidSignature

            if not signature_str.startswith("ed25519:"):
                raise ValueError("Signature must start with 'ed25519:'")
            b64_part = signature_str[len("ed25519:"):]
            # base64url without padding
            padding = "=" * (-len(b64_part) % 4)
            try:
                sig_bytes = base64.urlsafe_b64decode(b64_part + padding)
            except Exception:
                raise ValueError("Malformed base64url in signature")

            try:
                pub_bytes = bytes.fromhex(public_key_hex)
            except ValueError:
                raise ValueError("Malformed public key hex")

            pub_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
            try:
                pub_key.verify(sig_bytes, message.encode())
                return True
            except InvalidSignature:
                return False

        # ── Agent registration — step 1 ───────────────────────────────────

        @app.post("/roar/agents/register")
        async def register(request: Request):
            """Issue a challenge for proof-of-possession registration.

            Accepts: { "did": str, "public_key": str, "card": {...} }
            Returns: { "challenge_id": ..., "nonce": ..., "expires_at": ... }
            """
            body = await _read_bounded_json(request)

            did = body.get("did", "")
            public_key = body.get("public_key", "")
            card_raw = body.get("card", {})

            if not isinstance(did, str) or not did:
                return JSONResponse(
                    status_code=400,
                    content={"error": "did is required"},
                )
            if not isinstance(public_key, str) or not public_key:
                return JSONResponse(
                    status_code=400,
                    content={"error": "public_key is required — cannot verify identity without key"},
                )

            try:
                challenge = hub._challenge_store.issue(did, public_key, card_raw)
            except RuntimeError as exc:
                return JSONResponse(
                    status_code=503,
                    content={"error": str(exc)},
                )

            logger.info("Challenge issued for DID: %s  challenge_id: %s", did, challenge.challenge_id)
            return {
                "challenge_id": challenge.challenge_id,
                "nonce": challenge.nonce,
                "expires_at": challenge.expires_at,
            }

        # ── Agent registration — step 2 ───────────────────────────────────

        @app.post("/roar/agents/challenge")
        async def complete_challenge(request: Request):
            """Verify signed challenge and register the agent card.

            Accepts: { "challenge_id": str, "signature": "ed25519:<base64url>" }
            Returns: { "registered": true }
            """
            body = await _read_bounded_json(request)

            challenge_id = body.get("challenge_id", "")
            signature = body.get("signature", "")

            if not isinstance(challenge_id, str) or not challenge_id:
                return JSONResponse(status_code=400, content={"error": "challenge_id is required"})
            if not isinstance(signature, str) or not signature:
                return JSONResponse(status_code=400, content={"error": "signature is required"})

            # Consume challenge (deletes it — prevents replay)
            challenge = hub._challenge_store.consume(challenge_id)
            if challenge is None:
                return JSONResponse(status_code=401, content={"error": "challenge_expired"})

            # Verify signature
            try:
                valid = _verify_ed25519(challenge.public_key, signature, challenge.nonce)
            except ImportError:
                return JSONResponse(
                    status_code=503,
                    content={"error": "signature_verification_unavailable"},
                )
            except ValueError as exc:
                return JSONResponse(status_code=401, content={"error": f"invalid_signature: {exc}"})

            if not valid:
                return JSONResponse(status_code=401, content={"error": "invalid_signature"})

            # Register the card stored in the challenge
            try:
                card = AgentCard(**challenge.card)
            except Exception as exc:
                return JSONResponse(status_code=400, content={"error": f"invalid card: {exc}"})

            entry = hub._directory.register(card)
            entry.hub_url = hub._hub_url
            logger.info("Registered (challenge ok): %s", card.identity.did)
            return {"registered": True}

        # ── Agent unregistration — signed proof required ──────────────────

        @app.delete("/roar/agents/{did:path}")
        async def unregister(did: str, request: Request):
            """Unregister an agent. Requires a signed proof of ownership.

            Accepts: { "did": str, "signature": str, "nonce": str, "timestamp": float }
            The signature must cover the string: ``delete:{did}:{nonce}:{timestamp}``
            """
            body = await _read_bounded_json(request)

            signature = body.get("signature", "")
            nonce = body.get("nonce", "")
            timestamp = body.get("timestamp")

            if not signature or not nonce or timestamp is None:
                return JSONResponse(
                    status_code=400,
                    content={"error": "signature, nonce, and timestamp are required"},
                )

            try:
                timestamp = float(timestamp)
            except (TypeError, ValueError):
                return JSONResponse(status_code=400, content={"error": "timestamp must be a number"})

            # Reject stale requests
            if abs(time.time() - timestamp) > 60:
                return JSONResponse(status_code=401, content={"error": "timestamp_expired"})

            # Look up the registered entry to get the public key
            entry = hub._directory.lookup(did)
            if not entry:
                raise HTTPException(status_code=404, detail="Agent not found")

            public_key = entry.agent_card.identity.public_key
            if not public_key:
                return JSONResponse(
                    status_code=400,
                    content={"error": "registered card has no public_key — cannot verify delete request"},
                )

            message = f"delete:{did}:{nonce}:{timestamp}"
            try:
                valid = _verify_ed25519(public_key, signature, message)
            except ImportError:
                return JSONResponse(
                    status_code=503,
                    content={"error": "signature_verification_unavailable"},
                )
            except ValueError as exc:
                return JSONResponse(status_code=401, content={"error": f"invalid_signature: {exc}"})

            if not valid:
                return JSONResponse(status_code=401, content={"error": "invalid_signature"})

            hub._directory.unregister(did)
            logger.info("Unregistered (signed): %s", did)
            return {"status": "removed", "did": did}

        # ── Agent lookup ──────────────────────────────────────────────────

        @app.get("/roar/agents")
        async def list_agents(capability: Optional[str] = None):
            if capability:
                entries = hub._directory.search(capability)
            else:
                entries = hub._directory.list_all()
            return {"agents": [e.model_dump() for e in entries]}

        @app.get("/roar/agents/{did:path}")
        async def lookup_agent(did: str):
            entry = hub._directory.lookup(did)
            if not entry:
                raise HTTPException(status_code=404, detail="Agent not found")
            return entry.model_dump()

        # ── Federation ───────────────────────────────────────────────────

        @app.post("/roar/federation/sync")
        async def receive_sync(request: Request):
            """Accept a batch of DiscoveryEntry objects from a peer hub.

            Requires Authorization header with federation secret.
            """
            import hmac as _hmac
            fed_secret = _os.getenv("ROAR_FEDERATION_SECRET", "")
            if fed_secret:
                auth_header = request.headers.get("authorization", "")
                if not auth_header.startswith("Bearer ") or not _hmac.compare_digest(
                    auth_header[7:], fed_secret
                ):
                    raise HTTPException(status_code=401, detail="Invalid federation secret")
            else:
                logger.warning("ROAR_FEDERATION_SECRET not set — federation sync is unauthenticated")

            body = await _read_bounded_json(request)
            entries = body.get("entries", [])
            imported = 0
            for raw in entries:
                try:
                    entry = DiscoveryEntry(**raw)
                    # Don't overwrite locally-registered agents
                    if not hub._directory.lookup(entry.agent_card.identity.did):
                        hub._directory.register(entry.agent_card)
                        imported += 1
                except Exception as exc:
                    logger.warning("federation/sync: skipping entry: %s", exc)
            return {"imported": imported, "total": len(entries)}

        @app.get("/roar/federation/export")
        async def export_for_peers():
            """Export all local entries for peer hubs to import."""
            entries = hub._directory.list_all()
            return {
                "hub_url": hub._hub_url,
                "exported_at": time.time(),
                "entries": [e.model_dump() for e in entries],
            }

        @app.get("/roar/health")
        async def health():
            import os as _os
            redis_status = "not_configured"
            redis_url = _os.getenv("ROAR_REDIS_URL")
            if redis_url:
                try:
                    import redis as _redis
                    r = _redis.from_url(redis_url, socket_timeout=1.0, socket_connect_timeout=1.0)
                    r.ping()
                    redis_status = "connected"
                except Exception:
                    redis_status = "disconnected"
            return {
                "status": "healthy",
                "protocol": "roar/1.0",
                "hub_url": hub._hub_url,
                "agents": len(hub._directory.list_all()),
                "peers": len(hub._peers),
                "dependencies": {"redis": redis_status},
            }

        logger.info("ROAR Hub starting on http://%s:%d", self._host, self._port)
        uvicorn.run(app, host=self._host, port=self._port, log_level="warning")

    async def push_to_peers(self) -> dict:
        """Push local entries to all configured peer hubs.

        Requires: pip install 'roar-sdk[http]'
        """
        try:
            import httpx
        except ImportError:
            raise ImportError("Federation push requires httpx: pip install 'roar-sdk[http]'")

        entries = [e.model_dump() for e in self._directory.list_all()]
        payload = {
            "hub_url": self._hub_url,
            "exported_at": time.time(),
            "entries": entries,
        }
        results: dict[str, dict[str, Any]] = {}
        async with httpx.AsyncClient(timeout=10) as client:
            for peer in self._peers:
                try:
                    r = await client.post(f"{peer.rstrip('/')}/roar/federation/sync", json=payload)
                    results[peer] = {"status": r.status_code, "imported": r.json().get("imported", 0)}
                except Exception as exc:
                    results[peer] = {"status": "error", "detail": str(exc)}
        return results

    async def pull_from_peers(self) -> dict:
        """Pull entries from all configured peer hubs.

        Requires: pip install 'roar-sdk[http]'
        """
        try:
            import httpx
        except ImportError:
            raise ImportError("Federation pull requires httpx: pip install 'roar-sdk[http]'")

        results: dict[str, dict[str, Any]] = {}
        async with httpx.AsyncClient(timeout=10) as client:
            for peer in self._peers:
                try:
                    r = await client.get(f"{peer.rstrip('/')}/roar/federation/export")
                    data = r.json()
                    imported = 0
                    for raw in data.get("entries", []):
                        try:
                            entry = DiscoveryEntry(**raw)
                            did = entry.agent_card.identity.did
                            if not self._directory.lookup(did):
                                self._directory._agents[did] = entry
                                imported += 1
                        except Exception:
                            pass
                    results[peer] = {"imported": imported}
                except Exception as exc:
                    results[peer] = {"status": "error", "detail": str(exc)}
        return results

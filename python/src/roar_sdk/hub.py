# -*- coding: utf-8 -*-
"""ROAR Protocol — Hub server with federation support (Layer 2).

A ROAR Hub is a discovery server that:
  1. Maintains a registry of agent cards (AgentDirectory)
  2. Exposes a REST API for registration, lookup, and search
  3. Federates with other hubs by syncing entries (push/pull)

Hub API endpoints (mounted on a FastAPI app):

  POST /roar/agents/register   — register an AgentCard
  DELETE /roar/agents/{did}    — unregister
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

import logging
import time
from typing import List, Optional

from .types import AgentCard, AgentDirectory, AgentIdentity, DiscoveryEntry

logger = logging.getLogger(__name__)


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
        try:
            from fastapi import FastAPI, HTTPException, Request
            from fastapi.responses import JSONResponse
            import uvicorn
        except ImportError:
            raise ImportError(
                "Hub server requires fastapi and uvicorn. "
                "Install them: pip install 'roar-sdk[server]'"
            )

        app = FastAPI(title=f"ROAR Hub — {self._hub_url}")
        hub = self

        # ── Agent registration ────────────────────────────────────────────

        _MAX_BODY = 256 * 1024  # 256 KiB — sufficient for any AgentCard

        async def _read_bounded_json(request: Request) -> Optional[dict]:
            """Read and parse the request body with a hard size cap.

            Returns the parsed dict or None if the body is too large or unparseable.
            """
            import json as _json
            raw = await request.body()
            if len(raw) > _MAX_BODY:
                return None
            try:
                data = _json.loads(raw)
                if not isinstance(data, dict):
                    return None
                return data
            except Exception:
                return None

        @app.post("/roar/agents/register")
        async def register(request: Request):
            body = await _read_bounded_json(request)
            if body is None:
                raise HTTPException(status_code=400, detail="Invalid or oversized request body")
            try:
                card = AgentCard(**body)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid AgentCard payload")
            entry = hub._directory.register(card)
            entry.hub_url = hub._hub_url
            logger.info("Registered: %s", card.identity.did)
            return entry.model_dump()

        @app.delete("/roar/agents/{did:path}")
        async def unregister(did: str):
            removed = hub._directory.unregister(did)
            if not removed:
                raise HTTPException(status_code=404, detail="Agent not found")
            return {"status": "removed", "did": did}

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
            """Accept a batch of DiscoveryEntry objects from a peer hub."""
            body = await _read_bounded_json(request)
            if body is None:
                raise HTTPException(status_code=400, detail="Invalid or oversized request body")
            entries = body.get("entries", [])
            imported = 0
            for raw in entries:
                try:
                    entry = DiscoveryEntry(**raw)
                    # Don't overwrite locally-registered agents
                    if not hub._directory.lookup(entry.agent_card.identity.did):
                        hub._directory._agents[entry.agent_card.identity.did] = entry
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
            return {
                "status": "ok",
                "protocol": "roar/1.0",
                "hub_url": hub._hub_url,
                "agents": len(hub._directory.list_all()),
                "peers": len(hub._peers),
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
        results = {}
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

        results = {}
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

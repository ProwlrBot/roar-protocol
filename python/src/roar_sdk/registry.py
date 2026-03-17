# -*- coding: utf-8 -*-
"""ROAR Protocol — Public Agent Discovery Registry (Layer 2+).

A PublicRegistry aggregates agents from multiple ROAR hubs and makes them
searchable by anyone on the internet.  It extends the hub's functionality
with cross-hub federation, full-text search, and machine-readable metadata.

REST API endpoints (mounted on a FastAPI app):

  GET  /registry/agents           — paginated agent list (filters: capability, protocol)
  GET  /registry/agents/{did}     — single agent lookup
  GET  /registry/search?q=<text>  — full-text search across names, descriptions, capabilities
  GET  /registry/hubs             — list registered hubs
  POST /registry/hubs             — register a new hub (requires admin API key)
  GET  /registry/stats            — registry statistics
  GET  /registry/health           — health check
  GET  /.well-known/roar-registry.json — machine-readable registry metadata

Usage::

    from roar_sdk.registry import PublicRegistry

    registry = PublicRegistry(
        host="0.0.0.0",
        port=8095,
        registry_name="My Public Registry",
        admin_api_key="supersecret",
    )
    registry.register_hub("http://localhost:8090")
    registry.serve()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

from .types import AgentCard, AgentDirectory, DiscoveryEntry

try:
    from fastapi import FastAPI, HTTPException, Query, Request  # type: ignore[import]
    from fastapi.responses import JSONResponse  # type: ignore[import]
    import uvicorn  # type: ignore[import]
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False
    Request = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

__all__ = ["PublicRegistry", "RegistryEntry"]


# ---------------------------------------------------------------------------
# RegistryEntry — extends DiscoveryEntry with hub provenance
# ---------------------------------------------------------------------------

@dataclass
class RegistryEntry:
    """An agent entry in the public registry.

    Extends the information from DiscoveryEntry with the hub it came from
    and the list of protocols the agent supports.
    """

    agent_card: AgentCard
    hub_url: str = ""
    registered_at: float = 0.0
    last_seen: float = 0.0
    protocols_supported: List[str] = dc_field(default_factory=list)

    def __post_init__(self) -> None:
        if self.registered_at == 0.0:
            self.registered_at = time.time()
        if self.last_seen == 0.0:
            self.last_seen = time.time()
        if not self.protocols_supported:
            protocols = ["roar/1.0"]
            for ch in self.agent_card.channels:
                if ch not in protocols:
                    protocols.append(ch)
            self.protocols_supported = protocols

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict suitable for JSON responses."""
        return {
            "agent_card": self.agent_card.model_dump(),
            "hub_url": self.hub_url,
            "registered_at": self.registered_at,
            "last_seen": self.last_seen,
            "protocols_supported": self.protocols_supported,
        }

    @classmethod
    def from_discovery_entry(
        cls, entry: DiscoveryEntry, hub_url: str = ""
    ) -> "RegistryEntry":
        """Convert a DiscoveryEntry into a RegistryEntry."""
        protocols = ["roar/1.0"]
        for ch in entry.agent_card.channels:
            if ch not in protocols:
                protocols.append(ch)
        return cls(
            agent_card=entry.agent_card,
            hub_url=hub_url or entry.hub_url,
            registered_at=entry.registered_at,
            last_seen=entry.last_seen,
            protocols_supported=protocols,
        )


# ---------------------------------------------------------------------------
# PublicRegistry — the main service
# ---------------------------------------------------------------------------

class PublicRegistry:
    """Public Agent Discovery Registry.

    Aggregates agents from multiple ROAR hubs and exposes a unified,
    searchable REST API.

    Requires: ``pip install 'roar-sdk[server]'``
    """

    REGISTRY_VERSION = "1.0.0"

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8095,
        registry_name: str = "ROAR Public Registry",
        admin_api_key: str = "",
    ) -> None:
        self._host = host
        self._port = port
        self._registry_name = registry_name
        self._admin_api_key = admin_api_key

        # Hub-URL -> last-sync timestamp
        self._hubs: Dict[str, float] = {}

        # DID -> RegistryEntry (deduplicated — latest registration wins)
        self._agents: Dict[str, RegistryEntry] = {}

        # Internal AgentDirectory used for capability search
        self._directory = AgentDirectory()

    # ------------------------------------------------------------------
    # Hub management
    # ------------------------------------------------------------------

    def register_hub(self, hub_url: str) -> None:
        """Register a peer hub as a source of agents."""
        url = hub_url.rstrip("/")
        if url not in self._hubs:
            self._hubs[url] = 0.0
            logger.info("Registered hub: %s", url)

    def list_hubs(self) -> List[Dict[str, Any]]:
        """Return a list of registered hubs with their sync status."""
        return [
            {"hub_url": url, "last_sync": ts}
            for url, ts in self._hubs.items()
        ]

    # ------------------------------------------------------------------
    # Agent ingestion & deduplication
    # ------------------------------------------------------------------

    def _ingest_entry(self, entry: DiscoveryEntry, hub_url: str) -> None:
        """Add or update an agent in the registry.

        Deduplication: if the DID already exists, the entry with the more
        recent ``registered_at`` timestamp wins.
        """
        did = entry.agent_card.identity.did
        reg_entry = RegistryEntry.from_discovery_entry(entry, hub_url=hub_url)

        existing = self._agents.get(did)
        if existing is None or reg_entry.registered_at >= existing.registered_at:
            self._agents[did] = reg_entry
            # Keep the internal directory in sync
            self._directory._agents[did] = entry

    async def pull_from_hubs(self) -> Dict[str, Any]:
        """Pull agent lists from all registered hubs (async).

        Requires: ``pip install 'roar-sdk[http]'``

        Returns a dict mapping hub_url -> result summary.
        """
        try:
            import httpx  # type: ignore[import]
        except ImportError:
            raise ImportError(
                "Registry pull requires httpx: pip install 'roar-sdk[http]'"
            )

        results: Dict[str, Any] = {}
        async with httpx.AsyncClient(timeout=10) as client:
            for hub_url in list(self._hubs.keys()):
                try:
                    resp = await client.get(
                        f"{hub_url}/roar/federation/export"
                    )
                    data = resp.json()
                    imported = 0
                    for raw in data.get("entries", []):
                        try:
                            entry = DiscoveryEntry(**raw)
                            self._ingest_entry(entry, hub_url=hub_url)
                            imported += 1
                        except Exception as exc:
                            logger.warning(
                                "Skipping entry from %s: %s", hub_url, exc
                            )
                    self._hubs[hub_url] = time.time()
                    results[hub_url] = {"imported": imported}
                except Exception as exc:
                    results[hub_url] = {"error": str(exc)}
        return results

    def pull_from_hubs_sync(self) -> Dict[str, Any]:
        """Synchronous wrapper around :meth:`pull_from_hubs`.

        Convenience for scripts that are not already running an event loop.
        """
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run, self.pull_from_hubs()
                ).result()
        return asyncio.run(self.pull_from_hubs())

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        *,
        capability: Optional[str] = None,
        protocol: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[RegistryEntry]:
        """Search agents with optional capability / protocol filters.

        Returns a paginated slice of matching RegistryEntry objects.
        """
        results: List[RegistryEntry] = []
        for entry in self._agents.values():
            if capability:
                if capability not in entry.agent_card.identity.capabilities:
                    continue
            if protocol:
                if protocol not in entry.protocols_supported:
                    continue
            results.append(entry)
        return results[offset : offset + limit]

    def full_text_search(
        self,
        query: str,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> List[RegistryEntry]:
        """Full-text search across names, descriptions, and capabilities.

        Case-insensitive substring matching on:
          - display_name
          - description (card-level)
          - capabilities list
          - skills list
        """
        q = query.lower()
        results: List[RegistryEntry] = []
        for entry in self._agents.values():
            card = entry.agent_card
            identity = card.identity
            haystack = " ".join([
                identity.display_name.lower(),
                card.description.lower(),
                " ".join(c.lower() for c in identity.capabilities),
                " ".join(s.lower() for s in card.skills),
            ])
            if q in haystack:
                results.append(entry)
        return results[offset : offset + limit]

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Return aggregate statistics about the registry."""
        by_protocol: Dict[str, int] = {}
        by_capability: Dict[str, int] = {}

        for entry in self._agents.values():
            for proto in entry.protocols_supported:
                by_protocol[proto] = by_protocol.get(proto, 0) + 1
            for cap in entry.agent_card.identity.capabilities:
                by_capability[cap] = by_capability.get(cap, 0) + 1

        return {
            "total_agents": len(self._agents),
            "total_hubs": len(self._hubs),
            "by_protocol": by_protocol,
            "by_capability": by_capability,
        }

    # ------------------------------------------------------------------
    # Well-known metadata
    # ------------------------------------------------------------------

    def well_known_metadata(self) -> Dict[str, Any]:
        """Machine-readable registry metadata for ``/.well-known/roar-registry.json``."""
        all_protocols: List[str] = []
        for entry in self._agents.values():
            for proto in entry.protocols_supported:
                if proto not in all_protocols:
                    all_protocols.append(proto)

        return {
            "name": self._registry_name,
            "version": self.REGISTRY_VERSION,
            "total_agents": len(self._agents),
            "total_hubs": len(self._hubs),
            "api_url": f"http://{self._host}:{self._port}/registry",
            "supported_protocols": all_protocols,
        }

    # ------------------------------------------------------------------
    # REST API (FastAPI)
    # ------------------------------------------------------------------

    def serve(self) -> None:
        """Start the registry HTTP server.

        Requires: ``pip install 'roar-sdk[server]'``
        """
        if not _FASTAPI_AVAILABLE:
            raise ImportError(
                "Registry server requires fastapi and uvicorn. "
                "Install them: pip install 'roar-sdk[server]'"
            )

        app = FastAPI(title=f"ROAR Registry — {self._registry_name}")
        registry = self

        # ── Helpers ───────────────────────────────────────────────

        def _require_admin(request: Request) -> None:
            """Verify the admin API key from the Authorization header."""
            if not registry._admin_api_key:
                return  # no key configured — allow all
            auth = request.headers.get("authorization", "")
            expected = f"Bearer {registry._admin_api_key}"
            if auth != expected:
                raise HTTPException(status_code=401, detail="Invalid admin API key")

        # ── GET /registry/agents ──────────────────────────────────

        @app.get("/registry/agents")
        async def list_agents(
            capability: Optional[str] = Query(None),
            protocol: Optional[str] = Query(None),
            limit: int = Query(20, ge=1, le=200),
            offset: int = Query(0, ge=0),
        ):
            entries = registry.search(
                capability=capability,
                protocol=protocol,
                limit=limit,
                offset=offset,
            )
            return {
                "agents": [e.to_dict() for e in entries],
                "total": len(registry._agents),
                "limit": limit,
                "offset": offset,
            }

        # ── GET /registry/agents/{did} ────────────────────────────

        @app.get("/registry/agents/{did:path}")
        async def get_agent(did: str):
            entry = registry._agents.get(did)
            if not entry:
                raise HTTPException(status_code=404, detail="Agent not found")
            return entry.to_dict()

        # ── GET /registry/search ──────────────────────────────────

        @app.get("/registry/search")
        async def search_agents(
            q: str = Query(..., min_length=1),
            limit: int = Query(20, ge=1, le=200),
            offset: int = Query(0, ge=0),
        ):
            entries = registry.full_text_search(q, limit=limit, offset=offset)
            return {
                "query": q,
                "results": [e.to_dict() for e in entries],
                "count": len(entries),
            }

        # ── GET /registry/hubs ────────────────────────────────────

        @app.get("/registry/hubs")
        async def list_hubs():
            return {"hubs": registry.list_hubs()}

        # ── POST /registry/hubs ───────────────────────────────────

        @app.post("/registry/hubs")
        async def add_hub(request: Request):
            _require_admin(request)
            body = await request.json()
            hub_url = body.get("hub_url", "")
            if not hub_url:
                return JSONResponse(
                    status_code=400,
                    content={"error": "hub_url is required"},
                )
            registry.register_hub(hub_url)
            return {"registered": True, "hub_url": hub_url}

        # ── GET /registry/stats ───────────────────────────────────

        @app.get("/registry/stats")
        async def stats():
            return registry.get_stats()

        # ── GET /registry/health ──────────────────────────────────

        @app.get("/registry/health")
        async def health():
            return {
                "status": "healthy",
                "registry_name": registry._registry_name,
                "total_agents": len(registry._agents),
                "total_hubs": len(registry._hubs),
            }

        # ── GET /.well-known/roar-registry.json ───────────────────

        @app.get("/.well-known/roar-registry.json")
        async def well_known():
            return registry.well_known_metadata()

        logger.info(
            "ROAR Public Registry starting on http://%s:%d",
            self._host,
            self._port,
        )
        uvicorn.run(app, host=self._host, port=self._port, log_level="warning")

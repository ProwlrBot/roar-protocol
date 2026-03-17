# -*- coding: utf-8 -*-
"""ROAR Protocol — Well-Known endpoint for agent/hub discovery.

Implements the /.well-known/roar.json specification for HTTP-based
discovery of ROAR hubs and their registered agents.

Usage (server-side)::

    from roar_sdk.well_known import serve_well_known
    app.include_router(serve_well_known(hub))

Usage (client-side)::

    from roar_sdk.well_known import fetch_well_known
    info = await fetch_well_known("example.com")
    print(info.hub_url, info.agents)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AgentSummary(BaseModel):
    """Minimal agent info for well-known discovery."""

    did: str
    display_name: str = ""
    capabilities: List[str] = Field(default_factory=list)
    endpoint: str = ""


class ROARWellKnown(BaseModel):
    """Schema for /.well-known/roar.json discovery document."""

    hub_url: str
    protocol: str = "roar/1.0"
    version: str = "1.0"
    federation_enabled: bool = False
    agents: List[AgentSummary] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


def serve_well_known(hub: Any):
    """Create a FastAPI router that serves /.well-known/roar.json from a hub.

    Args:
        hub: A ROARHub instance.

    Returns:
        APIRouter with GET /.well-known/roar.json endpoint.
    """
    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/.well-known/roar.json")
    async def well_known():
        agents = []
        for entry in hub._directory.list_all():
            card = entry.agent_card
            agents.append(AgentSummary(
                did=card.identity.did,
                display_name=card.identity.display_name,
                capabilities=card.identity.capabilities,
                endpoint=card.endpoints.get("http", ""),
            ))

        return ROARWellKnown(
            hub_url=hub._hub_url,
            federation_enabled=len(hub._peers) > 0,
            agents=agents,
            metadata={"agent_count": len(agents), "peer_count": len(hub._peers)},
        ).model_dump()

    return router


async def fetch_well_known(
    domain: str,
    *,
    scheme: str = "https",
    timeout: float = 5.0,
) -> Optional[ROARWellKnown]:
    """Fetch and parse a remote /.well-known/roar.json document.

    Args:
        domain: The domain to query (e.g., "hub.example.com").
        scheme: HTTP scheme (default "https").
        timeout: Request timeout in seconds.

    Returns:
        ROARWellKnown if successful, None on failure.
    """
    try:
        import httpx
    except ImportError:
        logger.error("httpx required for well-known fetching: pip install roar-sdk[http]")
        return None

    url = f"{scheme}://{domain}/.well-known/roar.json"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return ROARWellKnown.model_validate(resp.json())
            logger.warning("Well-known fetch failed: %s returned %d", url, resp.status_code)
    except Exception as exc:
        logger.debug("Well-known fetch error for %s: %s", domain, exc)

    return None

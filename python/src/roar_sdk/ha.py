# -*- coding: utf-8 -*-
"""ROAR Protocol — Multi-Hub High Availability & Load Balancing.

Provides active-active hub clustering with automatic failover,
consistent agent registration, and load-balanced message routing.

Usage::

    from roar_sdk.ha import HubCluster

    cluster = HubCluster(["http://hub-a:8090", "http://hub-b:8090"])
    await cluster.register_agent(card)           # registers on all hubs
    agents = await cluster.search("code-review") # merges results
    await cluster.send(message)                  # routes to healthiest hub
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class HubHealth:
    """Health state for a single hub in the cluster."""

    url: str
    alive: bool = True
    latency_ms: float = 0.0
    last_check: float = 0.0
    consecutive_failures: int = 0
    weight: float = 1.0  # higher = preferred for routing


class HubCluster:
    """Active-active hub cluster with health checking and failover.

    Distributes agent registrations across all healthy hubs and
    routes messages to the hub with the lowest latency.
    """

    def __init__(
        self,
        hub_urls: List[str],
        *,
        health_interval: float = 30.0,
        max_failures: int = 3,
        timeout: float = 5.0,
    ):
        self._hubs = [HubHealth(url=u.rstrip("/")) for u in hub_urls]
        self._health_interval = health_interval
        self._max_failures = max_failures
        self._timeout = timeout
        self._health_task: Optional[asyncio.Task] = None

    @property
    def healthy_hubs(self) -> List[HubHealth]:
        return [h for h in self._hubs if h.alive]

    @property
    def all_hubs(self) -> List[HubHealth]:
        return list(self._hubs)

    def _pick_hub(self) -> HubHealth:
        """Select the best hub for a request (weighted random by latency)."""
        healthy = self.healthy_hubs
        if not healthy:
            raise ConnectionError("No healthy hubs available")
        if len(healthy) == 1:
            return healthy[0]
        # Weight inversely by latency — faster hubs get more traffic
        weights = []
        for h in healthy:
            w = h.weight / max(h.latency_ms, 1.0)
            weights.append(w)
        total = sum(weights)
        r = random.random() * total
        cumulative = 0.0
        for i, w in enumerate(weights):
            cumulative += w
            if r <= cumulative:
                return healthy[i]
        return healthy[-1]

    async def check_health(self, hub: HubHealth) -> None:
        """Probe a single hub's health endpoint."""
        try:
            import httpx
        except ImportError:
            logger.debug("httpx not available for health checks")
            return

        url = f"{hub.url}/roar/health"
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url)
                elapsed = (time.monotonic() - start) * 1000
                if resp.status_code == 200:
                    hub.alive = True
                    hub.latency_ms = elapsed
                    hub.consecutive_failures = 0
                else:
                    hub.consecutive_failures += 1
        except Exception:
            hub.consecutive_failures += 1
            hub.latency_ms = self._timeout * 1000

        if hub.consecutive_failures >= self._max_failures:
            if hub.alive:
                logger.warning("Hub %s marked DOWN after %d failures", hub.url, hub.consecutive_failures)
            hub.alive = False
        hub.last_check = time.time()

    async def check_all_health(self) -> Dict[str, bool]:
        """Check health of all hubs concurrently."""
        await asyncio.gather(*(self.check_health(h) for h in self._hubs))
        return {h.url: h.alive for h in self._hubs}

    async def start_health_monitor(self) -> None:
        """Start background health check loop."""
        async def _loop():
            while True:
                await self.check_all_health()
                await asyncio.sleep(self._health_interval)
        self._health_task = asyncio.create_task(_loop())

    def stop_health_monitor(self) -> None:
        if self._health_task:
            self._health_task.cancel()
            self._health_task = None

    async def register_agent(self, card_dict: Dict[str, Any]) -> List[str]:
        """Register an agent on all healthy hubs. Returns list of hub URLs that succeeded."""
        try:
            import httpx
        except ImportError:
            raise ImportError("httpx required: pip install httpx")

        succeeded = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for hub in self.healthy_hubs:
                try:
                    resp = await client.post(f"{hub.url}/roar/agents", json=card_dict)
                    if resp.status_code in (200, 201):
                        succeeded.append(hub.url)
                except Exception as exc:
                    logger.warning("Registration failed on %s: %s", hub.url, exc)
        return succeeded

    async def search(self, capability: str) -> List[Dict[str, Any]]:
        """Search all healthy hubs and merge deduplicated results."""
        try:
            import httpx
        except ImportError:
            raise ImportError("httpx required: pip install httpx")

        seen_dids: set = set()
        results: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for hub in self.healthy_hubs:
                try:
                    resp = await client.get(f"{hub.url}/roar/agents", params={"capability": capability})
                    if resp.status_code == 200:
                        for agent in resp.json().get("agents", []):
                            did = agent.get("agent_card", {}).get("identity", {}).get("did", "")
                            if did and did not in seen_dids:
                                seen_dids.add(did)
                                results.append(agent)
                except Exception as exc:
                    logger.warning("Search failed on %s: %s", hub.url, exc)
        return results

    async def send(self, message_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Send a message through the best available hub."""
        try:
            import httpx
        except ImportError:
            raise ImportError("httpx required: pip install httpx")

        # Try the preferred hub, failover to others
        tried = set()
        last_error = None
        for _ in range(len(self._hubs)):
            hub = self._pick_hub()
            if hub.url in tried:
                continue
            tried.add(hub.url)
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(f"{hub.url}/roar/message", json=message_dict)
                    return resp.json()
            except Exception as exc:
                last_error = exc
                hub.consecutive_failures += 1
                if hub.consecutive_failures >= self._max_failures:
                    hub.alive = False
                logger.warning("Send failed on %s, trying next hub: %s", hub.url, exc)

        raise ConnectionError(f"All hubs failed. Last error: {last_error}")

    # ------------------------------------------------------------------
    # Split-brain detection
    # ------------------------------------------------------------------

    async def detect_split_brain(self) -> Dict[str, List[str]]:
        """Detect agent registration inconsistencies across hubs.

        Compares the agent list from each hub and reports DIDs that
        exist on some hubs but not others. A non-empty result indicates
        a potential split-brain or federation lag.

        Returns:
            Dict mapping hub URLs to lists of DIDs unique to that hub.
        """
        try:
            import httpx
        except ImportError:
            raise ImportError("httpx required: pip install httpx")

        hub_agents: Dict[str, set] = {}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for hub in self.healthy_hubs:
                try:
                    resp = await client.get(f"{hub.url}/roar/agents")
                    if resp.status_code == 200:
                        dids = set()
                        for agent in resp.json().get("agents", []):
                            did = agent.get("agent_card", {}).get("identity", {}).get("did", "")
                            if did:
                                dids.add(did)
                        hub_agents[hub.url] = dids
                except Exception as exc:
                    logger.warning("Split-brain check failed on %s: %s", hub.url, exc)

        if len(hub_agents) < 2:
            return {}

        # Find DIDs that aren't on all hubs
        all_dids = set()
        for dids in hub_agents.values():
            all_dids |= dids

        inconsistencies: Dict[str, List[str]] = {}
        for url, dids in hub_agents.items():
            unique = all_dids - dids
            if unique:
                inconsistencies[url] = sorted(unique)

        if inconsistencies:
            logger.warning("Split-brain detected: %d hub(s) have inconsistent registrations", len(inconsistencies))
        return inconsistencies

    async def heal_split_brain(self) -> int:
        """Trigger federation sync across all healthy hubs to resolve inconsistencies.

        Returns the number of sync operations performed.
        """
        try:
            import httpx
        except ImportError:
            raise ImportError("httpx required: pip install httpx")

        healthy = self.healthy_hubs
        synced = 0
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for i, hub_a in enumerate(healthy):
                for hub_b in healthy[i + 1:]:
                    try:
                        await client.post(
                            f"{hub_a.url}/roar/federation/sync",
                            json={"hub_url": hub_b.url},
                        )
                        synced += 1
                    except Exception as exc:
                        logger.warning("Federation sync %s -> %s failed: %s", hub_a.url, hub_b.url, exc)
                    try:
                        await client.post(
                            f"{hub_b.url}/roar/federation/sync",
                            json={"hub_url": hub_a.url},
                        )
                        synced += 1
                    except Exception as exc:
                        logger.warning("Federation sync %s -> %s failed: %s", hub_b.url, hub_a.url, exc)
        return synced

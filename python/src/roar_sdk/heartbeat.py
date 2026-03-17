# -*- coding: utf-8 -*-
"""ROAR Protocol — Agent Heartbeat & Liveness Detection.

Agents send periodic heartbeats to their hub. The hub tracks liveness
and reaps dead agents after a configurable timeout.

Usage::

    # Agent side
    from roar_sdk.heartbeat import HeartbeatClient
    hb = HeartbeatClient("http://hub:8090", agent_did, interval=60)
    await hb.start()  # sends heartbeats in background
    ...
    hb.stop()

    # Hub side
    from roar_sdk.heartbeat import HeartbeatTracker
    tracker = HeartbeatTracker(timeout=300)
    tracker.beat(agent_did)
    dead = tracker.reap()  # returns list of dead agent DIDs
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AgentPulse:
    """Liveness state for a single agent."""

    did: str
    last_beat: float = 0.0
    consecutive_misses: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def age_seconds(self) -> float:
        if self.last_beat == 0:
            return float("inf")
        return time.time() - self.last_beat


class HeartbeatTracker:
    """Hub-side tracker for agent liveness.

    Agents call ``beat(did)`` periodically. The hub calls ``reap()``
    to find and remove dead agents.
    """

    def __init__(self, timeout: float = 300.0):
        self._timeout = timeout
        self._agents: Dict[str, AgentPulse] = {}
        self._on_dead: Optional[Callable[[str], Any]] = None

    def on_dead(self, callback: Callable[[str], Any]) -> None:
        """Register a callback invoked when an agent is reaped."""
        self._on_dead = callback

    def beat(self, did: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Record a heartbeat from an agent."""
        if did not in self._agents:
            self._agents[did] = AgentPulse(did=did)
        pulse = self._agents[did]
        pulse.last_beat = time.time()
        pulse.consecutive_misses = 0
        if metadata:
            pulse.metadata.update(metadata)

    def is_alive(self, did: str) -> bool:
        pulse = self._agents.get(did)
        if not pulse:
            return False
        return pulse.age_seconds < self._timeout

    def get_pulse(self, did: str) -> Optional[AgentPulse]:
        return self._agents.get(did)

    def all_agents(self) -> List[AgentPulse]:
        return list(self._agents.values())

    def alive_agents(self) -> List[AgentPulse]:
        return [p for p in self._agents.values() if p.age_seconds < self._timeout]

    def dead_agents(self) -> List[AgentPulse]:
        return [p for p in self._agents.values() if p.age_seconds >= self._timeout]

    def reap(self) -> List[str]:
        """Remove dead agents and return their DIDs.

        Invokes the ``on_dead`` callback for each reaped agent.
        """
        dead = [p.did for p in self._agents.values() if p.age_seconds >= self._timeout]
        for did in dead:
            del self._agents[did]
            if self._on_dead:
                try:
                    self._on_dead(did)
                except Exception:
                    logger.exception("on_dead callback failed for %s", did)
            logger.info("Reaped dead agent: %s", did)
        return dead

    def unregister(self, did: str) -> None:
        """Gracefully remove an agent (not dead, just leaving)."""
        self._agents.pop(did, None)


class HeartbeatClient:
    """Agent-side heartbeat sender.

    Sends periodic HTTP POST to ``{hub_url}/roar/heartbeat`` with
    the agent's DID.
    """

    def __init__(
        self,
        hub_url: str,
        agent_did: str,
        *,
        interval: float = 60.0,
        timeout: float = 5.0,
    ):
        self._hub_url = hub_url.rstrip("/")
        self._agent_did = agent_did
        self._interval = interval
        self._timeout = timeout
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def _beat_once(self) -> bool:
        try:
            import httpx
        except ImportError:
            logger.debug("httpx not available for heartbeat")
            return False

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._hub_url}/roar/heartbeat",
                    json={"did": self._agent_did, "timestamp": time.time()},
                )
                return resp.status_code == 200
        except Exception as exc:
            logger.warning("Heartbeat failed: %s", exc)
            return False

    async def _loop(self) -> None:
        self._running = True
        while self._running:
            await self._beat_once()
            await asyncio.sleep(self._interval)

    async def start(self) -> None:
        """Start sending heartbeats in the background."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("Heartbeat started: %s every %.0fs", self._agent_did, self._interval)

    def stop(self) -> None:
        """Stop heartbeat loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    @property
    def is_running(self) -> bool:
        return self._running

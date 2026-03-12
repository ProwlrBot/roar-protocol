# -*- coding: utf-8 -*-
"""ROAR Protocol SDK — Client for sending messages and discovering agents."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .types import (
    AgentCard,
    AgentDirectory,
    AgentIdentity,
    ConnectionConfig,
    DiscoveryEntry,
    MessageIntent,
    ROARMessage,
    TransportType,
)

logger = logging.getLogger(__name__)


class ROARClient:
    """Send ROAR messages and discover agents.

    Usage::

        client = ROARClient(
            AgentIdentity(display_name="my-agent"),
            signing_secret="shared-secret",
        )
        client.register(AgentCard(identity=client.identity, description="..."))
        response = await client.send_remote(
            to_agent_id="did:roar:agent:echo-...",
            intent=MessageIntent.DELEGATE,
            content={"task": "hello"},
        )
    """

    def __init__(
        self,
        identity: AgentIdentity,
        directory_url: Optional[str] = None,
        signing_secret: str = "",
    ) -> None:
        self._identity = identity
        self._directory_url = directory_url
        self._signing_secret = signing_secret
        if not signing_secret:
            logger.warning(
                "ROARClient created without signing_secret — messages will be unsigned. "
                "Set a shared secret for production use."
            )
        self._directory = AgentDirectory()

    @property
    def identity(self) -> AgentIdentity:
        return self._identity

    @property
    def directory(self) -> AgentDirectory:
        return self._directory

    def register(self, card: AgentCard) -> DiscoveryEntry:
        """Register an agent card in the local directory."""
        return self._directory.register(card)

    def discover(self, capability: Optional[str] = None) -> List[DiscoveryEntry]:
        """Find agents, optionally filtered by capability."""
        if capability:
            return self._directory.search(capability)
        return self._directory.list_all()

    def send(
        self,
        to_agent_id: str,
        intent: MessageIntent,
        content: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> ROARMessage:
        """Build and sign a ROAR message locally (no network call).

        Use ``send_remote`` for actual network dispatch.
        """
        entry = self._directory.lookup(to_agent_id)
        to_identity = (
            entry.agent_card.identity
            if entry
            else AgentIdentity(did=to_agent_id, display_name="unknown")
        )
        msg = ROARMessage(
            **{"from": self._identity, "to": to_identity},
            intent=intent,
            payload=content,
            context=context or {},
        )
        return self._sign(msg)

    async def send_remote(
        self,
        to_agent_id: str,
        intent: MessageIntent,
        content: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        transport: Optional[TransportType] = None,
    ) -> ROARMessage:
        """Send a message over the wire and return the response.

        Raises:
            ConnectionError: If no endpoint is found or transport fails.
        """
        msg = self.send(to_agent_id, intent, content, context)
        selected = transport or self._best_transport(to_agent_id)
        config = self.connect(to_agent_id, selected)

        if not config.url:
            raise ConnectionError(
                f"No endpoint found for agent {to_agent_id}. "
                "Register the agent with client.directory.register(card) first."
            )

        from .transports import send_message

        logger.info("Sending %s → %s via %s", intent.value, to_agent_id[:40], config.transport.value)
        return await send_message(config, msg, self._signing_secret)

    def connect(
        self,
        agent_id: str,
        transport: TransportType = TransportType.HTTP,
    ) -> ConnectionConfig:
        """Build a ConnectionConfig for the given agent."""
        entry = self._directory.lookup(agent_id)
        url = ""
        if entry:
            endpoints = entry.agent_card.endpoints
            url = endpoints.get(transport.value, endpoints.get("http", ""))
        return ConnectionConfig(
            transport=transport,
            url=url,
            auth_method="hmac",
            secret=self._signing_secret,
        )

    def _best_transport(self, agent_id: str) -> TransportType:
        entry = self._directory.lookup(agent_id)
        if not entry:
            return TransportType.HTTP
        endpoints = entry.agent_card.endpoints
        if "websocket" in endpoints:
            return TransportType.WEBSOCKET
        if "http" in endpoints:
            return TransportType.HTTP
        if "stdio" in endpoints:
            return TransportType.STDIO
        return TransportType.HTTP

    def _sign(self, msg: ROARMessage) -> ROARMessage:
        if self._signing_secret:
            return msg.sign(self._signing_secret)
        return msg

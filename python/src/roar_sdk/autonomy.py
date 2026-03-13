# -*- coding: utf-8 -*-
"""Graduated autonomy model and runtime capability delegation (Layer 1).

Agents operate at different trust levels. The AutonomyLevel ladder defines
how much independent action an agent can take. CapabilityDelegation manages
in-memory grant/revoke/check at runtime.

This is distinct from DelegationToken (roar_sdk.delegation), which is a
*cryptographic artifact* that travels with messages and can be verified by
third parties without contacting the issuer. CapabilityDelegation is the
*server-side policy engine* that enforces who can do what.

Autonomy levels (from design doc):
  WATCH      — observe only, no actions
  GUIDE      — suggest actions for human approval
  DELEGATE   — act on specific delegated capabilities
  AUTONOMOUS — act freely within declared capabilities

Usage::

    delegation = CapabilityDelegation()

    token = delegation.grant(
        grantor="did:roar:human:admin-12345678",
        grantee="did:roar:agent:planner-abcdef00",
        capabilities=["code-review", "testing"],
        autonomy_level=AutonomyLevel.DELEGATE,
        ttl_seconds=3600,
    )

    if delegation.is_authorized("did:roar:agent:planner-abcdef00", "code-review"):
        ...  # agent may proceed

    delegation.revoke(token.id)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AutonomyLevel(str, Enum):
    """Graduated autonomy levels for ROAR agents."""

    WATCH = "watch"
    GUIDE = "guide"
    DELEGATE = "delegate"
    AUTONOMOUS = "autonomous"

    def can_act(self) -> bool:
        """True if this level allows the agent to take actions without approval."""
        return self in (AutonomyLevel.DELEGATE, AutonomyLevel.AUTONOMOUS)

    def requires_approval(self) -> bool:
        """True if actions at this level need human approval."""
        return self in (AutonomyLevel.WATCH, AutonomyLevel.GUIDE)


_AUTONOMY_ORDER = [
    AutonomyLevel.WATCH,
    AutonomyLevel.GUIDE,
    AutonomyLevel.DELEGATE,
    AutonomyLevel.AUTONOMOUS,
]


@dataclass
class RuntimeToken:
    """An in-memory capability grant between two agents.

    For cryptographically-signed, portable grants use DelegationToken
    from roar_sdk.delegation instead.
    """

    id: str = ""
    grantor: str = ""
    grantee: str = ""
    capabilities: List[str] = field(default_factory=list)
    autonomy_level: AutonomyLevel = AutonomyLevel.GUIDE
    constraints: Dict[str, Any] = field(default_factory=dict)
    issued_at: float = 0.0
    expires_at: float = 0.0  # 0 = no expiry
    revoked: bool = False

    def __post_init__(self):
        if not self.id:
            self.id = f"rt-{uuid.uuid4().hex[:16]}"
        if not self.issued_at:
            self.issued_at = time.time()

    @property
    def expired(self) -> bool:
        if self.expires_at <= 0:
            return False
        return time.time() > self.expires_at

    @property
    def valid(self) -> bool:
        return not self.revoked and not self.expired

    def allows(self, capability: str) -> bool:
        if not self.valid:
            return False
        return capability in self.capabilities or "*" in self.capabilities


class CapabilityDelegation:
    """Runtime manager for agent capability grants.

    Manages RuntimeTokens in memory. For persistent grants, serialize
    token.id and recreate on startup, or pair with a DelegationToken.
    """

    def __init__(self) -> None:
        self._tokens: Dict[str, RuntimeToken] = {}
        self._by_grantee: Dict[str, List[str]] = {}

    def grant(
        self,
        grantor: str,
        grantee: str,
        capabilities: List[str],
        autonomy_level: AutonomyLevel = AutonomyLevel.GUIDE,
        constraints: Optional[Dict[str, Any]] = None,
        ttl_seconds: float = 0,
    ) -> RuntimeToken:
        """Grant capabilities from grantor to grantee.

        Args:
            grantor: DID of the granting agent/human.
            grantee: DID of the receiving agent.
            capabilities: List of capability names to delegate.
            autonomy_level: Maximum autonomy for these capabilities.
            constraints: Additional scope constraints.
            ttl_seconds: Time-to-live (0 = no expiry).

        Returns:
            The created RuntimeToken.
        """
        token = RuntimeToken(
            grantor=grantor,
            grantee=grantee,
            capabilities=capabilities,
            autonomy_level=autonomy_level,
            constraints=constraints or {},
            expires_at=time.time() + ttl_seconds if ttl_seconds > 0 else 0,
        )
        self._tokens[token.id] = token
        self._by_grantee.setdefault(grantee, []).append(token.id)
        return token

    def revoke(self, token_id: str) -> bool:
        """Revoke a grant. Returns True if found and revoked."""
        token = self._tokens.get(token_id)
        if token:
            token.revoked = True
            return True
        return False

    def is_authorized(
        self,
        agent_did: str,
        capability: str,
        min_autonomy: AutonomyLevel = AutonomyLevel.DELEGATE,
    ) -> bool:
        """Check if an agent is authorized for a capability.

        Args:
            agent_did: The agent's DID.
            capability: The capability to check.
            min_autonomy: Minimum required autonomy level.

        Returns:
            True if the agent has a valid token for this capability at or
            above the required autonomy level.
        """
        min_idx = _AUTONOMY_ORDER.index(min_autonomy)
        for tid in self._by_grantee.get(agent_did, []):
            token = self._tokens.get(tid)
            if not token or not token.valid:
                continue
            if not token.allows(capability):
                continue
            if _AUTONOMY_ORDER.index(token.autonomy_level) >= min_idx:
                return True
        return False

    def get_autonomy_level(self, agent_did: str) -> AutonomyLevel:
        """Get the highest autonomy level currently granted to an agent."""
        highest_idx = 0
        highest = AutonomyLevel.WATCH
        for tid in self._by_grantee.get(agent_did, []):
            token = self._tokens.get(tid)
            if not token or not token.valid:
                continue
            idx = _AUTONOMY_ORDER.index(token.autonomy_level)
            if idx > highest_idx:
                highest_idx = idx
                highest = token.autonomy_level
        return highest

    def list_tokens(self, grantee: Optional[str] = None) -> List[RuntimeToken]:
        """List grants, optionally filtered by grantee."""
        if grantee:
            return [
                self._tokens[tid]
                for tid in self._by_grantee.get(grantee, [])
                if tid in self._tokens
            ]
        return list(self._tokens.values())

    def cleanup_expired(self) -> int:
        """Remove expired and revoked tokens. Returns count removed."""
        to_remove = [tid for tid, t in self._tokens.items() if not t.valid]
        for tid in to_remove:
            token = self._tokens.pop(tid)
            grantee_list = self._by_grantee.get(token.grantee, [])
            if tid in grantee_list:
                grantee_list.remove(tid)
        return len(to_remove)

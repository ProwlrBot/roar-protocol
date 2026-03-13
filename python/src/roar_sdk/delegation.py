# -*- coding: utf-8 -*-
"""ROAR Protocol — Delegation tokens for scoped capability grants (Layer 1).

A delegation token allows an agent (the delegator) to grant a subset of
their capabilities to another agent (the delegate) for a limited time or
number of uses. The token is signed with the delegator's Ed25519 private key,
so the delegate can prove the grant to third parties without the delegator
being online.

Usage::

    from roar_sdk.signing import generate_keypair
    from roar_sdk.delegation import DelegationToken, issue_token, verify_token

    # Delegator issues a token
    priv, pub = generate_keypair()
    token = issue_token(
        delegator_did="did:roar:agent:alice-...",
        delegator_private_key=priv,
        delegate_did="did:roar:agent:bob-...",
        capabilities=["recon", "scan"],
        expires_in_seconds=3600,
        max_uses=10,
    )

    # Delegate includes the token in their messages:
    msg.context["delegation_token"] = token.model_dump()

    # Third party verifies:
    ok = verify_token(token, delegator_public_key=pub)
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from typing import List, Optional

from pydantic import BaseModel, Field


class DelegationToken(BaseModel):
    """A signed capability grant from one agent to another."""

    token_id: str = Field(default_factory=lambda: f"tok_{uuid.uuid4().hex[:10]}")
    delegator_did: str
    delegate_did: str
    capabilities: List[str]  # subset of delegator's capabilities
    issued_at: float = Field(default_factory=time.time)
    expires_at: Optional[float] = None   # None = no expiry
    max_uses: Optional[int] = None       # None = unlimited
    use_count: int = 0
    can_redelegate: bool = False         # can the delegate further delegate?
    signature: str = ""                  # "ed25519:<base64url>"

    def is_valid(self) -> bool:
        """Check expiry and use count (does NOT verify signature)."""
        if self.expires_at is not None and time.time() > self.expires_at:
            return False
        if self.max_uses is not None and self.use_count >= self.max_uses:
            return False
        return True

    def grants(self, capability: str) -> bool:
        """Check if this token grants a specific capability."""
        return self.is_valid() and capability in self.capabilities

    def consume(self) -> bool:
        """Record one use of this token. Returns False if the token is exhausted.

        Call this every time the token is accepted so max_uses is enforced.
        """
        if not self.is_valid():
            return False
        self.use_count += 1
        return True

    def _signing_body(self) -> bytes:
        """Canonical body for signing — deterministic, sorted keys."""
        body = json.dumps(
            {
                "capabilities": sorted(self.capabilities),
                "can_redelegate": self.can_redelegate,
                "delegate_did": self.delegate_did,
                "delegator_did": self.delegator_did,
                "expires_at": self.expires_at,
                "issued_at": self.issued_at,
                "max_uses": self.max_uses,
                "token_id": self.token_id,
            },
            sort_keys=True,
        )
        return body.encode("utf-8")


def issue_token(
    delegator_did: str,
    delegator_private_key: str,
    delegate_did: str,
    capabilities: List[str],
    *,
    expires_in_seconds: Optional[float] = 3600.0,
    max_uses: Optional[int] = None,
    can_redelegate: bool = False,
) -> DelegationToken:
    """Issue and sign a delegation token.

    Args:
        delegator_did: The issuing agent's DID.
        delegator_private_key: 64-char hex Ed25519 private key.
        delegate_did: The receiving agent's DID.
        capabilities: List of capability strings being granted.
        expires_in_seconds: TTL from now (None = no expiry).
        max_uses: Maximum number of uses (None = unlimited).
        can_redelegate: Whether the delegate can further delegate.

    Returns:
        A signed DelegationToken.

    Raises:
        ImportError: If cryptography package is not installed.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        raise ImportError(
            "Delegation tokens require the 'cryptography' package. "
            "Install it: pip install 'roar-sdk[ed25519]'"
        )

    expires_at = (time.time() + expires_in_seconds) if expires_in_seconds else None

    token = DelegationToken(
        delegator_did=delegator_did,
        delegate_did=delegate_did,
        capabilities=capabilities,
        expires_at=expires_at,
        max_uses=max_uses,
        can_redelegate=can_redelegate,
    )

    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(delegator_private_key))
    raw_sig = private.sign(token._signing_body())
    sig_b64 = base64.urlsafe_b64encode(raw_sig).decode("ascii").rstrip("=")
    token.signature = f"ed25519:{sig_b64}"
    return token


def verify_token(
    token: DelegationToken,
    delegator_public_key: str,
) -> bool:
    """Verify a delegation token's signature and validity.

    Args:
        token: The token to verify.
        delegator_public_key: 64-char hex Ed25519 public key of the delegator.

    Returns:
        True if the signature is valid and the token has not expired or been exhausted.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        raise ImportError(
            "Delegation tokens require the 'cryptography' package. "
            "Install it: pip install 'roar-sdk[ed25519]'"
        )

    if not token.is_valid():
        return False

    sig_value = token.signature
    if not sig_value.startswith("ed25519:"):
        return False

    b64 = sig_value[len("ed25519:"):]
    padding = (4 - len(b64) % 4) % 4
    raw_sig = base64.urlsafe_b64decode(b64 + "=" * padding)

    try:
        public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(delegator_public_key))
        public.verify(raw_sig, token._signing_body())
        return True
    except (InvalidSignature, ValueError):
        return False

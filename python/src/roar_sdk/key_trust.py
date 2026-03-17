# -*- coding: utf-8 -*-
"""ROAR Protocol — Ed25519 key trust enforcement.

Implements strict key trust policies for production deployments.

Security invariants:
  - Public keys MUST be resolved from trusted sources (DID documents, hub registry)
  - Public keys from message auth headers MUST NOT be trusted (attacker-controlled)
  - Key rotation MUST support backward compatibility windows
  - Expired keys MUST be rejected even if cryptographically valid

Usage::

    from roar_sdk.key_trust import KeyTrustStore, KeyMetadata

    store = KeyTrustStore()
    store.register_key("did:roar:agent:alice", "aabbcc...", max_age_hours=720)

    # Verify a message — only trusts keys in the store
    result = store.verify_message(msg)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class KeyMetadata:
    """Metadata for a trusted public key."""

    public_key_hex: str
    did: str
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    rotated_at: Optional[float] = None
    replaced_by: Optional[str] = None  # public_key_hex of successor
    source: str = "manual"  # "manual", "hub", "did_document", "challenge_response"

    @property
    def is_expired(self) -> bool:
        """Check if this key has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    @property
    def is_rotated(self) -> bool:
        """Check if this key has been replaced by a newer key."""
        return self.replaced_by is not None

    @property
    def age_hours(self) -> float:
        """Hours since key was created."""
        return (time.time() - self.created_at) / 3600


@dataclass(frozen=True)
class KeyTrustResult:
    """Result of a key trust check."""

    trusted: bool
    error: str = ""
    key_metadata: Optional[KeyMetadata] = None


class KeyTrustStore:
    """Manages trusted public keys for Ed25519 verification.

    Security policy:
      - Only keys explicitly registered or resolved from trusted sources are accepted
      - Keys have mandatory expiration (default 30 days)
      - Rotated keys remain valid during a grace period for in-flight messages
      - Keys from message auth headers (attacker-controlled) are NEVER trusted
    """

    def __init__(
        self,
        *,
        default_max_age_hours: float = 720.0,  # 30 days
        rotation_grace_hours: float = 24.0,  # 24-hour grace for rotated keys
    ) -> None:
        self._default_max_age = default_max_age_hours
        self._rotation_grace = rotation_grace_hours
        # did -> list of KeyMetadata (newest first)
        self._keys: Dict[str, List[KeyMetadata]] = {}

    def register_key(
        self,
        did: str,
        public_key_hex: str,
        *,
        max_age_hours: Optional[float] = None,
        source: str = "manual",
    ) -> KeyMetadata:
        """Register a trusted public key for a DID.

        Args:
            did: The agent's DID.
            public_key_hex: The Ed25519 public key (64-char hex).
            max_age_hours: Key lifetime in hours. None uses default (30 days).
            source: Where this key was obtained from.

        Returns:
            The KeyMetadata for the registered key.
        """
        if len(public_key_hex) != 64:
            raise ValueError(f"Invalid public key length: expected 64 hex chars, got {len(public_key_hex)}")

        try:
            bytes.fromhex(public_key_hex)
        except ValueError:
            raise ValueError("Invalid public key: not valid hex")

        lifetime = (max_age_hours or self._default_max_age) * 3600
        now = time.time()

        meta = KeyMetadata(
            public_key_hex=public_key_hex,
            did=did,
            created_at=now,
            expires_at=now + lifetime,
            source=source,
        )

        if did not in self._keys:
            self._keys[did] = []
        self._keys[did].insert(0, meta)  # newest first

        logger.info(
            "Registered key for %s (source=%s, expires in %.0fh)",
            did, source, max_age_hours or self._default_max_age,
        )
        return meta

    def rotate_key(
        self,
        did: str,
        new_public_key_hex: str,
        *,
        source: str = "rotation",
    ) -> KeyMetadata:
        """Rotate a DID's key — old key enters grace period, new key becomes active.

        Args:
            did: The agent's DID.
            new_public_key_hex: The new Ed25519 public key.
            source: Source of the new key.

        Returns:
            KeyMetadata for the new key.
        """
        now = time.time()

        # Mark current active key as rotated with grace period
        current_keys = self._keys.get(did, [])
        for key in current_keys:
            if not key.is_expired and not key.is_rotated:
                key.rotated_at = now
                key.replaced_by = new_public_key_hex
                # Set expiry to grace period from now
                key.expires_at = now + (self._rotation_grace * 3600)
                logger.info(
                    "Key for %s rotated — old key valid for %.0fh grace period",
                    did, self._rotation_grace,
                )
                break

        # Register the new key
        return self.register_key(did, new_public_key_hex, source=source)

    def get_trusted_key(self, did: str) -> KeyTrustResult:
        """Get the current trusted public key for a DID.

        Returns the newest non-expired, non-rotated key.

        Args:
            did: The agent's DID.

        Returns:
            KeyTrustResult with the trusted key or an error.
        """
        keys = self._keys.get(did, [])
        if not keys:
            return KeyTrustResult(False, f"no_keys_registered_for_{did}")

        for key in keys:
            if key.is_expired:
                continue
            if key.is_rotated:
                continue  # skip rotated keys for primary lookup
            return KeyTrustResult(True, key_metadata=key)

        return KeyTrustResult(False, "all_keys_expired_or_rotated")

    def is_key_trusted(self, did: str, public_key_hex: str) -> KeyTrustResult:
        """Check if a specific public key is trusted for a DID.

        Accepts both active keys and keys in rotation grace period.

        Args:
            did: The agent's DID.
            public_key_hex: The key to check.

        Returns:
            KeyTrustResult indicating whether the key is trusted.
        """
        keys = self._keys.get(did, [])
        if not keys:
            return KeyTrustResult(False, "no_keys_registered")

        for key in keys:
            if key.public_key_hex != public_key_hex:
                continue
            if key.is_expired:
                return KeyTrustResult(False, "key_expired")
            return KeyTrustResult(True, key_metadata=key)

        return KeyTrustResult(False, "key_not_in_trust_store")

    def verify_message(self, msg) -> KeyTrustResult:
        """Verify a message's Ed25519 signature against the trust store.

        SECURITY: This method NEVER uses auth["public_key"] from the message.
        It only uses keys registered in the trust store for the sender's DID.

        Args:
            msg: A ROARMessage with an ed25519 signature.

        Returns:
            KeyTrustResult indicating verification success or failure.
        """
        from .signing import verify_ed25519

        sig = msg.auth.get("signature", "")
        if not sig.startswith("ed25519:"):
            return KeyTrustResult(False, "not_ed25519_signature")

        sender_did = msg.from_identity.did
        keys = self._keys.get(sender_did, [])

        if not keys:
            return KeyTrustResult(False, f"no_trusted_keys_for_{sender_did}")

        # Try each non-expired key (supports rotation grace period)
        for key in keys:
            if key.is_expired:
                continue
            if verify_ed25519(msg, max_age_seconds=0, public_key_hex=key.public_key_hex):
                return KeyTrustResult(True, key_metadata=key)

        return KeyTrustResult(False, "signature_not_valid_with_any_trusted_key")

    def purge_expired(self) -> int:
        """Remove all expired keys from the store.

        Returns:
            Number of keys purged.
        """
        purged = 0
        for did in list(self._keys.keys()):
            before = len(self._keys[did])
            self._keys[did] = [k for k in self._keys[did] if not k.is_expired]
            purged += before - len(self._keys[did])
            if not self._keys[did]:
                del self._keys[did]
        return purged

    def list_keys(self, did: str) -> List[KeyMetadata]:
        """List all keys (including expired) for a DID."""
        return list(self._keys.get(did, []))

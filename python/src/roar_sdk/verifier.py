# -*- coding: utf-8 -*-
"""ROAR Protocol — strict reference verifier.

This module provides a policy-enforcing verifier intended for production
receivers. It layers replay checks, recipient binding, and stricter timestamp
handling on top of signature verification.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable, Optional

from .dedup import IdempotencyGuard
from .signing import verify_ed25519
from .types import ROARMessage


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    error: str = ""


class StrictMessageVerifier:
    """Reference message verifier with explicit security policy.

    Policy defaults are intentionally strict and should be tuned only with care.
    """

    def __init__(
        self,
        *,
        hmac_secret: str = "",
        hmac_secrets: Optional[dict[str, str]] = None,
        expected_recipient_did: Optional[str] = None,
        max_age_seconds: float = 300.0,
        max_future_skew_seconds: float = 30.0,
        replay_guard: Optional[IdempotencyGuard] = None,
        allowed_signature_schemes: Iterable[str] = ("hmac-sha256", "ed25519"),
        trusted_ed25519_keys: Optional[dict[str, str]] = None,
    ) -> None:
        self._hmac_secret = hmac_secret
        # kid-keyed HMAC secrets for key rotation: {"kid-1": "secret-1", "kid-2": "secret-2"}
        self._hmac_secrets: dict[str, str] = hmac_secrets or {}
        self._expected_recipient_did = expected_recipient_did
        self._max_age = max_age_seconds
        self._max_future_skew = max_future_skew_seconds
        self._replay_guard = replay_guard
        self._allowed = set(allowed_signature_schemes)
        # Maps DID -> public_key_hex for Ed25519 verification.
        # Keys MUST come from a trusted source (DID Document, hub registry),
        # NEVER from the message itself.
        self._trusted_ed25519_keys = trusted_ed25519_keys or {}

    def verify(self, msg: ROARMessage) -> VerificationResult:
        # Protocol version check — reject unknown major versions (fail-closed).
        if not msg.roar or not msg.roar.startswith("1."):
            return VerificationResult(False, "unsupported_protocol_version")

        signature = msg.auth.get("signature")
        if not isinstance(signature, str) or ":" not in signature:
            return VerificationResult(False, "missing_or_invalid_signature")

        scheme, _ = signature.split(":", 1)
        if scheme not in self._allowed:
            return VerificationResult(False, "signature_scheme_not_allowed")

        # kid (key identifier) check — if present, must match a known key.
        kid = msg.auth.get("kid")
        if kid is not None and isinstance(kid, str):
            if scheme == "hmac-sha256" and self._hmac_secrets:
                if kid not in self._hmac_secrets:
                    return VerificationResult(False, "unknown_key_identifier")
            elif scheme == "ed25519" and kid not in self._trusted_ed25519_keys:
                return VerificationResult(False, "unknown_key_identifier")

        if self._expected_recipient_did and msg.to_identity.did != self._expected_recipient_did:
            return VerificationResult(False, "recipient_mismatch")

        ts = msg.auth.get("timestamp")
        if not isinstance(ts, (int, float)):
            return VerificationResult(False, "missing_or_invalid_auth_timestamp")

        now = time.time()
        age = now - float(ts)
        if age > self._max_age:
            return VerificationResult(False, "message_expired")
        if -age > self._max_future_skew:
            return VerificationResult(False, "message_from_future")

        if self._replay_guard is not None and self._replay_guard.is_duplicate(msg.id):
            return VerificationResult(False, "replay_detected")

        if scheme == "hmac-sha256":
            # Resolve the correct secret: kid-based lookup first, then fallback.
            secret = self._hmac_secret
            kid = msg.auth.get("kid")
            if kid and self._hmac_secrets:
                secret = self._hmac_secrets.get(kid, "")
            if not secret:
                return VerificationResult(False, "missing_hmac_secret")
            if not msg.verify(secret, max_age_seconds=0):
                return VerificationResult(False, "invalid_hmac_signature")
            return VerificationResult(True)

        if scheme == "ed25519":
            # SECURITY: NEVER fall back to msg.from_identity.public_key —
            # that field is attacker-controlled (spec 04-exchange.md line 152).
            trusted_key = self._trusted_ed25519_keys.get(msg.from_identity.did)
            if not trusted_key:
                return VerificationResult(
                    False,
                    "ed25519_no_trusted_key: sender DID not in trusted_ed25519_keys",
                )
            if not verify_ed25519(msg, max_age_seconds=0, public_key_hex=trusted_key):
                return VerificationResult(False, "invalid_ed25519_signature")
            return VerificationResult(True)

        return VerificationResult(False, "unsupported_signature_scheme")

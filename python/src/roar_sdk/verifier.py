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
        expected_recipient_did: Optional[str] = None,
        max_age_seconds: float = 300.0,
        max_future_skew_seconds: float = 30.0,
        replay_guard: Optional[IdempotencyGuard] = None,
        allowed_signature_schemes: Iterable[str] = ("hmac-sha256", "ed25519"),
    ) -> None:
        self._hmac_secret = hmac_secret
        self._expected_recipient_did = expected_recipient_did
        self._max_age = max_age_seconds
        self._max_future_skew = max_future_skew_seconds
        self._replay_guard = replay_guard
        self._allowed = set(allowed_signature_schemes)

    def verify(self, msg: ROARMessage) -> VerificationResult:
        signature = msg.auth.get("signature")
        if not isinstance(signature, str) or ":" not in signature:
            return VerificationResult(False, "missing_or_invalid_signature")

        scheme, _ = signature.split(":", 1)
        if scheme not in self._allowed:
            return VerificationResult(False, "signature_scheme_not_allowed")

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
            if not self._hmac_secret:
                return VerificationResult(False, "missing_hmac_secret")
            if not msg.verify(self._hmac_secret, max_age_seconds=0):
                return VerificationResult(False, "invalid_hmac_signature")
            return VerificationResult(True)

        if scheme == "ed25519":
            if not verify_ed25519(msg, max_age_seconds=0):
                return VerificationResult(False, "invalid_ed25519_signature")
            return VerificationResult(True)

        return VerificationResult(False, "unsupported_signature_scheme")

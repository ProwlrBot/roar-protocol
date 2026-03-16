# -*- coding: utf-8 -*-
"""ROAR Protocol — Hub challenge-response authentication.

Provides ChallengeStore for proof-of-possession registration:
  1. Hub issues a short-lived nonce challenge tied to the registrant's DID.
  2. Client signs the nonce with its Ed25519 private key.
  3. Hub verifies the signature, then admits the agent card.

This store is single-process. Distributed deployments should replace it with
Redis SETNX with TTL for atomic challenge issuance.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class PendingChallenge:
    challenge_id: str
    did: str
    nonce: str
    expires_at: float
    public_key: str   # hex-encoded Ed25519 public key from registration request
    card: dict = field(default_factory=dict)  # raw AgentCard dict to register on success


class ChallengeStore:
    """In-memory store for pending registration challenges.

    Nonces expire after NONCE_TTL_SECONDS. Replayed challenge_ids are rejected
    because ``consume`` deletes the entry on first retrieval.

    This store is single-process; distributed deployments should replace with
    Redis SETNX with TTL for atomic challenge issuance.
    """

    NONCE_TTL_SECONDS = 30.0
    MAX_PENDING = 1000

    def __init__(self) -> None:
        self._pending: Dict[str, PendingChallenge] = {}

    def issue(self, did: str, public_key: str, card: dict) -> PendingChallenge:
        """Issue a new challenge for *did*.  Evicts expired entries first."""
        self._evict_expired()
        if len(self._pending) >= self.MAX_PENDING:
            raise RuntimeError("Too many pending challenges — server busy")
        challenge_id = secrets.token_hex(16)
        nonce = secrets.token_hex(32)
        challenge = PendingChallenge(
            challenge_id=challenge_id,
            did=did,
            nonce=nonce,
            expires_at=time.time() + self.NONCE_TTL_SECONDS,
            public_key=public_key,
            card=card,
        )
        self._pending[challenge_id] = challenge
        return challenge

    def consume(self, challenge_id: str) -> Optional[PendingChallenge]:
        """Return and DELETE the challenge (prevents replay).

        Returns None if the challenge has expired or was never issued.
        """
        self._evict_expired()
        return self._pending.pop(challenge_id, None)

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [cid for cid, c in self._pending.items() if c.expires_at < now]
        for cid in expired:
            del self._pending[cid]

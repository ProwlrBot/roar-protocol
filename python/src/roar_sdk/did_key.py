# -*- coding: utf-8 -*-
"""did:key method — ephemeral, self-certifying agent identities.

A did:key is derived entirely from a public key, requiring no external
registry. Ideal for ephemeral agents that need verifiable identity for
a single session or short-lived task.

Format: did:key:z<base58-multicodec-ed25519-pubkey>

Requires: pip install 'roar-sdk[ed25519]'
Optionally: pip install base58  (for correct did:key encoding)

Ref: https://w3c-ccg.github.io/did-method-key/

Usage::

    method = DIDKeyMethod()
    identity = method.generate()
    print(identity.did)         # did:key:z6Mk...
    print(identity.public_hex)  # 64-char hex public key
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .did_document import DIDDocument
from .signing import generate_keypair

# Multicodec prefix for Ed25519 public key: 0xed01
_ED25519_MULTICODEC = b"\xed\x01"

try:
    import base58 as _base58

    def _b58encode(data: bytes) -> str:
        return _base58.b58encode(data).decode()

except ImportError:
    # Fallback: hex-encode. Not a valid did:key but at least runnable.
    def _b58encode(data: bytes) -> str:  # type: ignore[misc]
        return data.hex()


@dataclass
class DIDKeyIdentity:
    """An ephemeral identity derived from an Ed25519 keypair.

    Attributes:
        did: The did:key string.
        private_hex: 32-byte Ed25519 private key (hex).
        public_hex: 32-byte Ed25519 public key (hex).
    """

    did: str
    private_hex: str
    public_hex: str


class DIDKeyMethod:
    """did:key method for ephemeral, self-certifying identities."""

    @staticmethod
    def generate() -> DIDKeyIdentity:
        """Generate a new did:key identity.

        Returns:
            A DIDKeyIdentity with keypair and DID.

        Raises:
            ImportError: If 'roar-sdk[ed25519]' is not installed.
        """
        private_hex, public_hex = generate_keypair()
        did = DIDKeyMethod._public_key_to_did(public_hex)
        return DIDKeyIdentity(did=did, private_hex=private_hex, public_hex=public_hex)

    @staticmethod
    def _public_key_to_did(public_hex: str) -> str:
        """Derive a did:key from a hex-encoded Ed25519 public key."""
        raw = bytes.fromhex(public_hex)
        multicodec = _ED25519_MULTICODEC + raw
        return "did:key:z" + _b58encode(multicodec)

    @staticmethod
    def resolve(did: str, public_hex: str = "") -> DIDDocument:
        """Resolve a did:key to a DID Document.

        Since did:key is self-describing, resolution unpacks the public key
        from the DID itself (or uses the provided public_hex override).

        Args:
            did: The did:key string.
            public_hex: Optional pre-extracted public key (hex).

        Returns:
            A DIDDocument with the embedded public key.
        """
        return DIDDocument.for_agent(did=did, public_key=public_hex)

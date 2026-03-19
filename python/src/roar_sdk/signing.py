# -*- coding: utf-8 -*-
"""ROAR Protocol — Ed25519 asymmetric signing for Layer 1 identity.

Provides per-agent key pair generation and message signing/verification.
Unlike HMAC-SHA256, Ed25519 uses asymmetric keys: agents sign with their
private key, and anyone can verify using the public key in their AgentIdentity.

Usage::

    from roar_sdk.signing import generate_keypair, sign_ed25519, verify_ed25519

    # Generate a key pair for an agent
    private_hex, public_hex = generate_keypair()
    identity = AgentIdentity(display_name="my-agent", public_key=public_hex)

    # Sign a message
    msg = ROARMessage(...)
    sign_ed25519(msg, private_hex)

    # Verify (uses from_identity.public_key automatically)
    ok = verify_ed25519(msg)

Requires: pip install 'roar-sdk[ed25519]'
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import ROARMessage, AgentCard

_MISSING = (
    "Ed25519 signing requires the 'cryptography' package. "
    "Install it: pip install 'roar-sdk[ed25519]'"
)


def generate_keypair() -> tuple[str, str]:
    """Generate an Ed25519 key pair for an agent identity.

    Returns:
        (private_key_hex, public_key_hex) — 64-char and 64-char hex strings.
        Store private_key_hex securely. Put public_key_hex in AgentIdentity.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        raise ImportError(_MISSING)

    private = Ed25519PrivateKey.generate()
    public = private.public_key()

    private_bytes = private.private_bytes_raw()
    public_bytes = public.public_bytes_raw()

    return private_bytes.hex(), public_bytes.hex()


def _signing_body_ed25519(msg: "ROARMessage") -> bytes:
    """Canonical JSON body for Ed25519 signing — same as HMAC body."""
    body = json.dumps(
        {
            "id": msg.id,
            "from": msg.from_identity.did,
            "to": msg.to_identity.did,
            "intent": msg.intent,
            "payload": msg.payload,
            "context": msg.context,
            "timestamp": msg.auth.get("timestamp", msg.timestamp),
        },
        sort_keys=True,
        separators=(", ", ": "),
    )
    return body.encode("utf-8")


def sign_ed25519(msg: "ROARMessage", private_key_hex: str) -> "ROARMessage":
    """Sign a ROARMessage with an Ed25519 private key.

    Sets msg.auth["signature"] = "ed25519:<base64url>" and
    msg.auth["public_key"] to the corresponding public key hex.

    Args:
        msg: The message to sign (mutated in place, returned for chaining).
        private_key_hex: 64-char hex string (32 bytes) from generate_keypair().

    Returns:
        The signed message (same object).
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        raise ImportError(_MISSING)

    import time

    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    public = private.public_key()

    msg.auth = {"timestamp": time.time()}
    body = _signing_body_ed25519(msg)
    raw_sig = private.sign(body)
    sig_b64 = base64.urlsafe_b64encode(raw_sig).decode("ascii").rstrip("=")

    msg.auth["signature"] = f"ed25519:{sig_b64}"
    msg.auth["public_key"] = public.public_bytes_raw().hex()
    return msg


def _card_canonical_body(card: "AgentCard") -> bytes:
    """Canonical JSON body for AgentCard signing.

    Covers all identity fields except ``attestation`` itself.
    Keys are sorted alphabetically for deterministic output.
    """
    body = json.dumps(
        {
            "did": card.identity.did,
            "capabilities": card.identity.capabilities,
            "description": card.description,
            "skills": card.skills,
            "channels": card.channels,
            "endpoints": card.endpoints,
            "declared_capabilities": [
                cap.model_dump() for cap in card.declared_capabilities
            ],
        },
        sort_keys=True,
    )
    return body.encode("utf-8")


def sign_agent_card(card: "AgentCard", private_key_hex: str) -> str:
    """Sign an AgentCard and return the base64url attestation string.

    Sets ``card.attestation`` in-place and returns it.

    Args:
        card: The AgentCard to sign (mutated in place).
        private_key_hex: 64-char hex string (32 bytes) from generate_keypair().

    Returns:
        The base64url-encoded Ed25519 signature string.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        raise ImportError(_MISSING)

    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    body = _card_canonical_body(card)
    raw_sig = private.sign(body)
    attestation = base64.urlsafe_b64encode(raw_sig).decode("ascii").rstrip("=")
    card.attestation = attestation
    return attestation


def verify_agent_card(card: "AgentCard") -> bool:
    """Verify AgentCard.attestation against the card's identity.public_key.

    Returns False if attestation is missing, public_key is missing, or the
    signature is invalid.

    Args:
        card: The AgentCard to verify.

    Returns:
        True if the attestation is a valid Ed25519 signature over the card.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        raise ImportError(_MISSING)

    if not card.attestation:
        return False
    key_hex = card.identity.public_key
    if not key_hex:
        return False

    b64 = card.attestation
    padding = (4 - len(b64) % 4) % 4
    raw_sig = base64.urlsafe_b64decode(b64 + "=" * padding)

    try:
        public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(key_hex))
        body = _card_canonical_body(card)
        public.verify(raw_sig, body)
        return True
    except (InvalidSignature, ValueError):
        return False


def verify_ed25519(
    msg: "ROARMessage",
    max_age_seconds: float = 300.0,
    *,
    public_key_hex: str | None = None,
) -> bool:
    """Verify an Ed25519 signed ROARMessage.

    Uses msg.from_identity.public_key by default, or a provided public_key_hex.

    Args:
        msg: The message to verify.
        max_age_seconds: Maximum message age in seconds. 0 = skip age check.
        public_key_hex: Override the public key (optional).

    Returns:
        True if signature is valid and message is within the time window.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        raise ImportError(_MISSING)

    import time

    sig_value: str = msg.auth.get("signature", "")
    if not sig_value.startswith("ed25519:"):
        return False

    if max_age_seconds > 0:
        msg_time: float = msg.auth.get("timestamp", 0)
        if abs(time.time() - msg_time) > max_age_seconds:
            return False

    key_hex = public_key_hex or msg.from_identity.public_key
    if not key_hex:
        return False

    # Restore base64url padding
    b64 = sig_value[len("ed25519:"):]
    padding = (4 - len(b64) % 4) % 4
    raw_sig = base64.urlsafe_b64decode(b64 + "=" * padding)

    try:
        public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(key_hex))
        body = _signing_body_ed25519(msg)
        public.verify(raw_sig, body)
        return True
    except (InvalidSignature, ValueError):
        return False

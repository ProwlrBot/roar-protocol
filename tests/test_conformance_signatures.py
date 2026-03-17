"""Conformance tests — invalid signature scenarios.

Verifies that the verifier correctly rejects all forms of signature
manipulation, scheme confusion, and truncation attacks.
"""

import pytest

from roar_sdk import AgentIdentity, ROARMessage, MessageIntent
from roar_sdk.verifier import StrictMessageVerifier

SECRET = "roar-conformance-test-secret"
SRC = AgentIdentity(display_name="sig-src", capabilities=["test"])
DST = AgentIdentity(display_name="sig-dst", capabilities=["test"])


def _make_signed() -> ROARMessage:
    msg = ROARMessage(
        **{"from": SRC.model_copy(deep=True), "to": DST.model_copy(deep=True)},
        intent=MessageIntent.DELEGATE,
        payload={"task": "sig-test"},
    )
    msg.sign(SECRET)
    return msg


def _verifier(**kwargs) -> StrictMessageVerifier:
    defaults = dict(hmac_secret=SECRET, expected_recipient_did=DST.did)
    defaults.update(kwargs)
    return StrictMessageVerifier(**defaults)


# ---------------------------------------------------------------------------
# Truncated signatures
# ---------------------------------------------------------------------------


def test_truncated_hmac_signature_rejected():
    """HMAC signature truncated to 16 hex chars MUST be rejected."""
    msg = _make_signed()
    full_sig = msg.auth["signature"]
    msg.auth["signature"] = full_sig[:len("hmac-sha256:") + 16]
    result = _verifier().verify(msg)
    assert not result.ok
    assert result.error == "invalid_hmac_signature"


def test_empty_signature_value_rejected():
    """Empty signature string MUST be rejected."""
    msg = _make_signed()
    msg.auth["signature"] = ""
    result = _verifier().verify(msg)
    assert not result.ok
    assert result.error == "missing_or_invalid_signature"


def test_signature_without_scheme_prefix_rejected():
    """Signature without 'scheme:' prefix MUST be rejected."""
    msg = _make_signed()
    hex_part = msg.auth["signature"].split(":")[1]
    msg.auth["signature"] = hex_part
    result = _verifier().verify(msg)
    assert not result.ok
    assert result.error == "missing_or_invalid_signature"


# ---------------------------------------------------------------------------
# Scheme confusion attacks
# ---------------------------------------------------------------------------


def test_unknown_scheme_rejected():
    """Unknown signature scheme MUST be rejected."""
    msg = _make_signed()
    msg.auth["signature"] = "rsa-pss:" + "ab" * 32
    result = _verifier().verify(msg)
    assert not result.ok
    assert result.error == "signature_scheme_not_allowed"


def test_scheme_case_sensitivity():
    """Scheme names MUST be case-sensitive: 'HMAC-SHA256' != 'hmac-sha256'."""
    msg = _make_signed()
    sig = msg.auth["signature"]
    msg.auth["signature"] = sig.replace("hmac-sha256", "HMAC-SHA256")
    result = _verifier().verify(msg)
    assert not result.ok, "uppercase scheme must be rejected"


def test_restricted_scheme_allowlist():
    """Verifier configured with only ed25519 MUST reject hmac-sha256."""
    msg = _make_signed()
    v = _verifier(allowed_signature_schemes=("ed25519",))
    result = v.verify(msg)
    assert not result.ok
    assert result.error == "signature_scheme_not_allowed"


def test_none_scheme_rejected():
    """'none:' scheme (JWT-style bypass) MUST be rejected."""
    msg = _make_signed()
    msg.auth["signature"] = "none:"
    result = _verifier().verify(msg)
    assert not result.ok


def test_empty_scheme_rejected():
    """':hexvalue' (empty scheme) MUST be rejected."""
    msg = _make_signed()
    msg.auth["signature"] = ":" + "ab" * 32
    result = _verifier().verify(msg)
    assert not result.ok


# ---------------------------------------------------------------------------
# Tampered signature bytes
# ---------------------------------------------------------------------------


def test_single_bit_flip_in_signature_rejected():
    """Flipping one hex character in the HMAC digest MUST be rejected."""
    msg = _make_signed()
    sig = msg.auth["signature"]
    prefix, hex_digest = sig.split(":", 1)
    flipped = chr(ord(hex_digest[0]) ^ 0x01) + hex_digest[1:]
    msg.auth["signature"] = f"{prefix}:{flipped}"
    result = _verifier().verify(msg)
    assert not result.ok
    assert result.error == "invalid_hmac_signature"


def test_all_zeros_signature_rejected():
    """All-zeros HMAC digest MUST be rejected."""
    msg = _make_signed()
    msg.auth["signature"] = "hmac-sha256:" + "0" * 64
    result = _verifier().verify(msg)
    assert not result.ok
    assert result.error == "invalid_hmac_signature"


def test_all_ff_signature_rejected():
    """All-ff HMAC digest MUST be rejected."""
    msg = _make_signed()
    msg.auth["signature"] = "hmac-sha256:" + "f" * 64
    result = _verifier().verify(msg)
    assert not result.ok
    assert result.error == "invalid_hmac_signature"


# ---------------------------------------------------------------------------
# Wrong secret
# ---------------------------------------------------------------------------


def test_signature_from_different_secret_rejected():
    """Message signed with secret A, verified with secret B MUST fail."""
    msg = _make_signed()
    v = _verifier(hmac_secret="completely-different-secret")
    result = v.verify(msg)
    assert not result.ok
    assert result.error == "invalid_hmac_signature"


# ---------------------------------------------------------------------------
# Missing HMAC secret in verifier
# ---------------------------------------------------------------------------


def test_verifier_without_hmac_secret_rejects():
    """Verifier with empty hmac_secret MUST reject hmac-sha256 messages."""
    msg = _make_signed()
    v = _verifier(hmac_secret="")
    result = v.verify(msg)
    assert not result.ok
    assert result.error == "missing_hmac_secret"


# ---------------------------------------------------------------------------
# Signature with non-hex characters
# ---------------------------------------------------------------------------


def test_signature_with_non_hex_chars_rejected():
    """Signature containing non-hex characters MUST be rejected."""
    msg = _make_signed()
    msg.auth["signature"] = "hmac-sha256:" + "zz" * 32
    result = _verifier().verify(msg)
    assert not result.ok
    assert result.error == "invalid_hmac_signature"

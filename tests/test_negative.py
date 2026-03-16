"""Negative conformance tests for ROAR Protocol Python SDK.

These tests verify that the SDK correctly *rejects* invalid, tampered, or expired
inputs. A conformant implementation must fail loudly on bad data, not silently
pass or produce unexpected output.
"""

import time
import pytest
from roar_sdk import AgentIdentity, ROARMessage, MessageIntent
from roar_sdk.delegation import DelegationToken, issue_token


SECRET = "roar-conformance-test-secret"


def _make_signed_message(secret: str = SECRET) -> ROARMessage:
    sender = AgentIdentity(display_name="neg-sender", capabilities=["test"])
    receiver = AgentIdentity(display_name="neg-receiver", capabilities=["test"])
    msg = ROARMessage(
        **{"from": sender, "to": receiver},
        intent=MessageIntent.DELEGATE,
        payload={"task": "negative-test"},
    )
    msg.sign(secret)
    return msg


# ---------------------------------------------------------------------------
# 1. Empty auth dict must fail verify()
# ---------------------------------------------------------------------------

def test_empty_auth_dict_fails_verification():
    """auth: {} (empty dict) must not pass HMAC verification."""
    msg = _make_signed_message()
    # Overwrite auth with an empty dict (the C-1 vulnerability if not fixed)
    msg.auth = {}
    assert msg.verify(SECRET) is False, (
        "empty auth: {} must fail verification — not silently bypass it"
    )


# ---------------------------------------------------------------------------
# 2. Stale timestamp (> 300 s in the past) must fail verify()
# ---------------------------------------------------------------------------

def test_stale_timestamp_fails_verification():
    """A message whose auth.timestamp is >300 s old must be rejected."""
    msg = _make_signed_message()
    # Re-sign with a timestamp 400 seconds in the past
    stale_ts = time.time() - 400
    msg.auth = {"timestamp": stale_ts}
    msg.sign(SECRET)  # produces a valid HMAC but over a stale timestamp
    # Now revert the timestamp to the stale value without re-signing so the
    # HMAC is valid but the timestamp check should still reject it
    # Actually — sign() sets auth.timestamp internally; we need to set it after
    raw = msg.model_dump(by_alias=True)
    raw["auth"]["timestamp"] = stale_ts
    # Rebuild: re-serialize and re-parse (verify reads auth.timestamp from wire)
    from roar_sdk.types import ROARMessage as _M
    wire_msg = _M.model_validate(raw)
    assert wire_msg.verify(SECRET, max_age_seconds=300) is False, (
        "message with auth.timestamp > 300 s old must fail verify()"
    )


# ---------------------------------------------------------------------------
# 3. Tampered payload must fail verify() (HMAC mismatch)
# ---------------------------------------------------------------------------

def test_tampered_payload_fails_verification():
    """Changing payload after signing must break the HMAC."""
    msg = _make_signed_message()
    # Tamper with the payload after signing
    msg.payload = {"task": "TAMPERED"}
    assert msg.verify(SECRET) is False, (
        "tampered payload must produce HMAC mismatch"
    )


# ---------------------------------------------------------------------------
# 4. Wrong secret must fail verify()
# ---------------------------------------------------------------------------

def test_wrong_secret_fails_verification():
    """Verifying with the wrong HMAC secret must fail."""
    msg = _make_signed_message(secret=SECRET)
    assert msg.verify("totally-wrong-secret") is False, (
        "verifying with the wrong secret must fail"
    )


# ---------------------------------------------------------------------------
# 5. Missing signature in auth must fail verify()
# ---------------------------------------------------------------------------

def test_missing_signature_fails_verification():
    """auth dict without a 'signature' key must fail verify()."""
    msg = _make_signed_message()
    msg.auth = {"timestamp": time.time()}  # valid timestamp, no signature
    assert msg.verify(SECRET) is False, (
        "auth without signature field must fail verify()"
    )


# ---------------------------------------------------------------------------
# 6. Expired delegation token must fail is_valid()
# ---------------------------------------------------------------------------

def test_expired_delegation_token_is_invalid():
    """A DelegationToken whose expires_at is in the past must fail is_valid()."""
    issuer = AgentIdentity(display_name="issuer", capabilities=["delegate"])
    delegate = AgentIdentity(display_name="delegate", capabilities=[])

    expired_token = DelegationToken(
        token_id="tok_expired_test",
        delegator_did=issuer.did,
        delegate_did=delegate.did,
        capabilities=["read"],
        issued_at=time.time() - 3600,
        expires_at=time.time() - 1800,  # expired 30 minutes ago
        max_uses=10,
        use_count=0,
        can_redelegate=False,
        signature="",
    )
    assert expired_token.is_valid() is False, (
        "DelegationToken with past expires_at must fail is_valid()"
    )


# ---------------------------------------------------------------------------
# 7. Exhausted delegation token must fail is_valid()
# ---------------------------------------------------------------------------

def test_exhausted_delegation_token_is_invalid():
    """A DelegationToken whose use_count >= max_uses must fail is_valid()."""
    issuer = AgentIdentity(display_name="issuer", capabilities=["delegate"])
    delegate = AgentIdentity(display_name="delegate", capabilities=[])

    exhausted_token = DelegationToken(
        token_id="tok_exhausted_test",
        delegator_did=issuer.did,
        delegate_did=delegate.did,
        capabilities=["read"],
        issued_at=time.time(),
        expires_at=time.time() + 3600,
        max_uses=3,
        use_count=3,  # exactly at the limit
        can_redelegate=False,
        signature="",
    )
    assert exhausted_token.is_valid() is False, (
        "DelegationToken with use_count >= max_uses must fail is_valid()"
    )


# ---------------------------------------------------------------------------
# 8. Re-delegation must be blocked when can_redelegate=False
# ---------------------------------------------------------------------------

def test_redelegate_blocked_when_not_permitted():
    """issue_token() with a parent_token that has can_redelegate=False must raise."""
    import pytest as _pt
    issuer = AgentIdentity(display_name="issuer", capabilities=["delegate"])
    middle = AgentIdentity(display_name="middle", capabilities=[])
    end = AgentIdentity(display_name="end", capabilities=[])

    # Create a non-redelegatable parent token (no real Ed25519 key — just test the guard)
    parent = DelegationToken(
        token_id="tok_parent",
        delegator_did=issuer.did,
        delegate_did=middle.did,
        capabilities=["read"],
        issued_at=time.time(),
        expires_at=time.time() + 3600,
        max_uses=None,
        use_count=0,
        can_redelegate=False,
        signature="placeholder",
    )

    with _pt.raises(ValueError, match="re-delegation"):
        # middle tries to sub-delegate, passing the non-redelegatable parent
        issue_token(
            delegator_did=middle.did,
            delegator_private_key="a" * 64,  # placeholder — guard fires before key use
            delegate_did=end.did,
            capabilities=["read"],
            parent_token=parent,
        )

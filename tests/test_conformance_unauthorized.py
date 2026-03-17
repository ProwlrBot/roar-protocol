"""Conformance tests — unauthorized access scenarios.

Verifies that the StrictMessageVerifier correctly rejects messages
with recipient mismatch, missing auth, future timestamps, and
restricted scheme configurations.
"""

import time

from roar_sdk import AgentIdentity, ROARMessage, MessageIntent
from roar_sdk.verifier import StrictMessageVerifier
from roar_sdk.dedup import IdempotencyGuard

SECRET = "roar-conformance-test-secret"
SRC = AgentIdentity(display_name="unauth-src", capabilities=["test"])
DST = AgentIdentity(display_name="unauth-dst", capabilities=["test"])
OTHER = AgentIdentity(display_name="other-agent", capabilities=["test"])


def _make_signed() -> ROARMessage:
    msg = ROARMessage(
        **{"from": SRC.model_copy(deep=True), "to": DST.model_copy(deep=True)},
        intent=MessageIntent.DELEGATE,
        payload={"task": "unauth-test"},
    )
    msg.sign(SECRET)
    return msg


def _verifier(**kwargs) -> StrictMessageVerifier:
    defaults = dict(hmac_secret=SECRET, expected_recipient_did=DST.did)
    defaults.update(kwargs)
    return StrictMessageVerifier(**defaults)


# ---------------------------------------------------------------------------
# Recipient mismatch
# ---------------------------------------------------------------------------


def test_message_to_wrong_recipient_rejected():
    """Message addressed to agent A, verified by agent B MUST be rejected."""
    msg = _make_signed()  # addressed to DST
    v = _verifier(expected_recipient_did=OTHER.did)
    result = v.verify(msg)
    assert not result.ok
    assert result.error == "recipient_mismatch"


def test_no_recipient_binding_allows_any():
    """Verifier with expected_recipient_did=None MUST accept any recipient."""
    msg = _make_signed()
    v = _verifier(expected_recipient_did=None)
    result = v.verify(msg)
    assert result.ok


# ---------------------------------------------------------------------------
# Future timestamp
# ---------------------------------------------------------------------------


def test_message_from_far_future_rejected():
    """Message with timestamp 120s in the future MUST be rejected (default skew=30s)."""
    msg = _make_signed()
    msg.auth["timestamp"] = time.time() + 120
    result = _verifier().verify(msg)
    assert not result.ok
    assert result.error == "message_from_future"


def test_message_within_skew_accepted():
    """Freshly signed message MUST be accepted (within 30s skew)."""
    msg = _make_signed()
    result = _verifier().verify(msg)
    assert result.ok


def test_custom_future_skew():
    """Custom max_future_skew_seconds MUST be respected."""
    msg = _make_signed()
    msg.auth["timestamp"] = time.time() + 5
    v = _verifier(max_future_skew_seconds=2.0)
    result = v.verify(msg)
    assert not result.ok
    assert result.error == "message_from_future"


# ---------------------------------------------------------------------------
# Expired message
# ---------------------------------------------------------------------------


def test_expired_message_rejected():
    """Message older than max_age MUST be rejected."""
    msg = _make_signed()
    msg.auth["timestamp"] = time.time() - 600
    result = _verifier().verify(msg)
    assert not result.ok
    assert result.error == "message_expired"


def test_custom_max_age_enforced():
    """Custom max_age_seconds MUST be respected."""
    msg = _make_signed()
    msg.auth["timestamp"] = time.time() - 10
    v = _verifier(max_age_seconds=5.0)
    result = v.verify(msg)
    assert not result.ok
    assert result.error == "message_expired"


# ---------------------------------------------------------------------------
# Missing auth entirely
# ---------------------------------------------------------------------------


def test_completely_missing_auth_rejected():
    """Message with auth={} MUST be rejected."""
    msg = _make_signed()
    msg.auth = {}
    result = _verifier().verify(msg)
    assert not result.ok
    assert result.error == "missing_or_invalid_signature"


def test_auth_with_only_timestamp_rejected():
    """auth with timestamp but no signature MUST be rejected."""
    msg = _make_signed()
    msg.auth = {"timestamp": time.time()}
    result = _verifier().verify(msg)
    assert not result.ok
    assert result.error == "missing_or_invalid_signature"


def test_auth_with_only_signature_no_timestamp():
    """auth with signature but no timestamp MUST be rejected."""
    msg = _make_signed()
    ts = msg.auth.pop("timestamp", None)
    result = _verifier().verify(msg)
    assert not result.ok
    assert result.error == "missing_or_invalid_auth_timestamp"


# ---------------------------------------------------------------------------
# Compound: replay + expired
# ---------------------------------------------------------------------------


def test_replay_of_expired_message_rejected():
    """A replayed expired message MUST be rejected (either error is acceptable)."""
    guard = IdempotencyGuard()
    v = StrictMessageVerifier(
        hmac_secret=SECRET,
        expected_recipient_did=DST.did,
        replay_guard=guard,
        max_age_seconds=1.0,
    )
    msg = _make_signed()
    r1 = v.verify(msg)
    assert r1.ok

    msg.auth["timestamp"] = time.time() - 10
    r2 = v.verify(msg)
    assert not r2.ok
    assert r2.error in ("replay_detected", "message_expired")


# ---------------------------------------------------------------------------
# Multiple verification policies
# ---------------------------------------------------------------------------


def test_strict_verifier_all_checks_pass():
    """A properly signed, fresh, correctly-addressed message MUST pass all checks."""
    guard = IdempotencyGuard()
    v = StrictMessageVerifier(
        hmac_secret=SECRET,
        expected_recipient_did=DST.did,
        replay_guard=guard,
        max_age_seconds=300.0,
        max_future_skew_seconds=30.0,
    )
    msg = _make_signed()
    result = v.verify(msg)
    assert result.ok, f"all checks should pass: {result.error}"


def test_verifier_rejects_unsupported_scheme():
    """Verifier with empty allowed_signature_schemes MUST reject everything."""
    v = _verifier(allowed_signature_schemes=())
    msg = _make_signed()
    result = v.verify(msg)
    assert not result.ok
    assert result.error == "signature_scheme_not_allowed"

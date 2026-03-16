#!/usr/bin/env python3
"""Security invariants for StrictMessageVerifier reference implementation."""

import time

from roar_sdk import AgentIdentity, MessageIntent, ROARMessage
from roar_sdk.dedup import IdempotencyGuard
from roar_sdk.verifier import StrictMessageVerifier

SRC = AgentIdentity(display_name="sender")
DST = AgentIdentity(display_name="receiver")


def make_signed(secret: str = "test-secret") -> ROARMessage:
    msg = ROARMessage(
        **{"from": SRC.model_copy(deep=True), "to": DST.model_copy(deep=True)},
        intent=MessageIntent.DELEGATE,
        payload={"task": "hello"},
    )
    msg.sign(secret)
    return msg


def assert_ok(cond: bool, name: str) -> None:
    if not cond:
        raise AssertionError(name)


msg = make_signed()
replay_verifier = StrictMessageVerifier(
    hmac_secret="test-secret",
    expected_recipient_did=DST.did,
    replay_guard=IdempotencyGuard(),
)
assert_ok(replay_verifier.verify(msg).ok, "valid_message")
assert_ok(not replay_verifier.verify(msg).ok, "replay_rejected")

msg2 = make_signed()
msg2.to_identity.did = "did:roar:agent:not-me-00000000"
verifier2 = StrictMessageVerifier(hmac_secret="test-secret", expected_recipient_did=DST.did)
assert_ok(verifier2.verify(msg2).error == "recipient_mismatch", "recipient_binding")

msg3 = make_signed()
msg3.auth["timestamp"] = time.time() + 120
verifier3 = StrictMessageVerifier(hmac_secret="test-secret", expected_recipient_did=DST.did)
assert_ok(verifier3.verify(msg3).error == "message_from_future", "future_timestamp_rejected")

msg4 = make_signed()
msg4.auth["signature"] = "hmac-sha256:" + "0" * 64
verifier4 = StrictMessageVerifier(hmac_secret="test-secret", expected_recipient_did=DST.did)
assert_ok(verifier4.verify(msg4).error == "invalid_hmac_signature", "tamper_detected")

msg5 = make_signed()
msg5.auth["signature"] = "rsa-pss:" + "ab" * 64
verifier5 = StrictMessageVerifier(hmac_secret="test-secret", expected_recipient_did=DST.did)
assert_ok(verifier5.verify(msg5).error == "signature_scheme_not_allowed", "scheme_allowlist")

msg6 = make_signed()
msg6.auth.pop("timestamp", None)
verifier6 = StrictMessageVerifier(hmac_secret="test-secret", expected_recipient_did=DST.did)
assert_ok(verifier6.verify(msg6).error == "missing_or_invalid_auth_timestamp", "timestamp_required")

print("strict verifier checks passed")

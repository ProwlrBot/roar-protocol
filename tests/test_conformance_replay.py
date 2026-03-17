"""Conformance tests — replay attack scenarios.

Verifies that the IdempotencyGuard and StrictMessageVerifier correctly
detect and reject replayed messages under various conditions.

NOTE: Basic duplicate detection is already tested in test_negative.py.
These tests cover additional edge cases: LRU eviction, burst replay,
guard lifecycle, and verifier integration with/without guard.
"""

import time

from roar_sdk import AgentIdentity, ROARMessage, MessageIntent
from roar_sdk.dedup import IdempotencyGuard
from roar_sdk.verifier import StrictMessageVerifier

SECRET = "roar-conformance-test-secret"
SRC = AgentIdentity(display_name="replay-src", capabilities=["test"])
DST = AgentIdentity(display_name="replay-dst", capabilities=["test"])


def _make_signed() -> ROARMessage:
    msg = ROARMessage(
        **{"from": SRC.model_copy(deep=True), "to": DST.model_copy(deep=True)},
        intent=MessageIntent.DELEGATE,
        payload={"task": "replay-test"},
    )
    msg.sign(SECRET)
    return msg


# ---------------------------------------------------------------------------
# IdempotencyGuard — LRU eviction and capacity
# ---------------------------------------------------------------------------


def test_guard_lru_eviction_under_capacity():
    """Guard MUST evict oldest entries when max_keys is exceeded."""
    guard = IdempotencyGuard(max_keys=3, ttl_seconds=600)
    guard.is_duplicate("msg_1")  # records msg_1
    guard.is_duplicate("msg_2")  # records msg_2
    guard.is_duplicate("msg_3")  # records msg_3
    guard.is_duplicate("msg_4")  # records msg_4, evicts msg_1 (oldest)
    # msg_1 was evicted — checking it re-records it (returns False = not duplicate)
    assert guard.is_duplicate("msg_1") is False, "evicted key should not be duplicate"
    # After re-recording msg_1, guard has: msg_3, msg_4, msg_1 (msg_2 evicted)
    # msg_4 should still be tracked
    assert guard.is_duplicate("msg_4") is True, "msg_4 still tracked"


def test_guard_burst_replay_all_detected():
    """Burst of 100 identical IDs: only first should pass, rest MUST be duplicates."""
    guard = IdempotencyGuard()
    msg_id = "msg_burst_target"
    results = [guard.is_duplicate(msg_id) for _ in range(100)]
    assert results[0] is False, "first in burst should pass"
    assert all(r is True for r in results[1:]), "all replays in burst must be detected"


def test_guard_clear_resets_state():
    """clear() MUST allow previously-seen IDs to pass again."""
    guard = IdempotencyGuard()
    guard.is_duplicate("msg_clear_test")
    guard.clear()
    assert guard.is_duplicate("msg_clear_test") is False


def test_guard_size_tracks_entries():
    """size property MUST reflect the number of tracked entries."""
    guard = IdempotencyGuard()
    assert guard.size == 0
    guard.is_duplicate("a")
    guard.is_duplicate("b")
    assert guard.size == 2


def test_guard_mark_seen_records_without_check():
    """mark_seen() MUST record a key so subsequent is_duplicate returns True."""
    guard = IdempotencyGuard()
    guard.mark_seen("msg_marked")
    assert guard.is_duplicate("msg_marked") is True


def test_guard_different_ids_not_duplicate():
    """Different IDs MUST NOT trigger false-positive duplicate detection."""
    guard = IdempotencyGuard()
    guard.is_duplicate("msg_a")
    assert guard.is_duplicate("msg_b") is False


def test_guard_large_capacity():
    """Guard with large max_keys MUST handle many unique IDs without eviction."""
    guard = IdempotencyGuard(max_keys=100_000)
    for i in range(1000):
        assert guard.is_duplicate(f"msg_{i}") is False
    assert guard.size == 1000
    # All should still be tracked
    for i in range(1000):
        assert guard.is_duplicate(f"msg_{i}") is True


# ---------------------------------------------------------------------------
# StrictMessageVerifier replay integration
# ---------------------------------------------------------------------------


def test_verifier_rejects_replayed_message():
    """StrictMessageVerifier with replay_guard MUST reject the second submission."""
    guard = IdempotencyGuard()
    v = StrictMessageVerifier(
        hmac_secret=SECRET,
        expected_recipient_did=DST.did,
        replay_guard=guard,
    )
    msg = _make_signed()
    r1 = v.verify(msg)
    assert r1.ok, "first submission should pass"
    r2 = v.verify(msg)
    assert not r2.ok, "replay must be rejected"
    assert r2.error == "replay_detected"


def test_verifier_without_guard_allows_replay():
    """Without a replay_guard, the verifier MUST NOT reject duplicates."""
    v = StrictMessageVerifier(
        hmac_secret=SECRET,
        expected_recipient_did=DST.did,
        replay_guard=None,
    )
    msg = _make_signed()
    r1 = v.verify(msg)
    r2 = v.verify(msg)
    assert r1.ok and r2.ok, "without guard, duplicates pass"


def test_verifier_different_messages_with_guard():
    """Multiple unique messages with guard MUST all pass."""
    guard = IdempotencyGuard()
    v = StrictMessageVerifier(
        hmac_secret=SECRET,
        expected_recipient_did=DST.did,
        replay_guard=guard,
    )
    for _ in range(10):
        msg = _make_signed()  # each has unique ID
        result = v.verify(msg)
        assert result.ok, f"unique message should pass: {result.error}"

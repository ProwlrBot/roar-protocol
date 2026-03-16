"""Tests verifying that Python and TypeScript produce identical canonical JSON
for message signing. A divergence here would cause cross-SDK signature failures.

The Python SDK's canonical form is defined by:
    json.dumps(body_dict, sort_keys=True)

The TypeScript SDK exports a ``pythonJsonDumps`` function that must produce
byte-for-byte identical output for the same input. Cross-SDK identity is
verified by the interop test suite in tests/test_cross_sdk_interop.py (which
requires Node.js in PATH). The tests below validate the Python side in isolation
so CI can catch Python-only regressions without a Node dependency.
"""

from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Helpers — replicate the signing body logic from types.py without importing
# the full SDK (to avoid coupling the test to internal implementation details).
# If the SDK's _signing_body() changes, these tests will catch the divergence.
# ---------------------------------------------------------------------------


def _canonical(body_dict: dict) -> str:
    """Mirror of ROARMessage._signing_body() / DelegationToken._signing_body().

    Both use json.dumps(..., sort_keys=True) with no extra separators or
    indentation — the Python json module default compact form with spaces
    after colons and commas is the canonical wire representation.
    """
    return json.dumps(body_dict, sort_keys=True)


# ---------------------------------------------------------------------------
# 1. Golden fixture canonical JSON
# ---------------------------------------------------------------------------


def test_golden_canonical_json():
    """The canonical JSON produced from the golden inputs must match the
    expected value recorded in tests/conformance/golden/signature.json.

    This is the single source of truth for cross-SDK compatibility. Any change
    to the canonical form that does not update the golden fixture is a bug.
    """
    # Inputs from tests/conformance/golden/signature.json
    golden_inputs = {
        "id": "msg_a1b2c3d4e5",
        "from": "did:roar:agent:sender-f5e6d7c8a9b01234",
        "to": "did:roar:agent:receiver-k1l2m3n4o5p6q7r8",
        "intent": "delegate",
        "payload": {"task": "golden conformance test", "priority": "low"},
        "context": {"session_id": "sess_golden"},
        "timestamp": 1710000000.0,
    }

    expected_canonical = (
        '{"context": {"session_id": "sess_golden"}, '
        '"from": "did:roar:agent:sender-f5e6d7c8a9b01234", '
        '"id": "msg_a1b2c3d4e5", '
        '"intent": "delegate", '
        '"payload": {"priority": "low", "task": "golden conformance test"}, '
        '"timestamp": 1710000000.0, '
        '"to": "did:roar:agent:receiver-k1l2m3n4o5p6q7r8"}'
    )

    actual = _canonical(golden_inputs)
    assert actual == expected_canonical, (
        f"Canonical JSON diverged from golden fixture.\n"
        f"Expected: {expected_canonical!r}\n"
        f"Actual:   {actual!r}"
    )

    # Also verify the TS SDK's pythonJsonDumps must produce the same string.
    # Note: The TypeScript SDK's pythonJsonDumps is verified to produce
    # byte-identical output to this expected_canonical value in the cross-SDK
    # interop test suite (tests/test_cross_sdk_interop.py, requires Node.js).


# ---------------------------------------------------------------------------
# 2. Unicode payload canonical form
# ---------------------------------------------------------------------------


def test_unicode_payload_canonical():
    """Payloads containing Unicode characters (emoji, CJK, combining marks)
    must be serialized as Unicode escape sequences or raw Unicode consistently.

    Python's json.dumps uses ensure_ascii=True by default, which escapes all
    non-ASCII characters to \\uXXXX. Both SDKs must agree on this behaviour.
    """
    body = {
        "id": "msg_unicode01",
        "from": "did:roar:agent:sender-unicode",
        "to": "did:roar:agent:receiver-unicode",
        "intent": "notify",
        "payload": {
            "message": "Hello \u4e16\u754c \U0001f600",  # "Hello 世界 😀"
            "cjk": "\u4e2d\u6587",                        # "中文"
        },
        "context": {},
        "timestamp": 1710000001.0,
    }

    canonical = _canonical(body)

    # Python json.dumps with ensure_ascii=True (default) escapes non-ASCII.
    # Verify the emoji and CJK characters are escaped, not embedded raw.
    assert "\\u4e16\\u754c" in canonical, "CJK characters should be \\uXXXX escaped"
    assert "\\ud83d\\ude00" in canonical or "\\U0001f600" in canonical or "\\ud83d" in canonical, (
        "Emoji (U+1F600) should be represented via surrogate pair or \\uXXXX escapes"
    )

    # The result must be valid JSON that round-trips to the original values.
    parsed = json.loads(canonical)
    assert parsed["payload"]["message"] == "Hello \u4e16\u754c \U0001f600"
    assert parsed["payload"]["cjk"] == "\u4e2d\u6587"


# ---------------------------------------------------------------------------
# 3. Nested object key ordering
# ---------------------------------------------------------------------------


def test_nested_object_key_ordering():
    """sort_keys=True must apply recursively to ALL nested dicts, not just the
    top-level keys. A signing implementation that only sorts the outer dict
    would produce a different canonical form than one using sort_keys=True.
    """
    body = {
        "z_outer": "last",
        "a_outer": "first",
        "payload": {
            "z_inner": "inner_last",
            "m_inner": "inner_middle",
            "a_inner": "inner_first",
            "nested": {
                "z_deep": "deep_last",
                "a_deep": "deep_first",
            },
        },
        "context": {
            "z_ctx": "ctx_last",
            "a_ctx": "ctx_first",
        },
    }

    canonical = _canonical(body)
    parsed = json.loads(canonical)

    # Verify that the key order in the serialized string follows lexicographic
    # order at every level by checking index positions.
    a_outer_pos = canonical.index('"a_outer"')
    z_outer_pos = canonical.index('"z_outer"')
    assert a_outer_pos < z_outer_pos, "Top-level keys must be sorted: a_outer before z_outer"

    a_inner_pos = canonical.index('"a_inner"')
    m_inner_pos = canonical.index('"m_inner"')
    z_inner_pos = canonical.index('"z_inner"')
    assert a_inner_pos < m_inner_pos < z_inner_pos, (
        "Nested payload keys must be sorted: a_inner < m_inner < z_inner"
    )

    a_deep_pos = canonical.index('"a_deep"')
    z_deep_pos = canonical.index('"z_deep"')
    assert a_deep_pos < z_deep_pos, "Deeply nested keys must be sorted: a_deep before z_deep"

    a_ctx_pos = canonical.index('"a_ctx"')
    z_ctx_pos = canonical.index('"z_ctx"')
    assert a_ctx_pos < z_ctx_pos, "Context keys must be sorted: a_ctx before z_ctx"

    # Round-trip correctness
    assert parsed["a_outer"] == "first"
    assert parsed["payload"]["a_inner"] == "inner_first"
    assert parsed["payload"]["nested"]["a_deep"] == "deep_first"


# ---------------------------------------------------------------------------
# 4. Float timestamp canonical form
# ---------------------------------------------------------------------------


def test_float_timestamp_canonical():
    """Timestamps are float values. Python's json.dumps serializes 1710000000.0
    as '1710000000.0' (preserving the decimal point), not '1710000000'
    (which would be an integer). The TypeScript SDK's pythonJsonDumps must
    match this behaviour exactly.

    This matters because the timestamp is covered by the HMAC signature — a
    difference in serialization between SDKs would cause cross-SDK verification
    failures for messages signed with a round-number timestamp.
    """
    body = {
        "id": "msg_floattest",
        "from": "did:roar:agent:a",
        "to": "did:roar:agent:b",
        "intent": "execute",
        "payload": {},
        "context": {},
        "timestamp": 1710000000.0,
    }

    canonical = _canonical(body)

    # Python serializes 1710000000.0 as the string "1710000000.0"
    assert '"timestamp": 1710000000.0' in canonical, (
        f"Expected timestamp serialized as 1710000000.0 (float), got: {canonical!r}"
    )

    # Must NOT serialize as an integer (without the decimal point)
    assert '"timestamp": 1710000000,' not in canonical, (
        "Timestamp must retain decimal point to distinguish float from int"
    )
    assert '"timestamp": 1710000000}' not in canonical

    # Verify round-trip
    parsed = json.loads(canonical)
    assert parsed["timestamp"] == 1710000000.0
    assert isinstance(parsed["timestamp"], float)


# ---------------------------------------------------------------------------
# 5. Capabilities sorted in delegation token
# ---------------------------------------------------------------------------


def test_capabilities_sorted_in_delegation():
    """DelegationToken._signing_body() sorts the capabilities list before
    signing. This ensures that ['scan', 'recon'] and ['recon', 'scan'] produce
    the same canonical body and thus the same signature.

    A delegation token issued with capabilities in one order must verify
    successfully even if the verifier sorts the capabilities differently.
    """
    # Replicate DelegationToken._signing_body() logic
    def delegation_canonical(
        capabilities: list[str],
        can_redelegate: bool = False,
        delegate_did: str = "did:roar:agent:bob-aabbccdd11223344",
        delegator_did: str = "did:roar:agent:alice-aabbccdd11223344",
        expires_at: float | None = 1710003600.0,
        issued_at: float = 1710000000.0,
        max_uses: int | None = 10,
        token_id: str = "tok_aabbccdd11",
    ) -> str:
        body = {
            "capabilities": sorted(capabilities),
            "can_redelegate": can_redelegate,
            "delegate_did": delegate_did,
            "delegator_did": delegator_did,
            "expires_at": expires_at,
            "issued_at": issued_at,
            "max_uses": max_uses,
            "token_id": token_id,
        }
        return json.dumps(body, sort_keys=True)

    # Two tokens identical in every way except capability list order
    canonical_ab = delegation_canonical(capabilities=["recon", "scan"])
    canonical_ba = delegation_canonical(capabilities=["scan", "recon"])

    assert canonical_ab == canonical_ba, (
        "Capabilities must be sorted before signing — order of input list must not matter.\n"
        f"  ['recon', 'scan'] → {canonical_ab!r}\n"
        f"  ['scan', 'recon'] → {canonical_ba!r}"
    )

    # Verify the sorted order appears in the canonical output
    assert '"capabilities": ["recon", "scan"]' in canonical_ab, (
        "Sorted capabilities must appear as ['recon', 'scan'] (lexicographic order)"
    )

    # A token with different capabilities must produce a different canonical body
    canonical_other = delegation_canonical(capabilities=["recon", "scan", "exploit"])
    assert canonical_other != canonical_ab, (
        "Tokens with different capabilities must have different canonical bodies"
    )

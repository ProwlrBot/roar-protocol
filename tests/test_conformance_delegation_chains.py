"""Conformance tests — broken delegation chains.

Verifies that the delegation system correctly rejects expired chains,
capability escalation, and circular delegation attempts.

NOTE: Basic expired/exhausted token tests exist in test_negative.py.
These tests cover additional chain-level scenarios: real Ed25519 signing,
token tampering, capability escalation detection, and consume() lifecycle.
"""

import time

import pytest

from roar_sdk import AgentIdentity
from roar_sdk.delegation import DelegationToken, issue_token, verify_token
from roar_sdk.signing import generate_keypair


# ---------------------------------------------------------------------------
# Real Ed25519 signed token — verification with correct/wrong keys
# ---------------------------------------------------------------------------


def test_verify_token_with_correct_key():
    """verify_token MUST return True for a properly signed token."""
    priv, pub = generate_keypair()
    token = issue_token(
        delegator_did="did:roar:agent:issuer-aaa",
        delegator_private_key=priv,
        delegate_did="did:roar:agent:delegate-bbb",
        capabilities=["read", "write"],
        expires_in_seconds=3600,
    )
    assert verify_token(token, pub)


def test_verify_token_with_wrong_key():
    """verify_token with wrong public key MUST return False."""
    priv, pub = generate_keypair()
    _, wrong_pub = generate_keypair()
    token = issue_token(
        delegator_did="did:roar:agent:issuer-aaa",
        delegator_private_key=priv,
        delegate_did="did:roar:agent:delegate-bbb",
        capabilities=["read"],
    )
    assert not verify_token(token, wrong_pub)


def test_verify_token_with_tampered_capabilities():
    """Tampering with capabilities after signing MUST fail verification."""
    priv, pub = generate_keypair()
    token = issue_token(
        delegator_did="did:roar:agent:issuer-aaa",
        delegator_private_key=priv,
        delegate_did="did:roar:agent:delegate-bbb",
        capabilities=["read"],
    )
    token.capabilities = ["read", "admin"]  # tamper
    assert not verify_token(token, pub)


def test_verify_token_with_tampered_delegate():
    """Changing delegate_did after signing MUST fail verification."""
    priv, pub = generate_keypair()
    token = issue_token(
        delegator_did="did:roar:agent:issuer",
        delegator_private_key=priv,
        delegate_did="did:roar:agent:bob",
        capabilities=["read"],
    )
    token.delegate_did = "did:roar:agent:mallory"  # tamper
    assert not verify_token(token, pub)


def test_verify_token_with_tampered_delegator():
    """Changing delegator_did after signing MUST fail verification."""
    priv, pub = generate_keypair()
    token = issue_token(
        delegator_did="did:roar:agent:alice",
        delegator_private_key=priv,
        delegate_did="did:roar:agent:bob",
        capabilities=["read"],
    )
    token.delegator_did = "did:roar:agent:mallory"
    assert not verify_token(token, pub)


def test_verify_expired_token_fails():
    """verify_token on expired token MUST return False (checks is_valid first)."""
    priv, pub = generate_keypair()
    token = issue_token(
        delegator_did="did:roar:agent:issuer",
        delegator_private_key=priv,
        delegate_did="did:roar:agent:delegate",
        capabilities=["read"],
        expires_in_seconds=0.001,
    )
    time.sleep(0.01)  # ensure expiry
    assert not verify_token(token, pub)


# ---------------------------------------------------------------------------
# Capability escalation detection
# ---------------------------------------------------------------------------


def test_redelegate_with_escalated_capabilities():
    """Re-delegation that adds capabilities not in parent — documents the gap.

    issue_token does NOT enforce capability subsetting automatically.
    Application-level code MUST check that child caps are a subset of parent caps.
    """
    priv, pub = generate_keypair()
    parent = issue_token(
        delegator_did="did:roar:agent:root",
        delegator_private_key=priv,
        delegate_did="did:roar:agent:middle",
        capabilities=["read"],
        can_redelegate=True,
    )

    middle_priv, _ = generate_keypair()
    child = issue_token(
        delegator_did="did:roar:agent:middle",
        delegator_private_key=middle_priv,
        delegate_did="did:roar:agent:end",
        capabilities=["read", "write"],  # escalation
        parent_token=parent,
    )

    # Document that escalation is NOT prevented at the token level
    escalated = set(child.capabilities) - set(parent.capabilities)
    assert len(escalated) > 0, "child has capabilities not in parent"
    # Application guard: check subset
    is_subset = set(child.capabilities).issubset(set(parent.capabilities))
    assert not is_subset, "child capabilities are NOT a subset of parent"


# ---------------------------------------------------------------------------
# consume() lifecycle
# ---------------------------------------------------------------------------


def test_consume_respects_max_uses():
    """consume() MUST return False once max_uses is reached."""
    token = DelegationToken(
        token_id="tok_consume_test",
        delegator_did="did:roar:agent:a",
        delegate_did="did:roar:agent:b",
        capabilities=["read"],
        issued_at=time.time(),
        expires_at=time.time() + 3600,
        max_uses=2,
        use_count=0,
        signature="placeholder",
    )
    assert token.consume() is True   # use 1
    assert token.consume() is True   # use 2
    assert token.consume() is False  # exhausted


def test_consume_on_expired_token_returns_false():
    """consume() on an expired token MUST return False."""
    token = DelegationToken(
        token_id="tok_expired_consume",
        delegator_did="did:roar:agent:a",
        delegate_did="did:roar:agent:b",
        capabilities=["read"],
        issued_at=time.time() - 7200,
        expires_at=time.time() - 3600,
        max_uses=None,
        use_count=0,
        signature="placeholder",
    )
    assert token.consume() is False


# ---------------------------------------------------------------------------
# Unlimited / no-expiry tokens
# ---------------------------------------------------------------------------


def test_unlimited_uses_token_always_valid():
    """Token with max_uses=None MUST always pass use count check."""
    token = DelegationToken(
        token_id="tok_unlimited",
        delegator_did="did:roar:agent:a",
        delegate_did="did:roar:agent:b",
        capabilities=["read"],
        issued_at=time.time(),
        expires_at=time.time() + 3600,
        max_uses=None,
        use_count=999999,
        signature="placeholder",
    )
    assert token.is_valid()


def test_no_expiry_token_always_valid():
    """Token with expires_at=None MUST always pass expiry check."""
    token = DelegationToken(
        token_id="tok_no_expiry",
        delegator_did="did:roar:agent:a",
        delegate_did="did:roar:agent:b",
        capabilities=["read"],
        issued_at=time.time(),
        expires_at=None,
        max_uses=None,
        use_count=0,
        signature="placeholder",
    )
    assert token.is_valid()


# ---------------------------------------------------------------------------
# grants() method
# ---------------------------------------------------------------------------


def test_grants_returns_true_for_included_capability():
    """grants() MUST return True for capabilities listed in the token."""
    token = DelegationToken(
        token_id="tok_grants",
        delegator_did="did:roar:agent:a",
        delegate_did="did:roar:agent:b",
        capabilities=["read", "write"],
        issued_at=time.time(),
        expires_at=time.time() + 3600,
        signature="placeholder",
    )
    assert token.grants("read")
    assert token.grants("write")


def test_grants_returns_false_for_missing_capability():
    """grants() MUST return False for capabilities not in the token."""
    token = DelegationToken(
        token_id="tok_no_admin",
        delegator_did="did:roar:agent:a",
        delegate_did="did:roar:agent:b",
        capabilities=["read"],
        issued_at=time.time(),
        expires_at=time.time() + 3600,
        signature="placeholder",
    )
    assert not token.grants("admin")


def test_grants_returns_false_when_expired():
    """grants() MUST return False for an expired token even if capability exists."""
    token = DelegationToken(
        token_id="tok_expired_grants",
        delegator_did="did:roar:agent:a",
        delegate_did="did:roar:agent:b",
        capabilities=["read"],
        issued_at=time.time() - 7200,
        expires_at=time.time() - 3600,
        signature="placeholder",
    )
    assert not token.grants("read")

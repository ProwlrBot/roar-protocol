# -*- coding: utf-8 -*-
"""Tests for AgentCard signed attestation (discovery poisoning mitigation)."""

import pytest
from roar_sdk import AgentIdentity, AgentCard, AgentCapability
from roar_sdk.signing import generate_keypair, sign_agent_card, verify_agent_card


def _make_card(with_public_key: bool = True) -> tuple["AgentCard", str]:
    """Return (card, private_key_hex). Card has a real Ed25519 public key if requested."""
    private_hex, public_hex = generate_keypair()
    identity = AgentIdentity(
        display_name="test-agent",
        capabilities=["read", "write"],
        public_key=public_hex if with_public_key else None,
    )
    card = AgentCard(
        identity=identity,
        description="A test agent",
        skills=["testing"],
        channels=["http"],
        endpoints={"main": "https://example.com/roar"},
        declared_capabilities=[
            AgentCapability(name="read", description="Read capability"),
        ],
    )
    return card, private_hex


# ---------------------------------------------------------------------------
# 1. Signing sets attestation and verification passes
# ---------------------------------------------------------------------------

def test_sign_agent_card_sets_attestation():
    """sign_agent_card must set card.attestation to a non-empty string."""
    card, private_hex = _make_card()
    assert card.attestation is None, "attestation should be None before signing"
    result = sign_agent_card(card, private_hex)
    assert isinstance(result, str)
    assert len(result) > 0
    assert card.attestation == result


def test_verify_agent_card_passes_after_signing():
    """verify_agent_card must return True for a correctly signed card."""
    card, private_hex = _make_card()
    sign_agent_card(card, private_hex)
    assert verify_agent_card(card) is True


# ---------------------------------------------------------------------------
# 2. Tampered card fails verification
# ---------------------------------------------------------------------------

def test_tampered_description_fails_verification():
    """Changing description after signing must break the attestation."""
    card, private_hex = _make_card()
    sign_agent_card(card, private_hex)
    card.description = "TAMPERED description"
    assert verify_agent_card(card) is False


def test_tampered_skills_fails_verification():
    """Changing skills after signing must break the attestation."""
    card, private_hex = _make_card()
    sign_agent_card(card, private_hex)
    card.skills = ["hacked"]
    assert verify_agent_card(card) is False


def test_tampered_capabilities_fails_verification():
    """Changing identity.capabilities after signing must break the attestation."""
    card, private_hex = _make_card()
    sign_agent_card(card, private_hex)
    card.identity.capabilities = ["admin"]
    assert verify_agent_card(card) is False


# ---------------------------------------------------------------------------
# 3. Missing attestation returns False
# ---------------------------------------------------------------------------

def test_missing_attestation_returns_false():
    """verify_agent_card must return False if attestation is None."""
    card, _ = _make_card()
    assert card.attestation is None
    assert verify_agent_card(card) is False


def test_empty_attestation_returns_false():
    """verify_agent_card must return False if attestation is an empty string."""
    card, _ = _make_card()
    card.attestation = ""
    assert verify_agent_card(card) is False


# ---------------------------------------------------------------------------
# 4. Missing public_key returns False
# ---------------------------------------------------------------------------

def test_missing_public_key_returns_false():
    """verify_agent_card must return False if identity.public_key is None."""
    card, private_hex = _make_card(with_public_key=False)
    sign_agent_card(card, private_hex)
    # attestation was set but public_key is missing
    assert verify_agent_card(card) is False


# ---------------------------------------------------------------------------
# 5. attestation field is optional / backwards compatible
# ---------------------------------------------------------------------------

def test_agent_card_without_attestation_is_valid_model():
    """AgentCard must be constructable without attestation (backwards compatible)."""
    identity = AgentIdentity(display_name="no-attest-agent")
    card = AgentCard(identity=identity)
    assert card.attestation is None


def test_agent_card_serialises_without_attestation_by_default():
    """Serialised AgentCard must include attestation=None when unset."""
    identity = AgentIdentity(display_name="serial-agent")
    card = AgentCard(identity=identity)
    data = card.model_dump()
    assert "attestation" in data
    assert data["attestation"] is None

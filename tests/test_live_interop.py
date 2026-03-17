"""Cross-SDK live integration tests.

Go beyond golden fixture validation — test that Python and TypeScript SDKs
can sign/verify each other's messages and attestations at runtime via
subprocess calls to Node.js helper scripts.

Requires Node.js >= 18 and the TS SDK built (cd ts && npm run build).
"""

import json
import os
import subprocess
import sys

import pytest

from roar_sdk import AgentIdentity, MessageIntent, ROARMessage
from roar_sdk.signing import (
    generate_keypair,
    sign_agent_card,
    sign_ed25519,
    verify_agent_card,
    verify_ed25519,
)
from roar_sdk.types import AgentCard, AgentCapability

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HELPERS = os.path.join(_REPO_ROOT, "tests", "helpers")
_SECRET = "roar-live-interop-test-secret-32"


def _node_available() -> bool:
    try:
        r = subprocess.run(["node", "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


requires_node = pytest.mark.skipif(
    not _node_available(), reason="Node.js not available"
)


def _run_helper(script: str, input_data: dict, *args: str) -> subprocess.CompletedProcess:
    """Run a Node.js helper script with JSON on stdin."""
    return subprocess.run(
        ["node", os.path.join(_HELPERS, script), *args],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        timeout=15,
        cwd=_REPO_ROOT,
    )


def _make_message() -> ROARMessage:
    sender = AgentIdentity(display_name="py-sender", capabilities=["test"])
    receiver = AgentIdentity(display_name="ts-receiver", capabilities=["test"])
    return ROARMessage(
        **{"from": sender, "to": receiver},
        intent=MessageIntent.DELEGATE,
        payload={"task": "live-interop", "source": "python"},
        context={"test": True},
    )


def _make_card(public_key: str) -> AgentCard:
    identity = AgentIdentity(
        display_name="test-agent",
        capabilities=["test"],
        public_key=public_key,
    )
    return AgentCard(
        identity=identity,
        description="Test agent for interop",
        skills=["testing"],
        channels=["http"],
        endpoints={"http": "http://localhost:8089"},
        declared_capabilities=[
            AgentCapability(name="test", description="Test capability")
        ],
    )


# ── HMAC Message Tests ──────────────────────────────────────────────────────

@requires_node
def test_python_sign_ts_verify_hmac():
    """Python signs HMAC message -> TypeScript verifies."""
    msg = _make_message()
    msg.sign(_SECRET)
    wire = msg.model_dump(by_alias=True)

    result = _run_helper("ts_verify_message.mjs", wire, _SECRET)
    assert result.returncode == 0, f"TS rejected Python HMAC sig: {result.stderr}"


@requires_node
def test_ts_sign_python_verify_hmac():
    """TypeScript signs HMAC message -> Python verifies."""
    msg = _make_message()
    wire = msg.model_dump(by_alias=True)

    result = _run_helper("ts_sign_message.mjs", wire, _SECRET)
    assert result.returncode == 0, f"TS signing failed: {result.stderr}"

    signed = json.loads(result.stdout)
    received = ROARMessage.model_validate(signed)
    assert received.verify(_SECRET, max_age_seconds=0), "Python rejected TS HMAC signature"


@requires_node
def test_tampered_message_rejected_cross_sdk():
    """A tampered message must fail verification in both directions."""
    msg = _make_message()
    msg.sign(_SECRET)
    wire = msg.model_dump(by_alias=True)
    wire["payload"]["task"] = "TAMPERED"

    result = _run_helper("ts_verify_message.mjs", wire, _SECRET)
    assert result.returncode != 0, "TS should reject tampered message"


# ── Ed25519 AgentCard Attestation Tests ──────────────────────────────────────

@requires_node
def test_python_sign_ts_verify_agentcard():
    """Python signs AgentCard attestation -> TypeScript verifies."""
    priv, pub = generate_keypair()
    card = _make_card(pub)
    sign_agent_card(card, priv)

    wire = card.model_dump()
    result = _run_helper("ts_verify_agentcard.mjs", wire)
    assert result.returncode == 0, f"TS rejected Python attestation: {result.stderr}"


@requires_node
def test_ts_sign_python_verify_agentcard():
    """TypeScript signs AgentCard attestation -> Python verifies."""
    priv, pub = generate_keypair()
    card = _make_card(pub)
    wire = card.model_dump()

    result = _run_helper("ts_sign_agentcard.mjs", wire, priv)
    assert result.returncode == 0, f"TS signing failed: {result.stderr}"

    signed = json.loads(result.stdout)
    received = AgentCard.model_validate(signed)
    assert verify_agent_card(received), "Python rejected TS attestation"


# ── Canonical Form Tests ─────────────────────────────────────────────────────

@requires_node
def test_roundtrip_sign_verify_both_directions():
    """A message signed by one SDK, verified by the other, then re-signed and verified back."""
    # Python sign -> TS verify -> TS re-sign -> Python verify
    msg = _make_message()
    msg.sign(_SECRET)
    wire = msg.model_dump(by_alias=True)

    # TS verifies Python's signature
    result = _run_helper("ts_verify_message.mjs", wire, _SECRET)
    assert result.returncode == 0, f"TS rejected Python sig: {result.stderr}"

    # TS re-signs the message
    result2 = _run_helper("ts_sign_message.mjs", wire, _SECRET)
    assert result2.returncode == 0, f"TS re-sign failed: {result2.stderr}"

    # Python verifies TS's re-signed message
    ts_wire = json.loads(result2.stdout)
    received = ROARMessage.model_validate(ts_wire)
    assert received.verify(_SECRET, max_age_seconds=0), "Python rejected TS re-signed msg"

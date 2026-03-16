"""Cross-SDK interoperability tests.

These tests verify that a message signed by the Python SDK can be verified by
the TypeScript SDK (and vice versa), catching canonicalization divergence between
implementations.

Requires Node.js >= 18 in PATH and the TypeScript SDK source at ts/src/.
"""

import json
import os
import subprocess
import sys
import tempfile
import time

import pytest

from roar_sdk import AgentIdentity, ROARMessage, MessageIntent

# Shared HMAC secret used by both Python and TypeScript sides of the test
_SECRET = "roar-interop-test-secret-32chars"

# Path to the TS verifier script (relative to repo root)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TS_VERIFIER = os.path.join(_REPO_ROOT, "tests", "verify_cross_sdk.mjs")


def _node_available() -> bool:
    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


requires_node = pytest.mark.skipif(
    not _node_available(),
    reason="Node.js not available in PATH",
)


def _sign_message_python(secret: str = _SECRET) -> dict:
    """Build and sign a ROARMessage in Python, return the wire dict."""
    sender = AgentIdentity(display_name="py-sender", capabilities=["python"])
    receiver = AgentIdentity(display_name="ts-receiver", capabilities=["typescript"])
    msg = ROARMessage(
        **{"from": sender, "to": receiver},
        intent=MessageIntent.DELEGATE,
        payload={"task": "cross-sdk-interop", "source": "python"},
        context={"test": True},
    )
    msg.sign(secret)
    return msg.model_dump(by_alias=True)


@requires_node
def test_python_sign_typescript_verify():
    """A message signed in Python must verify correctly in TypeScript."""
    wire = _sign_message_python()

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(wire, f)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["node", _TS_VERIFIER, tmp_path, _SECRET],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=_REPO_ROOT,
        )
        assert result.returncode == 0, (
            f"TypeScript verifier rejected a Python-signed message.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    finally:
        os.unlink(tmp_path)


@requires_node
def test_python_sign_typescript_verify_detects_tampering():
    """TypeScript must reject a Python-signed message with tampered payload."""
    wire = _sign_message_python()
    wire["payload"]["task"] = "TAMPERED-BY-TEST"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(wire, f)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["node", _TS_VERIFIER, tmp_path, _SECRET],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=_REPO_ROOT,
        )
        assert result.returncode != 0, (
            "TypeScript verifier should have rejected the tampered message but accepted it"
        )
    finally:
        os.unlink(tmp_path)


@requires_node
def test_golden_fixture_typescript_verify():
    """TypeScript must accept the canonical golden fixture signed by Python."""
    golden_path = os.path.join(
        _REPO_ROOT, "tests", "conformance", "golden", "message.json"
    )
    if not os.path.exists(golden_path):
        pytest.skip("Golden fixture not found")

    golden_secret = "roar-conformance-test-secret"

    result = subprocess.run(
        ["node", _TS_VERIFIER, golden_path, golden_secret],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=_REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"TypeScript failed to verify the golden fixture.\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )

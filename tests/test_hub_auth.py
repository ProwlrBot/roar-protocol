# -*- coding: utf-8 -*-
"""Tests for hub challenge-response registration authentication."""

from __future__ import annotations

import base64
import json
import time

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers — build a minimal FastAPI app from ROARHub internals
# ---------------------------------------------------------------------------

def _make_client() -> tuple:
    """Return (TestClient, hub_instance)."""
    from roar_sdk.hub import ROARHub

    hub = ROARHub(hub_id="http://testserver")
    # We need the FastAPI app without calling serve() (which calls uvicorn.run).
    # Re-create the app setup that serve() does by calling _build_app().
    # Since serve() is monolithic, we extract the app via a patched uvicorn.

    import unittest.mock as mock

    captured = {}

    def fake_run(app, **kwargs):
        captured["app"] = app

    with mock.patch("uvicorn.run", side_effect=fake_run):
        try:
            hub.serve()
        except Exception:
            pass  # fake_run raises nothing

    app = captured["app"]
    return TestClient(app), hub


def _gen_keypair():
    """Generate a real Ed25519 keypair. Returns (private_key, public_key_hex)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    pub_bytes = public_key.public_bytes_raw()
    return private_key, pub_bytes.hex()


def _sign(private_key, message: str) -> str:
    """Sign *message* with *private_key* and return ``ed25519:<base64url>``."""
    sig_bytes = private_key.sign(message.encode())
    b64 = base64.urlsafe_b64encode(sig_bytes).rstrip(b"=").decode()
    return f"ed25519:{b64}"


def _minimal_card(did: str, public_key_hex: str) -> dict:
    return {
        "identity": {
            "did": did,
            "display_name": "Test Agent",
            "public_key": public_key_hex,
        }
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client_hub():
    client, hub = _make_client()
    return client, hub


@pytest.fixture()
def client(client_hub):
    return client_hub[0]


@pytest.fixture()
def hub(client_hub):
    return client_hub[1]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRegisterStep1:
    def test_register_requires_public_key(self, client):
        """POST /roar/agents/register without public_key → 400."""
        resp = client.post(
            "/roar/agents/register",
            json={"did": "did:roar:agent:test-abc123", "card": {}},
        )
        assert resp.status_code == 400
        assert "public_key" in resp.json().get("error", "")

    def test_register_requires_did(self, client):
        """POST /roar/agents/register without did → 400."""
        resp = client.post(
            "/roar/agents/register",
            json={"public_key": "aa" * 32, "card": {}},
        )
        assert resp.status_code == 400
        assert "did" in resp.json().get("error", "")

    def test_register_issues_challenge(self, client):
        """Valid request returns challenge_id + nonce + expires_at."""
        _, pub_hex = _gen_keypair()
        did = "did:roar:agent:issuetest-001"
        resp = client.post(
            "/roar/agents/register",
            json={"did": did, "public_key": pub_hex, "card": _minimal_card(did, pub_hex)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "challenge_id" in data
        assert "nonce" in data
        assert "expires_at" in data
        assert data["expires_at"] > time.time()


class TestRegisterStep2:
    def test_challenge_expired_rejected(self, client, hub):
        """Manually expire the challenge; POST /roar/agents/challenge → 401 challenge_expired."""
        _, pub_hex = _gen_keypair()
        did = "did:roar:agent:expiretest-001"
        resp = client.post(
            "/roar/agents/register",
            json={"did": did, "public_key": pub_hex, "card": _minimal_card(did, pub_hex)},
        )
        challenge_id = resp.json()["challenge_id"]

        # Manually expire the challenge
        challenge = hub._challenge_store._pending[challenge_id]
        challenge.expires_at = time.time() - 1  # already expired

        resp2 = client.post(
            "/roar/agents/challenge",
            json={"challenge_id": challenge_id, "signature": "ed25519:AAAA"},
        )
        assert resp2.status_code == 401
        assert resp2.json()["error"] == "challenge_expired"

    def test_challenge_replay_rejected(self, client):
        """Consuming the same challenge_id twice → second call returns 401."""
        priv, pub_hex = _gen_keypair()
        did = "did:roar:agent:replaytest-001"
        resp = client.post(
            "/roar/agents/register",
            json={"did": did, "public_key": pub_hex, "card": _minimal_card(did, pub_hex)},
        )
        data = resp.json()
        challenge_id = data["challenge_id"]
        nonce = data["nonce"]

        sig = _sign(priv, nonce)

        # First call — should succeed
        resp1 = client.post(
            "/roar/agents/challenge",
            json={"challenge_id": challenge_id, "signature": sig},
        )
        assert resp1.status_code == 200

        # Second call with same challenge_id — must be rejected
        resp2 = client.post(
            "/roar/agents/challenge",
            json={"challenge_id": challenge_id, "signature": sig},
        )
        assert resp2.status_code == 401
        assert resp2.json()["error"] == "challenge_expired"

    def test_challenge_invalid_signature_rejected(self, client):
        """Wrong signature → 401 invalid_signature."""
        priv, pub_hex = _gen_keypair()
        did = "did:roar:agent:badsig-001"
        resp = client.post(
            "/roar/agents/register",
            json={"did": did, "public_key": pub_hex, "card": _minimal_card(did, pub_hex)},
        )
        challenge_id = resp.json()["challenge_id"]

        # Sign the wrong message
        wrong_sig = _sign(priv, "this is not the nonce")

        resp2 = client.post(
            "/roar/agents/challenge",
            json={"challenge_id": challenge_id, "signature": wrong_sig},
        )
        assert resp2.status_code == 401
        assert "invalid_signature" in resp2.json()["error"]

    def test_challenge_success_registers_card(self, client, hub):
        """Valid signature → agent card registered in directory."""
        priv, pub_hex = _gen_keypair()
        did = "did:roar:agent:successtest-001"
        card = _minimal_card(did, pub_hex)

        resp = client.post(
            "/roar/agents/register",
            json={"did": did, "public_key": pub_hex, "card": card},
        )
        data = resp.json()
        challenge_id = data["challenge_id"]
        nonce = data["nonce"]

        sig = _sign(priv, nonce)
        resp2 = client.post(
            "/roar/agents/challenge",
            json={"challenge_id": challenge_id, "signature": sig},
        )
        assert resp2.status_code == 200
        assert resp2.json()["registered"] is True

        # Agent must now appear in the directory
        entry = hub._directory.lookup(did)
        assert entry is not None
        assert entry.agent_card.identity.did == did


class TestDeleteEndpoint:
    def _register_agent(self, client, priv, pub_hex, did):
        """Helper: complete full challenge flow and return the DID."""
        card = _minimal_card(did, pub_hex)
        resp = client.post(
            "/roar/agents/register",
            json={"did": did, "public_key": pub_hex, "card": card},
        )
        data = resp.json()
        sig = _sign(priv, data["nonce"])
        client.post(
            "/roar/agents/challenge",
            json={"challenge_id": data["challenge_id"], "signature": sig},
        )

    def _delete(self, client, did: str, body: dict):
        """Helper: send DELETE with JSON body (TestClient.delete lacks json= kwarg)."""
        return client.request(
            "DELETE",
            f"/roar/agents/{did}",
            content=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )

    def test_delete_requires_signed_proof(self, client):
        """DELETE without signature → 400."""
        priv, pub_hex = _gen_keypair()
        did = "did:roar:agent:delnoauth-001"
        self._register_agent(client, priv, pub_hex, did)

        resp = self._delete(client, did, {"did": did})
        assert resp.status_code == 400

    def test_delete_with_stale_timestamp_rejected(self, client):
        """Timestamp > 60s old → 401."""
        priv, pub_hex = _gen_keypair()
        did = "did:roar:agent:delstale-001"
        self._register_agent(client, priv, pub_hex, did)

        nonce = "randomnonce"
        timestamp = time.time() - 120  # 2 minutes ago
        message = f"delete:{did}:{nonce}:{timestamp}"
        sig = _sign(priv, message)

        resp = self._delete(client, did, {"did": did, "signature": sig, "nonce": nonce, "timestamp": timestamp})
        assert resp.status_code == 401
        assert resp.json()["error"] == "timestamp_expired"

    def test_delete_with_valid_signature(self, client, hub):
        """Properly signed delete → agent removed."""
        priv, pub_hex = _gen_keypair()
        did = "did:roar:agent:delsuccess-001"
        self._register_agent(client, priv, pub_hex, did)

        # Verify agent exists
        assert hub._directory.lookup(did) is not None

        nonce = "mynonce123"
        timestamp = time.time()
        message = f"delete:{did}:{nonce}:{timestamp}"
        sig = _sign(priv, message)

        resp = self._delete(client, did, {"did": did, "signature": sig, "nonce": nonce, "timestamp": timestamp})
        assert resp.status_code == 200
        assert resp.json()["status"] == "removed"

        # Agent must be gone
        assert hub._directory.lookup(did) is None

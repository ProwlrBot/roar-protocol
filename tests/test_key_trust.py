# -*- coding: utf-8 -*-
"""Tests for Ed25519 key trust enforcement and key rotation."""

import time
import pytest

from roar_sdk import AgentIdentity, MessageIntent, ROARMessage
from roar_sdk.signing import generate_keypair, sign_ed25519
from roar_sdk.key_trust import KeyTrustStore, KeyMetadata, KeyTrustResult


@pytest.fixture
def store():
    return KeyTrustStore(default_max_age_hours=720, rotation_grace_hours=24)


@pytest.fixture
def keypair():
    return generate_keypair()


@pytest.fixture
def agent_a(keypair):
    _, pub = keypair
    return AgentIdentity(display_name="agent-a", public_key=pub)


@pytest.fixture
def agent_b():
    return AgentIdentity(display_name="agent-b")


# ── Key Registration ─────────────────────────────────────────────────────────

class TestKeyRegistration:
    def test_register_key(self, store, keypair):
        _, pub = keypair
        meta = store.register_key("did:roar:agent:alice", pub)
        assert meta.public_key_hex == pub
        assert meta.did == "did:roar:agent:alice"
        assert meta.source == "manual"
        assert not meta.is_expired
        assert not meta.is_rotated

    def test_register_key_with_expiry(self, store, keypair):
        _, pub = keypair
        meta = store.register_key("did:roar:agent:alice", pub, max_age_hours=1)
        assert meta.expires_at is not None
        assert meta.expires_at - meta.created_at == pytest.approx(3600, abs=1)

    def test_register_invalid_key_length(self, store):
        with pytest.raises(ValueError, match="Invalid public key length"):
            store.register_key("did:roar:agent:alice", "aabb")

    def test_register_invalid_hex(self, store):
        with pytest.raises(ValueError, match="not valid hex"):
            store.register_key("did:roar:agent:alice", "z" * 64)

    def test_get_trusted_key(self, store, keypair):
        _, pub = keypair
        store.register_key("did:roar:agent:alice", pub)
        result = store.get_trusted_key("did:roar:agent:alice")
        assert result.trusted
        assert result.key_metadata.public_key_hex == pub

    def test_no_keys_registered(self, store):
        result = store.get_trusted_key("did:roar:agent:unknown")
        assert not result.trusted
        assert "no_keys" in result.error

    def test_is_key_trusted(self, store, keypair):
        _, pub = keypair
        store.register_key("did:roar:agent:alice", pub)
        result = store.is_key_trusted("did:roar:agent:alice", pub)
        assert result.trusted

    def test_untrusted_key(self, store, keypair):
        _, pub = keypair
        store.register_key("did:roar:agent:alice", pub)
        _, other = generate_keypair()
        result = store.is_key_trusted("did:roar:agent:alice", other)
        assert not result.trusted
        assert "not_in_trust_store" in result.error


# ── Key Expiration ───────────────────────────────────────────────────────────

class TestKeyExpiration:
    def test_expired_key_rejected(self, store):
        _, pub = generate_keypair()
        meta = store.register_key("did:roar:agent:alice", pub, max_age_hours=0.0001)
        # Force expiry
        meta.expires_at = time.time() - 1
        result = store.is_key_trusted("did:roar:agent:alice", pub)
        assert not result.trusted
        assert "expired" in result.error

    def test_expired_key_not_returned_as_trusted(self, store):
        _, pub = generate_keypair()
        meta = store.register_key("did:roar:agent:alice", pub)
        meta.expires_at = time.time() - 1
        result = store.get_trusted_key("did:roar:agent:alice")
        assert not result.trusted

    def test_purge_expired(self, store):
        _, pub1 = generate_keypair()
        _, pub2 = generate_keypair()
        m1 = store.register_key("did:roar:agent:alice", pub1)
        store.register_key("did:roar:agent:bob", pub2)
        m1.expires_at = time.time() - 1  # expire alice's key
        purged = store.purge_expired()
        assert purged == 1
        assert store.get_trusted_key("did:roar:agent:bob").trusted
        assert not store.get_trusted_key("did:roar:agent:alice").trusted


# ── Key Rotation ─────────────────────────────────────────────────────────────

class TestKeyRotation:
    def test_rotate_key(self, store):
        _, pub_old = generate_keypair()
        _, pub_new = generate_keypair()

        store.register_key("did:roar:agent:alice", pub_old)
        store.rotate_key("did:roar:agent:alice", pub_new)

        # New key should be the primary trusted key
        result = store.get_trusted_key("did:roar:agent:alice")
        assert result.trusted
        assert result.key_metadata.public_key_hex == pub_new

    def test_rotated_old_key_still_valid_in_grace(self, store):
        _, pub_old = generate_keypair()
        _, pub_new = generate_keypair()

        store.register_key("did:roar:agent:alice", pub_old)
        store.rotate_key("did:roar:agent:alice", pub_new)

        # Old key should still be trusted during grace period
        result = store.is_key_trusted("did:roar:agent:alice", pub_old)
        assert result.trusted

    def test_rotated_old_key_rejected_after_grace(self, store):
        _, pub_old = generate_keypair()
        _, pub_new = generate_keypair()

        store.register_key("did:roar:agent:alice", pub_old)
        store.rotate_key("did:roar:agent:alice", pub_new)

        # Force old key past grace period
        for key in store.list_keys("did:roar:agent:alice"):
            if key.public_key_hex == pub_old:
                key.expires_at = time.time() - 1

        result = store.is_key_trusted("did:roar:agent:alice", pub_old)
        assert not result.trusted
        assert "expired" in result.error

    def test_multiple_rotations(self, store):
        _, pub1 = generate_keypair()
        _, pub2 = generate_keypair()
        _, pub3 = generate_keypair()

        store.register_key("did:roar:agent:alice", pub1)
        store.rotate_key("did:roar:agent:alice", pub2)
        store.rotate_key("did:roar:agent:alice", pub3)

        # Newest key is primary
        result = store.get_trusted_key("did:roar:agent:alice")
        assert result.key_metadata.public_key_hex == pub3

        # All 3 keys exist
        assert len(store.list_keys("did:roar:agent:alice")) == 3


# ── Message Verification with Trust Store ────────────────────────────────────

class TestMessageVerification:
    def test_verify_with_trusted_key(self, store):
        priv, pub = generate_keypair()
        sender = AgentIdentity(display_name="sender", public_key=pub)
        receiver = AgentIdentity(display_name="receiver")

        store.register_key(sender.did, pub, source="hub")

        msg = ROARMessage(
            **{"from": sender, "to": receiver},
            intent=MessageIntent.DELEGATE,
            payload={"task": "test"},
        )
        sign_ed25519(msg, priv)

        result = store.verify_message(msg)
        assert result.trusted

    def test_reject_untrusted_key(self, store):
        priv, pub = generate_keypair()
        sender = AgentIdentity(display_name="sender", public_key=pub)
        receiver = AgentIdentity(display_name="receiver")

        # Key NOT registered in trust store

        msg = ROARMessage(
            **{"from": sender, "to": receiver},
            intent=MessageIntent.DELEGATE,
            payload={"task": "test"},
        )
        sign_ed25519(msg, priv)

        result = store.verify_message(msg)
        assert not result.trusted
        assert "no_trusted_keys" in result.error

    def test_reject_wrong_key(self, store):
        priv, pub = generate_keypair()
        _, other_pub = generate_keypair()
        sender = AgentIdentity(display_name="sender", public_key=pub)
        receiver = AgentIdentity(display_name="receiver")

        # Register a DIFFERENT key for this DID
        store.register_key(sender.did, other_pub)

        msg = ROARMessage(
            **{"from": sender, "to": receiver},
            intent=MessageIntent.DELEGATE,
            payload={"task": "test"},
        )
        sign_ed25519(msg, priv)

        result = store.verify_message(msg)
        assert not result.trusted
        assert "not_valid_with_any_trusted_key" in result.error

    def test_verify_with_rotated_key_in_grace(self, store):
        """Messages signed with a recently-rotated key should still verify."""
        priv_old, pub_old = generate_keypair()
        _, pub_new = generate_keypair()
        sender = AgentIdentity(display_name="sender", public_key=pub_old)
        receiver = AgentIdentity(display_name="receiver")

        store.register_key(sender.did, pub_old)
        store.rotate_key(sender.did, pub_new)

        # Sign with the OLD key (in-flight message during rotation)
        msg = ROARMessage(
            **{"from": sender, "to": receiver},
            intent=MessageIntent.DELEGATE,
            payload={"task": "test"},
        )
        sign_ed25519(msg, priv_old)

        result = store.verify_message(msg)
        assert result.trusted  # grace period allows old key

    def test_reject_hmac_signature(self, store):
        sender = AgentIdentity(display_name="sender")
        receiver = AgentIdentity(display_name="receiver")
        msg = ROARMessage(
            **{"from": sender, "to": receiver},
            intent=MessageIntent.DELEGATE,
            payload={"task": "test"},
        )
        msg.sign("secret")  # HMAC, not Ed25519

        result = store.verify_message(msg)
        assert not result.trusted
        assert "not_ed25519" in result.error

    def test_never_trusts_auth_header_key(self, store):
        """SECURITY: The public_key in msg.auth MUST be ignored."""
        priv, pub = generate_keypair()
        sender = AgentIdentity(display_name="sender", public_key=pub)
        receiver = AgentIdentity(display_name="receiver")

        # Sign the message (this puts public_key in auth)
        msg = ROARMessage(
            **{"from": sender, "to": receiver},
            intent=MessageIntent.DELEGATE,
            payload={"task": "test"},
        )
        sign_ed25519(msg, priv)

        # Key is in msg.auth["public_key"] but NOT in the trust store
        assert msg.auth.get("public_key") == pub

        # verify_message should STILL fail — it must not use auth["public_key"]
        result = store.verify_message(msg)
        assert not result.trusted

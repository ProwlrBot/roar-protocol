# -*- coding: utf-8 -*-
"""Tests for the Agent Identity Migration Toolkit (Feature 31)."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from roar_sdk.signing import generate_keypair
from roar_sdk.types import AgentIdentity
from roar_sdk.migration import IdentityMigrator, MigrationProof


@pytest.fixture
def identity_and_key():
    """Create a test identity with a valid Ed25519 keypair."""
    priv, pub = generate_keypair()
    identity = AgentIdentity(
        display_name="test-agent",
        agent_type="agent",
        capabilities=["code", "review"],
        version="2.0",
        public_key=pub,
    )
    return identity, priv, pub


@pytest.fixture
def migrator():
    return IdentityMigrator()


# ------------------------------------------------------------------
# migrate_did_method
# ------------------------------------------------------------------


class TestMigrateDIDMethod:
    def test_creates_valid_new_identity(self, migrator, identity_and_key):
        identity, priv, pub = identity_and_key
        new_id, proof = migrator.migrate_did_method(identity, "did:key", priv)

        assert new_id.did.startswith("did:key:")
        assert new_id.public_key == pub
        assert new_id.display_name == identity.display_name
        assert new_id.agent_type == identity.agent_type

    def test_proof_is_verifiable(self, migrator, identity_and_key):
        identity, priv, pub = identity_and_key
        new_id, proof = migrator.migrate_did_method(identity, "did:key", priv)

        assert proof.old_did == identity.did
        assert proof.new_did == new_id.did
        assert proof.reason == "did_method_change"
        assert migrator.verify_migration(proof, pub)

    def test_preserves_capabilities_and_display_name(self, migrator, identity_and_key):
        identity, priv, _pub = identity_and_key
        new_id, _proof = migrator.migrate_did_method(identity, "did:key", priv)

        assert new_id.capabilities == identity.capabilities
        assert new_id.display_name == identity.display_name
        assert new_id.version == identity.version

    def test_migrate_to_did_roar(self, migrator, identity_and_key):
        identity, priv, pub = identity_and_key
        new_id, proof = migrator.migrate_did_method(identity, "did:roar", priv)

        assert new_id.did.startswith("did:roar:")
        assert migrator.verify_migration(proof, pub)

    def test_migrate_to_did_web(self, migrator, identity_and_key):
        identity, priv, pub = identity_and_key
        new_id, proof = migrator.migrate_did_method(identity, "did:web", priv)

        assert new_id.did.startswith("did:web:")
        assert migrator.verify_migration(proof, pub)

    def test_unsupported_method_raises(self, migrator, identity_and_key):
        identity, priv, _pub = identity_and_key
        with pytest.raises(ValueError, match="Unsupported DID method"):
            migrator.migrate_did_method(identity, "did:foobar", priv)


# ------------------------------------------------------------------
# rotate_keys
# ------------------------------------------------------------------


class TestRotateKeys:
    def test_generates_new_keypair(self, migrator, identity_and_key):
        identity, old_priv, old_pub = identity_and_key
        new_id, new_priv, proof = migrator.rotate_keys(identity, old_priv)

        # New key material must differ
        assert new_id.public_key != old_pub
        assert new_priv != old_priv
        # Private key is 32 bytes = 64 hex chars
        assert len(new_priv) == 64

    def test_proof_links_old_to_new(self, migrator, identity_and_key):
        identity, old_priv, old_pub = identity_and_key
        new_id, _new_priv, proof = migrator.rotate_keys(identity, old_priv)

        assert proof.old_did == identity.did
        assert proof.reason == "key_rotation"
        # Proof must be verifiable with the OLD public key
        assert migrator.verify_migration(proof, old_pub)

    def test_did_key_rotation_changes_did(self, migrator):
        """For did:key identities, the DID itself changes on key rotation."""
        from roar_sdk.did_key import DIDKeyMethod

        kid = DIDKeyMethod.generate()
        identity = AgentIdentity(
            did=kid.did,
            display_name="ephemeral",
            public_key=kid.public_hex,
        )
        new_id, _new_priv, proof = migrator.rotate_keys(identity, kid.private_hex)

        # did:key DID is derived from the key, so it must change
        assert new_id.did != identity.did
        assert new_id.did.startswith("did:key:")

    def test_did_roar_rotation_preserves_did(self, migrator, identity_and_key):
        """For did:roar identities, the DID stays the same on key rotation."""
        identity, old_priv, _pub = identity_and_key
        new_id, _new_priv, _proof = migrator.rotate_keys(identity, old_priv)
        assert new_id.did == identity.did


# ------------------------------------------------------------------
# verify_migration
# ------------------------------------------------------------------


class TestVerifyMigration:
    def test_accepts_valid_proof(self, migrator, identity_and_key):
        identity, priv, pub = identity_and_key
        _new_id, proof = migrator.migrate_did_method(identity, "did:key", priv)

        assert migrator.verify_migration(proof, pub) is True

    def test_rejects_tampered_proof(self, migrator, identity_and_key):
        identity, priv, pub = identity_and_key
        _new_id, proof = migrator.migrate_did_method(identity, "did:key", priv)

        # Tamper with the new_did
        proof.new_did = "did:key:z_tampered_value"
        assert migrator.verify_migration(proof, pub) is False

    def test_rejects_wrong_public_key(self, migrator, identity_and_key):
        identity, priv, _pub = identity_and_key
        _new_id, proof = migrator.migrate_did_method(identity, "did:key", priv)

        # Verify with a completely different key
        other_priv, other_pub = generate_keypair()
        assert migrator.verify_migration(proof, other_pub) is False

    def test_rejects_tampered_timestamp(self, migrator, identity_and_key):
        identity, priv, pub = identity_and_key
        _new_id, proof = migrator.migrate_did_method(identity, "did:key", priv)

        proof.timestamp = 0.0
        assert migrator.verify_migration(proof, pub) is False


# ------------------------------------------------------------------
# Export / Import
# ------------------------------------------------------------------


class TestExportImport:
    def test_round_trip_encrypted(self, migrator, identity_and_key):
        identity, priv, _pub = identity_and_key
        passphrase = "test-passphrase-42"

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            migrator.export_identity(identity, priv, path, passphrase=passphrase)

            # File should contain encrypted envelope
            with open(path, "r") as fp:
                data = json.load(fp)
            assert data.get("encrypted") is True

            restored_id, restored_key = migrator.import_identity(path, passphrase=passphrase)
            assert restored_id.did == identity.did
            assert restored_id.display_name == identity.display_name
            assert restored_id.capabilities == identity.capabilities
            assert restored_id.public_key == identity.public_key
            assert restored_key == priv
        finally:
            os.unlink(path)

    def test_round_trip_plaintext(self, migrator, identity_and_key):
        identity, priv, _pub = identity_and_key

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            migrator.export_identity(identity, priv, path)

            # File should be plain JSON
            with open(path, "r") as fp:
                data = json.load(fp)
            assert "encrypted" not in data
            assert data["private_key_hex"] == priv

            restored_id, restored_key = migrator.import_identity(path)
            assert restored_id.did == identity.did
            assert restored_key == priv
        finally:
            os.unlink(path)

    def test_wrong_passphrase_fails(self, migrator, identity_and_key):
        identity, priv, _pub = identity_and_key

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            migrator.export_identity(identity, priv, path, passphrase="correct")

            with pytest.raises(ValueError, match="Wrong passphrase"):
                migrator.import_identity(path, passphrase="incorrect")
        finally:
            os.unlink(path)


# ------------------------------------------------------------------
# MigrationProof serialization
# ------------------------------------------------------------------


class TestMigrationProofSerialization:
    def test_to_dict_roundtrip(self, migrator, identity_and_key):
        identity, priv, _pub = identity_and_key
        _new_id, proof = migrator.migrate_did_method(identity, "did:key", priv)

        d = proof.to_dict()
        assert isinstance(d, dict)
        assert set(d.keys()) == {"old_did", "new_did", "timestamp", "signature", "reason"}

        restored = MigrationProof.from_dict(d)
        assert restored.old_did == proof.old_did
        assert restored.new_did == proof.new_did
        assert restored.timestamp == proof.timestamp
        assert restored.signature == proof.signature
        assert restored.reason == proof.reason

    def test_json_roundtrip(self, migrator, identity_and_key):
        identity, priv, pub = identity_and_key
        _new_id, proof = migrator.migrate_did_method(identity, "did:key", priv)

        json_str = json.dumps(proof.to_dict())
        restored = MigrationProof.from_dict(json.loads(json_str))

        # The restored proof should still verify
        assert migrator.verify_migration(restored, pub)


# ------------------------------------------------------------------
# Hub transfer
# ------------------------------------------------------------------


class TestTransferToHub:
    def test_transfer_creates_proof(self, migrator, identity_and_key):
        identity, priv, pub = identity_and_key
        proof = migrator.transfer_to_hub(
            identity,
            from_hub_url="https://hub-a.example.com",
            to_hub_url="https://hub-b.example.com",
            private_key_hex=priv,
        )

        assert proof.reason == "hub_transfer"
        assert proof.old_did == identity.did
        assert "hub-b.example.com" in proof.new_did
        assert migrator.verify_migration(proof, pub)

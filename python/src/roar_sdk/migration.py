# -*- coding: utf-8 -*-
"""ROAR Protocol — Agent Identity Migration Toolkit.

Provides key rotation, DID method migration, and cross-hub transfer
utilities for ROAR agent identities.

Usage::

    from roar_sdk.migration import IdentityMigrator, MigrationProof

    migrator = IdentityMigrator()

    # Rotate keys
    new_id, new_priv, proof = migrator.rotate_keys(identity, old_private_hex)

    # Migrate DID method (e.g. did:roar -> did:key)
    new_id, proof = migrator.migrate_did_method(identity, "did:key", old_private_hex)

    # Export / import identity
    migrator.export_identity(identity, private_hex, "agent.json", passphrase="s3cret")
    restored_id, restored_key = migrator.import_identity("agent.json", passphrase="s3cret")
"""

from __future__ import annotations

import base64
import json
import os
import time
import warnings
from dataclasses import asdict, dataclass
from typing import Tuple

from .signing import generate_keypair
from .types import AgentIdentity

_MISSING_CRYPTO = (
    "Identity migration requires the 'cryptography' package. "
    "Install it: pip install 'roar-sdk[ed25519]'"
)

_VALID_REASONS = {"key_rotation", "did_method_change", "hub_transfer"}


@dataclass
class MigrationProof:
    """Cryptographic proof linking an old DID to a new DID.

    The ``signature`` is an Ed25519 signature (base64url) produced by the
    old private key over a canonical JSON body, proving the holder of the
    old identity authorised the migration.
    """

    old_did: str
    new_did: str
    timestamp: float
    signature: str  # base64url Ed25519 signed by old key
    reason: str  # key_rotation | did_method_change | hub_transfer

    def to_dict(self) -> dict:
        """Serialize to a plain dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MigrationProof":
        """Deserialize from a dictionary."""
        return cls(
            old_did=data["old_did"],
            new_did=data["new_did"],
            timestamp=data["timestamp"],
            signature=data["signature"],
            reason=data["reason"],
        )


def _migration_signing_body(old_did: str, new_did: str, timestamp: float, reason: str) -> bytes:
    """Canonical JSON body for migration proof signing."""
    body = json.dumps(
        {
            "new_did": new_did,
            "old_did": old_did,
            "reason": reason,
            "timestamp": timestamp,
        },
        sort_keys=True,
    )
    return body.encode("utf-8")


def _sign_migration(
    old_did: str,
    new_did: str,
    timestamp: float,
    reason: str,
    private_key_hex: str,
) -> str:
    """Sign a migration proof with Ed25519 and return base64url signature."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        raise ImportError(_MISSING_CRYPTO)

    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    body = _migration_signing_body(old_did, new_did, timestamp, reason)
    raw_sig = private.sign(body)
    return base64.urlsafe_b64encode(raw_sig).decode("ascii").rstrip("=")


class IdentityMigrator:
    """Toolkit for migrating ROAR agent identities.

    Supports:
    - DID method migration (e.g. did:roar -> did:key)
    - Key rotation (new keypair, same logical agent)
    - Identity export/import with optional encryption
    - Cross-hub transfer with signed proofs
    """

    # ------------------------------------------------------------------
    # DID method migration
    # ------------------------------------------------------------------

    def migrate_did_method(
        self,
        identity: AgentIdentity,
        new_method: str,
        private_key_hex: str,
    ) -> Tuple[AgentIdentity, MigrationProof]:
        """Migrate an agent identity to a different DID method.

        Creates a new identity under the target DID method while preserving
        ``display_name``, ``agent_type``, ``capabilities``, and ``version``.
        A :class:`MigrationProof` signed by the old key links the two DIDs.

        Args:
            identity: The current agent identity.
            new_method: Target DID method string (``"did:key"``, ``"did:web"``,
                ``"did:roar"``).
            private_key_hex: Hex-encoded Ed25519 private key for the current
                identity (used to sign the migration proof).

        Returns:
            A tuple of ``(new_identity, migration_proof)``.

        Raises:
            ValueError: If *new_method* is not supported.
            ImportError: If the ``cryptography`` package is not installed.
        """
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError:
            raise ImportError(_MISSING_CRYPTO)

        # Derive the public key from the private key for the new identity
        private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
        public_hex = private.public_key().public_bytes_raw().hex()

        if new_method == "did:key":
            from .did_key import DIDKeyMethod

            new_did = DIDKeyMethod._public_key_to_did(public_hex)
        elif new_method == "did:roar":
            # Generate a did:roar with the same metadata
            temp = AgentIdentity(
                display_name=identity.display_name,
                agent_type=identity.agent_type,
            )
            new_did = temp.did
        elif new_method == "did:web":
            # did:web requires a domain; use a placeholder that the caller
            # should update. We encode the agent display name in the path.
            slug = identity.display_name.lower().replace(" ", "-")[:20] or "agent"
            new_did = f"did:web:localhost:agents:{slug}"
        else:
            raise ValueError(f"Unsupported DID method: {new_method}")

        new_identity = AgentIdentity(
            did=new_did,
            display_name=identity.display_name,
            agent_type=identity.agent_type,
            capabilities=list(identity.capabilities),
            version=identity.version,
            public_key=public_hex,
        )

        ts = time.time()
        sig = _sign_migration(
            identity.did, new_did, ts, "did_method_change", private_key_hex,
        )
        proof = MigrationProof(
            old_did=identity.did,
            new_did=new_did,
            timestamp=ts,
            signature=sig,
            reason="did_method_change",
        )

        return new_identity, proof

    # ------------------------------------------------------------------
    # Key rotation
    # ------------------------------------------------------------------

    def rotate_keys(
        self,
        identity: AgentIdentity,
        old_private_key_hex: str,
    ) -> Tuple[AgentIdentity, str, MigrationProof]:
        """Rotate the Ed25519 keypair for an agent identity.

        Generates a fresh keypair, creates a new identity with the same DID
        stem but updated public key, and signs a migration proof with the
        old key.

        Args:
            identity: The current agent identity.
            old_private_key_hex: Hex-encoded old Ed25519 private key.

        Returns:
            A tuple of ``(new_identity, new_private_key_hex, migration_proof)``.
        """
        new_private_hex, new_public_hex = generate_keypair()

        # For did:key the whole DID is derived from the key, so regenerate
        if identity.did.startswith("did:key:"):
            from .did_key import DIDKeyMethod

            new_did = DIDKeyMethod._public_key_to_did(new_public_hex)
        else:
            # For did:roar and others, keep the same DID (key rotation
            # doesn't change the DID, only the public key material)
            new_did = identity.did

        new_identity = AgentIdentity(
            did=new_did,
            display_name=identity.display_name,
            agent_type=identity.agent_type,
            capabilities=list(identity.capabilities),
            version=identity.version,
            public_key=new_public_hex,
        )

        ts = time.time()
        sig = _sign_migration(
            identity.did, new_did, ts, "key_rotation", old_private_key_hex,
        )
        proof = MigrationProof(
            old_did=identity.did,
            new_did=new_did,
            timestamp=ts,
            signature=sig,
            reason="key_rotation",
        )

        return new_identity, new_private_hex, proof

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    @staticmethod
    def verify_migration(proof: MigrationProof, old_public_key_hex: str) -> bool:
        """Verify a migration proof signature.

        Args:
            proof: The migration proof to verify.
            old_public_key_hex: Hex-encoded Ed25519 public key of the old identity.

        Returns:
            ``True`` if the signature is valid; ``False`` otherwise.
        """
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            from cryptography.exceptions import InvalidSignature
        except ImportError:
            raise ImportError(_MISSING_CRYPTO)

        body = _migration_signing_body(
            proof.old_did, proof.new_did, proof.timestamp, proof.reason,
        )

        # Restore base64url padding
        b64 = proof.signature
        padding = (4 - len(b64) % 4) % 4
        raw_sig = base64.urlsafe_b64decode(b64 + "=" * padding)

        try:
            public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(old_public_key_hex))
            public.verify(raw_sig, body)
            return True
        except (InvalidSignature, ValueError):
            return False

    # ------------------------------------------------------------------
    # Export / Import
    # ------------------------------------------------------------------

    @staticmethod
    def export_identity(
        identity: AgentIdentity,
        private_key_hex: str,
        path: str,
        passphrase: str = "",
    ) -> None:
        """Export an agent identity and private key to a JSON file.

        If a *passphrase* is provided and the ``cryptography`` package is
        available, the file is encrypted with Fernet (PBKDF2 + AES).
        Otherwise, a plain-text JSON file is written (with a warning when
        a passphrase was requested but encryption is unavailable).

        Args:
            identity: The agent identity to export.
            private_key_hex: Hex-encoded Ed25519 private key.
            path: Filesystem path for the output file.
            passphrase: Optional encryption passphrase.
        """
        payload = {
            "identity": identity.model_dump(),
            "private_key_hex": private_key_hex,
            "exported_at": time.time(),
        }
        raw_json = json.dumps(payload, sort_keys=True)

        if passphrase:
            try:
                from cryptography.fernet import Fernet
                from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
                from cryptography.hazmat.primitives import hashes
            except ImportError:
                warnings.warn(
                    "cryptography package not available; exporting as plain JSON. "
                    "Install 'cryptography' for encrypted export.",
                    stacklevel=2,
                )
                with open(path, "w", encoding="utf-8") as fp:
                    fp.write(raw_json)
                return

            salt = os.urandom(16)
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=480_000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))
            fernet = Fernet(key)
            token = fernet.encrypt(raw_json.encode("utf-8"))

            envelope = {
                "encrypted": True,
                "salt": base64.urlsafe_b64encode(salt).decode("ascii"),
                "token": token.decode("ascii"),
            }
            with open(path, "w", encoding="utf-8") as fp:
                json.dump(envelope, fp)
        else:
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(raw_json)

    @staticmethod
    def import_identity(
        path: str,
        passphrase: str = "",
    ) -> Tuple[AgentIdentity, str]:
        """Import an agent identity from a JSON file.

        Args:
            path: Path to the exported JSON file.
            passphrase: Decryption passphrase (required if file is encrypted).

        Returns:
            A tuple of ``(identity, private_key_hex)``.

        Raises:
            ValueError: If the passphrase is wrong or the file is corrupted.
            ImportError: If decryption is needed but ``cryptography`` is not
                installed.
        """
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)

        if data.get("encrypted"):
            try:
                from cryptography.fernet import Fernet, InvalidToken
                from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
                from cryptography.hazmat.primitives import hashes
            except ImportError:
                raise ImportError(
                    "cryptography package required to decrypt identity file. "
                    "Install it: pip install 'roar-sdk[ed25519]'"
                )

            salt = base64.urlsafe_b64decode(data["salt"])
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=480_000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))
            fernet = Fernet(key)

            try:
                raw_json = fernet.decrypt(data["token"].encode("ascii"))
            except InvalidToken:
                raise ValueError("Wrong passphrase or corrupted identity file")

            payload = json.loads(raw_json)
        else:
            payload = data

        identity = AgentIdentity(**payload["identity"])
        return identity, payload["private_key_hex"]

    # ------------------------------------------------------------------
    # Cross-hub transfer
    # ------------------------------------------------------------------

    def transfer_to_hub(
        self,
        identity: AgentIdentity,
        from_hub_url: str,
        to_hub_url: str,
        private_key_hex: str,
    ) -> MigrationProof:
        """Transfer an agent identity between ROAR hubs.

        Creates a signed migration proof documenting the transfer from
        *from_hub_url* to *to_hub_url*. The DID remains unchanged; only
        the hub registration changes.

        In a production deployment the caller would use the proof to:
        1. Unregister from the old hub (presenting the signed proof).
        2. Register with the new hub (challenge-response using the key).

        This method generates and returns the proof; actual HTTP calls to
        hub endpoints are left to the caller or a higher-level orchestrator.

        Args:
            identity: The agent identity being transferred.
            from_hub_url: URL of the source hub.
            to_hub_url: URL of the destination hub.
            private_key_hex: Hex-encoded Ed25519 private key.

        Returns:
            A :class:`MigrationProof` with ``reason="hub_transfer"``.
        """
        ts = time.time()

        # Encode hub URLs in the new_did field as a composite reference
        transfer_ref = f"{identity.did}@{to_hub_url}"

        sig = _sign_migration(
            identity.did, transfer_ref, ts, "hub_transfer", private_key_hex,
        )

        return MigrationProof(
            old_did=identity.did,
            new_did=transfer_ref,
            timestamp=ts,
            signature=sig,
            reason="hub_transfer",
        )

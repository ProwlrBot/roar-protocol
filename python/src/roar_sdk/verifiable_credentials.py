# -*- coding: utf-8 -*-
"""ROAR Protocol — W3C Verifiable Credentials for agent capability attestation.

Implements W3C VC Data Model v1.1 for issuing and verifying capability
credentials between ROAR agents using Ed25519 signatures.

Usage::

    from roar_sdk.signing import generate_keypair
    from roar_sdk.verifiable_credentials import (
        VerifiableCredential, issue_credential, verify_credential,
        credential_to_json_ld, extract_capabilities,
    )

    priv, pub = generate_keypair()
    vc = issue_credential(
        issuer_did="did:roar:agent:issuer-abc",
        subject_did="did:roar:agent:subject-xyz",
        capabilities=["code-review", "deploy"],
        private_key_hex=priv,
    )
    assert verify_credential(vc, pub)
    caps = extract_capabilities(vc)
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from pydantic import BaseModel, Field

_MISSING = (
    "Ed25519 signing requires the 'cryptography' package. "
    "Install it: pip install 'roar-sdk[ed25519]'"
)

W3C_VC_CONTEXT = [
    "https://www.w3.org/2018/credentials/v1",
    "https://w3id.org/security/suites/ed25519-2020/v1",
]

VC_TYPE_BASE = "VerifiableCredential"
VC_TYPE_CAPABILITY = "ROARCapabilityAttestation"


class CredentialProof(BaseModel):
    """Ed25519Signature2020 proof block."""

    type: str = "Ed25519Signature2020"
    created: str = ""
    verification_method: str = ""
    signature: str = ""


class CredentialSubject(BaseModel):
    """Subject of the credential — the agent and its attested capabilities."""

    id: str = ""
    capabilities: List[str] = Field(default_factory=list)


class VerifiableCredential(BaseModel):
    """W3C Verifiable Credential for ROAR agent capability attestation."""

    id: str = ""
    type: List[str] = Field(default_factory=lambda: [VC_TYPE_BASE, VC_TYPE_CAPABILITY])
    issuer: str = ""
    issuance_date: str = ""
    expiration_date: str = ""
    credential_subject: CredentialSubject = Field(default_factory=CredentialSubject)
    proof: CredentialProof = Field(default_factory=CredentialProof)


def _canonical_payload(vc: VerifiableCredential) -> bytes:
    """Deterministic JSON representation of the credential (excluding proof)."""
    body: Dict[str, Any] = {
        "id": vc.id,
        "type": vc.type,
        "issuer": vc.issuer,
        "issuanceDate": vc.issuance_date,
        "expirationDate": vc.expiration_date,
        "credentialSubject": {
            "id": vc.credential_subject.id,
            "capabilities": vc.credential_subject.capabilities,
        },
    }
    return json.dumps(body, sort_keys=True).encode("utf-8")


def _sign_bytes(data: bytes, private_key_hex: str) -> tuple[str, str]:
    """Sign *data* with Ed25519, return (base64url_sig, public_key_hex)."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        raise ImportError(_MISSING)

    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    raw_sig = private.sign(data)
    sig_b64 = base64.urlsafe_b64encode(raw_sig).decode("ascii").rstrip("=")
    pub_hex = private.public_key().public_bytes_raw().hex()
    return sig_b64, pub_hex


def _verify_bytes(data: bytes, signature_b64: str, public_key_hex: str) -> bool:
    """Verify an Ed25519 signature over *data*."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        raise ImportError(_MISSING)

    padding = (4 - len(signature_b64) % 4) % 4
    raw_sig = base64.urlsafe_b64decode(signature_b64 + "=" * padding)

    try:
        public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        public.verify(raw_sig, data)
        return True
    except (InvalidSignature, ValueError):
        return False


def issue_credential(
    issuer_did: str,
    subject_did: str,
    capabilities: List[str],
    private_key_hex: str,
    expires_in_hours: int = 720,
) -> VerifiableCredential:
    """Issue a signed Verifiable Credential attesting agent capabilities.

    Args:
        issuer_did: DID of the issuing agent / authority.
        subject_did: DID of the agent receiving the attestation.
        capabilities: List of capability strings being attested.
        private_key_hex: 64-char hex Ed25519 private key of the issuer.
        expires_in_hours: Credential lifetime (default 30 days).

    Returns:
        A signed :class:`VerifiableCredential`.
    """
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(hours=expires_in_hours)

    vc = VerifiableCredential(
        id=f"urn:uuid:{uuid.uuid4()}",
        type=[VC_TYPE_BASE, VC_TYPE_CAPABILITY],
        issuer=issuer_did,
        issuance_date=now.isoformat(),
        expiration_date=expiry.isoformat(),
        credential_subject=CredentialSubject(
            id=subject_did,
            capabilities=list(capabilities),
        ),
    )

    sig_b64, pub_hex = _sign_bytes(_canonical_payload(vc), private_key_hex)

    vc.proof = CredentialProof(
        type="Ed25519Signature2020",
        created=now.isoformat(),
        verification_method=f"{issuer_did}#key-1",
        signature=sig_b64,
    )
    return vc


def verify_credential(credential: VerifiableCredential, public_key_hex: str) -> bool:
    """Verify a credential's signature and check that it has not expired.

    Args:
        credential: The VC to verify.
        public_key_hex: 64-char hex Ed25519 public key of the issuer.

    Returns:
        True if the signature is valid and the credential is not expired.
    """
    if not credential.proof.signature:
        return False

    # Check expiration
    try:
        expiry = datetime.fromisoformat(credential.expiration_date)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expiry:
            return False
    except (ValueError, TypeError):
        return False

    return _verify_bytes(
        _canonical_payload(credential),
        credential.proof.signature,
        public_key_hex,
    )


def credential_to_json_ld(credential: VerifiableCredential) -> Dict[str, Any]:
    """Serialize a credential to W3C JSON-LD format.

    Returns:
        A dict ready for ``json.dumps`` with ``@context`` and camelCase keys.
    """
    return {
        "@context": list(W3C_VC_CONTEXT),
        "id": credential.id,
        "type": credential.type,
        "issuer": credential.issuer,
        "issuanceDate": credential.issuance_date,
        "expirationDate": credential.expiration_date,
        "credentialSubject": {
            "id": credential.credential_subject.id,
            "capabilities": credential.credential_subject.capabilities,
        },
        "proof": {
            "type": credential.proof.type,
            "created": credential.proof.created,
            "verificationMethod": credential.proof.verification_method,
            "proofValue": credential.proof.signature,
        },
    }


def extract_capabilities(credential: VerifiableCredential) -> List[str]:
    """Extract the capabilities list from a credential's subject.

    Args:
        credential: A :class:`VerifiableCredential`.

    Returns:
        List of capability strings, or empty list if none present.
    """
    return list(credential.credential_subject.capabilities)


# ---------------------------------------------------------------------------
# Credential Revocation Registry
# ---------------------------------------------------------------------------


class RevocationRegistry:
    """In-memory credential revocation list.

    Issuers can revoke credentials by ID. Verifiers check the registry
    before trusting a credential.

    For production, back this with Redis or a database.
    """

    def __init__(self) -> None:
        self._revoked: Dict[str, str] = {}  # vc_id -> reason

    def revoke(self, credential_id: str, reason: str = "revoked") -> None:
        """Revoke a credential by its ID."""
        self._revoked[credential_id] = reason

    def is_revoked(self, credential_id: str) -> bool:
        """Check if a credential has been revoked."""
        return credential_id in self._revoked

    def get_reason(self, credential_id: str) -> str:
        """Get the revocation reason, or empty string if not revoked."""
        return self._revoked.get(credential_id, "")

    def revoked_count(self) -> int:
        return len(self._revoked)


def verify_credential_with_revocation(
    credential: VerifiableCredential,
    public_key_hex: str,
    registry: RevocationRegistry,
) -> bool:
    """Verify a credential's signature, expiration, AND revocation status.

    Args:
        credential: The VC to verify.
        public_key_hex: Issuer's public key.
        registry: Revocation registry to check against.

    Returns:
        True only if signature is valid, not expired, and not revoked.
    """
    if registry.is_revoked(credential.id):
        return False
    return verify_credential(credential, public_key_hex)


# ---------------------------------------------------------------------------
# Issuer Trust Chain
# ---------------------------------------------------------------------------


class IssuerTrustChain:
    """Registry of trusted credential issuers.

    Maps issuer DIDs to their public keys. Only credentials from
    trusted issuers pass full verification.
    """

    def __init__(self) -> None:
        self._trusted: Dict[str, str] = {}  # issuer_did -> public_key_hex

    def trust_issuer(self, issuer_did: str, public_key_hex: str) -> None:
        """Add an issuer to the trust chain."""
        self._trusted[issuer_did] = public_key_hex

    def untrust_issuer(self, issuer_did: str) -> None:
        """Remove an issuer from the trust chain."""
        self._trusted.pop(issuer_did, None)

    def is_trusted(self, issuer_did: str) -> bool:
        return issuer_did in self._trusted

    def get_public_key(self, issuer_did: str) -> str:
        """Get the public key for a trusted issuer, or empty string."""
        return self._trusted.get(issuer_did, "")

    def verify_from_chain(
        self,
        credential: VerifiableCredential,
        revocation: RevocationRegistry | None = None,
    ) -> bool:
        """Verify a credential using only the trust chain for key resolution.

        This is the recommended verification path — keys come from the
        trust chain, never from the credential itself.

        Args:
            credential: The VC to verify.
            revocation: Optional revocation registry.

        Returns:
            True if the issuer is trusted, the signature is valid,
            the credential is not expired, and (if registry provided)
            not revoked.
        """
        pub = self.get_public_key(credential.issuer)
        if not pub:
            return False
        if revocation and revocation.is_revoked(credential.id):
            return False
        return verify_credential(credential, pub)

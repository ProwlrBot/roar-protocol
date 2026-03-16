# -*- coding: utf-8 -*-
"""Tests for python/src/roar_sdk/did_resolver.py"""

import json
import pytest

from roar_sdk.did_resolver import (
    DIDResolutionError,
    _extract_ed25519_key,
    resolve_did_to_public_key,
)
from roar_sdk.did_key import DIDKeyMethod
from roar_sdk.signing import generate_keypair


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def did_key_identity():
    """A fresh did:key identity backed by a real Ed25519 keypair."""
    return DIDKeyMethod.generate()


# ---------------------------------------------------------------------------
# did:key tests
# ---------------------------------------------------------------------------

class TestResolveDidKey:
    def test_valid_did_key_resolves_to_correct_hex(self, did_key_identity):
        """A freshly generated did:key resolves back to the same public key hex."""
        result = resolve_did_to_public_key(did_key_identity.did)
        assert result == did_key_identity.public_hex

    def test_resolve_known_fixture(self):
        """Verify a known did:key against its expected public key hex.

        Key generated once and hardcoded to ensure deterministic test output.
        did:key is derived from a known 32-byte all-zeros key (for testing only).
        """
        import base58

        # Build a known key: 32 zero bytes
        raw_key = bytes(32)
        multicodec = b"\xed\x01" + raw_key
        encoded = base58.b58encode(multicodec).decode()
        did = f"did:key:z{encoded}"
        expected_hex = raw_key.hex()

        result = resolve_did_to_public_key(did)
        assert result == expected_hex

    def test_invalid_did_key_malformed_raises(self):
        """A malformed did:key raises DIDResolutionError."""
        with pytest.raises(DIDResolutionError, match="did:key"):
            resolve_did_to_public_key("did:key:NOTBASE58!!!")

    def test_invalid_did_key_wrong_prefix_raises(self):
        """A did:key without the 'z' multibase prefix raises DIDResolutionError."""
        with pytest.raises(DIDResolutionError):
            resolve_did_to_public_key("did:key:abc123")  # no 'z'

    def test_invalid_did_key_wrong_multicodec_raises(self):
        """A did:key with a non-Ed25519 multicodec prefix raises DIDResolutionError."""
        import base58

        # Use 0x1200 prefix (X25519) instead of 0xed01
        raw_key = bytes(32)
        multicodec = b"\x12\x00" + raw_key  # wrong codec
        encoded = base58.b58encode(multicodec).decode()
        did = f"did:key:z{encoded}"

        with pytest.raises(DIDResolutionError, match="Ed25519"):
            resolve_did_to_public_key(did)


# ---------------------------------------------------------------------------
# Unsupported DID method
# ---------------------------------------------------------------------------

class TestUnsupportedMethod:
    def test_did_roar_raises(self):
        """did:roar cannot be resolved without a registry."""
        with pytest.raises(DIDResolutionError, match="unsupported method"):
            resolve_did_to_public_key("did:roar:agent:alice-abc123")

    def test_did_ethr_raises(self):
        """Unknown DID methods raise DIDResolutionError."""
        with pytest.raises(DIDResolutionError, match="unsupported method"):
            resolve_did_to_public_key("did:ethr:0xabcdef1234567890")


# ---------------------------------------------------------------------------
# did:web SSRF protection
# ---------------------------------------------------------------------------

class TestDidWebSecurity:
    def test_ssrf_link_local_blocked(self):
        """did:web pointing at 169.254.x.x (AWS metadata) is rejected."""
        with pytest.raises(DIDResolutionError, match="private"):
            resolve_did_to_public_key("did:web:169.254.169.254")

    def test_ssrf_localhost_blocked(self):
        """did:web pointing at localhost is rejected."""
        with pytest.raises(DIDResolutionError, match="private"):
            resolve_did_to_public_key("did:web:localhost")

    def test_ssrf_127_0_0_1_blocked(self):
        """did:web pointing at 127.0.0.1 is rejected."""
        with pytest.raises(DIDResolutionError, match="private"):
            resolve_did_to_public_key("did:web:127.0.0.1")

    def test_http_url_rejected(self, monkeypatch):
        """A did:web that somehow produces an HTTP URL is rejected.

        did:web spec always produces https:// so we monkeypatch did_to_url
        to simulate a bug or attacker-controlled fallback.
        """
        from roar_sdk import did_web as did_web_mod

        # Monkeypatch the class method so it returns an HTTP URL
        original_did_to_url = did_web_mod.DIDWebMethod.did_to_url

        def evil_did_to_url(did: str) -> str:
            return "http://example.com/.well-known/did.json"

        monkeypatch.setattr(did_web_mod.DIDWebMethod, "did_to_url", staticmethod(evil_did_to_url))

        with pytest.raises(DIDResolutionError, match="HTTPS"):
            resolve_did_to_public_key("did:web:example.com")


# ---------------------------------------------------------------------------
# did:web success path (mocked)
# ---------------------------------------------------------------------------

class TestDidWebSuccess:
    def test_resolve_did_web_success_via_extract(self):
        """Mock a DID document and verify _extract_ed25519_key returns the right hex."""
        # Use a real keypair so the hex is plausible
        _, public_hex = generate_keypair()

        doc = {
            "@context": ["https://www.w3.org/ns/did/v1"],
            "id": "did:web:example.com",
            "verificationMethod": [
                {
                    "id": "did:web:example.com#key-1",
                    "type": "Ed25519VerificationKey2020",
                    "controller": "did:web:example.com",
                    "publicKeyHex": public_hex,
                }
            ],
        }

        result = _extract_ed25519_key(doc, "did:web:example.com")
        assert result == public_hex

    def test_resolve_did_web_jwk(self):
        """_extract_ed25519_key handles publicKeyJwk with base64url x field."""
        import base64

        _, public_hex = generate_keypair()
        key_bytes = bytes.fromhex(public_hex)
        x_b64 = base64.urlsafe_b64encode(key_bytes).rstrip(b"=").decode("ascii")

        doc = {
            "verificationMethod": [
                {
                    "type": "JsonWebKey2020",
                    "publicKeyJwk": {
                        "kty": "OKP",
                        "crv": "Ed25519",
                        "x": x_b64,
                    },
                }
            ]
        }

        result = _extract_ed25519_key(doc, "did:web:example.com")
        assert result == public_hex

    def test_resolve_did_web_multibase(self):
        """_extract_ed25519_key handles publicKeyMultibase (z-prefix base58btc)."""
        import base58

        _, public_hex = generate_keypair()
        key_bytes = bytes.fromhex(public_hex)
        multicodec = b"\xed\x01" + key_bytes
        pmb = "z" + base58.b58encode(multicodec).decode()

        doc = {
            "verificationMethod": [
                {
                    "type": "Ed25519VerificationKey2020",
                    "publicKeyMultibase": pmb,
                }
            ]
        }

        result = _extract_ed25519_key(doc, "did:web:example.com")
        assert result == public_hex

    def test_extract_no_ed25519_key_raises(self):
        """_extract_ed25519_key raises when no Ed25519 key is present."""
        doc = {
            "verificationMethod": [
                {
                    "type": "RsaVerificationKey2018",
                    "publicKeyPem": "-----BEGIN PUBLIC KEY-----...",
                }
            ]
        }
        with pytest.raises(DIDResolutionError, match="No Ed25519"):
            _extract_ed25519_key(doc, "did:web:example.com")

    def test_resolve_did_web_full_mock(self, monkeypatch):
        """End-to-end mock: monkeypatch urllib to return a DID document."""
        from roar_sdk import did_resolver as resolver_mod

        _, public_hex = generate_keypair()

        doc = {
            "@context": ["https://www.w3.org/ns/did/v1"],
            "id": "did:web:example.com",
            "verificationMethod": [
                {
                    "id": "did:web:example.com#key-1",
                    "type": "Ed25519VerificationKey2020",
                    "controller": "did:web:example.com",
                    "publicKeyHex": public_hex,
                }
            ],
        }

        class FakeResponse:
            status = 200
            def read(self, n):
                return json.dumps(doc).encode()
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        def fake_urlopen(req, timeout=None):
            return FakeResponse()

        # Monkeypatch _is_private_ip to pass the SSRF check
        monkeypatch.setattr(resolver_mod, "_is_private_ip", lambda hostname: False)

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        result = resolve_did_to_public_key("did:web:example.com")
        assert result == public_hex

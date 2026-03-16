# -*- coding: utf-8 -*-
"""Minimal DID resolver for did:key and did:web methods.

SECURITY: Resolution failures always raise, never return None silently.
Callers should catch DIDResolutionError and reject the operation.

SSRF protection: did:web URLs are restricted to HTTPS and validated
against a private-IP blocklist before fetching.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Optional

# Private IP ranges to block for SSRF protection
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / AWS metadata
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


class DIDResolutionError(Exception):
    """Raised when a DID cannot be resolved to a public key."""


def _is_private_ip(hostname: str) -> bool:
    """Return True if hostname resolves to a private/loopback IP (SSRF guard)."""
    try:
        addr = socket.getaddrinfo(hostname, None)[0][4][0]
        ip = ipaddress.ip_address(addr)
        return any(ip in net for net in _PRIVATE_NETWORKS)
    except (socket.gaierror, ValueError):
        return True  # fail closed on resolution error


def resolve_did_to_public_key(did: str, timeout: float = 5.0) -> str:
    """Resolve a DID to a hex-encoded Ed25519 public key.

    Supports:
    - did:key:z... (multibase-encoded Ed25519 key, no network fetch)
    - did:web:domain (HTTPS fetch of DID document)
    - did:roar:... (cannot be resolved without registry — raises)

    Returns: 64-char hex string (32 bytes)
    Raises: DIDResolutionError on any failure
    """
    if did.startswith("did:key:"):
        return _resolve_did_key(did)
    elif did.startswith("did:web:"):
        return _resolve_did_web(did, timeout)
    else:
        raise DIDResolutionError(
            f"Cannot resolve DID '{did}': unsupported method. "
            "Only did:key and did:web are resolvable without a registry."
        )


def _resolve_did_key(did: str) -> str:
    """Extract Ed25519 public key from did:key multibase encoding."""
    if not did.startswith("did:key:z"):
        raise DIDResolutionError(
            f"Failed to decode did:key '{did}': must start with 'did:key:z' (base58btc multibase)"
        )
    encoded = did[len("did:key:z"):]
    try:
        import base58
        key_bytes = base58.b58decode(encoded)
    except ImportError:
        raise DIDResolutionError(
            f"Failed to decode did:key '{did}': 'base58' package required. "
            "Install: pip install base58"
        )
    except Exception as e:
        raise DIDResolutionError(f"Failed to decode did:key '{did}': {e}") from e

    # Ed25519 multicodec prefix: 0xed 0x01
    if len(key_bytes) != 34 or key_bytes[0] != 0xed or key_bytes[1] != 0x01:
        raise DIDResolutionError(
            f"Failed to decode did:key '{did}': does not contain Ed25519 multicodec prefix 0xed01"
        )
    return key_bytes[2:].hex()


def _resolve_did_web(did: str, timeout: float) -> str:
    """Fetch DID document from HTTPS and extract Ed25519 verification key."""
    # Build URL per did:web spec using existing module
    from roar_sdk.did_web import DIDWebMethod
    try:
        url = DIDWebMethod.did_to_url(did)
    except Exception as e:
        raise DIDResolutionError(f"Failed to build did:web URL for '{did}': {e}") from e

    if not url.startswith("https://"):
        raise DIDResolutionError(f"did:web must resolve to HTTPS, got: {url}")

    # SSRF guard: resolve hostname and check against private ranges
    from urllib.parse import urlparse
    hostname = urlparse(url).hostname
    if not hostname or _is_private_ip(hostname):
        raise DIDResolutionError(
            f"did:web hostname '{hostname}' resolves to a private/internal address"
        )

    # Fetch DID document
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ROAR-DID-Resolver/0.3"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                raise DIDResolutionError(f"DID document fetch returned HTTP {resp.status}")
            import json
            doc = json.loads(resp.read(65536))  # 64 KiB max
    except DIDResolutionError:
        raise
    except Exception as e:
        raise DIDResolutionError(f"Failed to fetch DID document for '{did}': {e}") from e

    return _extract_ed25519_key(doc, did)


def _extract_ed25519_key(doc: dict, did: str) -> str:
    """Extract the first Ed25519 public key hex from a DID Document."""
    import base64 as _base64
    methods = doc.get("verificationMethod", [])
    for method in methods:
        # publicKeyMultibase (base58btc z-prefix)
        if pmb := method.get("publicKeyMultibase"):
            if pmb.startswith("z"):
                try:
                    import base58
                    key_bytes = base58.b58decode(pmb[1:])
                    # Ed25519 has 0xed01 prefix (2 bytes)
                    if len(key_bytes) == 34 and key_bytes[0] == 0xed and key_bytes[1] == 0x01:
                        return key_bytes[2:].hex()
                except Exception:
                    continue
        # publicKeyHex directly
        if pkh := method.get("publicKeyHex"):
            if len(pkh) == 64:
                return pkh
        # publicKeyJwk (x field = base64url-encoded key)
        if jwk := method.get("publicKeyJwk"):
            if jwk.get("crv") == "Ed25519" and (x := jwk.get("x")):
                try:
                    key_bytes = _base64.urlsafe_b64decode(x + "==")
                    if len(key_bytes) == 32:
                        return key_bytes.hex()
                except Exception:
                    continue

    raise DIDResolutionError(
        f"No Ed25519 verification method found in DID document for '{did}'"
    )

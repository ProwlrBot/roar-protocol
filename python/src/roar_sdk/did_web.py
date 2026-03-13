# -*- coding: utf-8 -*-
"""did:web method — persistent, DNS-bound agent identities.

A did:web DID is tied to a domain name, resolved via HTTPS.
The DID Document is hosted at a well-known URL derived from the DID.

Format: did:web:example.com:agents:planner
Resolves to: https://example.com/agents/planner/did.json

Ref: https://w3c-ccg.github.io/did-method-web/

Usage::

    method = DIDWebMethod()

    identity = method.create(domain="example.com", path="agents/planner")
    print(identity.did)           # did:web:example.com:agents:planner
    print(identity.document_url)  # https://example.com/agents/planner/did.json
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .did_document import DIDDocument


@dataclass
class DIDWebIdentity:
    """A persistent identity bound to a web domain.

    Attributes:
        did: The did:web string.
        domain: The hosting domain.
        path: The path within the domain.
        document_url: Where the DID Document is hosted.
    """

    did: str
    domain: str
    path: str
    document_url: str


class DIDWebMethod:
    """did:web method for persistent, DNS-bound identities."""

    @staticmethod
    def create(
        domain: str,
        path: str = "",
        port: Optional[int] = None,
    ) -> DIDWebIdentity:
        """Create a did:web identity for an agent.

        Args:
            domain: The hosting domain (e.g. "example.com").
            path: Path within the domain (e.g. "agents/planner").
            port: Optional port (encoded as domain%3A8080 in the DID).

        Returns:
            A DIDWebIdentity with the DID and document URL.
        """
        domain_part = f"{domain}%3A{port}" if port else domain
        base_url = f"https://{domain}:{port}" if port else f"https://{domain}"

        if path:
            path_parts = path.strip("/").replace("/", ":")
            did = f"did:web:{domain_part}:{path_parts}"
            document_url = f"{base_url}/{path.strip('/')}/did.json"
        else:
            did = f"did:web:{domain_part}"
            document_url = f"{base_url}/.well-known/did.json"

        return DIDWebIdentity(did=did, domain=domain, path=path, document_url=document_url)

    @staticmethod
    def did_to_url(did: str) -> str:
        """Convert a did:web to its HTTPS resolution URL.

        Args:
            did: A did:web string.

        Returns:
            The URL where the DID Document should be hosted.
        """
        if not did.startswith("did:web:"):
            raise ValueError(f"Not a did:web: {did}")

        parts = did[8:].split(":")  # strip "did:web:"
        domain = parts[0].replace("%3A", ":")

        if len(parts) == 1:
            return f"https://{domain}/.well-known/did.json"
        path = "/".join(parts[1:])
        return f"https://{domain}/{path}/did.json"

    @staticmethod
    def generate_document(
        identity: DIDWebIdentity,
        public_key: str = "",
        endpoints: Optional[Dict[str, str]] = None,
    ) -> DIDDocument:
        """Generate a DID Document ready for hosting at identity.document_url.

        Args:
            identity: The DIDWebIdentity.
            public_key: Hex-encoded Ed25519 public key.
            endpoints: Transport → URL mapping.

        Returns:
            A DIDDocument ready to serialize as did.json.
        """
        return DIDDocument.for_agent(
            did=identity.did,
            public_key=public_key,
            endpoints=endpoints,
        )

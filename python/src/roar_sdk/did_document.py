# -*- coding: utf-8 -*-
"""DID Document generation and resolution (W3C DID Core v1.0).

A DID Document describes an agent's identity, public keys, and service
endpoints. Publish this as JSON-LD at the agent's well-known URL.

Ref: https://www.w3.org/TR/did-core/

Usage::

    doc = DIDDocument.for_agent(
        did="did:roar:agent:planner-abc12345",
        display_name="planner",
        public_key="<hex-encoded-ed25519-public-key>",
        endpoints={"http": "http://localhost:8089"},
    )
    json_ld = doc.to_dict()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VerificationMethod:
    """A public key or other verification method in the DID Document."""

    id: str
    type: str  # e.g. "Ed25519VerificationKey2020", "JsonWebKey2020"
    controller: str
    public_key_multibase: str = ""


@dataclass
class ServiceEndpoint:
    """A service endpoint in the DID Document."""

    id: str
    type: str  # e.g. "ROARMessaging", "MCPToolServer"
    service_endpoint: str  # URL


@dataclass
class DIDDocument:
    """W3C DID Document for a ROAR agent.

    Usage::

        doc = DIDDocument.for_agent(
            did="did:roar:agent:planner-abc12345",
            public_key="<hex-encoded-ed25519-public-key>",
            endpoints={"http": "http://localhost:8089"},
        )
        json_ld = doc.to_dict()
    """

    id: str
    controller: str = ""
    verification_methods: List[VerificationMethod] = field(default_factory=list)
    authentication: List[str] = field(default_factory=list)
    assertion_method: List[str] = field(default_factory=list)
    services: List[ServiceEndpoint] = field(default_factory=list)
    created: float = 0.0
    updated: float = 0.0

    def __post_init__(self):
        if not self.controller:
            self.controller = self.id
        if not self.created:
            self.created = time.time()
        if not self.updated:
            self.updated = self.created

    @classmethod
    def for_agent(
        cls,
        did: str,
        display_name: str = "",
        public_key: str = "",
        endpoints: Optional[Dict[str, str]] = None,
    ) -> "DIDDocument":
        """Create a DID Document for a ROAR agent.

        Args:
            did: The agent's DID.
            display_name: Human-readable name (unused in wire format, for reference).
            public_key: Hex-encoded Ed25519 public key (optional).
            endpoints: Dict of transport → URL.

        Returns:
            A populated DIDDocument.
        """
        doc = cls(id=did)

        if public_key:
            # Encode as multibase (base16 / hex with 'f' prefix per multibase spec)
            vm = VerificationMethod(
                id=f"{did}#key-1",
                type="Ed25519VerificationKey2020",
                controller=did,
                public_key_multibase=f"f{public_key}",
            )
            doc.verification_methods.append(vm)
            doc.authentication.append(f"{did}#key-1")
            doc.assertion_method.append(f"{did}#key-1")

        if endpoints:
            for transport, url in endpoints.items():
                svc = ServiceEndpoint(
                    id=f"{did}#svc-{transport}",
                    type="ROARMessaging",
                    service_endpoint=url,
                )
                doc.services.append(svc)

        return doc

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a W3C DID Document JSON-LD structure."""
        doc: Dict[str, Any] = {
            "@context": [
                "https://www.w3.org/ns/did/v1",
                "https://w3id.org/security/suites/ed25519-2020/v1",
            ],
            "id": self.id,
            "controller": self.controller,
        }

        if self.verification_methods:
            doc["verificationMethod"] = [
                {
                    "id": vm.id,
                    "type": vm.type,
                    "controller": vm.controller,
                    "publicKeyMultibase": vm.public_key_multibase,
                }
                for vm in self.verification_methods
            ]

        if self.authentication:
            doc["authentication"] = self.authentication

        if self.assertion_method:
            doc["assertionMethod"] = self.assertion_method

        if self.services:
            doc["service"] = [
                {
                    "id": svc.id,
                    "type": svc.type,
                    "serviceEndpoint": svc.service_endpoint,
                }
                for svc in self.services
            ]

        return doc

# -*- coding: utf-8 -*-
"""ROAR Protocol — Python SDK.

Standalone implementation of the 5-layer agent communication standard.
Design: @kdairatchi — https://github.com/ProwlrBot/roar-protocol

Quick start::

    from roar_sdk import AgentIdentity, ROARMessage, MessageIntent, ROARClient, ROARServer

    # Layer 1: Identity
    identity = AgentIdentity(display_name="my-agent", capabilities=["code"])
    print(identity.did)  # did:roar:agent:my-agent-a1b2c3d4...

    # Layer 4: Exchange — build and sign a message
    msg = ROARMessage(
        **{"from": identity, "to": other_identity},
        intent=MessageIntent.DELEGATE,
        payload={"task": "review"},
    )
    msg.sign("shared-secret")

    # Layer 3: Connect — send over HTTP
    client = ROARClient(identity, signing_secret="shared-secret")
    response = await client.send_remote(
        to_agent_id=other_identity.did,
        intent=MessageIntent.DELEGATE,
        content={"task": "review"},
    )
"""

__version__ = "0.3.2"
__author__ = "kdairatchi"
__spec_version__ = "0.3.0"

from .types import (
    # Layer 1
    AgentIdentity,
    AgentCapability,
    AgentCard,
    # Layer 2
    DiscoveryEntry,
    AgentDirectory,
    # Layer 3
    TransportType,
    ConnectionConfig,
    # Layer 4
    MessageIntent,
    ROARMessage,
    # Layer 5
    StreamEventType,
    StreamEvent,
    # Adapters
    MCPAdapter,
    A2AAdapter,
)
from .client import ROARClient
from .server import ROARServer
from .streaming import EventBus, StreamFilter, Subscription
from .signing import generate_keypair, sign_ed25519, verify_ed25519, sign_agent_card, verify_agent_card
from .delegation import DelegationToken, issue_token, verify_token
from .token_store import InMemoryTokenStore, RedisTokenStore
from .adapters import ACPAdapter
from .adapters.detect import detect_protocol, ProtocolType
from .hub import ROARHub
from .registry import PublicRegistry, RegistryEntry
from .did_document import DIDDocument, VerificationMethod, ServiceEndpoint
from .did_key import DIDKeyMethod, DIDKeyIdentity
from .did_web import DIDWebMethod, DIDWebIdentity
from .sqlite_directory import SQLiteAgentDirectory
from .discovery_cache import DiscoveryCache
from .dedup import IdempotencyGuard
from .autonomy import AutonomyLevel, CapabilityDelegation, RuntimeToken
from .verifier import StrictMessageVerifier, VerificationResult
from .auth_middleware import AuthConfig, AuthStrategy, require_auth
from .tracing import Tracer, Span, inject_trace_context, extract_trace_context
from .audit import AuditLog, AuditEntry
from .workflow import TaskStatus, WorkflowTask, Workflow, WorkflowEngine, CyclicDependencyError
from .plugin import ROARPlugin, PluginManager
from .migration import IdentityMigrator, MigrationProof
from .verifiable_credentials import VerifiableCredential, issue_credential, verify_credential
from .transaction import (
    Transaction,
    sign_transaction,
    verify_transaction,
    create_purchase_authorization,
    commit_transaction,
)

__all__ = [
    # Layer 1
    "AgentIdentity",
    "AgentCapability",
    "AgentCard",
    # Layer 2
    "DiscoveryEntry",
    "AgentDirectory",
    # Layer 3
    "TransportType",
    "ConnectionConfig",
    # Layer 4
    "MessageIntent",
    "ROARMessage",
    # Layer 5
    "StreamEventType",
    "StreamEvent",
    # Adapters
    "MCPAdapter",
    "A2AAdapter",
    "ACPAdapter",
    "detect_protocol",
    "ProtocolType",
    # Client / Server / Hub
    "ROARClient",
    "ROARServer",
    "ROARHub",
    "PublicRegistry",
    "RegistryEntry",
    # Streaming
    "EventBus",
    "StreamFilter",
    "Subscription",
    # Ed25519 signing
    "generate_keypair",
    "sign_ed25519",
    "verify_ed25519",
    "sign_agent_card",
    "verify_agent_card",
    # Delegation tokens (cryptographic, portable)
    "DelegationToken",
    "issue_token",
    "verify_token",
    # DID methods
    "DIDDocument",
    "VerificationMethod",
    "ServiceEndpoint",
    "DIDKeyMethod",
    "DIDKeyIdentity",
    "DIDWebMethod",
    "DIDWebIdentity",
    # Persistent discovery
    "SQLiteAgentDirectory",
    "DiscoveryCache",
    # Autonomy model (runtime policy enforcement)
    "AutonomyLevel",
    "CapabilityDelegation",
    "RuntimeToken",
    # Deduplication
    "IdempotencyGuard",
    # Strict verification
    "StrictMessageVerifier",
    "VerificationResult",
    # Token stores
    "InMemoryTokenStore",
    "RedisTokenStore",
    # Auth middleware
    "AuthConfig",
    "AuthStrategy",
    "require_auth",
    # Tracing & Observability
    "Tracer",
    "Span",
    "inject_trace_context",
    "extract_trace_context",
    # Audit trail
    "AuditLog",
    "AuditEntry",
    # Workflow orchestration
    "TaskStatus",
    "WorkflowTask",
    "Workflow",
    "WorkflowEngine",
    "CyclicDependencyError",
    # Plugin & Extension API
    "ROARPlugin",
    "PluginManager",
    # Identity migration toolkit
    "IdentityMigrator",
    "MigrationProof",
    # Verifiable Credentials (W3C VC capability attestation)
    "VerifiableCredential",
    "issue_credential",
    "verify_credential",
    # Agentic Commerce Transaction Signing
    "Transaction",
    "sign_transaction",
    "verify_transaction",
    "create_purchase_authorization",
    "commit_transaction",
]

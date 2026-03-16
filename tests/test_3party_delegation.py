# -*- coding: utf-8 -*-
"""Tests for 3-party delegation verification in ROARServer.

These tests verify that:
1. The delegate_did bind check fires BEFORE DID resolution.
2. A 3-party delegation resolves the delegator's DID and verifies the signature.
3. DID resolution failure produces delegation_unverifiable.
4. A bad signature produces invalid_delegation_signature.
"""

import asyncio
import pytest

from roar_sdk.delegation import DelegationToken, issue_token, verify_token
from roar_sdk.did_resolver import DIDResolutionError
from roar_sdk.server import ROARServer
from roar_sdk.signing import generate_keypair
from roar_sdk.types import AgentIdentity, MessageIntent, ROARMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_identity(display_name: str, public_key: str | None = None) -> AgentIdentity:
    """Create an AgentIdentity with an optional public key."""
    return AgentIdentity(display_name=display_name, public_key=public_key)


def make_server() -> ROARServer:
    """Create a minimal ROARServer with an RESPOND handler."""
    server_identity = make_identity("test-server")
    server = ROARServer(server_identity)

    @server.on(MessageIntent.DELEGATE)
    async def handler(msg: ROARMessage) -> ROARMessage:
        return ROARMessage(
            **{"from": server_identity, "to": msg.from_identity},
            intent=MessageIntent.RESPOND,
            payload={"status": "ok"},
            context={"in_reply_to": msg.id},
        )

    return server


def make_msg(
    sender: AgentIdentity,
    server: ROARServer,
    token: DelegationToken | None = None,
) -> ROARMessage:
    """Build a ROARMessage from sender to server, optionally with a delegation token."""
    context: dict = {}
    if token:
        context["delegation_token"] = token.model_dump()
    return ROARMessage(
        **{"from": sender, "to": server.identity},
        intent=MessageIntent.DELEGATE,
        payload={"action": "test"},
        context=context,
    )


# ---------------------------------------------------------------------------
# Test: 3-party delegation resolved successfully
# ---------------------------------------------------------------------------

class Test3PartyDelegationResolved:
    def test_3party_delegation_resolved(self, monkeypatch):
        """Mock resolver returns valid key; 3-party delegation succeeds."""
        delegator_priv, delegator_pub = generate_keypair()
        _, delegate_pub = generate_keypair()

        delegator_identity = make_identity("delegator")
        delegate_identity = make_identity("delegate", public_key=delegate_pub)
        server = make_server()

        token = issue_token(
            delegator_did=delegator_identity.did,
            delegator_private_key=delegator_priv,
            delegate_did=delegate_identity.did,
            capabilities=["test"],
            expires_in_seconds=3600,
            max_uses=5,
        )

        # Mock the resolver so it returns the real delegator public key
        import roar_sdk.server as server_mod
        monkeypatch.setattr(
            server_mod,
            "resolve_did_to_public_key",
            lambda did: delegator_pub,
        )

        msg = make_msg(delegate_identity, server, token)
        response = asyncio.get_event_loop().run_until_complete(server.handle_message(msg))

        # Should reach the handler and return ok
        assert response.payload.get("status") == "ok"


# ---------------------------------------------------------------------------
# Test: DID resolution failure → delegation_unverifiable
# ---------------------------------------------------------------------------

class Test3PartyDelegationResolutionFailure:
    def test_3party_delegation_resolution_failure(self, monkeypatch):
        """Resolver raises; response contains delegation_unverifiable."""
        delegator_priv, delegator_pub = generate_keypair()
        _, delegate_pub = generate_keypair()

        delegator_identity = make_identity("delegator")
        delegate_identity = make_identity("delegate", public_key=delegate_pub)
        server = make_server()

        token = issue_token(
            delegator_did=delegator_identity.did,
            delegator_private_key=delegator_priv,
            delegate_did=delegate_identity.did,
            capabilities=["test"],
            expires_in_seconds=3600,
        )

        # Mock the resolver to always fail
        import roar_sdk.server as server_mod

        def failing_resolver(did: str) -> str:
            raise DIDResolutionError(f"Network unreachable for DID: {did}")

        monkeypatch.setattr(server_mod, "resolve_did_to_public_key", failing_resolver)

        msg = make_msg(delegate_identity, server, token)
        response = asyncio.get_event_loop().run_until_complete(server.handle_message(msg))

        assert response.payload.get("error") == "delegation_unverifiable"


# ---------------------------------------------------------------------------
# Test: resolved key, but wrong signature → invalid_delegation_signature
# ---------------------------------------------------------------------------

class Test3PartyDelegationInvalidSignature:
    def test_3party_delegation_invalid_signature(self, monkeypatch):
        """Resolver returns a key but signature doesn't match → invalid_delegation_signature."""
        delegator_priv, delegator_pub = generate_keypair()
        _, wrong_pub = generate_keypair()   # different key pair
        _, delegate_pub = generate_keypair()

        delegator_identity = make_identity("delegator")
        delegate_identity = make_identity("delegate", public_key=delegate_pub)
        server = make_server()

        token = issue_token(
            delegator_did=delegator_identity.did,
            delegator_private_key=delegator_priv,
            delegate_did=delegate_identity.did,
            capabilities=["test"],
            expires_in_seconds=3600,
        )

        # Resolver returns the WRONG public key → signature check fails
        import roar_sdk.server as server_mod
        monkeypatch.setattr(
            server_mod,
            "resolve_did_to_public_key",
            lambda did: wrong_pub,
        )

        msg = make_msg(delegate_identity, server, token)
        response = asyncio.get_event_loop().run_until_complete(server.handle_message(msg))

        assert response.payload.get("error") == "invalid_delegation_signature"


# ---------------------------------------------------------------------------
# Test: bind check fires BEFORE resolver is called
# ---------------------------------------------------------------------------

class TestBindCheckOrder:
    def test_bind_check_still_first(self, monkeypatch):
        """delegate_did check fires before resolver is called.

        If the bind check triggers, the resolver mock must NOT be called.
        """
        delegator_priv, delegator_pub = generate_keypair()
        _, delegate_pub = generate_keypair()
        _, impostor_pub = generate_keypair()

        delegator_identity = make_identity("delegator")
        delegate_identity = make_identity("delegate", public_key=delegate_pub)
        impostor_identity = make_identity("impostor", public_key=impostor_pub)
        server = make_server()

        # Token is issued to delegate_identity, not impostor_identity
        token = issue_token(
            delegator_did=delegator_identity.did,
            delegator_private_key=delegator_priv,
            delegate_did=delegate_identity.did,
            capabilities=["test"],
            expires_in_seconds=3600,
        )

        resolver_called = []

        def tracking_resolver(did: str) -> str:
            resolver_called.append(did)
            return delegator_pub

        import roar_sdk.server as server_mod
        monkeypatch.setattr(server_mod, "resolve_did_to_public_key", tracking_resolver)

        # Send the message AS the impostor (wrong sender DID)
        msg = make_msg(impostor_identity, server, token)
        response = asyncio.get_event_loop().run_until_complete(server.handle_message(msg))

        # Bind check must have fired
        assert response.payload.get("error") == "delegation_token_unauthorized"
        # Resolver must NOT have been called
        assert resolver_called == [], "Resolver was called before bind check!"

    def test_bind_check_passes_when_delegate_matches(self, monkeypatch):
        """When the delegate DID matches, the resolver IS called for 3-party."""
        delegator_priv, delegator_pub = generate_keypair()
        _, delegate_pub = generate_keypair()

        delegator_identity = make_identity("delegator")
        delegate_identity = make_identity("delegate", public_key=delegate_pub)
        server = make_server()

        token = issue_token(
            delegator_did=delegator_identity.did,
            delegator_private_key=delegator_priv,
            delegate_did=delegate_identity.did,
            capabilities=["test"],
            expires_in_seconds=3600,
        )

        resolver_called = []

        def tracking_resolver(did: str) -> str:
            resolver_called.append(did)
            return delegator_pub

        import roar_sdk.server as server_mod
        monkeypatch.setattr(server_mod, "resolve_did_to_public_key", tracking_resolver)

        msg = make_msg(delegate_identity, server, token)
        asyncio.get_event_loop().run_until_complete(server.handle_message(msg))

        # Resolver was called because delegator != delegate (3-party)
        assert resolver_called == [delegator_identity.did]


# ---------------------------------------------------------------------------
# Test: max_uses token store enforcement
# ---------------------------------------------------------------------------

class TestTokenStoreEnforcement:
    def test_token_exhausted_after_max_uses(self, monkeypatch):
        """Token is rejected after max_uses reached, even with valid signature."""
        delegator_priv, delegator_pub = generate_keypair()
        _, delegate_pub = generate_keypair()

        delegator_identity = make_identity("delegator")
        delegate_identity = make_identity("delegate", public_key=delegate_pub)
        server = make_server()

        token = issue_token(
            delegator_did=delegator_identity.did,
            delegator_private_key=delegator_priv,
            delegate_did=delegate_identity.did,
            capabilities=["test"],
            expires_in_seconds=3600,
            max_uses=2,
        )

        import roar_sdk.server as server_mod
        monkeypatch.setattr(
            server_mod,
            "resolve_did_to_public_key",
            lambda did: delegator_pub,
        )

        loop = asyncio.get_event_loop()

        # Use 1 and 2 — both succeed
        msg1 = make_msg(delegate_identity, server, token)
        r1 = loop.run_until_complete(server.handle_message(msg1))
        assert r1.payload.get("status") == "ok"

        msg2 = make_msg(delegate_identity, server, token)
        r2 = loop.run_until_complete(server.handle_message(msg2))
        assert r2.payload.get("status") == "ok"

        # Use 3 — must be rejected
        msg3 = make_msg(delegate_identity, server, token)
        r3 = loop.run_until_complete(server.handle_message(msg3))
        assert r3.payload.get("error") == "delegation_token_exhausted"

# -*- coding: utf-8 -*-
"""Tests for the ROAR Plugin & Extension API."""

from __future__ import annotations

import pytest

from roar_sdk.types import AgentCard, AgentIdentity, MessageIntent, ROARMessage
from roar_sdk.plugin import PluginManager, ROARPlugin


# ---------------------------------------------------------------------------
# Helpers — reusable identities and messages
# ---------------------------------------------------------------------------

def _make_identity(name: str = "test-agent") -> AgentIdentity:
    return AgentIdentity(display_name=name)


def _make_msg(
    payload: dict | None = None,
    intent: MessageIntent = MessageIntent.DELEGATE,
) -> ROARMessage:
    sender = _make_identity("sender")
    receiver = _make_identity("receiver")
    return ROARMessage(
        **{"from": sender, "to": receiver},
        intent=intent,
        payload=payload or {"task": "test"},
    )


# ---------------------------------------------------------------------------
# Concrete plugin implementations for testing
# ---------------------------------------------------------------------------

class TagPlugin(ROARPlugin):
    """Adds a 'tagged' key to message payloads."""

    name = "tagger"
    version = "1.0.0"

    def __init__(self, tag: str = "tagged") -> None:
        self.tag = tag
        self.loaded_server: object | None = None
        self.unloaded = False
        self.errors: list[tuple[Exception, ROARMessage | None]] = []
        self.registered_cards: list[AgentCard] = []

    def on_load(self, server: object) -> None:
        self.loaded_server = server

    def on_unload(self) -> None:
        self.unloaded = True

    def on_message_received(self, msg: ROARMessage) -> ROARMessage:
        new_payload = {**msg.payload, self.tag: True}
        return msg.model_copy(update={"payload": new_payload})

    def on_message_sent(self, msg: ROARMessage) -> ROARMessage:
        new_payload = {**msg.payload, f"{self.tag}_sent": True}
        return msg.model_copy(update={"payload": new_payload})

    def on_agent_registered(self, card: AgentCard) -> None:
        self.registered_cards.append(card)

    def on_error(self, error: Exception, msg: ROARMessage | None = None) -> None:
        self.errors.append((error, msg))


class RejectPlugin(ROARPlugin):
    """Rejects all messages by returning None."""

    name = "rejector"
    version = "0.0.1"

    def on_message_received(self, msg: ROARMessage) -> None:
        return None


class OrderPlugin(ROARPlugin):
    """Records the order in which hooks fire."""

    def __init__(self, name: str, order_list: list[str]) -> None:
        self.name = name  # type: ignore[assignment]
        self.version = "1.0.0"
        self._order_list = order_list

    def on_message_received(self, msg: ROARMessage) -> ROARMessage:
        self._order_list.append(self.name)
        return msg


# ---------------------------------------------------------------------------
# Tests — registration / unregistration
# ---------------------------------------------------------------------------

class TestPluginRegistration:
    def test_register_and_list(self) -> None:
        mgr = PluginManager()
        p = TagPlugin()
        mgr.register(p)
        assert mgr.list_plugins() == [p]

    def test_register_duplicate_raises(self) -> None:
        mgr = PluginManager()
        mgr.register(TagPlugin("a"))
        with pytest.raises(ValueError, match="already registered"):
            mgr.register(TagPlugin("b"))  # same name "tagger"

    def test_unregister_removes_plugin(self) -> None:
        mgr = PluginManager()
        p = TagPlugin()
        mgr.register(p)
        mgr.unregister("tagger")
        assert mgr.list_plugins() == []
        assert p.unloaded is True

    def test_unregister_unknown_raises(self) -> None:
        mgr = PluginManager()
        with pytest.raises(KeyError, match="no-such"):
            mgr.unregister("no-such")

    def test_list_plugins_returns_all(self) -> None:
        mgr = PluginManager()
        p1 = TagPlugin("x")
        p1.name = "plugin-a"
        p2 = TagPlugin("y")
        p2.name = "plugin-b"
        mgr.register(p1)
        mgr.register(p2)
        assert mgr.list_plugins() == [p1, p2]


# ---------------------------------------------------------------------------
# Tests — message hooks
# ---------------------------------------------------------------------------

class TestMessageHooks:
    def test_on_message_received_modifies_message(self) -> None:
        mgr = PluginManager()
        mgr.register(TagPlugin("marked"))
        msg = _make_msg()
        result = mgr.run_hook("on_message_received", msg)
        assert result is not None
        assert result.payload["marked"] is True
        # Original payload preserved
        assert result.payload["task"] == "test"

    def test_on_message_sent_modifies_response(self) -> None:
        mgr = PluginManager()
        mgr.register(TagPlugin("resp"))
        msg = _make_msg()
        result = mgr.run_hook("on_message_sent", msg)
        assert result is not None
        assert result.payload["resp_sent"] is True

    def test_reject_plugin_returns_none(self) -> None:
        mgr = PluginManager()
        mgr.register(RejectPlugin())
        msg = _make_msg()
        result = mgr.run_hook("on_message_received", msg)
        assert result is None

    def test_reject_short_circuits_pipeline(self) -> None:
        """If a plugin rejects, subsequent plugins never run."""
        mgr = PluginManager()
        mgr.register(RejectPlugin())
        tag = TagPlugin()
        tag.name = "after-reject"
        mgr.register(tag)
        msg = _make_msg()
        result = mgr.run_hook("on_message_received", msg)
        assert result is None

    def test_no_plugins_returns_input_unchanged(self) -> None:
        mgr = PluginManager()
        msg = _make_msg()
        result = mgr.run_hook("on_message_received", msg)
        assert result is not None
        assert result.id == msg.id
        assert result.payload == msg.payload


# ---------------------------------------------------------------------------
# Tests — plugin ordering
# ---------------------------------------------------------------------------

class TestPluginOrdering:
    def test_first_registered_runs_first(self) -> None:
        order: list[str] = []
        mgr = PluginManager()
        mgr.register(OrderPlugin("alpha", order))
        mgr.register(OrderPlugin("beta", order))
        mgr.register(OrderPlugin("gamma", order))
        mgr.run_hook("on_message_received", _make_msg())
        assert order == ["alpha", "beta", "gamma"]


# ---------------------------------------------------------------------------
# Tests — error hook
# ---------------------------------------------------------------------------

class TestErrorHook:
    def test_on_error_called(self) -> None:
        mgr = PluginManager()
        p = TagPlugin()
        mgr.register(p)
        err = RuntimeError("boom")
        msg = _make_msg()
        mgr.run_hook("on_error", err, msg)
        assert len(p.errors) == 1
        assert p.errors[0] == (err, msg)

    def test_on_error_without_message(self) -> None:
        mgr = PluginManager()
        p = TagPlugin()
        mgr.register(p)
        err = ValueError("oops")
        mgr.run_hook("on_error", err)
        assert len(p.errors) == 1
        assert p.errors[0] == (err, None)


# ---------------------------------------------------------------------------
# Tests — agent registration hook
# ---------------------------------------------------------------------------

class TestAgentRegisteredHook:
    def test_on_agent_registered(self) -> None:
        mgr = PluginManager()
        p = TagPlugin()
        mgr.register(p)
        card = AgentCard(identity=_make_identity("new-agent"))
        mgr.run_hook("on_agent_registered", card)
        assert p.registered_cards == [card]


# ---------------------------------------------------------------------------
# Tests — extension points: transports
# ---------------------------------------------------------------------------

class TestRegisterTransport:
    def test_register_and_get_transport(self) -> None:
        mgr = PluginManager()

        class WebSocketTransport:
            pass

        mgr.register_transport("websocket", WebSocketTransport)
        assert mgr.get_transport("websocket") is WebSocketTransport
        assert "websocket" in mgr.list_transports()

    def test_get_unknown_transport_returns_none(self) -> None:
        mgr = PluginManager()
        assert mgr.get_transport("quic") is None


# ---------------------------------------------------------------------------
# Tests — extension points: adapters
# ---------------------------------------------------------------------------

class TestRegisterAdapter:
    def test_register_and_get_adapter(self) -> None:
        mgr = PluginManager()

        class CustomRPCAdapter:
            pass

        mgr.register_adapter("custom-rpc", CustomRPCAdapter)
        assert mgr.get_adapter("custom-rpc") is CustomRPCAdapter
        assert "custom-rpc" in mgr.list_adapters()

    def test_get_unknown_adapter_returns_none(self) -> None:
        mgr = PluginManager()
        assert mgr.get_adapter("nope") is None


# ---------------------------------------------------------------------------
# Tests — extension points: auth strategies
# ---------------------------------------------------------------------------

class TestRegisterAuthStrategy:
    def test_register_and_get_auth(self) -> None:
        mgr = PluginManager()

        def api_key_auth(msg: ROARMessage) -> bool:
            return msg.context.get("api_key") == "secret"

        mgr.register_auth_strategy("api-key", api_key_auth)
        assert mgr.get_auth_strategy("api-key") is api_key_auth
        assert "api-key" in mgr.list_auth_strategies()


# ---------------------------------------------------------------------------
# Tests — extension points: discovery backends
# ---------------------------------------------------------------------------

class TestRegisterDiscoveryBackend:
    def test_register_and_get_backend(self) -> None:
        mgr = PluginManager()

        class ConsulBackend:
            pass

        mgr.register_discovery_backend("consul", ConsulBackend)
        assert mgr.get_discovery_backend("consul") is ConsulBackend
        assert "consul" in mgr.list_discovery_backends()


# ---------------------------------------------------------------------------
# Tests — server integration (install)
# ---------------------------------------------------------------------------

class TestInstall:
    def test_install_calls_on_load(self) -> None:
        mgr = PluginManager()
        p = TagPlugin()
        mgr.register(p)
        sentinel = object()
        mgr.install(sentinel)
        assert p.loaded_server is sentinel

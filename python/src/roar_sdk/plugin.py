# -*- coding: utf-8 -*-
"""ROAR Protocol — Plugin & Extension API.

A lightweight plugin system that lets developers extend ROAR servers
without modifying core code.  Plugins hook into the message lifecycle
and can register custom transports, adapters, auth strategies, and
discovery backends.

Usage::

    from roar_sdk.plugin import ROARPlugin, PluginManager

    class LoggingPlugin(ROARPlugin):
        name = "logging"
        version = "1.0.0"

        def on_message_received(self, msg):
            print(f"[LOG] received {msg.id}")
            return msg

    manager = PluginManager()
    manager.register(LoggingPlugin())

    # Integrate with a ROARServer:
    server = ROARServer(identity=...)
    manager.install(server)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Type

from .types import AgentCard, ROARMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base plugin class
# ---------------------------------------------------------------------------

class ROARPlugin:
    """Base class for ROAR plugins.

    Subclass this and override any hooks you need.  All hooks have safe
    default implementations so you only override what you care about.
    """

    name: str = "unnamed-plugin"
    version: str = "0.1.0"

    # -- lifecycle hooks ----------------------------------------------------

    def on_load(self, server: Any) -> None:
        """Called when the plugin is installed into a server."""

    def on_unload(self) -> None:
        """Called when the plugin is unregistered."""

    # -- message hooks ------------------------------------------------------

    def on_message_received(self, msg: ROARMessage) -> Optional[ROARMessage]:
        """Called before message dispatch.

        Return the (possibly modified) message to continue processing,
        or ``None`` to reject / swallow the message.
        """
        return msg

    def on_message_sent(self, msg: ROARMessage) -> Optional[ROARMessage]:
        """Called after a response is generated, before it is sent.

        Return the (possibly modified) response, or ``None`` to suppress.
        """
        return msg

    # -- registration hooks -------------------------------------------------

    def on_agent_registered(self, card: AgentCard) -> None:
        """Called when an agent registers with the hub."""

    # -- error hook ---------------------------------------------------------

    def on_error(self, error: Exception, msg: Optional[ROARMessage] = None) -> None:
        """Called on processing errors."""


# ---------------------------------------------------------------------------
# Plugin manager
# ---------------------------------------------------------------------------

class PluginManager:
    """Manages plugin registration, ordering, and hook dispatch.

    Plugins execute in *registration order* — the first plugin registered
    is the first to run for every hook.
    """

    def __init__(self) -> None:
        self._plugins: List[ROARPlugin] = []
        self._plugins_by_name: Dict[str, ROARPlugin] = {}

        # Extension registries
        self._transports: Dict[str, Type[Any]] = {}
        self._adapters: Dict[str, Type[Any]] = {}
        self._auth_strategies: Dict[str, Callable[..., Any]] = {}
        self._discovery_backends: Dict[str, Type[Any]] = {}

    # -- plugin lifecycle ---------------------------------------------------

    def register(self, plugin: ROARPlugin) -> None:
        """Register a plugin.

        Raises ``ValueError`` if a plugin with the same name is already
        registered.
        """
        if plugin.name in self._plugins_by_name:
            raise ValueError(
                f"A plugin named '{plugin.name}' is already registered."
            )
        self._plugins.append(plugin)
        self._plugins_by_name[plugin.name] = plugin
        logger.info("Plugin registered: %s v%s", plugin.name, plugin.version)

    def unregister(self, name: str) -> None:
        """Remove a previously registered plugin by name.

        Calls the plugin's ``on_unload`` hook before removal.
        Raises ``KeyError`` if no such plugin exists.
        """
        plugin = self._plugins_by_name.pop(name, None)
        if plugin is None:
            raise KeyError(f"No plugin named '{name}' is registered.")
        self._plugins.remove(plugin)
        plugin.on_unload()
        logger.info("Plugin unregistered: %s", name)

    def list_plugins(self) -> List[ROARPlugin]:
        """Return all registered plugins in registration order."""
        return list(self._plugins)

    # -- hook dispatch ------------------------------------------------------

    def run_hook(self, hook_name: str, *args: Any, **kwargs: Any) -> Any:
        """Execute a named hook across all registered plugins.

        For message hooks (``on_message_received``, ``on_message_sent``),
        the first positional argument is the message; each plugin receives
        the output of the previous plugin (pipeline style).  If any plugin
        returns ``None``, the pipeline short-circuits and ``None`` is
        returned.

        For other hooks the return value is a list of individual results
        (one per plugin).
        """
        pipeline_hooks = {"on_message_received", "on_message_sent"}

        if hook_name in pipeline_hooks:
            return self._run_pipeline_hook(hook_name, *args, **kwargs)
        return self._run_broadcast_hook(hook_name, *args, **kwargs)

    def _run_pipeline_hook(
        self, hook_name: str, *args: Any, **kwargs: Any
    ) -> Optional[ROARMessage]:
        """Run a pipeline hook where each plugin transforms the message."""
        if not args:
            return None
        current: Optional[ROARMessage] = args[0]
        remaining_args = args[1:]
        for plugin in self._plugins:
            if current is None:
                return None
            hook = getattr(plugin, hook_name, None)
            if hook is not None:
                current = hook(current, *remaining_args, **kwargs)
        return current

    def _run_broadcast_hook(
        self, hook_name: str, *args: Any, **kwargs: Any
    ) -> List[Any]:
        """Run a broadcast hook and collect results."""
        results: List[Any] = []
        for plugin in self._plugins:
            hook = getattr(plugin, hook_name, None)
            if hook is not None:
                results.append(hook(*args, **kwargs))
        return results

    # -- extension point registries -----------------------------------------

    def register_transport(self, name: str, transport_class: Type[Any]) -> None:
        """Register a custom transport implementation.

        Args:
            name: Transport identifier (e.g. ``"websocket"``, ``"quic"``).
            transport_class: The class implementing the transport.
        """
        self._transports[name] = transport_class
        logger.info("Custom transport registered: %s", name)

    def get_transport(self, name: str) -> Optional[Type[Any]]:
        """Look up a registered transport by name."""
        return self._transports.get(name)

    def list_transports(self) -> Dict[str, Type[Any]]:
        """Return all registered transports."""
        return dict(self._transports)

    def register_adapter(self, protocol_type: str, adapter_class: Type[Any]) -> None:
        """Register a custom protocol adapter.

        Args:
            protocol_type: Protocol identifier (e.g. ``"custom-rpc"``).
            adapter_class: The adapter class with ``to_roar`` / ``from_roar``
                methods.
        """
        self._adapters[protocol_type] = adapter_class
        logger.info("Custom adapter registered: %s", protocol_type)

    def get_adapter(self, protocol_type: str) -> Optional[Type[Any]]:
        """Look up a registered adapter by protocol type."""
        return self._adapters.get(protocol_type)

    def list_adapters(self) -> Dict[str, Type[Any]]:
        """Return all registered adapters."""
        return dict(self._adapters)

    def register_auth_strategy(self, name: str, auth_fn: Callable[..., Any]) -> None:
        """Register a custom authentication strategy.

        Args:
            name: Strategy identifier (e.g. ``"oauth2"``, ``"api-key"``).
            auth_fn: A callable that performs authentication.  It should
                accept a ROARMessage and return ``True`` / ``False``.
        """
        self._auth_strategies[name] = auth_fn
        logger.info("Custom auth strategy registered: %s", name)

    def get_auth_strategy(self, name: str) -> Optional[Callable[..., Any]]:
        """Look up a registered auth strategy by name."""
        return self._auth_strategies.get(name)

    def list_auth_strategies(self) -> Dict[str, Callable[..., Any]]:
        """Return all registered auth strategies."""
        return dict(self._auth_strategies)

    def register_discovery_backend(
        self, name: str, backend_class: Type[Any]
    ) -> None:
        """Register a custom discovery backend.

        Args:
            name: Backend identifier (e.g. ``"consul"``, ``"etcd"``).
            backend_class: The class implementing the discovery backend.
        """
        self._discovery_backends[name] = backend_class
        logger.info("Custom discovery backend registered: %s", name)

    def get_discovery_backend(self, name: str) -> Optional[Type[Any]]:
        """Look up a registered discovery backend by name."""
        return self._discovery_backends.get(name)

    def list_discovery_backends(self) -> Dict[str, Type[Any]]:
        """Return all registered discovery backends."""
        return dict(self._discovery_backends)

    # -- server integration -------------------------------------------------

    def install(self, server: Any) -> None:
        """Install all registered plugins into a ROARServer.

        Calls ``on_load(server)`` on each plugin.
        """
        for plugin in self._plugins:
            plugin.on_load(server)
        logger.info(
            "Installed %d plugin(s) into server", len(self._plugins)
        )

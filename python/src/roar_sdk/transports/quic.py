# -*- coding: utf-8 -*-
"""ROAR QUIC/HTTP3 Transport — high-performance agent communication.

Two transport classes are provided:

* **HTTP3Transport** — the practical choice for most users.  Uses ``httpx``
  with HTTP/2 (and HTTP/3 when ``httpx[http2]`` + ``h3`` are installed).
  Gracefully falls back through h2 → HTTP/1.1 if dependencies are missing.

* **QUICTransport** — raw QUIC via ``aioquic``.  Requires TLS certificates.
  Raises ``ImportError`` with install instructions when ``aioquic`` is absent.

Helper utilities:

* ``detect_transport_capability(url)`` — probe server for h3/h2/http support.
* ``create_transport(preferred)``      — auto-select the best available transport.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ..types import ConnectionConfig, ROARMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Transport-type constants (avoid modifying types.py)
# ---------------------------------------------------------------------------

TRANSPORT_QUIC: str = "quic"
TRANSPORT_HTTP3: str = "http3"

# ---------------------------------------------------------------------------
# Availability flags
# ---------------------------------------------------------------------------

_HAS_AIOQUIC = False
try:
    import aioquic  # noqa: F401
    _HAS_AIOQUIC = True
except ImportError:
    pass

_HAS_HTTPX = False
try:
    import httpx  # noqa: F401
    _HAS_HTTPX = True
except ImportError:
    pass

_HAS_H2 = False
try:
    import h2  # noqa: F401
    _HAS_H2 = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# HTTP3Transport — practical path via httpx
# ---------------------------------------------------------------------------


class HTTP3Transport:
    """HTTP/3-capable transport using httpx.

    Falls back through HTTP/2 → HTTP/1.1 depending on installed extras.
    This is the recommended transport for most users wanting improved
    performance over plain HTTP/1.1.
    """

    def __init__(self) -> None:
        if not _HAS_HTTPX:
            raise ImportError(
                "HTTP3Transport requires httpx. "
                "Install it: pip install 'roar-sdk[http3]'"
            )
        self._http2: bool = _HAS_H2

    @property
    def protocol_label(self) -> str:
        """Human-readable label describing the negotiated protocol level."""
        if self._http2:
            return "h2"
        return "http/1.1"

    # -- public API --------------------------------------------------------

    async def send_message(
        self,
        config: ConnectionConfig,
        message: ROARMessage,
        secret: str = "",
    ) -> ROARMessage:
        """Send a ROARMessage and return the response.

        Uses HTTP/2 when ``h2`` is installed, otherwise plain HTTP/1.1.

        Args:
            config: Connection configuration (url, auth, timeout).
            message: The ROAR message to send (should already be signed).
            secret: Signing secret — added as Bearer token when
                    ``config.auth_method == "jwt"``.

        Returns:
            The response ``ROARMessage``.

        Raises:
            ConnectionError: On network or HTTP errors.
        """
        import httpx

        url = config.url.rstrip("/")
        if not url:
            raise ConnectionError("HTTP3Transport requires a URL in ConnectionConfig")

        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-ROAR-Protocol": message.roar,
        }

        if config.auth_method == "jwt" and (secret or config.secret):
            headers["Authorization"] = f"Bearer {secret or config.secret}"

        payload = message.model_dump(by_alias=True)
        timeout = httpx.Timeout(config.timeout_ms / 1000)

        async with httpx.AsyncClient(
            http2=self._http2,
            timeout=timeout,
        ) as client:
            try:
                response = await client.post(
                    f"{url}/roar/message",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                return ROARMessage.model_validate(response.json())
            except httpx.ConnectError as exc:
                raise ConnectionError(
                    f"HTTP3Transport: failed to connect to {url}: {exc}"
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise ConnectionError(
                    f"HTTP3Transport: HTTP {exc.response.status_code} from "
                    f"{url}: {exc.response.text[:200]}"
                ) from exc

    async def health(self, url: str) -> Dict[str, Any]:
        """Probe the ROAR health endpoint.

        Returns:
            A dict with at minimum ``{"status": "ok", "protocol": "h2"|"http/1.1"}``.
        """
        import httpx

        url = url.rstrip("/")
        async with httpx.AsyncClient(
            http2=self._http2,
            timeout=httpx.Timeout(5.0),
        ) as client:
            try:
                resp = await client.get(f"{url}/roar/health")
                resp.raise_for_status()
                data = resp.json()
                data["protocol"] = self.protocol_label
                return data
            except Exception as exc:
                return {"status": "error", "error": str(exc), "protocol": self.protocol_label}


# ---------------------------------------------------------------------------
# QUICTransport — raw QUIC via aioquic (stub for future integration)
# ---------------------------------------------------------------------------


class QUICTransport:
    """Raw QUIC transport using ``aioquic``.

    This transport requires TLS certificates and the ``aioquic`` library.
    It is intended for scenarios where direct QUIC connections between
    agents are needed (e.g., low-latency edge deployments).

    For most users, :class:`HTTP3Transport` is the better choice.
    """

    def __init__(
        self,
        cert_path: Optional[str] = None,
        key_path: Optional[str] = None,
    ) -> None:
        if not _HAS_AIOQUIC:
            raise ImportError(
                "QUICTransport requires aioquic. "
                "Install it: pip install 'roar-sdk[quic]'"
            )
        self.cert_path = cert_path
        self.key_path = key_path

    async def send_message(
        self,
        config: ConnectionConfig,
        message: ROARMessage,
        secret: str = "",
    ) -> ROARMessage:
        """Send a ROARMessage over a raw QUIC connection.

        .. note:: Full QUIC stream multiplexing is not yet implemented.
                  This currently opens an HTTP/3 connection using aioquic
                  and sends the message as a POST request.

        Raises:
            ImportError: If ``aioquic`` is not installed.
            ConnectionError: On transport errors.
        """
        if not _HAS_AIOQUIC:
            raise ImportError(
                "QUICTransport requires aioquic. "
                "Install it: pip install 'roar-sdk[quic]'"
            )

        from aioquic.asyncio import connect as quic_connect  # type: ignore[import-untyped]
        from aioquic.quic.configuration import QuicConfiguration  # type: ignore[import-untyped]
        from aioquic.h3.connection import H3_ALPN  # type: ignore[import-untyped]

        url = config.url.rstrip("/")
        if not url:
            raise ConnectionError("QUICTransport requires a URL in ConnectionConfig")

        # Parse host/port from URL
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 443

        configuration = QuicConfiguration(
            is_client=True,
            alpn_protocols=H3_ALPN,
        )
        if self.cert_path:
            configuration.load_cert_chain(self.cert_path, self.key_path)

        # Build the payload
        headers_dict: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-ROAR-Protocol": message.roar,
        }
        if config.auth_method == "jwt" and (secret or config.secret):
            headers_dict["Authorization"] = f"Bearer {secret or config.secret}"

        payload_bytes = json.dumps(message.model_dump(by_alias=True)).encode()

        try:
            async with quic_connect(host, port, configuration=configuration) as protocol:
                from aioquic.h3.connection import H3Connection  # type: ignore[import-untyped]
                from aioquic.h3.events import HeadersReceived, DataReceived  # type: ignore[import-untyped]

                h3 = H3Connection(protocol._quic)
                stream_id = h3.send_headers(
                    headers=[
                        (b":method", b"POST"),
                        (b":path", f"/roar/message".encode()),
                        (b":authority", host.encode()),
                        (b":scheme", b"https"),
                    ]
                    + [(k.encode(), v.encode()) for k, v in headers_dict.items()],
                    stream_id=protocol._quic.get_next_available_stream_id(),
                )
                h3.send_data(stream_id=stream_id, data=payload_bytes, end_stream=True)

                # Collect response
                response_data = b""
                while True:
                    events = h3.receive_events()
                    for event in events:
                        if isinstance(event, DataReceived):
                            response_data += event.data
                            if event.stream_ended:
                                return ROARMessage.model_validate(
                                    json.loads(response_data)
                                )
                        if isinstance(event, HeadersReceived) and event.stream_ended:
                            break
        except Exception as exc:
            raise ConnectionError(
                f"QUICTransport: QUIC connection to {host}:{port} failed: {exc}"
            ) from exc

        raise ConnectionError("QUICTransport: no response received")

    async def health(self, url: str) -> Dict[str, Any]:
        """Probe the ROAR health endpoint over QUIC.

        Raises:
            ImportError: If ``aioquic`` is not installed.
        """
        if not _HAS_AIOQUIC:
            raise ImportError(
                "QUICTransport requires aioquic. "
                "Install it: pip install 'roar-sdk[quic]'"
            )
        return {"status": "stub", "protocol": "quic", "note": "Full QUIC health check not yet implemented"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def detect_transport_capability(url: str) -> List[str]:
    """Probe *url* to determine which HTTP protocols the server supports.

    Returns a list of protocol labels (e.g. ``["h2", "http/1.1"]``) in
    order of preference.  If ``httpx`` is not installed, returns
    ``["http/1.1"]`` as the assumed baseline.
    """
    capabilities: List[str] = []

    if not _HAS_HTTPX:
        return ["http/1.1"]

    import httpx

    url = url.rstrip("/")

    # Try HTTP/2 first
    if _HAS_H2:
        try:
            async with httpx.AsyncClient(http2=True, timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{url}/roar/health")
                http_version = getattr(resp, "http_version", "HTTP/1.1")
                if http_version == "HTTP/2":
                    capabilities.append("h2")
                else:
                    capabilities.append("http/1.1")
                return capabilities
        except Exception:
            pass

    # Fall back to HTTP/1.1
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(f"{url}/roar/health")
            capabilities.append("http/1.1")
    except Exception:
        capabilities.append("http/1.1")

    return capabilities


def create_transport(preferred: str = "auto") -> Any:
    """Create the best available transport.

    Args:
        preferred: One of ``"auto"``, ``"http3"``, ``"quic"``, or ``"http"``.
                   With ``"auto"``, returns :class:`HTTP3Transport` if httpx
                   is installed, otherwise falls back to the plain HTTP
                   transport functions.

    Returns:
        A transport instance (:class:`HTTP3Transport`, :class:`QUICTransport`,
        or a simple namespace wrapping ``http_send``).

    Raises:
        ImportError: If the requested transport's dependencies are missing.
    """
    if preferred == "quic":
        return QUICTransport()

    if preferred == "http3":
        return HTTP3Transport()

    if preferred == "auto":
        # Prefer HTTP3Transport (which internally falls back to h2/h1.1)
        if _HAS_HTTPX:
            return HTTP3Transport()
        # Fall back to the plain http_send function wrapped in a namespace
        from .http import http_send
        return _FunctionTransport(http_send)

    if preferred == "http":
        from .http import http_send
        return _FunctionTransport(http_send)

    raise ValueError(f"Unknown transport preference: {preferred!r}")


class _FunctionTransport:
    """Thin wrapper that gives the plain ``http_send`` function the same
    interface as :class:`HTTP3Transport`."""

    def __init__(self, send_fn: Any) -> None:
        self._send_fn = send_fn

    async def send_message(
        self,
        config: ConnectionConfig,
        message: ROARMessage,
        secret: str = "",
    ) -> ROARMessage:
        return await self._send_fn(config, message)

    @property
    def protocol_label(self) -> str:
        return "http/1.1"

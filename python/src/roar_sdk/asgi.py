# -*- coding: utf-8 -*-
"""ROAR Protocol — ASGI entrypoint for production deployment.

Usage with Gunicorn:
    gunicorn roar_sdk.asgi:app --worker-class uvicorn.workers.UvicornWorker

Environment variables:
    ROAR_SIGNING_SECRET  — HMAC signing secret (required for message verification)
    ROAR_REDIS_URL       — Redis URL for token store (optional, falls back to in-memory)
    ROAR_ALLOWED_ORIGINS — Comma-separated CORS origins (optional)
    ROAR_HOST_NAME       — Display name for this agent (default: "roar-server")
    ROAR_HOST_PORT       — Port for endpoint URLs in AgentCard (default: 8000)
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .router import create_roar_router
from .server import ROARServer
from .types import AgentIdentity
from .verifier import StrictMessageVerifier
from .dedup import IdempotencyGuard

logger = logging.getLogger(__name__)

# Build the ASGI app
_display_name = os.getenv("ROAR_HOST_NAME", "roar-server")
_port = int(os.getenv("ROAR_HOST_PORT", "8000"))
_signing_secret = os.getenv("ROAR_SIGNING_SECRET", "")

_identity = AgentIdentity(display_name=_display_name)
_server = ROARServer(
    _identity,
    port=_port,
    signing_secret=_signing_secret,
)

# StrictMessageVerifier (if signing is configured)
_strict_verifier = None
if _signing_secret:
    _strict_verifier = StrictMessageVerifier(
        hmac_secret=_signing_secret,
        replay_guard=IdempotencyGuard(max_keys=10_000, ttl_seconds=600.0),
    )

app = FastAPI(title=f"ROAR Agent: {_display_name}")

# CORS middleware — reads ROAR_ALLOWED_ORIGINS
_origins = [
    o.strip()
    for o in os.getenv("ROAR_ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

# Prometheus metrics (optional)
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")
except ImportError:
    pass

# Mount the ROAR router
app.include_router(
    create_roar_router(
        _server,
        strict_verifier=_strict_verifier,
    )
)

logger.info("ROAR ASGI app initialized: %s", _display_name)

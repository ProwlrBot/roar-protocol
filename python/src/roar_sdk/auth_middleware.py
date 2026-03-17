# -*- coding: utf-8 -*-
"""ROAR Protocol — Configurable API authentication middleware.

Provides pluggable auth strategies for FastAPI routes: API key,
JWT bearer (optional PyJWT), and challenge-response (already in hub).

Usage::

    from roar_sdk.auth_middleware import AuthConfig, AuthStrategy, require_auth
    from fastapi import Depends

    config = AuthConfig(strategy=AuthStrategy.API_KEY, api_keys=["my-key"])
    app.include_router(router, dependencies=[Depends(require_auth(config))])

Requires: pip install 'roar-sdk[server]'
"""

import enum
import hmac as _hmac
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)

_MISSING_FASTAPI = (
    "Auth middleware requires FastAPI. Install with: pip install 'roar-sdk[server]'"
)


class AuthStrategy(str, enum.Enum):
    """Supported authentication strategies."""
    API_KEY = "api_key"
    JWT_BEARER = "jwt_bearer"
    CHALLENGE_RESPONSE = "challenge_response"
    NONE = "none"


@dataclass
class AuthConfig:
    """Configuration for API authentication.

    Args:
        strategy: Which auth method to enforce.
        api_keys: Accepted API keys (for API_KEY strategy).
        jwt_secret: HMAC secret for JWT verification (for JWT_BEARER strategy).
        allow_unauthenticated: If True, log a warning but allow requests through.
    """
    strategy: AuthStrategy = AuthStrategy.API_KEY
    api_keys: List[str] = field(default_factory=list)
    jwt_secret: str = ""
    allow_unauthenticated: bool = False


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    """Extract the token from an Authorization: Bearer <token> header."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization[7:].strip()


def _extract_api_key(request: Any) -> Optional[str]:
    """Extract API key from Authorization header or X-API-Key header."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return request.headers.get("x-api-key")


def _verify_api_key(key: str, valid_keys: List[str]) -> bool:
    """Constant-time comparison against all valid API keys."""
    return any(_hmac.compare_digest(key, valid) for valid in valid_keys)


def _verify_jwt(token: str, secret: str) -> bool:
    """Verify a JWT token. Requires PyJWT (optional dependency)."""
    try:
        import jwt  # type: ignore[import]
    except ImportError:
        logger.error("JWT auth requires PyJWT: pip install PyJWT")
        return False
    try:
        jwt.decode(token, secret, algorithms=["HS256"])
        return True
    except jwt.InvalidTokenError:
        return False


def require_auth(config: AuthConfig) -> Callable:
    """Create a FastAPI dependency that enforces authentication.

    Requires: pip install 'roar-sdk[server]'

    Args:
        config: Auth configuration specifying strategy and credentials.

    Returns:
        A FastAPI dependency function.
    """
    try:
        from fastapi import HTTPException, Request
    except ImportError:
        raise ImportError(_MISSING_FASTAPI)

    async def _auth_dependency(request: Request) -> None:
        # Skip auth for NONE strategy
        if config.strategy == AuthStrategy.NONE:
            if config.allow_unauthenticated:
                logger.warning(
                    "AUTH DISABLED: request to %s allowed without authentication. "
                    "Do not use in production!",
                    request.url.path,
                )
            return

        # Skip auth for challenge-response endpoints (they ARE the auth)
        if config.strategy == AuthStrategy.CHALLENGE_RESPONSE:
            path = request.url.path
            if path.endswith("/register") or path.endswith("/challenge"):
                return

        # API Key auth
        if config.strategy == AuthStrategy.API_KEY:
            key = _extract_api_key(request)
            if key and _verify_api_key(key, config.api_keys):
                return
            if config.allow_unauthenticated:
                logger.warning(
                    "AUTH WARNING: unauthenticated request to %s (dev mode)",
                    request.url.path,
                )
                return
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing API key. "
                       "Provide via Authorization: Bearer <key> or X-API-Key header.",
            )

        # JWT Bearer auth
        if config.strategy == AuthStrategy.JWT_BEARER:
            token = _extract_bearer(request.headers.get("authorization"))
            if token and _verify_jwt(token, config.jwt_secret):
                return
            if config.allow_unauthenticated:
                logger.warning(
                    "AUTH WARNING: unauthenticated request to %s (dev mode)",
                    request.url.path,
                )
                return
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing JWT bearer token.",
            )

        # Challenge-response: non-challenge endpoints need a signed proof
        if config.strategy == AuthStrategy.CHALLENGE_RESPONSE:
            if config.allow_unauthenticated:
                logger.warning(
                    "AUTH WARNING: unauthenticated request to %s (dev mode)",
                    request.url.path,
                )
                return
            raise HTTPException(
                status_code=401,
                detail="Authentication required.",
            )

    return _auth_dependency

"""Tests for API authentication middleware."""

import pytest

from roar_sdk.auth_middleware import AuthConfig, AuthStrategy, require_auth

# Use httpx + FastAPI TestClient pattern
try:
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not _HAS_FASTAPI, reason="fastapi not installed")

API_KEY = "test-roar-api-key-2026"


def _make_app(config: AuthConfig) -> "TestClient":
    """Create a minimal FastAPI app with auth middleware."""
    app = FastAPI()
    auth = require_auth(config)

    @app.get("/roar/health")
    async def health():
        return {"status": "ok"}

    @app.get("/roar/message", dependencies=[Depends(auth)])
    async def message():
        return {"received": True}

    @app.get("/roar/agents", dependencies=[Depends(auth)])
    async def agents():
        return {"agents": []}

    return TestClient(app)


class TestApiKeyAuth:
    def test_unauthenticated_returns_401(self):
        client = _make_app(AuthConfig(strategy=AuthStrategy.API_KEY, api_keys=[API_KEY]))
        resp = client.get("/roar/message")
        assert resp.status_code == 401

    def test_valid_api_key_bearer(self):
        client = _make_app(AuthConfig(strategy=AuthStrategy.API_KEY, api_keys=[API_KEY]))
        resp = client.get(
            "/roar/message",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        assert resp.status_code == 200

    def test_valid_api_key_header(self):
        client = _make_app(AuthConfig(strategy=AuthStrategy.API_KEY, api_keys=[API_KEY]))
        resp = client.get(
            "/roar/message",
            headers={"X-API-Key": API_KEY},
        )
        assert resp.status_code == 200

    def test_invalid_api_key_returns_401(self):
        client = _make_app(AuthConfig(strategy=AuthStrategy.API_KEY, api_keys=[API_KEY]))
        resp = client.get(
            "/roar/message",
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401

    def test_dev_mode_allows_unauthenticated(self):
        client = _make_app(
            AuthConfig(
                strategy=AuthStrategy.API_KEY,
                api_keys=[API_KEY],
                allow_unauthenticated=True,
            )
        )
        resp = client.get("/roar/message")
        assert resp.status_code == 200

    def test_multiple_api_keys(self):
        client = _make_app(
            AuthConfig(strategy=AuthStrategy.API_KEY, api_keys=[API_KEY, "second-key"])
        )
        resp = client.get(
            "/roar/message",
            headers={"Authorization": "Bearer second-key"},
        )
        assert resp.status_code == 200


class TestNoAuth:
    def test_none_strategy_allows_all(self):
        client = _make_app(AuthConfig(strategy=AuthStrategy.NONE))
        resp = client.get("/roar/message")
        assert resp.status_code == 200

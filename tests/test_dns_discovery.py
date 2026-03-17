# -*- coding: utf-8 -*-
"""Tests for DNS-based discovery and well-known endpoint."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from roar_sdk.well_known import ROARWellKnown, AgentSummary
from roar_sdk.dns_discovery import (
    SRVRecord,
    ROARDNSResult,
    _parse_txt_records,
    resolve_srv,
    resolve_txt,
    discover_hub,
    discover_agents_dns,
)


# ── Well-Known Model Tests ───────────────────────────────────────────────────

class TestROARWellKnown:
    def test_basic_model(self):
        wk = ROARWellKnown(hub_url="https://hub.example.com")
        assert wk.hub_url == "https://hub.example.com"
        assert wk.protocol == "roar/1.0"
        assert wk.agents == []

    def test_with_agents(self):
        wk = ROARWellKnown(
            hub_url="https://hub.example.com",
            agents=[
                AgentSummary(did="did:roar:agent:test", display_name="test", capabilities=["code"]),
            ],
        )
        assert len(wk.agents) == 1
        assert wk.agents[0].display_name == "test"
        assert "code" in wk.agents[0].capabilities

    def test_federation_flag(self):
        wk = ROARWellKnown(hub_url="https://hub.example.com", federation_enabled=True)
        assert wk.federation_enabled is True

    def test_model_dump(self):
        wk = ROARWellKnown(hub_url="https://hub.example.com", version="2.0")
        d = wk.model_dump()
        assert d["hub_url"] == "https://hub.example.com"
        assert d["version"] == "2.0"

    def test_model_validate(self):
        data = {"hub_url": "https://x.com", "agents": [{"did": "did:roar:a", "capabilities": ["test"]}]}
        wk = ROARWellKnown.model_validate(data)
        assert wk.hub_url == "https://x.com"
        assert wk.agents[0].did == "did:roar:a"


# ── TXT Record Parsing ──────────────────────────────────────────────────────

class TestTXTParsing:
    def test_basic_kv(self):
        result = _parse_txt_records(["v=roar1 caps=code,test"])
        assert result["v"] == "roar1"
        assert result["caps"] == "code,test"

    def test_quoted_values(self):
        result = _parse_txt_records(['"v=roar1" "fed=true"'])
        assert result["v"] == "roar1"
        assert result["fed"] == "true"

    def test_empty(self):
        assert _parse_txt_records([]) == {}

    def test_no_equals(self):
        result = _parse_txt_records(["noequals"])
        assert result == {}


# ── SRV Resolution ───────────────────────────────────────────────────────────

class TestSRVResolution:
    def test_no_dnspython(self):
        """Without dnspython, resolve_srv returns empty."""
        with patch.dict("sys.modules", {"dns": None, "dns.resolver": None}):
            result = resolve_srv("example.com")
            assert result == []

    def test_srv_record_dataclass(self):
        rec = SRVRecord(priority=10, weight=0, port=8090, target="hub.example.com")
        assert rec.port == 8090
        assert rec.target == "hub.example.com"


# ── Discovery Fallback Chain ────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_dns_cache():
    """Clear DNS cache between tests."""
    import roar_sdk.dns_discovery as dd
    dd._dns_cache.clear()
    dd._dns_cache_ts.clear()


class TestDiscoverHub:
    @pytest.mark.asyncio
    async def test_manual_fallback(self):
        """When DNS and well-known fail, manual URL is used."""
        with patch("roar_sdk.dns_discovery.resolve_srv", return_value=[]):
            with patch("roar_sdk.dns_discovery.fetch_well_known", new_callable=AsyncMock, return_value=None):
                result = await discover_hub("example.com", manual_url="http://localhost:8090")
                assert result is not None
                assert result.hub_url == "http://localhost:8090"
                assert result.source == "manual"

    @pytest.mark.asyncio
    async def test_well_known_fallback(self):
        """When DNS fails but well-known succeeds."""
        wk = ROARWellKnown(hub_url="https://hub.example.com")
        with patch("roar_sdk.dns_discovery.resolve_srv", return_value=[]):
            with patch("roar_sdk.dns_discovery.fetch_well_known", new_callable=AsyncMock, return_value=wk):
                result = await discover_hub("example.com")
                assert result is not None
                assert result.hub_url == "https://hub.example.com"
                assert result.source == "well-known"

    @pytest.mark.asyncio
    async def test_dns_srv_preferred(self):
        """DNS SRV takes priority over well-known."""
        srv = [SRVRecord(priority=10, weight=0, port=8090, target="hub.example.com")]
        with patch("roar_sdk.dns_discovery.resolve_srv", return_value=srv):
            with patch("roar_sdk.dns_discovery.resolve_txt", return_value={"v": "roar1"}):
                result = await discover_hub("example.com")
                assert result is not None
                assert result.hub_url == "https://hub.example.com:8090"
                assert result.source == "dns"
                assert result.txt_metadata["v"] == "roar1"

    @pytest.mark.asyncio
    async def test_all_fail(self):
        """When everything fails, returns None."""
        with patch("roar_sdk.dns_discovery.resolve_srv", return_value=[]):
            with patch("roar_sdk.dns_discovery.fetch_well_known", new_callable=AsyncMock, return_value=None):
                result = await discover_hub("example.com")
                assert result is None


class TestDiscoverAgents:
    @pytest.mark.asyncio
    async def test_agents_from_well_known(self):
        wk = ROARWellKnown(
            hub_url="https://hub.example.com",
            agents=[AgentSummary(did="did:roar:a", capabilities=["code"])],
        )
        with patch("roar_sdk.dns_discovery.discover_hub", new_callable=AsyncMock) as mock:
            mock.return_value = ROARDNSResult(domain="example.com", hub_url="https://hub.example.com", well_known=wk, source="well-known")
            agents = await discover_agents_dns("example.com", capability="code")
            assert len(agents) == 1
            assert agents[0]["did"] == "did:roar:a"

    @pytest.mark.asyncio
    async def test_no_hub_returns_empty(self):
        with patch("roar_sdk.dns_discovery.discover_hub", new_callable=AsyncMock, return_value=None):
            agents = await discover_agents_dns("example.com")
            assert agents == []

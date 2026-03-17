# -*- coding: utf-8 -*-
"""Tests for DNS-based discovery with multi-standard support.

Tests cover:
  - DNS-AID (SVCB) record generation
  - Zone file generation
  - did:web DID Document generation (W3C format)
  - ANP JSON-LD description generation
  - Multi-strategy discovery resolver with mock HTTP responses
  - Backwards-compatible SRV/TXT resolution
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from roar_sdk.well_known import ROARWellKnown, AgentSummary
from roar_sdk.types import AgentCard, AgentIdentity, AgentCapability
from roar_sdk.dns_discovery import (
    SRVRecord,
    ROARDNSResult,
    _parse_txt_records,
    resolve_srv,
    resolve_txt,
    discover_hub,
    discover_agents_dns,
    generate_svcb_record,
    generate_zone_file,
    generate_did_document,
    generate_anp_description,
    resolve_agents_from_dns,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_agent_card():
    return AgentCard(
        identity=AgentIdentity(
            did="did:roar:agent:planner-abc123",
            display_name="planner",
            agent_type="agent",
            capabilities=["code-review", "testing"],
            version="1.0",
        ),
        description="An agent that reviews code and runs tests",
        skills=["code-review", "testing"],
        channels=["http", "websocket"],
        endpoints={"http": "https://agent.example.com/planner"},
        declared_capabilities=[
            AgentCapability(
                name="code-review",
                description="Reviews code for quality and bugs",
                input_schema={"type": "object", "properties": {"code": {"type": "string"}}},
                output_schema={"type": "object", "properties": {"review": {"type": "string"}}},
            ),
            AgentCapability(
                name="testing",
                description="Runs tests on code",
            ),
        ],
    )


@pytest.fixture
def sample_agent_cards(sample_agent_card):
    second = AgentCard(
        identity=AgentIdentity(
            did="did:roar:agent:deployer-def456",
            display_name="deployer",
            agent_type="agent",
            capabilities=["deploy", "rollback"],
        ),
        description="Deploys applications",
        skills=["deploy"],
        endpoints={"http": "https://agent.example.com/deployer"},
    )
    return [sample_agent_card, second]


@pytest.fixture(autouse=True)
def clear_dns_cache():
    """Clear DNS cache between tests."""
    import roar_sdk.dns_discovery as dd
    dd._dns_cache.clear()
    dd._dns_cache_ts.clear()


# ═══════════════════════════════════════════════════════════════════════════
# 1. DNS-AID (SVCB) record generation
# ═══════════════════════════════════════════════════════════════════════════


class TestSVCBGeneration:
    def test_basic_svcb_record(self):
        record = generate_svcb_record("https://hub.example.com", "example.com")
        assert "_agents.example.com." in record
        assert "SVCB" in record
        assert "hub.example.com." in record
        assert 'alpn="h2,h3"' in record

    def test_svcb_with_port(self):
        record = generate_svcb_record("https://hub.example.com:8090", "example.com")
        assert 'port="8090"' in record
        assert "hub.example.com." in record

    def test_svcb_http_scheme(self):
        record = generate_svcb_record("http://hub.example.com:9000", "example.com")
        assert 'alpn="h2"' in record
        assert 'port="9000"' in record

    def test_svcb_default_no_port(self):
        record = generate_svcb_record("https://hub.example.com", "example.com")
        assert "port=" not in record

    def test_svcb_record_format(self):
        record = generate_svcb_record("https://hub.example.com:443", "example.com")
        parts = record.split()
        assert parts[0] == "_agents.example.com."
        assert parts[1] == "3600"
        assert parts[2] == "IN"
        assert parts[3] == "SVCB"
        assert parts[4] == "1"
        assert parts[5] == "hub.example.com."


# ═══════════════════════════════════════════════════════════════════════════
# 2. Zone file generation
# ═══════════════════════════════════════════════════════════════════════════


class TestZoneFileGeneration:
    def test_basic_zone_file(self):
        zone = generate_zone_file("example.com", "https://hub.example.com:8090")
        assert "_agents.example.com." in zone
        assert "_roar._tcp.example.com." in zone
        assert "SVCB" in zone
        assert "SRV" in zone
        assert "TXT" in zone
        assert "hub.example.com" in zone

    def test_zone_file_with_agents(self, sample_agent_cards):
        zone = generate_zone_file("example.com", "https://hub.example.com", sample_agent_cards)
        assert "Agents: 2" in zone
        assert "code-review" in zone
        assert "deploy" in zone
        # Per-agent TXT records
        assert "planner._agents.example.com." in zone
        assert "deployer._agents.example.com." in zone
        assert "did=did:roar:agent:planner-abc123" in zone

    def test_zone_file_aggregate_capabilities(self, sample_agent_cards):
        zone = generate_zone_file("example.com", "https://hub.example.com", sample_agent_cards)
        # The agents TXT record should have aggregated capabilities
        lines = zone.split("\n")
        agents_txt = [l for l in lines if l.startswith("_agents.") and "TXT" in l]
        assert len(agents_txt) >= 1
        txt_line = agents_txt[0]
        assert "caps=" in txt_line

    def test_zone_file_no_agents(self):
        zone = generate_zone_file("example.com", "https://hub.example.com")
        assert "Agents: 0" in zone
        assert "Per-agent TXT" not in zone

    def test_zone_file_contains_legacy_srv(self):
        zone = generate_zone_file("example.com", "https://hub.example.com:8090")
        assert "SRV 10 0 8090 hub.example.com." in zone

    def test_zone_file_contains_version(self):
        zone = generate_zone_file("example.com", "https://hub.example.com")
        assert '"v=roar1"' in zone


# ═══════════════════════════════════════════════════════════════════════════
# 3. did:web DID Document generation (W3C format)
# ═══════════════════════════════════════════════════════════════════════════


class TestDIDDocumentGeneration:
    def test_basic_did_document(self):
        doc = generate_did_document("https://hub.example.com")
        assert "@context" in doc
        assert "https://www.w3.org/ns/did/v1" in doc["@context"]
        assert doc["id"].startswith("did:web:")
        assert "example.com" in doc["id"]

    def test_did_document_has_hub_service(self):
        doc = generate_did_document("https://hub.example.com")
        services = doc.get("service", [])
        hub_svc = [s for s in services if "roar-hub" in s.get("id", "")]
        assert len(hub_svc) == 1
        assert hub_svc[0]["serviceEndpoint"] == "https://hub.example.com"
        assert hub_svc[0]["type"] == "ROARMessaging"

    def test_did_document_has_agents_service(self):
        doc = generate_did_document("https://hub.example.com")
        services = doc.get("service", [])
        agents_svc = [s for s in services if "roar-agents" in s.get("id", "")]
        assert len(agents_svc) == 1
        assert agents_svc[0]["serviceEndpoint"] == "https://hub.example.com/roar/agents"

    def test_did_document_with_agents(self, sample_agent_cards):
        doc = generate_did_document("https://hub.example.com", sample_agent_cards)
        services = doc.get("service", [])
        agent_svcs = [s for s in services if s.get("type") == "ROARAgent"]
        assert len(agent_svcs) == 2
        # Check that agent services have capabilities
        planner_svc = [s for s in agent_svcs if "planner" in s.get("id", "")]
        assert len(planner_svc) == 1
        assert "code-review" in planner_svc[0]["capabilities"]

    def test_did_document_with_public_key(self):
        doc = generate_did_document(
            "https://hub.example.com",
            public_key="abcdef1234567890",
        )
        assert "verificationMethod" in doc
        vm = doc["verificationMethod"][0]
        assert vm["type"] == "Ed25519VerificationKey2020"
        assert vm["publicKeyMultibase"] == "fabcdef1234567890"

    def test_did_document_explicit_domain(self):
        doc = generate_did_document(
            "https://hub.example.com",
            domain="custom.example.org",
        )
        assert "custom.example.org" in doc["id"]

    def test_did_document_w3c_context(self):
        doc = generate_did_document("https://hub.example.com")
        ctx = doc["@context"]
        assert isinstance(ctx, list)
        assert "https://www.w3.org/ns/did/v1" in ctx

    def test_did_document_controller(self):
        doc = generate_did_document("https://hub.example.com")
        assert doc["controller"] == doc["id"]


# ═══════════════════════════════════════════════════════════════════════════
# 4. ANP JSON-LD description generation
# ═══════════════════════════════════════════════════════════════════════════


class TestANPDescription:
    def test_basic_anp_description(self, sample_agent_card):
        desc = generate_anp_description(sample_agent_card, "https://hub.example.com")
        assert "@context" in desc
        assert "@type" in desc
        assert desc["@id"] == "did:roar:agent:planner-abc123"
        assert desc["name"] == "planner"

    def test_anp_has_skills(self, sample_agent_card):
        desc = generate_anp_description(sample_agent_card, "https://hub.example.com")
        skills = desc["skills"]
        assert len(skills) == 2
        skill_names = [s["name"] for s in skills]
        assert "code-review" in skill_names
        assert "testing" in skill_names

    def test_anp_skill_schemas(self, sample_agent_card):
        desc = generate_anp_description(sample_agent_card, "https://hub.example.com")
        code_review = [s for s in desc["skills"] if s["name"] == "code-review"][0]
        assert "inputSchema" in code_review
        assert code_review["inputSchema"]["type"] == "object"
        assert "description" in code_review

    def test_anp_has_endpoints(self, sample_agent_card):
        desc = generate_anp_description(sample_agent_card, "https://hub.example.com")
        endpoints = desc["endpoints"]
        assert len(endpoints) >= 2  # agent endpoint + roar hub endpoint
        protocols = [ep["protocol"] for ep in endpoints]
        assert "http" in protocols
        assert "roar" in protocols

    def test_anp_roar_endpoint(self, sample_agent_card):
        desc = generate_anp_description(sample_agent_card, "https://hub.example.com")
        roar_ep = [ep for ep in desc["endpoints"] if ep["protocol"] == "roar"][0]
        assert "hub.example.com/roar/agents/did:roar:agent:planner-abc123" in roar_ep["url"]

    def test_anp_protocols_supported(self, sample_agent_card):
        desc = generate_anp_description(sample_agent_card, "https://hub.example.com")
        assert "roar/1.0" in desc["protocolsSupported"]
        assert "http" in desc["protocolsSupported"]
        assert "websocket" in desc["protocolsSupported"]

    def test_anp_registered_hub(self, sample_agent_card):
        desc = generate_anp_description(sample_agent_card, "https://hub.example.com")
        assert desc["registeredHub"] == "https://hub.example.com"

    def test_anp_json_ld_context(self, sample_agent_card):
        desc = generate_anp_description(sample_agent_card, "https://hub.example.com")
        ctx = desc["@context"]
        assert isinstance(ctx, list)
        assert "https://www.w3.org/ns/activitystreams" in ctx

    def test_anp_summary_from_description(self, sample_agent_card):
        desc = generate_anp_description(sample_agent_card, "https://hub.example.com")
        assert desc["summary"] == "An agent that reviews code and runs tests"

    def test_anp_fallback_capabilities(self):
        """When no declared_capabilities, falls back to string capabilities."""
        card = AgentCard(
            identity=AgentIdentity(
                did="did:roar:agent:simple-001",
                display_name="simple",
                capabilities=["search", "summarize"],
            ),
        )
        desc = generate_anp_description(card, "https://hub.example.com")
        skills = desc["skills"]
        assert len(skills) == 2
        assert skills[0]["name"] == "search"

    def test_anp_version(self, sample_agent_card):
        desc = generate_anp_description(sample_agent_card, "https://hub.example.com")
        assert desc["version"] == "1.0"

    def test_anp_metadata(self):
        card = AgentCard(
            identity=AgentIdentity(
                did="did:roar:agent:meta-001",
                display_name="meta-agent",
            ),
            metadata={"custom_key": "custom_value"},
        )
        desc = generate_anp_description(card, "https://hub.example.com")
        assert desc["metadata"] == {"custom_key": "custom_value"}


# ═══════════════════════════════════════════════════════════════════════════
# 5. Discovery resolver with mock HTTP responses
# ═══════════════════════════════════════════════════════════════════════════


class TestDiscoverHub:
    @pytest.mark.asyncio
    async def test_manual_fallback(self):
        """When DNS and well-known fail, manual URL is used."""
        with patch("roar_sdk.dns_discovery.resolve_srv", return_value=[]):
            with patch("roar_sdk.dns_discovery.resolve_agents_from_dns", return_value=None):
                with patch("roar_sdk.dns_discovery.fetch_well_known", new_callable=AsyncMock, return_value=None):
                    with patch("roar_sdk.dns_discovery._try_did_web_discovery", new_callable=AsyncMock, return_value=None):
                        with patch("roar_sdk.dns_discovery._try_anp_discovery", new_callable=AsyncMock, return_value=None):
                            result = await discover_hub("example.com", manual_url="http://localhost:8090")
                            assert result is not None
                            assert result.hub_url == "http://localhost:8090"
                            assert result.source == "manual"

    @pytest.mark.asyncio
    async def test_well_known_fallback(self):
        """When DNS fails but well-known succeeds."""
        wk = ROARWellKnown(hub_url="https://hub.example.com")
        with patch("roar_sdk.dns_discovery.resolve_srv", return_value=[]):
            with patch("roar_sdk.dns_discovery.resolve_agents_from_dns", return_value=None):
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
    async def test_dns_aid_preferred_over_well_known(self):
        """DNS-AID TXT at _agents.{domain} takes priority over well-known."""
        with patch("roar_sdk.dns_discovery.resolve_srv", return_value=[]):
            with patch("roar_sdk.dns_discovery.resolve_agents_from_dns", return_value="https://hub.example.com:9090"):
                result = await discover_hub("example.com")
                assert result is not None
                assert result.hub_url == "https://hub.example.com:9090"
                assert result.source == "dns-aid"

    @pytest.mark.asyncio
    async def test_did_web_discovery(self):
        """did:web fallback when well-known fails."""
        with patch("roar_sdk.dns_discovery.resolve_srv", return_value=[]):
            with patch("roar_sdk.dns_discovery.resolve_agents_from_dns", return_value=None):
                with patch("roar_sdk.dns_discovery.fetch_well_known", new_callable=AsyncMock, return_value=None):
                    with patch("roar_sdk.dns_discovery._try_did_web_discovery", new_callable=AsyncMock, return_value="https://hub.example.com"):
                        result = await discover_hub("example.com")
                        assert result is not None
                        assert result.hub_url == "https://hub.example.com"
                        assert result.source == "did-web"

    @pytest.mark.asyncio
    async def test_anp_discovery(self):
        """ANP fallback when did:web fails."""
        with patch("roar_sdk.dns_discovery.resolve_srv", return_value=[]):
            with patch("roar_sdk.dns_discovery.resolve_agents_from_dns", return_value=None):
                with patch("roar_sdk.dns_discovery.fetch_well_known", new_callable=AsyncMock, return_value=None):
                    with patch("roar_sdk.dns_discovery._try_did_web_discovery", new_callable=AsyncMock, return_value=None):
                        with patch("roar_sdk.dns_discovery._try_anp_discovery", new_callable=AsyncMock, return_value="https://hub.example.com"):
                            result = await discover_hub("example.com")
                            assert result is not None
                            assert result.hub_url == "https://hub.example.com"
                            assert result.source == "anp"

    @pytest.mark.asyncio
    async def test_all_fail(self):
        """When everything fails, returns None."""
        with patch("roar_sdk.dns_discovery.resolve_srv", return_value=[]):
            with patch("roar_sdk.dns_discovery.resolve_agents_from_dns", return_value=None):
                with patch("roar_sdk.dns_discovery.fetch_well_known", new_callable=AsyncMock, return_value=None):
                    with patch("roar_sdk.dns_discovery._try_did_web_discovery", new_callable=AsyncMock, return_value=None):
                        with patch("roar_sdk.dns_discovery._try_anp_discovery", new_callable=AsyncMock, return_value=None):
                            result = await discover_hub("example.com")
                            assert result is None


# ── Backwards-compatible tests ────────────────────────────────────────────


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

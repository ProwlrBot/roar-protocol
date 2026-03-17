# -*- coding: utf-8 -*-
"""Tests for the ROAR Public Agent Discovery Registry."""

from __future__ import annotations

import time

import pytest

from roar_sdk.types import AgentCard, AgentIdentity, AgentCapability, DiscoveryEntry
from roar_sdk.registry import PublicRegistry, RegistryEntry


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_card(
    name: str,
    capabilities: list[str] | None = None,
    description: str = "",
    channels: list[str] | None = None,
    skills: list[str] | None = None,
    did: str = "",
) -> AgentCard:
    """Create a minimal AgentCard for testing."""
    identity = AgentIdentity(
        display_name=name,
        capabilities=capabilities or [],
        did=did or "",
    )
    return AgentCard(
        identity=identity,
        description=description,
        channels=channels or [],
        skills=skills or [],
    )


def _make_entry(
    card: AgentCard,
    hub_url: str = "http://hub1:8090",
    registered_at: float = 0.0,
) -> DiscoveryEntry:
    """Create a DiscoveryEntry wrapping a card."""
    return DiscoveryEntry(
        agent_card=card,
        hub_url=hub_url,
        registered_at=registered_at or time.time(),
    )


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def registry() -> PublicRegistry:
    return PublicRegistry(
        host="127.0.0.1",
        port=18095,
        registry_name="Test Registry",
        admin_api_key="test-key",
    )


@pytest.fixture
def populated_registry(registry: PublicRegistry) -> PublicRegistry:
    """Registry pre-loaded with several agents from two hubs."""
    hub1 = "http://hub1:8090"
    hub2 = "http://hub2:8090"

    cards = [
        _make_card("CodeReviewer", ["code-review", "testing"], "Reviews code changes"),
        _make_card("Translator", ["translation", "nlp"], "Translates between languages"),
        _make_card("Summarizer", ["summarization", "nlp"], "Summarizes long documents", channels=["a2a"]),
        _make_card("Deployer", ["deploy", "devops"], "Handles CI/CD deployments", channels=["mcp"]),
        _make_card("SearchBot", ["search", "web"], "Searches the web for information"),
    ]

    for i, card in enumerate(cards):
        hub = hub1 if i < 3 else hub2
        entry = _make_entry(card, hub_url=hub)
        registry._ingest_entry(entry, hub_url=hub)

    registry._hubs[hub1] = time.time()
    registry._hubs[hub2] = time.time()

    return registry


# ── Tests ───────────────────────────────────────────────────────────────────


class TestRegisterHub:
    def test_register_hub_adds_hub(self, registry: PublicRegistry):
        registry.register_hub("http://hub1:8090")
        assert "http://hub1:8090" in registry._hubs

    def test_register_hub_strips_trailing_slash(self, registry: PublicRegistry):
        registry.register_hub("http://hub1:8090/")
        assert "http://hub1:8090" in registry._hubs

    def test_register_hub_no_duplicates(self, registry: PublicRegistry):
        registry.register_hub("http://hub1:8090")
        registry.register_hub("http://hub1:8090")
        assert len(registry._hubs) == 1

    def test_list_hubs(self, registry: PublicRegistry):
        registry.register_hub("http://hub1:8090")
        registry.register_hub("http://hub2:8090")
        hubs = registry.list_hubs()
        assert len(hubs) == 2
        urls = {h["hub_url"] for h in hubs}
        assert "http://hub1:8090" in urls
        assert "http://hub2:8090" in urls


class TestSearchByCapability:
    def test_search_by_capability_returns_matching(self, populated_registry: PublicRegistry):
        results = populated_registry.search(capability="nlp")
        assert len(results) == 2
        names = {r.agent_card.identity.display_name for r in results}
        assert "Translator" in names
        assert "Summarizer" in names

    def test_search_by_capability_no_match(self, populated_registry: PublicRegistry):
        results = populated_registry.search(capability="nonexistent")
        assert len(results) == 0

    def test_search_no_filter_returns_all(self, populated_registry: PublicRegistry):
        results = populated_registry.search()
        assert len(results) == 5


class TestSearchByProtocol:
    def test_search_by_protocol_roar(self, populated_registry: PublicRegistry):
        results = populated_registry.search(protocol="roar/1.0")
        assert len(results) == 5  # all agents support roar/1.0

    def test_search_by_protocol_a2a(self, populated_registry: PublicRegistry):
        results = populated_registry.search(protocol="a2a")
        assert len(results) == 1
        assert results[0].agent_card.identity.display_name == "Summarizer"

    def test_search_by_protocol_mcp(self, populated_registry: PublicRegistry):
        results = populated_registry.search(protocol="mcp")
        assert len(results) == 1
        assert results[0].agent_card.identity.display_name == "Deployer"


class TestPagination:
    def test_limit(self, populated_registry: PublicRegistry):
        results = populated_registry.search(limit=2)
        assert len(results) == 2

    def test_offset(self, populated_registry: PublicRegistry):
        all_results = populated_registry.search(limit=100)
        offset_results = populated_registry.search(limit=100, offset=2)
        assert len(offset_results) == len(all_results) - 2

    def test_limit_and_offset(self, populated_registry: PublicRegistry):
        all_results = populated_registry.search(limit=100)
        page = populated_registry.search(limit=2, offset=1)
        assert len(page) == 2
        # The slice should correspond to all_results[1:3]
        assert page[0].agent_card.identity.did == all_results[1].agent_card.identity.did
        assert page[1].agent_card.identity.did == all_results[2].agent_card.identity.did

    def test_offset_beyond_range(self, populated_registry: PublicRegistry):
        results = populated_registry.search(limit=20, offset=999)
        assert len(results) == 0


class TestGetStats:
    def test_stats_total_agents(self, populated_registry: PublicRegistry):
        stats = populated_registry.get_stats()
        assert stats["total_agents"] == 5

    def test_stats_total_hubs(self, populated_registry: PublicRegistry):
        stats = populated_registry.get_stats()
        assert stats["total_hubs"] == 2

    def test_stats_by_protocol(self, populated_registry: PublicRegistry):
        stats = populated_registry.get_stats()
        assert stats["by_protocol"]["roar/1.0"] == 5
        assert stats["by_protocol"].get("a2a", 0) == 1
        assert stats["by_protocol"].get("mcp", 0) == 1

    def test_stats_by_capability(self, populated_registry: PublicRegistry):
        stats = populated_registry.get_stats()
        assert stats["by_capability"]["nlp"] == 2
        assert stats["by_capability"]["code-review"] == 1


class TestDeduplication:
    def test_dedup_by_did_latest_wins(self, registry: PublicRegistry):
        card = _make_card("Agent", ["cap1"], did="did:roar:agent:fixed-id")

        old_entry = _make_entry(card, hub_url="http://hub1:8090", registered_at=1000.0)
        new_entry = _make_entry(card, hub_url="http://hub2:8090", registered_at=2000.0)

        registry._ingest_entry(old_entry, hub_url="http://hub1:8090")
        registry._ingest_entry(new_entry, hub_url="http://hub2:8090")

        assert len(registry._agents) == 1
        stored = registry._agents["did:roar:agent:fixed-id"]
        assert stored.hub_url == "http://hub2:8090"
        assert stored.registered_at == 2000.0

    def test_dedup_old_does_not_overwrite_new(self, registry: PublicRegistry):
        card = _make_card("Agent", ["cap1"], did="did:roar:agent:fixed-id")

        new_entry = _make_entry(card, hub_url="http://hub1:8090", registered_at=2000.0)
        old_entry = _make_entry(card, hub_url="http://hub2:8090", registered_at=1000.0)

        registry._ingest_entry(new_entry, hub_url="http://hub1:8090")
        registry._ingest_entry(old_entry, hub_url="http://hub2:8090")

        stored = registry._agents["did:roar:agent:fixed-id"]
        assert stored.hub_url == "http://hub1:8090"
        assert stored.registered_at == 2000.0


class TestFullTextSearch:
    def test_search_matches_name(self, populated_registry: PublicRegistry):
        results = populated_registry.full_text_search("Translator")
        assert len(results) == 1
        assert results[0].agent_card.identity.display_name == "Translator"

    def test_search_matches_description(self, populated_registry: PublicRegistry):
        results = populated_registry.full_text_search("CI/CD")
        assert len(results) == 1
        assert results[0].agent_card.identity.display_name == "Deployer"

    def test_search_matches_capability(self, populated_registry: PublicRegistry):
        results = populated_registry.full_text_search("devops")
        assert len(results) == 1

    def test_search_case_insensitive(self, populated_registry: PublicRegistry):
        results = populated_registry.full_text_search("translator")
        assert len(results) == 1

    def test_search_no_match(self, populated_registry: PublicRegistry):
        results = populated_registry.full_text_search("zzz_nothing")
        assert len(results) == 0

    def test_search_pagination(self, populated_registry: PublicRegistry):
        # "nlp" matches Translator and Summarizer
        results = populated_registry.full_text_search("nlp", limit=1)
        assert len(results) == 1
        results_page2 = populated_registry.full_text_search("nlp", limit=1, offset=1)
        assert len(results_page2) == 1
        assert results[0].agent_card.identity.did != results_page2[0].agent_card.identity.did


class TestRegistryEntry:
    def test_entry_includes_hub_url(self):
        card = _make_card("TestAgent", ["testing"])
        entry = RegistryEntry(agent_card=card, hub_url="http://hub1:8090")
        assert entry.hub_url == "http://hub1:8090"

    def test_entry_includes_protocols(self):
        card = _make_card("TestAgent", ["testing"], channels=["a2a", "mcp"])
        entry = RegistryEntry(agent_card=card, hub_url="http://hub1:8090")
        assert "roar/1.0" in entry.protocols_supported
        assert "a2a" in entry.protocols_supported
        assert "mcp" in entry.protocols_supported

    def test_entry_default_protocols(self):
        card = _make_card("TestAgent", ["testing"])
        entry = RegistryEntry(agent_card=card)
        assert entry.protocols_supported == ["roar/1.0"]

    def test_entry_to_dict(self):
        card = _make_card("TestAgent", ["testing"])
        entry = RegistryEntry(agent_card=card, hub_url="http://hub1:8090")
        d = entry.to_dict()
        assert "agent_card" in d
        assert d["hub_url"] == "http://hub1:8090"
        assert "protocols_supported" in d
        assert "registered_at" in d

    def test_from_discovery_entry(self):
        card = _make_card("TestAgent", ["testing"], channels=["a2a"])
        disc_entry = DiscoveryEntry(
            agent_card=card,
            hub_url="http://hub1:8090",
            registered_at=1234567890.0,
        )
        reg_entry = RegistryEntry.from_discovery_entry(disc_entry)
        assert reg_entry.hub_url == "http://hub1:8090"
        assert reg_entry.registered_at == 1234567890.0
        assert "roar/1.0" in reg_entry.protocols_supported
        assert "a2a" in reg_entry.protocols_supported


class TestWellKnownMetadata:
    def test_metadata_format(self, populated_registry: PublicRegistry):
        meta = populated_registry.well_known_metadata()
        assert meta["name"] == "Test Registry"
        assert meta["version"] == "1.0.0"
        assert meta["total_agents"] == 5
        assert meta["total_hubs"] == 2
        assert "api_url" in meta
        assert isinstance(meta["supported_protocols"], list)
        assert "roar/1.0" in meta["supported_protocols"]

    def test_metadata_empty_registry(self, registry: PublicRegistry):
        meta = registry.well_known_metadata()
        assert meta["total_agents"] == 0
        assert meta["total_hubs"] == 0
        assert meta["supported_protocols"] == []

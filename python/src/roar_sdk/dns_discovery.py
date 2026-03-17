# -*- coding: utf-8 -*-
"""ROAR Protocol — DNS-based agent discovery (multi-standard).

Supports three discovery standards:

1. **DNS-AID** (IETF BANDAID successor):
   SVCB/TXT records at ``_agents.{domain}`` pointing to a ROAR hub.

2. **did:web publishing**:
   W3C DID Documents with service endpoints pointing to the hub.

3. **ANP (Agent Network Protocol) JSON-LD**:
   Agent descriptions in JSON-LD format including capabilities and endpoints.

Also provides:
- Zone file generation for DNS provisioning
- Multi-strategy discovery resolver (DNS TXT -> did:web -> ANP)
- Backwards-compatible SRV/TXT resolution from the original module

Resolution priority for ``discover_hub()``:
  1. DNS SRV records: ``_roar._tcp.{domain}``
  2. DNS-AID TXT at ``_agents.{domain}``
  3. Well-known URI: ``https://{domain}/.well-known/roar.json``
  4. did:web DID Document: ``https://{domain}/.well-known/did.json``
  5. Manual hub URL (caller-provided)

Usage::

    from roar_sdk.dns_discovery import (
        discover_hub, discover_agents_dns,
        generate_svcb_record, generate_zone_file,
        generate_did_document, generate_anp_description,
    )

    # Generate DNS records
    svcb = generate_svcb_record("https://hub.example.com", "example.com")

    # Generate a complete zone file snippet
    zone = generate_zone_file("example.com", "https://hub.example.com", agents)

    # Generate a DID Document for hub publishing
    did_doc = generate_did_document("https://hub.example.com", agent_cards)

    # Generate ANP JSON-LD description
    anp = generate_anp_description(agent_card, "https://hub.example.com")

    # Multi-strategy discovery
    hub_url = await discover_hub("example.com")
"""

from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .did_web import DIDWebMethod
from .types import AgentCard
from .well_known import ROARWellKnown, fetch_well_known

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Simple TTL cache (backwards-compatible with existing tests)
# ---------------------------------------------------------------------------

_dns_cache: Dict[str, Any] = {}
_dns_cache_ts: Dict[str, float] = {}
_DNS_CACHE_TTL = 300.0  # 5 minutes


def _cache_get(key: str) -> Any:
    ts = _dns_cache_ts.get(key, 0)
    if _time.time() - ts < _DNS_CACHE_TTL and key in _dns_cache:
        return _dns_cache[key]
    return None


def _cache_put(key: str, value: Any) -> None:
    _dns_cache[key] = value
    _dns_cache_ts[key] = _time.time()


# ---------------------------------------------------------------------------
# Data classes (backwards-compatible)
# ---------------------------------------------------------------------------


@dataclass
class SRVRecord:
    """Parsed DNS SRV record."""

    priority: int
    weight: int
    port: int
    target: str


@dataclass
class ROARDNSResult:
    """Result of DNS-based discovery for a domain."""

    domain: str
    hub_url: str = ""
    srv_records: List[SRVRecord] = field(default_factory=list)
    txt_metadata: Dict[str, str] = field(default_factory=dict)
    well_known: Optional[ROARWellKnown] = None
    source: str = ""  # "dns", "dns-aid", "well-known", "did-web", "anp", "manual"


# ---------------------------------------------------------------------------
# TXT record parsing (backwards-compatible)
# ---------------------------------------------------------------------------


def _parse_txt_records(txt_data: List[str]) -> Dict[str, str]:
    """Parse TXT record key=value pairs.

    Format: ``"v=roar1" "caps=code-review,testing" "fed=true"``
    """
    result: Dict[str, str] = {}
    for entry in txt_data:
        for part in entry.split():
            part = part.strip('"')
            if "=" in part:
                k, v = part.split("=", 1)
                result[k] = v
    return result


# ---------------------------------------------------------------------------
# Legacy SRV/TXT resolution (backwards-compatible)
# ---------------------------------------------------------------------------


def resolve_srv(domain: str) -> List[SRVRecord]:
    """Resolve DNS SRV records for ``_roar._tcp.{domain}``.

    Uses dnspython if available, otherwise returns empty list.
    """
    srv_name = f"_roar._tcp.{domain}"
    records: List[SRVRecord] = []

    try:
        import dns.resolver
        answers = dns.resolver.resolve(srv_name, "SRV")
        for rdata in answers:
            records.append(SRVRecord(
                priority=rdata.priority,
                weight=rdata.weight,
                port=rdata.port,
                target=str(rdata.target).rstrip("."),
            ))
        records.sort(key=lambda r: (r.priority, -r.weight))
    except ImportError:
        logger.debug("dnspython not installed; SRV lookup unavailable for %s", srv_name)
    except Exception as exc:
        logger.debug("SRV lookup failed for %s: %s", srv_name, exc)

    return records


def resolve_txt(domain: str) -> Dict[str, str]:
    """Resolve DNS TXT records for ``_roar._tcp.{domain}``."""
    txt_name = f"_roar._tcp.{domain}"

    try:
        import dns.resolver
        answers = dns.resolver.resolve(txt_name, "TXT")
        txt_strings = [str(rdata).strip('"') for rdata in answers]
        return _parse_txt_records(txt_strings)
    except ImportError:
        logger.debug("dnspython not installed; TXT lookup unavailable for %s", txt_name)
    except Exception as exc:
        logger.debug("TXT lookup failed for %s: %s", txt_name, exc)

    return {}


# ═══════════════════════════════════════════════════════════════════════════
# 1. DNS-AID (IETF BANDAID successor) — SVCB records at _agents.{domain}
# ═══════════════════════════════════════════════════════════════════════════


def generate_svcb_record(hub_url: str, domain: str) -> str:
    """Generate an SVCB DNS record pointing ``_agents.{domain}`` to a ROAR hub.

    The SVCB (Service Binding) record type is the successor to SRV for
    service discovery, as specified by the DNS-AID / BANDAID IETF draft.

    Args:
        hub_url: The hub's base URL (e.g. ``https://hub.example.com:8090``).
        domain: The domain to publish under (e.g. ``example.com``).

    Returns:
        A DNS zone file entry string for the SVCB record.

    Example::

        >>> generate_svcb_record("https://hub.example.com:8090", "example.com")
        '_agents.example.com. 3600 IN SVCB 1 hub.example.com. alpn="h2,h3" port="8090"'
    """
    parsed = urlparse(hub_url)
    target_host = parsed.hostname or domain
    port = parsed.port
    scheme = parsed.scheme or "https"

    # Determine ALPN based on scheme
    alpn = "h2,h3" if scheme == "https" else "h2"

    # Build the SVCB record
    parts = [
        f"_agents.{domain}.",
        "3600",
        "IN",
        "SVCB",
        "1",  # priority (1 = preferred service)
        f"{target_host}.",
        f'alpn="{alpn}"',
    ]
    if port:
        parts.append(f'port="{port}"')

    return " ".join(parts)


def _generate_agents_txt_record(hub_url: str, domain: str, capabilities: Optional[List[str]] = None) -> str:
    """Generate a TXT record for ``_agents.{domain}`` with hub metadata.

    Args:
        hub_url: The hub URL.
        domain: The domain.
        capabilities: Optional list of aggregate capabilities.

    Returns:
        A DNS zone file TXT entry.
    """
    parts = [
        f"_agents.{domain}.",
        "3600",
        "IN",
        "TXT",
        '"v=roar1"',
        f'"hub={hub_url}"',
    ]
    if capabilities:
        caps_str = ",".join(capabilities)
        parts.append(f'"caps={caps_str}"')

    return " ".join(parts)


def resolve_agents_from_dns(domain: str) -> Optional[str]:
    """Resolve ``_agents.{domain}`` TXT records to extract the hub URL.

    Looks for a TXT record with a ``hub=`` key at the DNS-AID convention
    name ``_agents.{domain}``.

    This does NOT actually perform DNS queries without dnspython.
    When dnspython is available, it queries real DNS.

    Args:
        domain: The domain to resolve.

    Returns:
        The hub URL string if found, or None.
    """
    agents_name = f"_agents.{domain}"

    try:
        import dns.resolver
        answers = dns.resolver.resolve(agents_name, "TXT")
        txt_strings = [str(rdata).strip('"') for rdata in answers]
        parsed = _parse_txt_records(txt_strings)
        hub_url = parsed.get("hub")
        if hub_url:
            logger.info("DNS-AID resolved hub for %s: %s", domain, hub_url)
            return hub_url
    except ImportError:
        logger.debug("dnspython not installed; DNS-AID lookup unavailable for %s", agents_name)
    except Exception as exc:
        logger.debug("DNS-AID TXT lookup failed for %s: %s", agents_name, exc)

    return None


# ═══════════════════════════════════════════════════════════════════════════
# 2. did:web publishing — DID Documents with hub service endpoints
# ═══════════════════════════════════════════════════════════════════════════


def generate_did_document(
    hub_url: str,
    agent_cards: Optional[List[AgentCard]] = None,
    *,
    domain: str = "",
    public_key: str = "",
) -> dict:
    """Generate a W3C DID Document with service endpoints pointing to a ROAR hub.

    The document extends the existing ``did:web`` support to include
    hub-level service endpoints and optional per-agent references.

    Args:
        hub_url: The hub's base URL.
        agent_cards: Optional list of AgentCards to reference in the document.
        domain: The domain for the did:web DID. Extracted from hub_url if empty.
        public_key: Optional hex-encoded Ed25519 public key for the hub.

    Returns:
        A W3C DID Document dict ready to host at ``/.well-known/did.json``.
    """
    if not domain:
        parsed = urlparse(hub_url)
        domain = parsed.hostname or "localhost"

    # Create the did:web identity for the domain root
    identity = DIDWebMethod.create(domain=domain)

    # Build endpoints: hub itself + per-agent services
    endpoints: Dict[str, str] = {
        "roar-hub": hub_url,
        "roar-agents": f"{hub_url.rstrip('/')}/roar/agents",
    }

    # Generate the base DID Document using existing infrastructure
    doc = DIDWebMethod.generate_document(
        identity,
        public_key=public_key,
        endpoints=endpoints,
    )
    doc_dict = doc.to_dict()

    # Add agent-specific service entries
    if agent_cards:
        services = doc_dict.get("service", [])
        for card in agent_cards:
            agent_did = card.identity.did
            agent_endpoint = card.endpoints.get("http", f"{hub_url.rstrip('/')}/roar/agents/{agent_did}")
            services.append({
                "id": f"{identity.did}#agent-{_safe_fragment(card.identity.display_name or agent_did)}",
                "type": "ROARAgent",
                "serviceEndpoint": agent_endpoint,
                "description": card.description,
                "capabilities": card.identity.capabilities,
            })
        doc_dict["service"] = services

    return doc_dict


def _safe_fragment(name: str) -> str:
    """Convert a name to a safe URI fragment identifier."""
    return name.lower().replace(" ", "-").replace(":", "-")[:40]


# ═══════════════════════════════════════════════════════════════════════════
# 3. ANP (Agent Network Protocol) JSON-LD descriptions
# ═══════════════════════════════════════════════════════════════════════════

# ANP JSON-LD context for agent descriptions
_ANP_CONTEXT = "https://www.w3.org/ns/activitystreams"
_ANP_AGENT_TYPE = "https://agentnetworkprotocol.com/ns/Agent"


def generate_anp_description(agent_card: AgentCard, hub_url: str) -> dict:
    """Generate an ANP-compatible JSON-LD agent description.

    ANP (Agent Network Protocol) describes agents using JSON-LD with
    ActivityStreams vocabulary extended for agent capabilities.

    Args:
        agent_card: The agent's AgentCard.
        hub_url: The ROAR hub URL where this agent is registered.

    Returns:
        An ANP agent description dict in JSON-LD format.
    """
    identity = agent_card.identity
    agent_did = identity.did
    display_name = identity.display_name or agent_did

    # Build capabilities as ANP skill objects
    skills = []
    for cap in agent_card.declared_capabilities:
        skill_entry: Dict[str, Any] = {
            "@type": "Skill",
            "name": cap.name,
        }
        if cap.description:
            skill_entry["description"] = cap.description
        if cap.input_schema:
            skill_entry["inputSchema"] = cap.input_schema
        if cap.output_schema:
            skill_entry["outputSchema"] = cap.output_schema
        skills.append(skill_entry)

    # Fallback: use string capabilities if no declared_capabilities
    if not skills and identity.capabilities:
        skills = [{"@type": "Skill", "name": c} for c in identity.capabilities]

    # Build the endpoints list
    endpoints = []
    for transport, url in agent_card.endpoints.items():
        endpoints.append({
            "@type": "Endpoint",
            "protocol": transport,
            "url": url,
        })

    # Always include the hub endpoint
    endpoints.append({
        "@type": "Endpoint",
        "protocol": "roar",
        "url": f"{hub_url.rstrip('/')}/roar/agents/{agent_did}",
    })

    # Protocols supported
    protocols_supported = ["roar/1.0"]
    for channel in agent_card.channels:
        if channel not in protocols_supported:
            protocols_supported.append(channel)

    description: Dict[str, Any] = {
        "@context": [
            _ANP_CONTEXT,
            {"roar": "https://roar-protocol.dev/ns/"},
        ],
        "@type": _ANP_AGENT_TYPE,
        "@id": agent_did,
        "name": display_name,
        "summary": agent_card.description or f"ROAR agent: {display_name}",
        "skills": skills,
        "endpoints": endpoints,
        "protocolsSupported": protocols_supported,
        "registeredHub": hub_url,
    }

    if identity.version:
        description["version"] = identity.version
    if agent_card.metadata:
        description["metadata"] = agent_card.metadata

    return description


# ═══════════════════════════════════════════════════════════════════════════
# 4. Zone file generator
# ═══════════════════════════════════════════════════════════════════════════


def generate_zone_file(
    domain: str,
    hub_url: str,
    agents: Optional[List[AgentCard]] = None,
) -> str:
    """Generate a complete DNS zone file snippet for ROAR agent discovery.

    Includes:
    - SVCB record for ``_agents.{domain}`` (DNS-AID)
    - TXT record for ``_agents.{domain}`` with hub URL and capabilities
    - SRV record for ``_roar._tcp.{domain}`` (legacy compatibility)
    - TXT record for ``_roar._tcp.{domain}`` with version and capabilities

    Args:
        domain: The domain name.
        hub_url: The ROAR hub URL.
        agents: Optional list of AgentCards to derive aggregate capabilities.

    Returns:
        A multi-line string with DNS zone file entries.
    """
    parsed = urlparse(hub_url)
    target_host = parsed.hostname or domain
    port = parsed.port or 443

    # Collect aggregate capabilities from all agents
    all_capabilities: List[str] = []
    if agents:
        for card in agents:
            for cap in card.identity.capabilities:
                if cap not in all_capabilities:
                    all_capabilities.append(cap)

    lines: List[str] = [
        f"; ROAR Protocol DNS records for {domain}",
        f"; Generated for hub: {hub_url}",
        f"; Agents: {len(agents) if agents else 0}",
        ";",
        "; --- DNS-AID (SVCB) records ---",
        generate_svcb_record(hub_url, domain),
        _generate_agents_txt_record(hub_url, domain, all_capabilities or None),
        ";",
        "; --- Legacy SRV records ---",
        f"_roar._tcp.{domain}. 3600 IN SRV 10 0 {port} {target_host}.",
    ]

    # Legacy TXT record
    txt_parts = [
        f"_roar._tcp.{domain}.",
        "3600",
        "IN",
        "TXT",
        '"v=roar1"',
    ]
    if all_capabilities:
        txt_parts.append(f'"caps={",".join(all_capabilities)}"')
    lines.append(" ".join(txt_parts))

    # Per-agent TXT records (optional, for rich DNS-based discovery)
    if agents:
        lines.append(";")
        lines.append("; --- Per-agent TXT records ---")
        for card in agents:
            name = card.identity.display_name or card.identity.did
            safe_name = name.lower().replace(" ", "-").replace(":", "-")[:63]
            agent_caps = ",".join(card.identity.capabilities) if card.identity.capabilities else ""
            agent_txt = f'{safe_name}._agents.{domain}. 3600 IN TXT "did={card.identity.did}"'
            if agent_caps:
                agent_txt += f' "caps={agent_caps}"'
            if card.description:
                # Truncate description for DNS TXT (max 255 chars per string)
                desc = card.description[:200]
                agent_txt += f' "desc={desc}"'
            lines.append(agent_txt)

    lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# 5. Discovery resolver — multi-strategy hub discovery
# ═══════════════════════════════════════════════════════════════════════════


async def _try_did_web_discovery(domain: str, scheme: str = "https") -> Optional[str]:
    """Try discovering a hub URL via did:web DID Document resolution.

    Fetches ``https://{domain}/.well-known/did.json`` and looks for a
    ROARMessaging or roar-hub service endpoint.

    Args:
        domain: The domain to query.
        scheme: HTTP scheme.

    Returns:
        Hub URL if found, None otherwise.
    """
    try:
        import httpx
    except ImportError:
        logger.debug("httpx not available for did:web discovery")
        return None

    url = f"{scheme}://{domain}/.well-known/did.json"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                doc = resp.json()
                # Look for service endpoints
                for svc in doc.get("service", []):
                    svc_type = svc.get("type", "")
                    if svc_type in ("ROARMessaging", "ROARHub"):
                        hub = svc.get("serviceEndpoint", "")
                        if hub:
                            logger.info("Discovered hub via did:web: %s", hub)
                            return hub
                    # Also check by id fragment
                    svc_id = svc.get("id", "")
                    if "roar-hub" in svc_id or "roar" in svc_id.lower():
                        hub = svc.get("serviceEndpoint", "")
                        if hub:
                            logger.info("Discovered hub via did:web (id match): %s", hub)
                            return hub
    except Exception as exc:
        logger.debug("did:web discovery failed for %s: %s", domain, exc)

    return None


async def _try_anp_discovery(domain: str, scheme: str = "https") -> Optional[str]:
    """Try discovering a hub URL via ANP agent description at well-known URL.

    Fetches ``https://{domain}/.well-known/agent.json`` and looks for
    a ROAR hub endpoint in the agent description.

    Args:
        domain: The domain to query.
        scheme: HTTP scheme.

    Returns:
        Hub URL if found, None otherwise.
    """
    try:
        import httpx
    except ImportError:
        logger.debug("httpx not available for ANP discovery")
        return None

    url = f"{scheme}://{domain}/.well-known/agent.json"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                desc = resp.json()
                # Check for registeredHub field
                hub = desc.get("registeredHub")
                if hub:
                    logger.info("Discovered hub via ANP: %s", hub)
                    return hub
                # Check endpoints for roar protocol
                for ep in desc.get("endpoints", []):
                    if ep.get("protocol") == "roar":
                        ep_url = ep.get("url", "")
                        if ep_url:
                            # Extract hub base URL from agent endpoint
                            # e.g. https://hub.example.com/roar/agents/did:... -> https://hub.example.com
                            idx = ep_url.find("/roar/")
                            if idx > 0:
                                hub = ep_url[:idx]
                            else:
                                hub = ep_url
                            logger.info("Discovered hub via ANP endpoint: %s", hub)
                            return hub
    except Exception as exc:
        logger.debug("ANP discovery failed for %s: %s", domain, exc)

    return None


async def discover_hub(
    domain: str,
    *,
    manual_url: str = "",
    scheme: str = "https",
) -> Optional[ROARDNSResult]:
    """Discover a ROAR hub for the given domain using multiple strategies.

    Resolution priority:
      1. DNS SRV: ``_roar._tcp.{domain}``
      2. DNS-AID TXT: ``_agents.{domain}``
      3. Well-known: ``https://{domain}/.well-known/roar.json``
      4. did:web: ``https://{domain}/.well-known/did.json``
      5. ANP: ``https://{domain}/.well-known/agent.json``
      6. Manual URL (if provided)

    Args:
        domain: Domain to discover hubs for.
        manual_url: Fallback hub URL if all methods fail.
        scheme: HTTP scheme for well-known endpoints (default "https").

    Returns:
        ROARDNSResult with hub details, or None if all methods fail.
    """
    # Check cache first
    cached = _cache_get(f"hub:{domain}")
    if cached is not None:
        return cached

    result = ROARDNSResult(domain=domain)

    # 1. Try DNS SRV records
    srv_records = resolve_srv(domain)
    if srv_records:
        result.srv_records = srv_records
        best = srv_records[0]
        result.hub_url = f"{scheme}://{best.target}:{best.port}"
        result.txt_metadata = resolve_txt(domain)
        result.source = "dns"
        _cache_put(f"hub:{domain}", result)
        logger.info("Discovered hub via DNS SRV: %s", result.hub_url)
        return result

    # 2. Try DNS-AID TXT at _agents.{domain}
    dns_aid_url = resolve_agents_from_dns(domain)
    if dns_aid_url:
        result.hub_url = dns_aid_url
        result.source = "dns-aid"
        _cache_put(f"hub:{domain}", result)
        return result

    # 3. Try well-known endpoint
    wk = await fetch_well_known(domain, scheme=scheme)
    if wk is not None:
        result.well_known = wk
        result.hub_url = wk.hub_url
        result.source = "well-known"
        _cache_put(f"hub:{domain}", result)
        logger.info("Discovered hub via well-known: %s", result.hub_url)
        return result

    # 4. Try did:web DID Document
    did_web_url = await _try_did_web_discovery(domain, scheme=scheme)
    if did_web_url:
        result.hub_url = did_web_url
        result.source = "did-web"
        _cache_put(f"hub:{domain}", result)
        return result

    # 5. Try ANP agent description
    anp_url = await _try_anp_discovery(domain, scheme=scheme)
    if anp_url:
        result.hub_url = anp_url
        result.source = "anp"
        _cache_put(f"hub:{domain}", result)
        return result

    # 6. Fallback to manual URL
    if manual_url:
        result.hub_url = manual_url
        result.source = "manual"
        _cache_put(f"hub:{domain}", result)
        logger.info("Using manual hub URL: %s", result.hub_url)
        return result

    logger.warning("No ROAR hub discovered for domain: %s", domain)
    return None


async def discover_agents_dns(
    domain: str,
    *,
    capability: str = "",
    scheme: str = "https",
) -> List[Dict[str, Any]]:
    """Discover agents for a domain, optionally filtered by capability.

    First discovers the hub, then queries it for agents.

    Args:
        domain: Domain to search.
        capability: Filter by capability (optional).
        scheme: HTTP scheme.

    Returns:
        List of agent card dicts from the hub.
    """
    hub_result = await discover_hub(domain, scheme=scheme)
    if hub_result is None or not hub_result.hub_url:
        return []

    # If we got agents from well-known, use those
    if hub_result.well_known and hub_result.well_known.agents:
        agents = hub_result.well_known.agents
        if capability:
            agents = [a for a in agents if capability in a.capabilities]
        return [a.model_dump() for a in agents]

    # Otherwise query the hub API
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            url = f"{hub_result.hub_url}/roar/agents"
            params = {"capability": capability} if capability else {}
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                return resp.json().get("agents", [])
    except Exception as exc:
        logger.warning("Failed to query hub at %s: %s", hub_result.hub_url, exc)

    return []

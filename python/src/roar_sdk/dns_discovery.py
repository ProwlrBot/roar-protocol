# -*- coding: utf-8 -*-
"""ROAR Protocol — DNS-based agent discovery.

Discovers ROAR hubs and agents using DNS SRV/TXT records and the
well-known endpoint as fallback.

Resolution priority:
  1. DNS SRV records: _roar._tcp.{domain}
  2. Well-known URI: https://{domain}/.well-known/roar.json
  3. Manual hub URL (caller-provided)

DNS Record Format:
  SRV: _roar._tcp.example.com  86400 IN SRV 10 0 8090 hub.example.com.
  TXT: _roar._tcp.example.com  86400 IN TXT "v=roar1" "caps=code-review,testing"

Usage::

    from roar_sdk.dns_discovery import discover_hub, discover_agents_dns

    # Find a hub for a domain
    hub_url = await discover_hub("example.com")

    # Find agents with a specific capability
    agents = await discover_agents_dns("example.com", capability="code-review")
"""

from __future__ import annotations

import logging
import socket
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .well_known import ROARWellKnown, fetch_well_known

logger = logging.getLogger(__name__)

# Simple TTL cache for DNS results
_dns_cache: Dict[str, Any] = {}
_dns_cache_ts: Dict[str, float] = {}
_DNS_CACHE_TTL = 300.0  # 5 minutes


def _cache_get(key: str) -> Any:
    import time
    ts = _dns_cache_ts.get(key, 0)
    if time.time() - ts < _DNS_CACHE_TTL and key in _dns_cache:
        return _dns_cache[key]
    return None


def _cache_put(key: str, value: Any) -> None:
    import time
    _dns_cache[key] = value
    _dns_cache_ts[key] = time.time()


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
    source: str = ""  # "dns", "well-known", or "manual"


def _parse_txt_records(txt_data: List[str]) -> Dict[str, str]:
    """Parse TXT record key=value pairs.

    Format: "v=roar1" "caps=code-review,testing" "fed=true"
    """
    result = {}
    for entry in txt_data:
        for part in entry.split():
            part = part.strip('"')
            if "=" in part:
                k, v = part.split("=", 1)
                result[k] = v
    return result


def resolve_srv(domain: str) -> List[SRVRecord]:
    """Resolve DNS SRV records for _roar._tcp.{domain}.

    Uses socket-level DNS resolution. For production, consider
    using dnspython for full SRV support.

    Returns empty list if no records found or DNS fails.
    """
    srv_name = f"_roar._tcp.{domain}"
    records = []

    try:
        # Try dnspython first (full SRV support)
        import dns.resolver
        answers = dns.resolver.resolve(srv_name, "SRV")
        for rdata in answers:
            records.append(SRVRecord(
                priority=rdata.priority,
                weight=rdata.weight,
                port=rdata.port,
                target=str(rdata.target).rstrip("."),
            ))
        # Sort by priority (lowest first), then weight (highest first)
        records.sort(key=lambda r: (r.priority, -r.weight))
    except ImportError:
        # Fallback: try basic socket resolution for the hub host
        logger.debug("dnspython not installed; SRV lookup unavailable for %s", srv_name)
    except Exception as exc:
        logger.debug("SRV lookup failed for %s: %s", srv_name, exc)

    return records


def resolve_txt(domain: str) -> Dict[str, str]:
    """Resolve DNS TXT records for _roar._tcp.{domain}."""
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


async def discover_hub(
    domain: str,
    *,
    manual_url: str = "",
    scheme: str = "https",
) -> Optional[ROARDNSResult]:
    """Discover a ROAR hub for the given domain.

    Resolution priority:
      1. DNS SRV: _roar._tcp.{domain}
      2. Well-known: https://{domain}/.well-known/roar.json
      3. Manual URL (if provided)

    Args:
        domain: Domain to discover hubs for.
        manual_url: Fallback hub URL if DNS and well-known fail.
        scheme: HTTP scheme for well-known (default "https").

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

    # 2. Try well-known endpoint
    wk = await fetch_well_known(domain, scheme=scheme)
    if wk is not None:
        result.well_known = wk
        result.hub_url = wk.hub_url
        result.source = "well-known"
        _cache_put(f"hub:{domain}", result)
        logger.info("Discovered hub via well-known: %s", result.hub_url)
        return result

    # 3. Fallback to manual URL
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

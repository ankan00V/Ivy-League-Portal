"""Trusted client-address extraction for security and observability code.

``X-Forwarded-For`` is supplied by the caller unless the TCP peer is a proxy
we explicitly operate.  Treating it as authoritative for every request lets a
public caller choose the address used by rate limits, device binding, audit
events, and admin IP allow-lists.  This module keeps the trust decision in one
place so those controls cannot quietly diverge.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from app.core.config import settings


def _peer_address(request: Any) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    client = getattr(request, "client", None)
    value = str(getattr(client, "host", "") or "").strip()
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _trusted_proxy_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for raw_value in list(settings.TRUSTED_PROXY_IPS or []):
        value = str(raw_value or "").strip()
        if not value:
            continue
        try:
            # A single address is a valid, deliberately narrow proxy entry.
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _is_trusted_proxy(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(address in network for network in _trusted_proxy_networks())


def _forwarded_client_address(request: Any) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    headers = getattr(request, "headers", {}) or {}
    forwarded = str(headers.get("x-forwarded-for") or "").strip()
    if not forwarded:
        return None

    # A trusted proxy appends its peer to the right.  Walk right-to-left and
    # discard only addresses that are also explicitly trusted, leaving the
    # closest untrusted hop as the client.  This is safe only after the actual
    # TCP peer was checked by ``client_ip`` below.
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for raw_value in forwarded.split(","):
        try:
            addresses.append(ipaddress.ip_address(raw_value.strip()))
        except ValueError:
            return None
    for address in reversed(addresses):
        if not _is_trusted_proxy(address):
            return address
    return None


def client_ip(request: Any) -> str:
    """Return the authenticated client network address, never raw header text.

    With no ``TRUSTED_PROXY_IPS`` configuration the direct socket peer is the
    only source of truth.  Deployments behind a reverse proxy must list that
    proxy's fixed address or network; merely enabling a proxy is not enough to
    make forwarded headers trustworthy.
    """

    peer = _peer_address(request)
    if peer is None:
        return "unknown"
    if not _is_trusted_proxy(peer):
        return str(peer)
    forwarded = _forwarded_client_address(request)
    return str(forwarded or peer)

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpx


class BlockedTargetURL(ValueError):
    """Raised when a URL resolves to a target the server must not fetch."""


_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")
_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal", "instance-data"}


def resolve_hostname(hostname: str) -> list[str]:
    """Resolve a hostname to raw address strings.

    Split out as a seam so tests can stub resolution. Provider-routing tests use
    non-resolvable hosts like careers.example.com and are not exercising this
    guard; production must keep the real lookup, since a literal-IP-only check
    is trivially bypassed by a hostname that answers 169.254.169.254.
    """
    return [info[4][0] for info in socket.getaddrinfo(hostname, None)]


def _addresses_for(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Every address the hostname resolves to.

    A literal-IP check alone is not enough: an attacker controls DNS for their
    own domain, so evil.example can simply answer with 169.254.169.254. Every
    resolved address has to be checked, not just the ones written as literals.
    """
    try:
        return [ipaddress.ip_address(hostname)]
    except ValueError:
        pass

    try:
        raw_addresses = resolve_hostname(hostname)
    except OSError as exc:
        raise BlockedTargetURL(f"target_host_unresolvable:{hostname}") from exc

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for raw in raw_addresses:
        try:
            addresses.append(ipaddress.ip_address(raw))
        except ValueError:
            continue
    if not addresses:
        raise BlockedTargetURL(f"target_host_unresolvable:{hostname}")
    return addresses


def public_addresses_for(url: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Validate `url` and return the addresses that were actually checked.

    One resolution, and the list handed back is that same list. This matters
    more than it looks: a caller that validates a hostname and then lets its
    HTTP client resolve the name again has not validated anything the client
    will use. Between the two lookups a resolver the attacker controls can
    answer public once and 169.254.169.254 once, so the caller connects to an
    address nothing checked.

    Returning the checked addresses lets a caller pin its connection to one of
    them, which is the only version of this guard that closes the window rather
    than narrowing it.
    """
    candidate = str(url or "").strip()
    if not candidate:
        raise BlockedTargetURL("target_url_empty")

    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise BlockedTargetURL(f"target_scheme_forbidden:{parsed.scheme}")
    if not parsed.hostname:
        raise BlockedTargetURL("target_host_missing")
    # user:pass@host can be used to confuse downstream parsers about the
    # real destination.
    if parsed.username or parsed.password:
        raise BlockedTargetURL("target_credentials_forbidden")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in _BLOCKED_HOSTNAMES or hostname.endswith(_BLOCKED_HOST_SUFFIXES):
        raise BlockedTargetURL(f"target_host_forbidden:{hostname}")

    addresses = _addresses_for(hostname)
    for address in addresses:
        # is_global excludes loopback, link-local (169.254.0.0/16, which is the
        # cloud metadata range), private RFC1918, multicast, reserved and
        # unspecified addresses in one check.
        if not address.is_global:
            raise BlockedTargetURL(f"target_address_forbidden:{address}")

    return addresses


def assert_public_http_url(url: str) -> str:
    """Validate that `url` is a public http(s) target, or raise BlockedTargetURL.

    Guards server-side fetches of user-supplied URLs. Without this, submitting
    a source pointed at http://169.254.169.254/ made the server read cloud
    instance metadata - including IAM credentials on IMDSv1 - and submitting
    http://10.0.0.5:8080/ turned the qualification pipeline into an internal
    port scanner, with the reachability result handed back to the submitter.

    Callers that go on to open a connection should prefer public_addresses_for
    and connect to an address it returned; this one answers "was it safe a
    moment ago", which a second DNS lookup can invalidate.
    """
    public_addresses_for(url)
    return str(url or "").strip()


async def assert_public_http_url_async(url: str) -> str:
    """Run DNS-backed target validation without blocking the event loop."""

    return await asyncio.to_thread(assert_public_http_url, url)


def is_public_http_url(url: str) -> bool:
    try:
        assert_public_http_url(url)
    except BlockedTargetURL:
        return False
    return True


class PinnedPublicTransport(httpx.AsyncHTTPTransport):
    """Open outbound HTTP connections only to the address just validated.

    Validating a hostname and then handing that hostname to an HTTP client is
    insufficient: the client performs its own DNS lookup and a hostile resolver
    can return a private address on that second lookup.  This transport resolves
    once, validates every answer and dials one of those exact public addresses.
    The original hostname remains in the Host header and TLS SNI, preserving
    normal virtual-host routing and certificate verification.
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        hostname = request.url.host
        addresses = await asyncio.to_thread(public_addresses_for, str(request.url))
        if not addresses:
            raise BlockedTargetURL(f"target_host_unresolvable:{hostname}")
        address = next((item for item in addresses if item.version == 4), addresses[0])
        if not address.is_global:
            raise BlockedTargetURL(f"target_address_forbidden:{address}")

        request.headers["Host"] = request.url.netloc.decode("ascii")
        request.extensions = {**dict(request.extensions or {}), "sni_hostname": hostname}
        request.url = request.url.copy_with(host=str(address))
        return await super().handle_async_request(request)

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


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


def assert_public_http_url(url: str) -> str:
    """Validate that `url` is a public http(s) target, or raise BlockedTargetURL.

    Guards server-side fetches of user-supplied URLs. Without this, submitting
    a source pointed at http://169.254.169.254/ made the server read cloud
    instance metadata - including IAM credentials on IMDSv1 - and submitting
    http://10.0.0.5:8080/ turned the qualification pipeline into an internal
    port scanner, with the reachability result handed back to the submitter.
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

    for address in _addresses_for(hostname):
        # is_global excludes loopback, link-local (169.254.0.0/16, which is the
        # cloud metadata range), private RFC1918, multicast, reserved and
        # unspecified addresses in one check.
        if not address.is_global:
            raise BlockedTargetURL(f"target_address_forbidden:{address}")

    return candidate


def is_public_http_url(url: str) -> bool:
    try:
        assert_public_http_url(url)
    except BlockedTargetURL:
        return False
    return True

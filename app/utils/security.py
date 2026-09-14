"""SSRF and URL-safety utilities.

This module is the single source of truth for validating that a URL is safe
to fetch (public HTTP/HTTPS destination, no private/loopback/link-local/cloud
metadata targets) and for performing HTTP requests through a client that
re-validates every redirect hop. Import from here rather than re-implementing
SSRF checks elsewhere (see task.md section 42).
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

import httpx

from app.config import get_settings
from app.schemas.models import CrawlScope

USER_AGENT = "WebRAG-Bot/1.0 (+https://github.com/)"

ALLOWED_SCHEMES = {"http", "https"}

# Explicit cloud metadata hostnames/IPs to always block, even if they don't
# resolve to a private range on this host.
BLOCKED_HOSTNAMES = {
    "metadata.google.internal",
    "metadata",
    "instance-data",
}
BLOCKED_IPS = {
    "169.254.169.254",
    "fd00:ec2::254",
}
LINK_LOCAL_V4_NET = ipaddress.ip_network("169.254.0.0/16")

TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_PARAMS = {"fbclid", "gclid", "ref", "mc_cid", "mc_eid", "igshid"}

DEFAULT_PORTS = {"http": 80, "https": 443}


def is_public_http_url(url: str) -> bool:
    """Return True only if `url` has scheme http or https and a hostname."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return False
    if not parsed.hostname:
        return False
    return True


def _is_blocked_ip(ip_str: str) -> bool:
    if ip_str in BLOCKED_IPS:
        return True
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # can't parse -> treat as unsafe
    if isinstance(ip, ipaddress.IPv4Address) and ip in LINK_LOCAL_V4_NET:
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def resolve_and_validate_host(hostname: str) -> list[str]:
    """Resolve `hostname` via DNS and return the list of resolved IP strings.

    Raises ValueError if the hostname is a known-blocked name, resolution
    fails, or any resolved address is private/loopback/link-local/multicast/
    reserved/unspecified/a cloud metadata address.
    """
    host_lower = hostname.lower().rstrip(".")
    if host_lower in BLOCKED_HOSTNAMES:
        raise ValueError(f"Blocked hostname: {hostname}")

    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for {hostname}: {exc}") from exc

    ips = []
    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        ips.append(ip_str)

    if not ips:
        raise ValueError(f"No addresses resolved for {hostname}")

    for ip_str in ips:
        if _is_blocked_ip(ip_str):
            raise ValueError(f"Unsafe resolved address for {hostname}: {ip_str}")

    return ips


def is_safe_url(url: str) -> tuple[bool, str]:
    """Combine scheme + host validation. Returns (ok, reason)."""
    if not is_public_http_url(url):
        return False, "URL scheme must be http or https with a hostname"

    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    try:
        resolve_and_validate_host(hostname)
    except ValueError as exc:
        return False, str(exc)

    return True, "ok"


def normalize_url(url: str, base: str | None = None) -> str:
    """Resolve relative URLs against `base`, strip fragments/tracking params,
    lowercase scheme/host, drop default ports, and normalize trailing slash.
    """
    resolved = urljoin(base, url) if base else url
    parsed = urlparse(resolved)

    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    if port is not None and DEFAULT_PORTS.get(scheme) == port:
        netloc = hostname
    elif port is not None:
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname

    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo += f":{parsed.password}"
        netloc = f"{userinfo}@{netloc}"

    path = parsed.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
        if not path:
            path = "/"

    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith(TRACKING_PARAM_PREFIXES) and k.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(query_pairs)

    return urlunparse((scheme, netloc, path, parsed.params, query, ""))


def _registrable_domain(hostname: str) -> str:
    """Best-effort registrable-domain extraction without an external PSL dep:
    returns the last two labels (e.g. 'example.com' from 'a.b.example.com'),
    falling back to the full hostname for short/edge-case hosts.
    """
    parts = hostname.lower().rstrip(".").split(".")
    if len(parts) <= 2:
        return ".".join(parts)
    return ".".join(parts[-2:])


def is_same_scope(
    url: str,
    root_url: str,
    scope: CrawlScope,
    allowed_path_prefix: str | None = None,
) -> bool:
    """Decide whether `url` is within the crawl scope relative to `root_url`.

    - single_page: only the root URL itself.
    - linked_pages: same host as root (caller further limits by link-depth-1).
    - entire_domain: same registrable domain as root (including subdomains).
    - selected_path: same host as root AND path starts with allowed_path_prefix.
    """
    url_p = urlparse(url)
    root_p = urlparse(root_url)
    url_host = (url_p.hostname or "").lower()
    root_host = (root_p.hostname or "").lower()

    if scope == CrawlScope.single_page:
        return normalize_url(url) == normalize_url(root_url)

    if scope == CrawlScope.linked_pages:
        return url_host == root_host

    if scope == CrawlScope.entire_domain:
        return _registrable_domain(url_host) == _registrable_domain(root_host)

    if scope == CrawlScope.selected_path:
        if url_host != root_host:
            return False
        prefix = allowed_path_prefix or root_p.path or "/"
        return url_p.path.startswith(prefix)

    return False


class SafeHTTPClient:
    """Async HTTP client that enforces SSRF protection on every request and
    on every redirect hop, plus timeout and max-response-size enforcement.
    """

    def __init__(self, timeout: float | None = None, max_response_bytes: int | None = None):
        settings = get_settings()
        self._timeout = timeout if timeout is not None else settings.request_timeout
        self._max_bytes = max_response_bytes if max_response_bytes is not None else settings.max_response_bytes
        self._client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=self._timeout,
            headers={"User-Agent": USER_AGENT},
        )

    async def __aenter__(self) -> "SafeHTTPClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, url: str, max_redirects: int = 5) -> httpx.Response:
        """GET `url` safely, validating SSRF-safety before the initial request
        and again before following each redirect (up to `max_redirects` hops).
        Raises ValueError on an unsafe URL, and httpx exceptions on network
        errors. Raises ValueError if the response body exceeds
        max_response_bytes.
        """
        current_url = url
        for _ in range(max_redirects + 1):
            ok, reason = is_safe_url(current_url)
            if not ok:
                raise ValueError(f"Refusing unsafe URL {current_url}: {reason}")

            request = self._client.build_request("GET", current_url)
            response = await self._client.send(request, stream=True)

            if response.is_redirect:
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    return response
                current_url = normalize_url(location, base=current_url)
                continue

            body = bytearray()
            try:
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self._max_bytes:
                        await response.aclose()
                        raise ValueError(
                            f"Response exceeded max_response_bytes ({self._max_bytes}) for {current_url}"
                        )
            finally:
                await response.aclose()

            response._content = bytes(body)
            return response

        raise ValueError(f"Too many redirects (> {max_redirects}) for {url}")

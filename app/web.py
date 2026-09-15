"""Website fetching and small same-site crawling, with SSRF protection.

Every outbound request goes through `safe_get`, which validates the scheme and
that the hostname resolves only to public IPs, on every redirect hop.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urldefrag, urljoin, urlparse

import httpx

from app.config import settings
from app.extract import html_to_text

MAX_BYTES = 5_000_000
MAX_REDIRECTS = 5
_SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".zip", ".mp4", ".mp3", ".css", ".js", ".xml", ".ico")
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; WebRAG/1.0)"}


class FetchError(Exception):
    pass


async def _check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise FetchError("Only http(s) URLs are allowed")
    host = parsed.hostname
    if host.lower() in ("localhost", "metadata.google.internal") or host.lower().endswith((".local", ".internal")):
        raise FetchError("Internal hosts are not allowed")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError(f"Could not resolve {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            raise FetchError("URL resolves to a private or reserved address")


async def safe_get(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    """GET an HTML page. Returns (final_url, html)."""
    for _ in range(MAX_REDIRECTS + 1):
        await _check_url(url)
        async with client.stream("GET", url, headers=_HEADERS) as resp:
            if resp.is_redirect:
                url = urljoin(url, resp.headers.get("location", ""))
                continue
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code}")
            if "html" not in resp.headers.get("content-type", "html"):
                raise FetchError("Not an HTML page")
            body = bytearray()
            async for part in resp.aiter_bytes():
                body.extend(part)
                if len(body) > MAX_BYTES:
                    raise FetchError("Page too large")
            return str(resp.url), body.decode(resp.encoding or "utf-8", errors="replace")
    raise FetchError("Too many redirects")


def _site_key(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


async def crawl(start_url: str, max_pages: int) -> list[dict]:
    """BFS over same-site links. Returns [{url, title, text}] for pages with text."""
    pages: list[dict] = []
    seen: set[str] = {urldefrag(start_url)[0]}
    queue: list[str] = [start_url]
    site = _site_key(start_url)
    sem = asyncio.Semaphore(5)

    async with httpx.AsyncClient(timeout=settings.request_timeout, follow_redirects=False) as client:

        async def fetch(url: str) -> tuple[str, str] | None:
            async with sem:
                try:
                    return await safe_get(client, url)
                except (FetchError, httpx.HTTPError):
                    if url == start_url:
                        raise
                    return None

        while queue and len(pages) < max_pages:
            batch, queue = queue[: max_pages - len(pages)], queue[max_pages - len(pages):]
            for result in await asyncio.gather(*(fetch(u) for u in batch)):
                if result is None:
                    continue
                final_url, html = result
                title, text, soup = html_to_text(html)
                if text:
                    pages.append({"url": final_url, "title": title or final_url, "text": text})
                for a in soup.find_all("a", href=True):
                    link = urldefrag(urljoin(final_url, a["href"]))[0]
                    parsed = urlparse(link)
                    if (
                        parsed.scheme in ("http", "https")
                        and _site_key(link) == site
                        and not parsed.path.lower().endswith(_SKIP_EXT)
                        and link not in seen
                        and len(seen) < max_pages * 5
                    ):
                        seen.add(link)
                        queue.append(link)
    return pages

"""BFS web crawler that discovers and fetches pages within a workspace's
configured scope, extracts clean content from each page, and reports
progress via callbacks.

Public entry point: `crawl_workspace`. It is callback-driven (not a
generator) so a caller (e.g. an API/background-task layer) can wire it into
a background task and stream progress over SSE without needing to iterate
an async generator.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Union
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

from app.config import get_settings
from app.rag.extraction import extract_page
from app.schemas.models import CrawlConfig, CrawlScope
from app.utils.security import USER_AGENT, SafeHTTPClient, is_safe_url, is_same_scope, normalize_url

logger = logging.getLogger(__name__)

OnPageCallback = Callable[[dict], Union[None, Awaitable[None]]]
OnProgressCallback = Callable[[int, int], Union[None, Awaitable[None]]]

HTML_CONTENT_TYPE_PREFIXES = ("text/html", "application/xhtml+xml")


@dataclass
class _CrawlState:
    discovered: set[str] = field(default_factory=set)
    processed: int = 0
    queued: list[tuple[str, int]] = field(default_factory=list)  # (url, depth)


async def _maybe_await(result):
    if asyncio.iscoroutine(result):
        await result


async def _load_robots(client: SafeHTTPClient, root_url: str) -> RobotFileParser:
    """Fetch and parse robots.txt for the root URL's origin. Any failure
    (missing file, network error, malformed content) is tolerated as
    "allow everything" per task requirements.
    """
    parsed = urlparse(root_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        response = await client.get(robots_url)
        if response.status_code >= 400:
            parser.parse([])
        else:
            text = response.text
            parser.parse(text.splitlines())
    except Exception as exc:
        logger.info("robots.txt unavailable for %s (%s); allowing all", robots_url, exc)
        parser.parse([])
    return parser


def _extract_links(html: str, page_url: str) -> list[str]:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return []
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        try:
            absolute = urljoin(page_url, href)
        except ValueError:
            continue
        links.append(absolute)
    return links


async def crawl_workspace(
    root_url: str,
    crawl_config: CrawlConfig,
    on_page: OnPageCallback,
    on_progress: OnProgressCallback,
) -> None:
    """Crawl a workspace starting at `root_url` under `crawl_config`.

    Behavior:
      - Validates `root_url` is a safe public http(s) URL (SSRF-protected);
        raises ValueError immediately if not.
      - Fetches and honors robots.txt for the root origin (missing/broken
        robots.txt is treated as "allow all").
      - Performs a breadth-first crawl bounded by `crawl_config.max_pages`
        and `crawl_config.max_depth`, restricted to `crawl_config.scope`
        (and `crawl_config.allowed_path_prefix` for `selected_path` scope).
      - Rate-limits outgoing requests to at most
        `settings.crawl_rate_limit_per_sec` requests/second.
      - Dedupes pages via normalized-URL set; skips non-HTML responses and
        gracefully logs+skips HTTP/network errors without aborting the
        whole crawl.
      - For every successfully fetched HTML page, extracts content with
        `app.rag.extraction.extract_page` and calls:
            on_page(source_document_dict)
        where `source_document_dict` is the dict returned by `extract_page`
        (keys: url, canonical_url, title, content, headings, breadcrumbs,
        word_count, content_hash, published_at, modified_at). `on_page` may
        be sync or async (async is awaited).
      - After every fetch attempt (success or failure), calls:
            on_progress(pages_discovered, pages_processed)
        with cumulative counts so far. `on_progress` may be sync or async.

    This function never raises for individual page failures; it only raises
    ValueError if `root_url` itself is unsafe/invalid before crawling starts.
    """
    ok, reason = is_safe_url(root_url)
    if not ok:
        raise ValueError(f"Refusing to crawl unsafe root URL {root_url}: {reason}")

    settings = get_settings()
    root_url = normalize_url(root_url)
    scope = crawl_config.scope
    max_pages = max(1, crawl_config.max_pages or settings.max_crawl_pages)
    max_depth = max(0, crawl_config.max_depth if crawl_config.max_depth is not None else settings.max_crawl_depth)
    min_interval = 1.0 / settings.crawl_rate_limit_per_sec if settings.crawl_rate_limit_per_sec > 0 else 0.0

    state = _CrawlState()
    state.discovered.add(root_url)
    state.queued.append((root_url, 0))

    last_request_time = 0.0

    async with SafeHTTPClient(
        timeout=settings.request_timeout, max_response_bytes=settings.max_response_bytes
    ) as client:
        robots = await _load_robots(client, root_url)

        while state.queued and state.processed < max_pages:
            url, depth = state.queued.pop(0)

            if depth > max_depth:
                continue

            can_fetch = True
            try:
                can_fetch = robots.can_fetch(USER_AGENT, url)
            except Exception:
                can_fetch = True
            if not can_fetch:
                logger.info("robots.txt disallows %s; skipping", url)
                await _maybe_await(on_progress(len(state.discovered), state.processed))
                continue

            elapsed = time.monotonic() - last_request_time
            if min_interval and elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
            last_request_time = time.monotonic()

            try:
                response = await client.get(url)
            except Exception as exc:
                logger.warning("Failed to fetch %s: %s", url, exc)
                state.processed += 1
                await _maybe_await(on_progress(len(state.discovered), state.processed))
                continue

            state.processed += 1

            if response.status_code >= 400:
                logger.info("Skipping %s (status %s)", url, response.status_code)
                await _maybe_await(on_progress(len(state.discovered), state.processed))
                continue

            content_type = response.headers.get("content-type", "")
            if not any(content_type.lower().startswith(p) for p in HTML_CONTENT_TYPE_PREFIXES):
                logger.info("Skipping non-HTML content-type %s for %s", content_type, url)
                await _maybe_await(on_progress(len(state.discovered), state.processed))
                continue

            try:
                html = response.text
            except Exception as exc:
                logger.warning("Failed to decode response body for %s: %s", url, exc)
                await _maybe_await(on_progress(len(state.discovered), state.processed))
                continue

            try:
                document = extract_page(html, url)
                await _maybe_await(on_page(document))
            except Exception as exc:
                logger.warning("Extraction/on_page callback failed for %s: %s", url, exc)

            if scope != CrawlScope.single_page and depth < max_depth and len(state.discovered) < max_pages:
                for link in _extract_links(html, url):
                    if not link.lower().startswith(("http://", "https://")):
                        continue
                    normalized = normalize_url(link)
                    if normalized in state.discovered:
                        continue
                    if scope == CrawlScope.linked_pages and depth >= 1:
                        # linked_pages: only follow links found on the root page itself.
                        continue
                    if not is_same_scope(normalized, root_url, scope, crawl_config.allowed_path_prefix):
                        continue
                    ok, _ = is_safe_url(normalized)
                    if not ok:
                        continue
                    if len(state.discovered) >= max_pages:
                        break
                    state.discovered.add(normalized)
                    state.queued.append((normalized, depth + 1))

            await _maybe_await(on_progress(len(state.discovered), state.processed))

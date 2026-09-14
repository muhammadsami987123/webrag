"""Tests for app.services.crawler_service.crawl_workspace.

All HTTP is mocked with respx (no real network calls). DNS resolution is
monkeypatched so SSRF validation treats our fake domain as a public IP.
"""
from __future__ import annotations

import socket

import pytest
import respx
import httpx

from app.schemas.models import CrawlConfig, CrawlScope
from app.services.crawler_service import crawl_workspace


PAGE_HTML = {
    "https://example.com/": """
        <html><head><title>Home</title></head>
        <body>
          <h1>Home</h1>
          <p>Welcome.</p>
          <a href="/about">About</a>
          <a href="/blog/post-1">Blog Post 1</a>
          <a href="https://other.com/external">External</a>
        </body></html>
    """,
    "https://example.com/about": """
        <html><head><title>About</title></head>
        <body><h1>About</h1><p>About us.</p><a href="/contact">Contact</a></body></html>
    """,
    "https://example.com/contact": """
        <html><head><title>Contact</title></head>
        <body><h1>Contact</h1><p>Contact us.</p></body></html>
    """,
    "https://example.com/blog/post-1": """
        <html><head><title>Post 1</title></head>
        <body><h1>Post 1</h1><p>Content.</p></body></html>
    """,
}


@pytest.fixture(autouse=True)
def patch_dns(monkeypatch):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host in ("example.com", "other.com"):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
        raise socket.gaierror("no mapping")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def _mock_routes(router: respx.MockRouter):
    router.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(404)
    )
    for url, html in PAGE_HTML.items():
        router.get(url).mock(return_value=httpx.Response(200, html=html, headers={"content-type": "text/html"}))
    router.get("https://other.com/external").mock(
        return_value=httpx.Response(200, html="<html><body>external</body></html>", headers={"content-type": "text/html"})
    )


@pytest.mark.asyncio
@respx.mock
async def test_crawl_respects_max_pages():
    _mock_routes(respx.mock)
    config = CrawlConfig(scope=CrawlScope.entire_domain, max_pages=2, max_depth=3)

    pages = []

    async def on_page(doc):
        pages.append(doc)

    progress_calls = []

    async def on_progress(discovered, processed):
        progress_calls.append((discovered, processed))

    await crawl_workspace("https://example.com/", config, on_page, on_progress)

    assert len(pages) <= 2
    assert progress_calls  # progress was reported


@pytest.mark.asyncio
@respx.mock
async def test_crawl_stays_in_scope_excludes_external_domain():
    _mock_routes(respx.mock)
    config = CrawlConfig(scope=CrawlScope.entire_domain, max_pages=10, max_depth=3)

    pages = []

    async def on_page(doc):
        pages.append(doc)

    async def on_progress(discovered, processed):
        pass

    await crawl_workspace("https://example.com/", config, on_page, on_progress)

    urls = {p["url"] for p in pages}
    assert all("other.com" not in u for u in urls)
    assert "https://example.com/" in urls


@pytest.mark.asyncio
@respx.mock
async def test_crawl_respects_max_depth_zero():
    _mock_routes(respx.mock)
    config = CrawlConfig(scope=CrawlScope.entire_domain, max_pages=10, max_depth=0)

    pages = []

    async def on_page(doc):
        pages.append(doc)

    async def on_progress(discovered, processed):
        pass

    await crawl_workspace("https://example.com/", config, on_page, on_progress)

    urls = {p["url"] for p in pages}
    assert urls == {"https://example.com/"}


@pytest.mark.asyncio
@respx.mock
async def test_crawl_dedupes_repeated_links():
    router = respx.mock
    router.get("https://example.com/robots.txt").mock(return_value=httpx.Response(404))
    router.get("https://example.com/").mock(
        return_value=httpx.Response(
            200,
            html="""<html><head><title>Home</title></head><body>
                <a href="/about">About</a>
                <a href="/about">About Again</a>
                <a href="/about#section">About Fragment</a>
            </body></html>""",
            headers={"content-type": "text/html"},
        )
    )
    router.get("https://example.com/about").mock(
        return_value=httpx.Response(200, html="<html><head><title>About</title></head><body>About us.</body></html>", headers={"content-type": "text/html"})
    )

    config = CrawlConfig(scope=CrawlScope.entire_domain, max_pages=10, max_depth=3)
    pages = []

    async def on_page(doc):
        pages.append(doc)

    async def on_progress(discovered, processed):
        pass

    await crawl_workspace("https://example.com/", config, on_page, on_progress)

    urls = [p["url"] for p in pages]
    assert urls.count("https://example.com/about") == 1


@pytest.mark.asyncio
@respx.mock
async def test_crawl_skips_non_html_content_type():
    router = respx.mock
    router.get("https://example.com/robots.txt").mock(return_value=httpx.Response(404))
    router.get("https://example.com/").mock(
        return_value=httpx.Response(
            200,
            html='<html><head><title>Home</title></head><body><a href="/file.pdf">PDF</a></body></html>',
            headers={"content-type": "text/html"},
        )
    )
    router.get("https://example.com/file.pdf").mock(
        return_value=httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})
    )

    config = CrawlConfig(scope=CrawlScope.entire_domain, max_pages=10, max_depth=3)
    pages = []

    async def on_page(doc):
        pages.append(doc)

    async def on_progress(discovered, processed):
        pass

    await crawl_workspace("https://example.com/", config, on_page, on_progress)

    urls = {p["url"] for p in pages}
    assert "https://example.com/file.pdf" not in urls


@pytest.mark.asyncio
async def test_crawl_rejects_unsafe_root_url():
    config = CrawlConfig(scope=CrawlScope.single_page, max_pages=1, max_depth=0)

    async def on_page(doc):
        pass

    async def on_progress(discovered, processed):
        pass

    with pytest.raises(ValueError):
        await crawl_workspace("file:///etc/passwd", config, on_page, on_progress)


@pytest.mark.asyncio
@respx.mock
async def test_crawl_single_page_scope_does_not_follow_links():
    _mock_routes(respx.mock)
    config = CrawlConfig(scope=CrawlScope.single_page, max_pages=10, max_depth=3)

    pages = []

    async def on_page(doc):
        pages.append(doc)

    async def on_progress(discovered, processed):
        pass

    await crawl_workspace("https://example.com/", config, on_page, on_progress)

    assert len(pages) == 1
    assert pages[0]["url"] == "https://example.com/"

"""Tests for app.rag.extraction — boilerplate stripping, heading capture,
table conversion, and defensive handling of malformed HTML.
"""
from __future__ import annotations

from app.rag.extraction import compute_content_hash, extract_page

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Sample Article</title>
  <link rel="canonical" href="https://example.com/sample-article" />
  <meta property="article:published_time" content="2024-01-15T00:00:00Z" />
  <meta property="article:modified_time" content="2024-02-01T00:00:00Z" />
</head>
<body>
  <header><div class="masthead">Site Header</div></header>
  <nav aria-label="breadcrumb">
    <a href="/">Home</a> / <a href="/blog">Blog</a> / <span>Sample Article</span>
  </nav>
  <div class="cookie-banner">We use cookies. <button>Accept</button></div>
  <main>
    <article>
      <h1>Sample Article</h1>
      <p>This is the introduction paragraph with real content.</p>
      <h2>Section One</h2>
      <p>Some detail about section one goes here.</p>
      <ul>
        <li>First point</li>
        <li>Second point</li>
      </ul>
      <h2>Data Table</h2>
      <table>
        <tr><th>Name</th><th>Value</th></tr>
        <tr><td>Alpha</td><td>1</td></tr>
        <tr><td>Beta</td><td>2</td></tr>
      </table>
      <div class="social-share">Share this on Twitter</div>
      <aside class="sidebar">Related links go here</aside>
    </article>
  </main>
  <footer>Copyright 2024. <div class="newsletter-signup">Subscribe now</div></footer>
  <script>alert('should never run or appear');</script>
</body>
</html>
"""


def test_extract_page_strips_nav_footer_and_ads():
    doc = extract_page(SAMPLE_HTML, "https://example.com/sample-article")
    content = doc["content"]
    assert "Site Header" not in content
    assert "Copyright 2024" not in content
    assert "cookies" not in content.lower()
    assert "Share this on Twitter" not in content
    assert "Related links" not in content
    assert "Subscribe now" not in content
    assert "alert(" not in content


def test_extract_page_preserves_headings_in_order():
    doc = extract_page(SAMPLE_HTML, "https://example.com/sample-article")
    levels_texts = [(h["level"], h["text"]) for h in doc["headings"]]
    assert levels_texts == [
        (1, "Sample Article"),
        (2, "Section One"),
        (2, "Data Table"),
    ]


def test_extract_page_converts_table_to_markdown_pipes():
    doc = extract_page(SAMPLE_HTML, "https://example.com/sample-article")
    content = doc["content"]
    assert "| Name | Value |" in content
    assert "| Alpha | 1 |" in content
    assert "| Beta | 2 |" in content


def test_extract_page_converts_list_items():
    doc = extract_page(SAMPLE_HTML, "https://example.com/sample-article")
    content = doc["content"]
    assert "- First point" in content
    assert "- Second point" in content


def test_extract_page_metadata_fields():
    doc = extract_page(SAMPLE_HTML, "https://example.com/sample-article")
    assert doc["title"] == "Sample Article"
    assert doc["canonical_url"] == "https://example.com/sample-article"
    assert doc["published_at"] == "2024-01-15T00:00:00Z"
    assert doc["modified_at"] == "2024-02-01T00:00:00Z"
    assert doc["breadcrumbs"] == ["Home", "Blog", "Sample Article"]
    assert doc["word_count"] > 0
    assert doc["content_hash"] == compute_content_hash(doc["content"])


def test_extract_page_handles_malformed_html_without_raising():
    garbage = "<html><body><div><p>Unclosed tags <span>oops"
    doc = extract_page(garbage, "https://example.com/broken")
    assert isinstance(doc, dict)
    assert "content" in doc


def test_extract_page_handles_empty_html():
    doc = extract_page("", "https://example.com/empty")
    assert doc["content"] == ""
    assert doc["headings"] == []
    assert doc["word_count"] == 0


def test_extract_page_never_executes_scripts_as_content():
    html = "<html><body><script>document.title='hacked';</script><p>Safe text</p></body></html>"
    doc = extract_page(html, "https://example.com/x")
    assert "hacked" not in doc["content"]
    assert "Safe text" in doc["content"]


def test_compute_content_hash_deterministic():
    h1 = compute_content_hash("hello world")
    h2 = compute_content_hash("hello world")
    assert h1 == h2
    assert h1 != compute_content_hash("hello world!")
    assert len(h1) == 64

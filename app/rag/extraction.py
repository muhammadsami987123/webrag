"""HTML content extraction pipeline.

Converts raw HTML into a clean, markdown-like text representation plus
structured metadata (headings, breadcrumbs, canonical URL, publish dates).
Extraction never executes scripts and treats all page content as inert
text data (see task.md section 43, prompt-injection defense) — this module
only parses markup with BeautifulSoup/lxml, it never evals or runs anything
found on the page.
"""
from __future__ import annotations

import hashlib
import json
import re

from bs4 import BeautifulSoup, Tag

# Tags that never contain meaningful reader content.
STRIP_TAGS = {
    "script",
    "style",
    "noscript",
    "iframe",
    "nav",
    "footer",
    "header",
    "aside",
    "form",
    "svg",
    "button",
    "input",
    "select",
    "textarea",
    "template",
}

# class/id substrings that indicate boilerplate/noise sections.
NOISE_PATTERN = re.compile(
    r"cookie|banner|advert|social|share|newsletter|sidebar|menu|breadcrumb-widget|"
    r"popup|modal|promo|subscribe|related-posts|comments|widget|masthead|toolbar",
    re.IGNORECASE,
)

HEADING_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6"]


def compute_content_hash(content: str) -> str:
    """Return a sha256 hex digest of `content`, used for change detection."""
    return hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()


def _make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _is_noise(tag: Tag) -> bool:
    if not isinstance(tag, Tag):
        return False
    classes = " ".join(tag.get("class", []) or [])
    tag_id = tag.get("id", "") or ""
    role = tag.get("role", "") or ""
    combined = f"{classes} {tag_id} {role}"
    return bool(NOISE_PATTERN.search(combined))


def _strip_boilerplate(soup: BeautifulSoup) -> None:
    for tag_name in STRIP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for tag in soup.find_all(True):
        if tag.name in ("html", "body"):
            continue
        if _is_noise(tag):
            tag.decompose()

    # Remove HTML comments.
    for comment in soup.find_all(string=lambda s: s.__class__.__name__ == "Comment"):
        comment.extract()


def _extract_title(soup: BeautifulSoup) -> str:
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return ""


def _extract_canonical(soup: BeautifulSoup) -> str | None:
    link = soup.find("link", rel=lambda v: v and "canonical" in v)
    if link and link.get("href"):
        return link["href"].strip()
    return None


def _extract_meta_date(soup: BeautifulSoup, prop_names: list[str]) -> str | None:
    for prop in prop_names:
        meta = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        if meta and meta.get("content"):
            return meta["content"].strip()
    time_tag = soup.find("time", attrs={"datetime": True})
    if time_tag:
        return time_tag["datetime"].strip()
    return None


def _extract_breadcrumbs(soup: BeautifulSoup) -> list[str]:
    nav = soup.find("nav", attrs={"aria-label": re.compile("breadcrumb", re.IGNORECASE)})
    if nav:
        items = [a.get_text(strip=True) for a in nav.find_all(["a", "span"]) if a.get_text(strip=True)]
        if items:
            return items

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if candidate.get("@type") == "BreadcrumbList":
                items = sorted(
                    candidate.get("itemListElement", []),
                    key=lambda e: e.get("position", 0),
                )
                names = []
                for item in items:
                    name = item.get("name")
                    if not name and isinstance(item.get("item"), dict):
                        name = item["item"].get("name")
                    if name:
                        names.append(name)
                if names:
                    return names
    return []


def _table_to_markdown(table: Tag) -> str:
    rows = table.find_all("tr")
    if not rows:
        return ""
    lines = []
    for idx, row in enumerate(rows):
        cells = row.find_all(["th", "td"])
        cell_text = [c.get_text(strip=True).replace("|", "\\|") for c in cells]
        if not cell_text:
            continue
        lines.append("| " + " | ".join(cell_text) + " |")
        if idx == 0:
            lines.append("| " + " | ".join(["---"] * len(cell_text)) + " |")
    return "\n".join(lines)


def _find_main_content(soup: BeautifulSoup) -> Tag:
    main = soup.find("main")
    if main:
        return main
    article = soup.find("article")
    if article:
        return article
    body = soup.find("body")
    return body if body else soup


def _render_markdown(root: Tag) -> tuple[str, list[dict]]:
    """Walk the tree depth-first rendering block-level content to markdown-ish
    text while recording headings in document order."""
    lines: list[str] = []
    headings: list[dict] = []
    seen_ids: set[int] = set()

    def emit(text: str) -> None:
        text = text.strip()
        if text:
            lines.append(text)

    def walk(node: Tag) -> None:
        for child in node.children:
            if not isinstance(child, Tag):
                continue
            if id(child) in seen_ids:
                continue

            name = child.name

            if name in HEADING_TAGS:
                seen_ids.add(id(child))
                level = int(name[1])
                text = child.get_text(" ", strip=True)
                if text:
                    headings.append({"level": level, "text": text})
                    emit("#" * level + " " + text)
                continue

            if name == "p":
                seen_ids.add(id(child))
                text = child.get_text(" ", strip=True)
                emit(text)
                continue

            if name in ("ul", "ol"):
                seen_ids.add(id(child))
                items = child.find_all("li", recursive=False)
                for li_idx, li in enumerate(items):
                    text = li.get_text(" ", strip=True)
                    if not text:
                        continue
                    prefix = f"{li_idx + 1}." if name == "ol" else "-"
                    emit(f"{prefix} {text}")
                continue

            if name == "table":
                seen_ids.add(id(child))
                md_table = _table_to_markdown(child)
                emit(md_table)
                continue

            if name == "blockquote":
                seen_ids.add(id(child))
                text = child.get_text(" ", strip=True)
                if text:
                    emit(f"> {text}")
                continue

            if name in ("pre", "code"):
                seen_ids.add(id(child))
                text = child.get_text("\n", strip=True)
                if text:
                    emit(f"```\n{text}\n```")
                continue

            # Container element: recurse.
            walk(child)

    walk(root)
    return "\n\n".join(lines), headings


def extract_page(html: str, url: str) -> dict:
    """Extract clean content and metadata from raw page HTML.

    Never raises: on malformed/garbage HTML this returns a best-effort or
    empty result instead of propagating an exception.

    Returns a dict shaped for `app.schemas.models.SourceDocument` (minus
    workspace_id/document_id, which the caller assigns):
        {
            "url": str,
            "canonical_url": str | None,
            "title": str,
            "content": str,               # markdown-like text
            "headings": [{"level": int, "text": str}, ...],
            "breadcrumbs": [str, ...],
            "word_count": int,
            "content_hash": str,
            "published_at": str | None,
            "modified_at": str | None,
        }
    """
    empty_result = {
        "url": url,
        "canonical_url": None,
        "title": "",
        "content": "",
        "headings": [],
        "breadcrumbs": [],
        "word_count": 0,
        "content_hash": compute_content_hash(""),
        "published_at": None,
        "modified_at": None,
    }

    if not html or not html.strip():
        return empty_result

    try:
        soup = _make_soup(html)
        title = _extract_title(soup)
        canonical = _extract_canonical(soup)
        published_at = _extract_meta_date(soup, ["article:published_time", "og:published_time", "datePublished"])
        modified_at = _extract_meta_date(soup, ["article:modified_time", "og:updated_time", "dateModified"])
        breadcrumbs = _extract_breadcrumbs(soup)

        _strip_boilerplate(soup)
        main_root = _find_main_content(soup)
        content, headings = _render_markdown(main_root)

        if title:
            content = f"# {title}\n\n{content}" if content else f"# {title}"

        word_count = len(content.split())

        return {
            "url": url,
            "canonical_url": canonical,
            "title": title,
            "content": content,
            "headings": headings,
            "breadcrumbs": breadcrumbs,
            "word_count": word_count,
            "content_hash": compute_content_hash(content),
            "published_at": published_at,
            "modified_at": modified_at,
        }
    except Exception:
        # Defensive: never let malformed HTML crash the caller.
        return empty_result

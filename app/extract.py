"""Turn raw HTML / uploaded files into plain text, and plain text into chunks."""
from __future__ import annotations

import io
import re

from bs4 import BeautifulSoup, Comment

_NOISE_TAGS = ["script", "style", "noscript", "template", "svg", "iframe", "nav", "footer", "header", "form", "button"]
FILE_TYPES = {".pdf", ".docx", ".txt", ".md", ".csv"}


def _resolve_streamed_suspense(soup: BeautifulSoup) -> None:
    """Next.js/React streaming SSR ships a loading skeleton in place and the real
    markup later as <div hidden id="S:N">, swapped in by JS. Do that swap statically."""
    for segment in soup.find_all("div", id=re.compile(r"^S:\d+$")):
        boundary = soup.find("template", id=f"B:{segment['id'][2:]}")
        if boundary is None:
            continue
        depth, node = 0, boundary.next_sibling
        while node is not None:  # drop fallback up to the matching <!--/$-->
            nxt = node.next_sibling
            if isinstance(node, Comment):
                marker = str(node).strip()
                if marker.startswith("$"):
                    depth += 1
                elif marker == "/$":
                    if depth == 0:
                        break
                    depth -= 1
            node.extract()
            node = nxt
        for child in list(segment.contents):
            boundary.insert_before(child.extract())
        boundary.decompose()
        segment.decompose()


def html_to_text(html: str) -> tuple[str, str, BeautifulSoup]:
    """Return (title, text, soup). The soup is returned so callers can read links."""
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else ""
    links_soup = BeautifulSoup(html, "lxml")

    _resolve_streamed_suspense(soup)
    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    text = root.get_text("\n", strip=True)
    if len(text.split()) < 50 and root is not soup.body and soup.body:
        text = soup.body.get_text("\n", strip=True)
    return title, _clean(text), links_soup


def file_to_text(filename: str, data: bytes) -> str:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return _clean("\n\n".join(page.extract_text() or "" for page in reader.pages))
    if ext == ".docx":
        from docx import Document

        doc = Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        return _clean("\n".join(parts))
    if ext in {".txt", ".md", ".csv"}:
        return _clean(data.decode("utf-8", errors="replace"))
    raise ValueError(f"Unsupported file type: {ext or filename}")


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Greedy paragraph packing into ~size-char chunks, with character overlap."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        while len(para) > size:  # hard-split very long paragraphs
            cut = para.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:cut].strip())
            para = para[max(cut - overlap, 1):].strip()
        if len(current) + len(para) + 1 > size and current:
            chunks.append(current)
            current = current[-overlap:].split(" ", 1)[-1] if overlap else ""
        current = f"{current}\n{para}".strip()
    if current:
        chunks.append(current)
    return chunks


def _clean(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

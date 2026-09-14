"""Heading-aware chunking of extracted SourceDocument content into Chunk records.

Splits markdown-like document content into sections by heading (#, ##, ###),
tracks heading hierarchy (heading_path), then splits each section into
overlapping chunks of roughly `chunk_size` characters, preferring to break on
sentence/paragraph boundaries rather than mid-sentence.
"""
from __future__ import annotations

import hashlib
import re

from app.schemas.models import Chunk, SourceDocument

try:  # extraction module is owned by another agent; fall back gracefully if absent.
    from app.rag.extraction import compute_content_hash  # type: ignore
except ImportError:  # pragma: no cover - exercised only before extraction.py lands

    def compute_content_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
# Sentence boundary: '. ', '! ', '? ' followed by whitespace, or a newline.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")


class _Section:
    __slots__ = ("heading_path", "section_title", "lines")

    def __init__(self, heading_path: list[str], section_title: str | None):
        self.heading_path = heading_path
        self.section_title = section_title
        self.lines: list[str] = []

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()


def _split_into_sections(content: str) -> list[_Section]:
    """Walk the document line by line, tracking heading hierarchy."""
    sections: list[_Section] = []
    # stack[i] = heading text at level i+1 (1-indexed headings)
    stack: dict[int, str] = {}
    current_path: list[str] = []
    current_title: str | None = None
    current = _Section(list(current_path), current_title)
    sections.append(current)

    for raw_line in content.splitlines():
        match = _HEADING_RE.match(raw_line.strip())
        if match:
            level = len(match.group(1))
            text = match.group(2).strip()
            # Drop deeper/equal levels from the stack, then push this heading.
            stack = {lvl: h for lvl, h in stack.items() if lvl < level}
            stack[level] = text
            current_path = [stack[lvl] for lvl in sorted(stack.keys())]
            current_title = text
            current = _Section(list(current_path), current_title)
            sections.append(current)
            continue
        current.lines.append(raw_line)

    # Drop empty leading/placeholder sections.
    return [s for s in sections if s.text]


def _split_paragraphs(text: str) -> list[str]:
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(text) if p.strip()]
    return paragraphs or ([text.strip()] if text.strip() else [])


def _split_sentences(paragraph: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(paragraph) if p.strip()]
    return parts or [paragraph]


def _hard_split(text: str, size: int) -> list[str]:
    """Fallback: split a giant sentence-less blob into hard character windows."""
    return [text[i : i + size] for i in range(0, len(text), size)] or [text]


def _pack_section(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Pack section text into ~chunk_size windows, preferring sentence/paragraph
    boundaries, with `overlap` characters of overlap between consecutive windows.
    """
    if not text:
        return []

    # Build a flat list of atomic units (sentences within paragraphs), each
    # short enough to combine; a unit longer than chunk_size is hard-split.
    units: list[str] = []
    for paragraph in _split_paragraphs(text):
        if len(paragraph) <= chunk_size:
            units.append(paragraph)
            continue
        for sentence in _split_sentences(paragraph):
            if len(sentence) <= chunk_size:
                units.append(sentence)
            else:
                units.extend(_hard_split(sentence, chunk_size))

    if not units:
        return []

    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current} {unit}".strip() if current else unit
        if len(candidate) <= chunk_size or not current:
            current = candidate
        else:
            chunks.append(current)
            if overlap > 0:
                tail = current[-overlap:]
                current = f"{tail} {unit}".strip()
            else:
                current = unit
    if current:
        chunks.append(current)

    return chunks


def chunk_document(
    doc: SourceDocument,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[Chunk]:
    """Split a SourceDocument's content into heading-aware, overlapping Chunks."""
    if chunk_size is None or overlap is None:
        from app.config import get_settings

        settings = get_settings()
        chunk_size = chunk_size if chunk_size is not None else settings.chunk_size
        overlap = overlap if overlap is not None else settings.chunk_overlap

    overlap = min(overlap, max(chunk_size - 1, 0))

    sections = _split_into_sections(doc.content or "")
    chunks: list[Chunk] = []
    chunk_index = 0

    for section in sections:
        pieces = _pack_section(section.text, chunk_size, overlap)
        for piece in pieces:
            chunk_id = f"{doc.document_id}:{chunk_index}"
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    workspace_id=doc.workspace_id,
                    document_id=doc.document_id,
                    source_url=doc.url,
                    page_title=doc.title,
                    section=section.section_title,
                    heading_path=section.heading_path,
                    chunk_index=chunk_index,
                    content=piece,
                    content_hash=compute_content_hash(piece),
                )
            )
            chunk_index += 1

    return chunks

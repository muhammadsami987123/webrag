from app.rag.chunking import chunk_document
from app.schemas.models import Heading, SourceDocument


def _make_doc(content: str, document_id: str = "doc1") -> SourceDocument:
    return SourceDocument(
        document_id=document_id,
        workspace_id="ws1",
        url="https://example.com/page",
        title="Example Page",
        content=content,
        headings=[],
        source_type="webpage",
    )


def test_chunking_preserves_heading_hierarchy():
    content = (
        "# Intro\n"
        "This is the introduction paragraph explaining the topic in detail. "
        "It has more than one sentence here.\n\n"
        "## Details\n"
        "This is a details section under Intro. It goes deeper into specifics. "
        "More content follows to pad this section out a bit.\n\n"
        "# Second Top Level\n"
        "This is a completely different top-level section with its own content."
    )
    doc = _make_doc(content)
    chunks = chunk_document(doc, chunk_size=500, overlap=50)

    assert len(chunks) >= 3
    # First section: heading_path == ["Intro"]
    intro_chunks = [c for c in chunks if c.heading_path == ["Intro"]]
    assert intro_chunks
    assert intro_chunks[0].section == "Intro"

    # Nested section: heading_path == ["Intro", "Details"]
    details_chunks = [c for c in chunks if c.heading_path == ["Intro", "Details"]]
    assert details_chunks
    assert details_chunks[0].section == "Details"

    # Second top-level section resets hierarchy.
    second_chunks = [c for c in chunks if c.heading_path == ["Second Top Level"]]
    assert second_chunks

    # chunk_id is deterministic: f"{document_id}:{chunk_index}"
    for i, c in enumerate(chunks):
        assert c.chunk_id == f"doc1:{i}"
        assert c.chunk_index == i
        assert c.workspace_id == "ws1"
        assert c.document_id == "doc1"
        assert c.content_hash  # sha256 hex digest present


def test_chunking_respects_size_and_overlap():
    # One giant paragraph with many sentences, no headings.
    sentence = "The quick brown fox jumps over the lazy dog in the park today. "
    content = sentence * 40  # ~2720 chars, well beyond chunk_size
    doc = _make_doc(content, document_id="doc2")

    chunk_size = 300
    overlap = 60
    chunks = chunk_document(doc, chunk_size=chunk_size, overlap=overlap)

    assert len(chunks) > 1
    for c in chunks:
        # Chunks should be roughly chunk_size or smaller (allow slack for one
        # extra unit that pushed it over before a new chunk was started).
        assert len(c.content) <= chunk_size + len(sentence)

    # Consecutive chunks in the same section should share overlapping text.
    for prev, curr in zip(chunks, chunks[1:]):
        tail = prev.content[-overlap:]
        # The overlap tail (or a good portion of it) should appear at the
        # start of the next chunk, confirming overlap was applied.
        assert tail[: overlap // 2] in curr.content[: overlap + len(sentence)]


def test_chunking_no_headings_still_chunks():
    content = "Just a plain paragraph with no headings at all in this document body."
    doc = _make_doc(content, document_id="doc3")
    chunks = chunk_document(doc, chunk_size=1000, overlap=100)

    assert len(chunks) == 1
    assert chunks[0].heading_path == []
    assert chunks[0].section is None
    assert chunks[0].content == content


def test_chunking_never_splits_mid_sentence_when_avoidable():
    content = (
        "# Section\n"
        "First sentence here is short. Second sentence is also fairly short. "
        "Third sentence rounds things out nicely."
    )
    doc = _make_doc(content, document_id="doc4")
    chunks = chunk_document(doc, chunk_size=60, overlap=10)

    for c in chunks:
        stripped = c.content.strip()
        # Each chunk should end at a sentence boundary (., !, ?) in this
        # scenario since no single sentence exceeds chunk_size.
        assert stripped[-1] in ".!?"

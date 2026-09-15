"""Offline tests: extraction, chunking, SSRF guard, and the API with OpenAI faked."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.extract import chunk_text, file_to_text, html_to_text
from app.web import FetchError, _check_url


def test_html_to_text_resolves_nextjs_streamed_content():
    html = """<html><head><title>T</title></head><body>
    <main><!--$?--><template id="B:0"></template><div>Loading page</div><!--/$--></main>
    <div hidden id="S:0"><h1>Real Heading</h1><div>Actual streamed body text.</div></div>
    <footer>footer links</footer></body></html>"""
    title, text, _ = html_to_text(html)
    assert title == "T"
    assert "Real Heading" in text and "Actual streamed body text." in text
    assert "Loading page" not in text and "footer links" not in text


def test_chunk_text_respects_size():
    text = "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(20))
    chunks = chunk_text(text, size=500, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 560 for c in chunks)
    assert "Paragraph 19" in chunks[-1]


def test_docx_and_txt_parsing():
    doc = Document()
    doc.add_paragraph("Hello from docx")
    buf = io.BytesIO()
    doc.save(buf)
    assert "Hello from docx" in file_to_text("a.docx", buf.getvalue())
    assert file_to_text("a.md", b"# Title\n\nbody") == "# Title\n\nbody"
    with pytest.raises(ValueError):
        file_to_text("a.exe", b"x")


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost:8000", "http://169.254.169.254/latest", "file:///etc/passwd", "http://10.0.0.5"])
def test_ssrf_guard_blocks_internal(url):
    with pytest.raises(FetchError):
        asyncio.run(_check_url(url))


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import llm, main
    from app.config import settings
    from app.store import Store

    monkeypatch.setattr(settings, "openai_api_key", "test")
    monkeypatch.setattr(main, "store", Store(tmp_path))

    async def fake_embed(texts):  # deterministic bag-of-words-ish vectors
        vecs = []
        for t in texts:
            v = [0.0] * 64
            for w in t.lower().split():
                v[int(hashlib.md5(w.strip(".,?!").encode()).hexdigest(), 16) % 64] += 1
            vecs.append(v)
        return vecs

    async def fake_stream(question, contexts, history):
        yield f"Answer using {len(contexts)} sources [1]"

    monkeypatch.setattr(llm, "embed", fake_embed)
    monkeypatch.setattr(llm, "stream_answer", fake_stream)
    return TestClient(main.app)


def test_upload_chat_delete_flow(client):
    files = [("files", ("notes.txt", b"MARSA is a women's health and safety app.", "text/plain"))]
    res = client.post("/api/sources/files", files=files)
    assert res.status_code == 200
    source = res.json()[0]
    assert source["status"] == "ready" and source["chunks"] == 1

    res = client.post("/api/chat", json={"question": "What is MARSA app?"})
    events = [block for block in res.text.split("\n\n") if block]
    assert events[0].startswith("event: sources")
    assert json.loads(events[0].split("data: ", 1)[1])[0]["name"] == "notes.txt"
    assert any("Answer using 1 sources" in e for e in events)
    assert events[-1].startswith("event: done")

    assert client.delete(f"/api/sources/{source['id']}").status_code == 204
    assert client.get("/api/sources").json() == []


def test_unsupported_upload_is_marked_failed(client):
    res = client.post("/api/sources/files", files=[("files", ("x.exe", b"bin", "application/octet-stream"))])
    assert res.json()[0]["status"] == "failed"


def test_index_page_served(client):
    assert "WebRAG" in client.get("/").text

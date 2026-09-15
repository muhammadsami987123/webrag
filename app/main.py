"""WebRAG: add websites and files, then chat with them using OpenAI."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

from app import llm
from app.config import settings
from app.extract import FILE_TYPES, chunk_text, file_to_text
from app.store import store
from app.web import FetchError, crawl

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("webrag")

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
app = FastAPI(title="WebRAG")
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


class UrlIn(BaseModel):
    url: HttpUrl
    max_pages: int = Field(default=settings.max_pages, ge=1, le=100)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    history: list[ChatMessage] = []


def _chunk_items(text: str, source_name: str, location: str) -> list[dict]:
    return [
        {"text": c, "source_name": source_name, "location": location}
        for c in chunk_text(text, settings.chunk_size, settings.chunk_overlap)
    ]


async def _index(source_id: str, items: list[dict], pages: int) -> None:
    if not items:
        raise ValueError("No readable text found")
    vectors = await llm.embed([i["text"] for i in items])
    await store.add_chunks(source_id, items, vectors)
    await store.update_source(source_id, status="ready", pages=pages, chunks=len(items))


async def _ingest_url(source_id: str, url: str, max_pages: int) -> None:
    try:
        pages = await crawl(url, max_pages)
        items = [item for p in pages for item in _chunk_items(p["text"], p["title"], p["url"])]
        await _index(source_id, items, len(pages))
        logger.info("Indexed %s: %d pages, %d chunks", url, len(pages), len(items))
    except Exception as exc:
        logger.exception("Failed to ingest %s", url)
        message = str(exc) if isinstance(exc, (FetchError, ValueError, RuntimeError)) else "Failed to fetch or index website"
        await store.update_source(source_id, status="failed", error=message)


# --- routes ------------------------------------------------------------------


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


@app.get("/api/status")
async def status() -> dict:
    return {"openai_configured": bool(settings.openai_api_key), "chat_model": settings.chat_model}


@app.get("/api/sources")
async def list_sources() -> list[dict]:
    return store.sources


@app.post("/api/sources/url", status_code=202)
async def add_url(body: UrlIn, background: BackgroundTasks) -> dict:
    source = await store.create_source("url", str(body.url))
    background.add_task(_ingest_url, source["id"], str(body.url), body.max_pages)
    return source


@app.post("/api/sources/files")
async def add_files(files: list[UploadFile]) -> list[dict]:
    results = []
    for upload in files:
        name = upload.filename or "file"
        source = await store.create_source("file", name)
        try:
            ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in FILE_TYPES:
                raise ValueError(f"Unsupported file type. Use: {', '.join(sorted(FILE_TYPES))}")
            data = await upload.read(settings.max_upload_mb * 1024 * 1024 + 1)
            if len(data) > settings.max_upload_mb * 1024 * 1024:
                raise ValueError(f"File larger than {settings.max_upload_mb} MB")
            text = await asyncio.to_thread(file_to_text, name, data)
            await _index(source["id"], _chunk_items(text, name, name), 1)
        except Exception as exc:
            logger.exception("Failed to ingest file %s", name)
            await store.update_source(source["id"], status="failed", error=str(exc) or "Could not read file")
        results.append(next(s for s in store.sources if s["id"] == source["id"]))
    return results


@app.delete("/api/sources/{source_id}", status_code=204)
async def delete_source(source_id: str) -> None:
    if not await store.delete_source(source_id):
        raise HTTPException(404, "Source not found")


@app.post("/api/chat")
async def chat(body: ChatIn) -> StreamingResponse:
    if not settings.openai_api_key:
        raise HTTPException(400, "OPENAI_API_KEY is not set in .env")

    async def events():
        def sse(event: str, data) -> str:
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        try:
            query_vec = (await llm.embed([body.question]))[0]
            contexts = store.search(query_vec, settings.top_k)
            yield sse(
                "sources",
                [
                    {"n": i, "name": c["source_name"], "location": c["location"], "snippet": c["text"][:280]}
                    for i, c in enumerate(contexts, 1)
                ],
            )
            history = [m.model_dump() for m in body.history]
            async for token in llm.stream_answer(body.question, contexts, history):
                yield sse("token", token)
            yield sse("done", {})
        except Exception as exc:
            logger.exception("Chat failed")
            yield sse("error", str(exc))

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

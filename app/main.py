"""FastAPI application entry point: wires all routers, middleware, static
frontend hosting, health check, and structured logging/error handling."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import (
    chat,
    compare,
    crawler,
    extraction,
    notebook,
    search,
    sources,
    summaries,
    topics,
    workspaces,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="WebRAG", description="Real URL-to-RAG research workspace")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workspaces.router)
app.include_router(crawler.router)
app.include_router(sources.router)
app.include_router(chat.router)
app.include_router(search.router)
app.include_router(summaries.router)
app.include_router(topics.router)
app.include_router(compare.router)
app.include_router(extraction.router)
app.include_router(notebook.router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "An internal error occurred."})


_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
_FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")

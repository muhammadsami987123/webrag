"""Single knowledge base persisted to DATA_DIR: sources.json, chunks.json, vectors.npy."""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.config import settings


def _atomic_write(path: Path, write) -> None:
    tmp = path.with_name(path.name + ".tmp")
    write(tmp)
    for attempt in range(10):  # Windows: target may be briefly locked by a reader/antivirus
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.05 * (attempt + 1))


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.dir = data_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = asyncio.Lock()
        self.sources: list[dict] = self._load_json("sources.json")
        self.chunks: list[dict] = self._load_json("chunks.json")
        vec_path = self.dir / "vectors.npy"
        self.vectors = np.load(vec_path) if vec_path.exists() else np.zeros((0, 0), dtype=np.float32)
        if len(self.vectors) != len(self.chunks):  # inconsistent state: start clean
            self.chunks, self.vectors = [], np.zeros((0, 0), dtype=np.float32)
        for s in self.sources:  # anything mid-ingestion at shutdown will never finish
            if s["status"] == "processing":
                s.update(status="failed", error="Interrupted by server restart")

    def _load_json(self, name: str) -> list[dict]:
        path = self.dir / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def _save(self) -> None:
        for name, data in (("sources.json", self.sources), ("chunks.json", self.chunks)):
            _atomic_write(self.dir / name, lambda p, d=data: p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8"))
        def write_vectors(p: Path) -> None:
            with open(p, "wb") as f:
                np.save(f, self.vectors)

        _atomic_write(self.dir / "vectors.npy", write_vectors)

    # --- sources -------------------------------------------------------------

    async def create_source(self, kind: str, name: str) -> dict:
        source = {
            "id": uuid.uuid4().hex[:12],
            "kind": kind,
            "name": name,
            "status": "processing",
            "error": None,
            "pages": 0,
            "chunks": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        async with self.lock:
            self.sources.insert(0, source)
            await asyncio.to_thread(self._save)
        return source

    async def update_source(self, source_id: str, **fields) -> None:
        async with self.lock:
            for s in self.sources:
                if s["id"] == source_id:
                    s.update(fields)
            await asyncio.to_thread(self._save)

    async def add_chunks(self, source_id: str, items: list[dict], vectors: list[list[float]]) -> None:
        """items: [{text, source_name, location}]"""
        if not items:
            return
        new = np.asarray(vectors, dtype=np.float32)
        new /= np.linalg.norm(new, axis=1, keepdims=True) + 1e-12
        async with self.lock:
            self.vectors = new if self.vectors.size == 0 else np.vstack([self.vectors, new])
            self.chunks.extend({**item, "source_id": source_id} for item in items)
            await asyncio.to_thread(self._save)

    async def delete_source(self, source_id: str) -> bool:
        async with self.lock:
            before = len(self.sources)
            self.sources = [s for s in self.sources if s["id"] != source_id]
            keep = [i for i, c in enumerate(self.chunks) if c["source_id"] != source_id]
            self.chunks = [self.chunks[i] for i in keep]
            self.vectors = self.vectors[keep] if keep else np.zeros((0, 0), dtype=np.float32)
            await asyncio.to_thread(self._save)
            return len(self.sources) < before

    # --- search --------------------------------------------------------------

    def search(self, query_vector: list[float], k: int) -> list[dict]:
        if self.vectors.size == 0:
            return []
        q = np.asarray(query_vector, dtype=np.float32)
        q /= np.linalg.norm(q) + 1e-12
        scores = self.vectors @ q
        top = np.argsort(-scores)[:k]
        return [{**self.chunks[i], "score": float(scores[i])} for i in top if scores[i] > 0.15]


store = Store(settings.data_dir)

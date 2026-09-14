"""Persistence for notes, highlights, collections, chat history, and the
change-detection snapshots used for section 30 (website-changes) diffing.

Each of notes.json / highlights.json / collections.json is a simple JSON
list of dict records, each carrying at least ``id`` and ``created_at``.
Chat history is one JSON file per conversation under chat/<conversation_id>.json,
a list of serialized ChatMessage. Snapshots are timestamped JSON files under
snapshots/<timestamp>.json holding a {url: content_hash} map.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.schemas.models import ChatMessage, SourceDocument
from app.storage._atomic import atomic_write_json, read_json


def _new_id() -> str:
    return uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MetadataStore:
    """Notes / highlights / collections / chat / snapshot persistence."""

    def __init__(self, base_path: Path | None = None) -> None:
        self._settings = get_settings()
        self._base_path = Path(base_path) if base_path is not None else self._settings.storage_root

    # ------------------------------------------------------------------ #
    # path helpers
    # ------------------------------------------------------------------ #
    def _workspace_dir(self, workspace_id: str) -> Path:
        d = self._base_path / "workspaces" / workspace_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _list_path(self, workspace_id: str, name: str) -> Path:
        return self._workspace_dir(workspace_id) / name

    def _chat_dir(self, workspace_id: str) -> Path:
        d = self._workspace_dir(workspace_id) / "chat"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _snapshots_dir(self, workspace_id: str) -> Path:
        d = self._workspace_dir(workspace_id) / "snapshots"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ------------------------------------------------------------------ #
    # generic record list helpers
    # ------------------------------------------------------------------ #
    def _append_record(self, workspace_id: str, filename: str, fields: dict[str, Any]) -> dict[str, Any]:
        path = self._list_path(workspace_id, filename)
        records: list[dict[str, Any]] = read_json(path) or []
        record = {"id": _new_id(), "created_at": _now_iso(), **fields}
        records.append(record)
        atomic_write_json(path, records)
        return record

    def _list_records(self, workspace_id: str, filename: str) -> list[dict[str, Any]]:
        path = self._list_path(workspace_id, filename)
        return read_json(path) or []

    def _delete_record(self, workspace_id: str, filename: str, record_id: str) -> None:
        path = self._list_path(workspace_id, filename)
        records: list[dict[str, Any]] = read_json(path) or []
        remaining = [r for r in records if r.get("id") != record_id]
        atomic_write_json(path, remaining)

    # ------------------------------------------------------------------ #
    # notes
    # ------------------------------------------------------------------ #
    def add_note(self, workspace_id: str, **fields: Any) -> dict[str, Any]:
        return self._append_record(workspace_id, "notes.json", fields)

    def list_notes(self, workspace_id: str) -> list[dict[str, Any]]:
        return self._list_records(workspace_id, "notes.json")

    def delete_note(self, workspace_id: str, note_id: str) -> None:
        self._delete_record(workspace_id, "notes.json", note_id)

    # ------------------------------------------------------------------ #
    # highlights
    # ------------------------------------------------------------------ #
    def add_highlight(self, workspace_id: str, **fields: Any) -> dict[str, Any]:
        return self._append_record(workspace_id, "highlights.json", fields)

    def list_highlights(self, workspace_id: str) -> list[dict[str, Any]]:
        return self._list_records(workspace_id, "highlights.json")

    # ------------------------------------------------------------------ #
    # collections
    # ------------------------------------------------------------------ #
    def add_collection(self, workspace_id: str, **fields: Any) -> dict[str, Any]:
        return self._append_record(workspace_id, "collections.json", fields)

    def list_collections(self, workspace_id: str) -> list[dict[str, Any]]:
        return self._list_records(workspace_id, "collections.json")

    # ------------------------------------------------------------------ #
    # chat history
    # ------------------------------------------------------------------ #
    def save_chat_message(self, workspace_id: str, conversation_id: str, message: ChatMessage) -> None:
        path = self._chat_dir(workspace_id) / f"{conversation_id}.json"
        history: list[dict[str, Any]] = read_json(path) or []
        history.append(message.model_dump(mode="json"))
        atomic_write_json(path, history)

    def load_chat_history(self, workspace_id: str, conversation_id: str) -> list[ChatMessage]:
        path = self._chat_dir(workspace_id) / f"{conversation_id}.json"
        data = read_json(path) or []
        return [ChatMessage.model_validate(item) for item in data]

    # ------------------------------------------------------------------ #
    # snapshots / change detection (section 30)
    # ------------------------------------------------------------------ #
    def save_snapshot(self, workspace_id: str, documents: list[SourceDocument]) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        url_hashes = {doc.url: doc.content_hash for doc in documents}
        payload = {"timestamp": _now_iso(), "url_hashes": url_hashes}
        atomic_write_json(self._snapshots_dir(workspace_id) / f"{timestamp}.json", payload)

    def _latest_snapshot(self, workspace_id: str) -> dict[str, Any] | None:
        snap_dir = self._snapshots_dir(workspace_id)
        files = sorted(snap_dir.glob("*.json"))
        if not files:
            return None
        return read_json(files[-1])

    def diff_against_last_snapshot(
        self, workspace_id: str, current_documents: list[SourceDocument]
    ) -> dict[str, Any]:
        current = {doc.url: doc.content_hash for doc in current_documents}
        snapshot = self._latest_snapshot(workspace_id)
        previous: dict[str, str] = (snapshot or {}).get("url_hashes", {})

        new_urls = [url for url in current if url not in previous]
        removed_urls = [url for url in previous if url not in current]
        changed_urls = [
            url for url in current if url in previous and previous[url] != current[url]
        ]
        unchanged_count = sum(
            1 for url in current if url in previous and previous[url] == current[url]
        )

        return {
            "new": new_urls,
            "removed": removed_urls,
            "changed": changed_urls,
            "unchanged_count": unchanged_count,
        }

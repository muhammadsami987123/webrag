"""Simple CRUD for notes, highlights, and collections (section 21)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import workspace_service
from app.storage.metadata_store import MetadataStore

router = APIRouter(prefix="/api/workspaces", tags=["notebook"])
_metadata_store = MetadataStore()


def _require_workspace(workspace_id: str) -> None:
    if workspace_service.get_workspace(workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")


class NoteRequest(BaseModel):
    document_id: str | None = None
    text: str
    tags: list[str] = []


class HighlightRequest(BaseModel):
    document_id: str
    text: str
    note: str | None = None


class CollectionRequest(BaseModel):
    name: str
    document_ids: list[str] = []


@router.post("/{workspace_id}/notes")
async def create_note(workspace_id: str, body: NoteRequest) -> dict[str, Any]:
    _require_workspace(workspace_id)
    return _metadata_store.add_note(workspace_id, **body.model_dump())


@router.get("/{workspace_id}/notes")
async def list_notes(workspace_id: str) -> list[dict[str, Any]]:
    _require_workspace(workspace_id)
    return _metadata_store.list_notes(workspace_id)


@router.post("/{workspace_id}/highlights")
async def create_highlight(workspace_id: str, body: HighlightRequest) -> dict[str, Any]:
    _require_workspace(workspace_id)
    return _metadata_store.add_highlight(workspace_id, **body.model_dump())


@router.get("/{workspace_id}/highlights")
async def list_highlights(workspace_id: str) -> list[dict[str, Any]]:
    _require_workspace(workspace_id)
    return _metadata_store.list_highlights(workspace_id)


@router.post("/{workspace_id}/collections")
async def create_collection(workspace_id: str, body: CollectionRequest) -> dict[str, Any]:
    _require_workspace(workspace_id)
    return _metadata_store.add_collection(workspace_id, **body.model_dump())


@router.get("/{workspace_id}/collections")
async def list_collections(workspace_id: str) -> list[dict[str, Any]]:
    _require_workspace(workspace_id)
    return _metadata_store.list_collections(workspace_id)

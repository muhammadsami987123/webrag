"""Source document listing, detail, and deletion endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.models import SourceDocument
from app.services import source_service, workspace_service

router = APIRouter(prefix="/api/workspaces", tags=["sources"])


def _require_workspace(workspace_id: str) -> None:
    if workspace_service.get_workspace(workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")


@router.get("/{workspace_id}/sources", response_model=list[SourceDocument])
async def list_sources(workspace_id: str) -> list[SourceDocument]:
    _require_workspace(workspace_id)
    return source_service.list_sources(workspace_id)


@router.get("/{workspace_id}/sources/{document_id}", response_model=SourceDocument)
async def get_source(workspace_id: str, document_id: str) -> SourceDocument:
    _require_workspace(workspace_id)
    doc = source_service.get_source(workspace_id, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Source document not found.")
    return doc


@router.delete("/{workspace_id}/sources/{document_id}", status_code=204)
async def delete_source(workspace_id: str, document_id: str) -> None:
    _require_workspace(workspace_id)
    deleted = await source_service.delete_source(workspace_id, document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Source document not found.")

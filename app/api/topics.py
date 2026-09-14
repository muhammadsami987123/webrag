"""Topics and ask-suggestions endpoints (heuristic, fast, no LLM round trip)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services import research_service, workspace_service

router = APIRouter(prefix="/api/workspaces", tags=["topics"])


def _require_workspace(workspace_id: str) -> None:
    if workspace_service.get_workspace(workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")


@router.get("/{workspace_id}/topics", response_model=list[str])
async def get_topics(workspace_id: str) -> list[str]:
    _require_workspace(workspace_id)
    return await research_service.list_topics(workspace_id)


@router.get("/{workspace_id}/suggestions", response_model=list[str])
async def get_suggestions(workspace_id: str) -> list[str]:
    _require_workspace(workspace_id)
    return await research_service.get_ask_suggestions(workspace_id)

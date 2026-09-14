"""Hierarchical/source summarization endpoint."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.schemas.models import ChatResponse
from app.services import research_service, workspace_service

router = APIRouter(prefix="/api/workspaces", tags=["summaries"])

_LLM_NOT_CONFIGURED_MESSAGE = (
    "AI provider is not configured. Set OPENAI_API_KEY or GEMINI_API_KEY."
)


class SummarizeRequest(BaseModel):
    document_ids: list[str] | None = None
    hierarchical: bool = True


@router.post("/{workspace_id}/summarize", response_model=ChatResponse)
async def summarize(workspace_id: str, body: SummarizeRequest) -> ChatResponse:
    if workspace_service.get_workspace(workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    try:
        return await research_service.summarize_sources(
            workspace_id, document_ids=body.document_ids, hierarchical=body.hierarchical
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=_LLM_NOT_CONFIGURED_MESSAGE) from exc

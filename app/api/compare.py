"""Grounded comparison endpoint."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.schemas.models import ChatResponse
from app.services import research_service, workspace_service

router = APIRouter(prefix="/api/workspaces", tags=["compare"])

_LLM_NOT_CONFIGURED_MESSAGE = (
    "AI provider is not configured. Set OPENAI_API_KEY or GEMINI_API_KEY."
)


class CompareRequest(BaseModel):
    query: str


@router.post("/{workspace_id}/compare", response_model=ChatResponse)
async def compare(workspace_id: str, body: CompareRequest) -> ChatResponse:
    if workspace_service.get_workspace(workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    try:
        return await research_service.compare_topics(workspace_id, body.query)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=_LLM_NOT_CONFIGURED_MESSAGE) from exc

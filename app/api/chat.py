"""Chat / research endpoints: non-streaming, streaming (SSE), and history."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from starlette.responses import StreamingResponse

from app.schemas.models import ChatMessage, ChatRequest, ChatResponse
from app.services import research_service, workspace_service
from app.storage.metadata_store import MetadataStore

router = APIRouter(prefix="/api", tags=["chat"])
_metadata_store = MetadataStore()

_LLM_NOT_CONFIGURED_MESSAGE = (
    "AI provider is not configured. Set OPENAI_API_KEY or GEMINI_API_KEY."
)


def _require_workspace(workspace_id: str) -> None:
    if workspace_service.get_workspace(workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, debug: bool = Query(default=False)) -> ChatResponse:
    _require_workspace(req.workspace_id)
    try:
        return await research_service.answer_question(req, stream=False, debug=debug)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=_LLM_NOT_CONFIGURED_MESSAGE) from exc


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    _require_workspace(req.workspace_id)

    try:
        generator = await research_service.answer_question(req, stream=True)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=_LLM_NOT_CONFIGURED_MESSAGE) from exc

    async def _event_stream():
        try:
            async for item in generator:
                if isinstance(item, dict):
                    yield f"data: {json.dumps(item)}\n\n"
                else:
                    yield f"data: {json.dumps({'delta': item})}\n\n"
        except Exception as exc:  # defensive: never let a raw traceback leak into the stream
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/workspaces/{workspace_id}/chat/history", response_model=list[ChatMessage])
async def chat_history(workspace_id: str, conversation_id: str = Query(default="default")) -> list[ChatMessage]:
    _require_workspace(workspace_id)
    return _metadata_store.load_chat_history(workspace_id, conversation_id)

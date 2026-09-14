"""SSE endpoint that streams live crawl/ingestion progress for a workspace."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException
from starlette.responses import StreamingResponse

from app.schemas.models import WorkspaceStatus
from app.services import workspace_service

router = APIRouter(prefix="/api/workspaces", tags=["crawler"])

_TERMINAL_STATUSES = {WorkspaceStatus.ready, WorkspaceStatus.failed}
_POLL_INTERVAL_SECONDS = 1.0


def _snapshot(workspace) -> dict:
    return {
        "status": workspace.status.value,
        "pages_discovered": workspace.pages_discovered,
        "pages_processed": workspace.pages_processed,
        "chunks_created": workspace.chunks_created,
        "embeddings_created": workspace.embeddings_created,
        "error": workspace.error,
    }


async def _progress_events(workspace_id: str):
    last_payload: str | None = None
    while True:
        workspace = workspace_service.get_workspace(workspace_id)
        if workspace is None:
            yield f"data: {json.dumps({'error': 'workspace not found'})}\n\n"
            return

        payload = json.dumps(_snapshot(workspace))
        if payload != last_payload:
            yield f"data: {payload}\n\n"
            last_payload = payload

        if workspace.status in _TERMINAL_STATUSES:
            return

        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


@router.get("/{workspace_id}/progress/stream")
async def stream_progress(workspace_id: str) -> StreamingResponse:
    workspace = workspace_service.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    return StreamingResponse(
        _progress_events(workspace_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )

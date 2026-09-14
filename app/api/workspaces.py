"""Workspace lifecycle endpoints: create, list, get, delete, reindex."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.schemas.models import CrawlConfig, Workspace
from app.services import workspace_service

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class CreateWorkspaceRequest(BaseModel):
    url: str
    crawl_config: CrawlConfig | None = None


@router.post("", response_model=Workspace, status_code=201)
async def create_workspace(body: CreateWorkspaceRequest, background_tasks: BackgroundTasks) -> Workspace:
    try:
        workspace = await workspace_service.create_workspace(body.url, body.crawl_config)
    except ValueError as exc:
        reason = str(exc)
        if "scheme" in reason:
            raise HTTPException(status_code=400, detail="Please enter a valid public HTTP/HTTPS URL.")
        raise HTTPException(status_code=400, detail="This website does not allow automated access.")

    background_tasks.add_task(_run_ingestion_background, workspace.workspace_id)
    return workspace


async def _run_ingestion_background(workspace_id: str) -> None:
    await workspace_service.run_ingestion(workspace_id)


@router.get("", response_model=list[Workspace])
async def list_workspaces() -> list[Workspace]:
    return workspace_service.list_workspaces()


@router.get("/{workspace_id}", response_model=Workspace)
async def get_workspace(workspace_id: str) -> Workspace:
    workspace = workspace_service.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return workspace


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: str) -> None:
    workspace = workspace_service.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    await workspace_service.delete_workspace(workspace_id)


@router.post("/{workspace_id}/reindex", status_code=202)
async def reindex_workspace(workspace_id: str, background_tasks: BackgroundTasks) -> dict:
    workspace = workspace_service.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    background_tasks.add_task(_run_reindex_background, workspace_id)
    return {"status": "reindexing_started", "workspace_id": workspace_id}


async def _run_reindex_background(workspace_id: str) -> None:
    try:
        await workspace_service.reindex_workspace(workspace_id)
    except Exception:
        import logging

        logging.getLogger(__name__).exception("Reindex failed for workspace %s", workspace_id)

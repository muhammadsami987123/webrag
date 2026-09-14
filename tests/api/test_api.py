"""API-level integration tests using FastAPI's TestClient.

These tests avoid real network access: the crawl is monkeypatched to a fake
implementation that invokes the on_page/on_progress callbacks synchronously
against fixture data, so ingestion completes instantly and deterministically.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    storage_dir = tmp_path / "storage"
    monkeypatch.setenv("STORAGE_PATH", str(storage_dir))
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")

    # Reset the lru_cache'd settings singleton so STORAGE_PATH above takes effect.
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()
    shutil.rmtree(storage_dir, ignore_errors=True)


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_workspace_invalid_url(client):
    response = client.post("/api/workspaces", json={"url": "not-a-url"})
    assert response.status_code == 400


def test_create_workspace_unsafe_url(client):
    # Loopback address: syntactically a valid http URL but must be refused (SSRF guard).
    response = client.post("/api/workspaces", json={"url": "http://127.0.0.1:9999/"})
    assert response.status_code == 400


class _FakeEmbedder:
    dimension = 8

    async def embed(self, texts):
        return [[0.1] * self.dimension for _ in texts]


def test_create_workspace_success(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.workspace_service.get_embedding_provider", lambda: _FakeEmbedder()
    )

    async def fake_crawl_workspace(root_url, crawl_config, on_page, on_progress):
        page = {
            "url": root_url,
            "canonical_url": None,
            "title": "Example Domain",
            "content": "# Example Domain\n\nThis domain is for illustrative examples.",
            "headings": [{"level": 1, "text": "Example Domain"}],
            "breadcrumbs": [],
            "word_count": 8,
            "content_hash": "abc123",
            "published_at": None,
            "modified_at": None,
        }
        await on_page(page)
        await on_progress(1, 1)

    monkeypatch.setattr(
        "app.services.workspace_service.crawl_workspace", fake_crawl_workspace
    )

    response = client.post("/api/workspaces", json={"url": "https://example.com"})
    assert response.status_code == 201
    body = response.json()
    assert body["root_url"] == "https://example.com"
    assert body["status"] in ("pending", "crawling", "processing", "embedding", "ready")
    assert "workspace_id" in body


def test_get_workspace_not_found(client):
    response = client.get("/api/workspaces/doesnotexist")
    assert response.status_code == 404


def test_delete_workspace(client, monkeypatch):
    async def fake_crawl_workspace(root_url, crawl_config, on_page, on_progress):
        await on_progress(0, 0)

    monkeypatch.setattr(
        "app.services.workspace_service.crawl_workspace", fake_crawl_workspace
    )

    create_response = client.post("/api/workspaces", json={"url": "https://example.com"})
    assert create_response.status_code == 201
    workspace_id = create_response.json()["workspace_id"]

    get_response = client.get(f"/api/workspaces/{workspace_id}")
    assert get_response.status_code == 200

    delete_response = client.delete(f"/api/workspaces/{workspace_id}")
    assert delete_response.status_code == 204

    get_after_delete = client.get(f"/api/workspaces/{workspace_id}")
    assert get_after_delete.status_code == 404

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_workspace_service
from app.db.app_database import connect_app_database
from app.knowledge.workspace_layout import initialize_knowledge_artifacts
from app.knowledge.sources import MAX_SOURCE_BYTES
from app.main import app
from app.services.workspace_service import WorkspaceService


@pytest.fixture
def knowledge_client(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    connection = connect_app_database(tmp_path / "app-data")
    service = WorkspaceService(connection)
    workspace = service.register(str(workspace_root))
    initialize_knowledge_artifacts(workspace_root, domain="review")
    app.dependency_overrides[get_workspace_service] = lambda: service
    try:
        with TestClient(app) as client:
            yield client, workspace_root, workspace.id
    finally:
        app.dependency_overrides.clear()
        connection.close()


def test_upload_registers_source_without_pretending_a_question_exists(
    knowledge_client,
) -> None:
    client, workspace, workspace_id = knowledge_client

    response = client.post(
        "/api/knowledge/sources",
        data={"workspaceId": workspace_id},
        files={
            "file": (
                "缓存.md",
                "缓存穿透是什么？\n缓存空值和布隆过滤器。".encode(),
                "text/markdown",
            )
        },
    )

    assert response.status_code == 201
    body = response.json()
    source = body["source"]
    assert source["workspaceId"] == workspace_id
    assert source["originalFilename"] == "缓存.md"
    assert source["contentType"] == "text/markdown"
    assert source["sizeBytes"] == len(
        "缓存穿透是什么？\n缓存空值和布隆过滤器。".encode()
    )
    assert source["storedPath"].startswith("artifacts/review/sources/")
    assert not source["storedPath"].startswith("/")
    assert source["draftId"] is None
    assert "draft" not in body
    assert "question" not in body
    assert len(list((workspace / "artifacts/review/sources").iterdir())) == 1
    assert not list((workspace / "knowledge-vault").rglob("*.md"))


def test_list_sources_persists_original_filename_and_isolates_workspace(
    knowledge_client, tmp_path: Path
) -> None:
    client, _workspace, workspace_id = knowledge_client
    content = "缓存穿透是什么？\n缓存空值。".encode()
    uploaded = client.post(
        "/api/knowledge/sources",
        data={"workspaceId": workspace_id},
        files={"file": ("缓存资料.md", content, "text/markdown")},
    ).json()

    response = client.get(
        "/api/knowledge/sources", params={"workspaceId": workspace_id}
    )

    assert response.status_code == 200
    assert response.json() == [uploaded["source"]]
    assert response.json()[0]["originalFilename"] == "缓存资料.md"
    assert response.json()[0]["draftId"] is None

    second_root = tmp_path / "second-workspace"
    second_root.mkdir()
    service = app.dependency_overrides[get_workspace_service]()
    second = service.register(str(second_root))
    isolated = client.get(
        "/api/knowledge/sources", params={"workspaceId": second.id}
    )
    assert isolated.status_code == 200
    assert isolated.json() == []


def test_upload_accepts_unicode_filename(knowledge_client) -> None:
    client, workspace, workspace_id = knowledge_client

    response = client.post(
        "/api/knowledge/sources",
        data={"workspaceId": workspace_id},
        files={"file": ("面试记录.md", "赛博产品设计".encode(), "text/markdown")},
    )

    assert response.status_code == 201
    assert list((workspace / "artifacts/review/sources").glob("*.md"))


@pytest.mark.parametrize("filename", ["../evil.txt", "nested/evil.txt"])
def test_upload_rejects_path_shaped_filename(
    knowledge_client, filename: str
) -> None:
    client, workspace, workspace_id = knowledge_client

    response = client.post(
        "/api/knowledge/sources",
        data={"workspaceId": workspace_id},
        files={"file": (filename, b"unsafe", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "workspace_path_denied"
    assert not list((workspace / "artifacts/review/sources").iterdir())


def test_upload_rejects_symlinked_sources_directory(
    knowledge_client, tmp_path: Path
) -> None:
    client, workspace, workspace_id = knowledge_client
    outside = tmp_path / "outside"
    outside.mkdir()
    sources = workspace / "artifacts/review/sources"
    sources.rmdir()
    sources.symlink_to(outside, target_is_directory=True)

    response = client.post(
        "/api/knowledge/sources",
        data={"workspaceId": workspace_id},
        files={"file": ("notes.md", b"safe", "text/markdown")},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "workspace_path_denied"
    assert not list(outside.iterdir())


def test_upload_rejects_unknown_workspace(knowledge_client) -> None:
    client, _workspace, _workspace_id = knowledge_client

    response = client.post(
        "/api/knowledge/sources",
        data={"workspaceId": "missing"},
        files={"file": ("notes.md", b"safe", "text/markdown")},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "workspace_not_found"


def test_upload_rejects_source_over_size_limit(knowledge_client) -> None:
    client, _workspace, workspace_id = knowledge_client

    response = client.post(
        "/api/knowledge/sources",
        data={"workspaceId": workspace_id},
        files={"file": ("large.txt", b"x" * (MAX_SOURCE_BYTES + 1), "text/plain")},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "source_too_large"


def test_rescan_uses_workspace_id(knowledge_client) -> None:
    client, workspace, workspace_id = knowledge_client
    vault = workspace / "knowledge-vault"
    (vault / "10_question_bank/question.md").write_text(
        "---\nid: q1\ntype: question\ntitle: Question\nstatus: ingested\ningestion:\n  confirmed_by_user: true\n---\n# Question\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/knowledge/rescan", data={"workspaceId": workspace_id}
    )

    assert response.status_code == 200
    assert response.json() == {"indexed": 1, "skipped": 0, "repaired": 0}
    db_path = vault / ".cyber-interview-agent/index.sqlite"
    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT COUNT(*) FROM manifest_documents").fetchone()[0] == 1

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.vault import initialize_vault


def test_rescan_indexes_markdown_documents_with_unique_relative_ids(tmp_path) -> None:
    vault = tmp_path / "knowledge-vault"
    question_dir = vault / "10_question_bank"
    session_dir = vault / "20_review_sessions"
    question_dir.mkdir(parents=True)
    session_dir.mkdir(parents=True)
    (question_dir / "same.md").write_text("SQL 注入 参数化查询", encoding="utf-8")
    (session_dir / "same.md").write_text("复习报告 weak point", encoding="utf-8")

    client = TestClient(app)
    response = client.post("/api/knowledge/rescan", data={"workspacePath": str(tmp_path)})

    assert response.status_code == 200
    assert response.json() == {"indexed": 2}

    db_path = vault / ".cyber-interview-agent" / "index.sqlite"
    connection = sqlite3.connect(db_path)
    rows = connection.execute("SELECT id, path FROM manifest_documents ORDER BY path").fetchall()

    assert rows == [
        ("10_question_bank__same", "10_question_bank/same.md"),
        ("20_review_sessions__same", "20_review_sessions/same.md"),
    ]


def test_upload_accepts_unicode_filename(tmp_path: Path) -> None:
    response = TestClient(app).post(
        "/api/knowledge/sources",
        data={"workspacePath": str(tmp_path)},
        files={"file": ("面试记录.md", "赛博产品设计".encode(), "text/markdown")},
    )

    assert response.status_code == 200
    assert (tmp_path / "knowledge-vault/00_inbox/面试记录.md").is_file()


def test_upload_rejects_symlinked_inbox(tmp_path: Path) -> None:
    vault = initialize_vault(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    inbox = vault / "00_inbox"
    inbox.rmdir()
    inbox.symlink_to(outside, target_is_directory=True)

    response = TestClient(app).post(
        "/api/knowledge/sources",
        data={"workspacePath": str(tmp_path)},
        files={"file": ("notes.md", b"safe", "text/markdown")},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "workspace_path_denied"
    assert not (outside / "notes.md").exists()


def test_rescan_rejects_symlinked_markdown_file(tmp_path: Path) -> None:
    vault = initialize_vault(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.md"
    outside.write_text("private", encoding="utf-8")
    (vault / "10_question_bank/escape.md").symlink_to(outside)

    response = TestClient(app).post(
        "/api/knowledge/rescan", data={"workspacePath": str(tmp_path)}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "workspace_path_denied"


def test_knowledge_routes_do_not_recreate_missing_workspace(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    response = TestClient(app).post(
        "/api/knowledge/rescan", data={"workspacePath": str(missing)}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "workspace_path_denied"
    assert not missing.exists()

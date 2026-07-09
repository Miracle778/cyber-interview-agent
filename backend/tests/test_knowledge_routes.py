import sqlite3

from fastapi.testclient import TestClient

from app.main import app


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

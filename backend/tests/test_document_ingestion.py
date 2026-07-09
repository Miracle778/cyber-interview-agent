from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.document_ingestion import create_question_draft


def test_create_question_draft_from_text() -> None:
    draft = create_question_draft("SQL 注入是什么？\n参考答案")
    assert draft.title == "SQL 注入是什么？"
    assert draft.topics == ["uncategorized"]


def test_upload_source_sanitizes_filename(tmp_path: Path) -> None:
    client = TestClient(app)

    response = client.post(
        "/api/knowledge/sources",
        data={"workspacePath": str(tmp_path)},
        files={"file": ("../evil.txt", b"SQL injection?\nanswer", "text/plain")},
    )

    assert response.status_code == 200
    assert (tmp_path / "knowledge-vault" / "00_inbox" / "evil.txt").exists()
    assert not (tmp_path / "evil.txt").exists()

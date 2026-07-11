from pathlib import Path

import pytest

from app.knowledge.sources import save_source
from app.security.workspace_paths import PathPolicyError
from app.services.document_ingestion import create_question_draft


def test_create_question_draft_from_text() -> None:
    draft = create_question_draft("SQL 注入是什么？\n参考答案")
    assert draft.title == "SQL 注入是什么？"
    assert draft.topics == ["uncategorized"]


@pytest.mark.parametrize("filename", ["../evil.txt", "nested/evil.txt", "C:\\evil.txt"])
def test_save_source_rejects_path_shaped_filename(
    tmp_path: Path, filename: str
) -> None:
    with pytest.raises(PathPolicyError):
        save_source(tmp_path, original_filename=filename, content=b"unsafe")

    assert not (tmp_path / "artifacts").exists()

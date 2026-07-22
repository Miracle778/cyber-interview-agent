from pathlib import Path

import pytest

from app.knowledge.sources import save_source
from app.security.workspace_paths import PathPolicyError
from app.services import document_ingestion
from app.services.document_ingestion import create_question_draft


def test_create_question_draft_from_text() -> None:
    draft = create_question_draft("SQL 注入是什么？\n参考答案")
    assert draft.title == "SQL 注入是什么？"
    assert draft.topics == ["uncategorized"]


def test_extract_text_result_classifies_text_content_without_guessing_encodings(
    tmp_path: Path,
) -> None:
    usable = tmp_path / "usable.txt"
    usable.write_text("How does Redis eviction work?", encoding="utf-8")
    whitespace = tmp_path / "whitespace.txt"
    whitespace.write_text(" \n\t ", encoding="utf-8")
    low_signal = tmp_path / "keywords.txt"
    low_signal.write_text("Redis TTL", encoding="utf-8")
    invalid = tmp_path / "invalid.txt"
    invalid.write_bytes(b"\xff\xfe\x80")

    extract_text_result = document_ingestion.extract_text_result
    assert extract_text_result(usable).code == "usable"
    assert extract_text_result(whitespace).code == "no_extractable_text"
    assert extract_text_result(low_signal).code == "low_signal"
    assert extract_text_result(invalid).code == "unsupported_encoding"


def test_extract_text_result_classifies_pdf_text_empty_and_parser_errors_safely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "notes.pdf"
    pdf.write_bytes(b"%PDF-test")

    class TextPage:
        def extract_text(self) -> str:
            return "PDF text layer question?"

    class TextReader:
        pages = (TextPage(),)

    monkeypatch.setattr(document_ingestion, "PdfReader", lambda _path: TextReader())
    extract_text_result = document_ingestion.extract_text_result
    assert extract_text_result(pdf).code == "usable"

    class EmptyPage:
        def extract_text(self) -> str:
            return ""

    class EmptyReader:
        pages = (EmptyPage(),)

    monkeypatch.setattr(document_ingestion, "PdfReader", lambda _path: EmptyReader())
    assert extract_text_result(pdf).code == "no_extractable_text"

    secret = "untrusted document text /private/notes.pdf"
    monkeypatch.setattr(
        document_ingestion,
        "PdfReader",
        lambda _path: (_ for _ in ()).throw(RuntimeError(secret)),
    )
    result = extract_text_result(pdf)
    assert result.code == "parse_failed"
    assert result.text == ""
    assert secret not in repr(result)


@pytest.mark.parametrize("filename", ["../evil.txt", "nested/evil.txt", "C:\\evil.txt"])
def test_save_source_rejects_path_shaped_filename(
    tmp_path: Path, filename: str
) -> None:
    with pytest.raises(PathPolicyError):
        save_source(tmp_path, original_filename=filename, content=b"unsafe")

    assert not (tmp_path / "artifacts").exists()

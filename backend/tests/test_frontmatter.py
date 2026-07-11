import frontmatter
import pytest
from pydantic import ValidationError

from app.knowledge.document_types import create_document_type_registry
from app.knowledge.frontmatter import (
    PublishedDocument,
    PublishedProvenance,
    render_published_document,
)


@pytest.mark.parametrize(
    ("document_type", "directory"),
    [
        ("source", "00_inbox"),
        ("question", "10_question_bank"),
        ("session_report", "20_review_sessions"),
        ("mastery_report", "30_mastery"),
        ("concept", "40_concepts"),
    ],
)
def test_document_types_use_canonical_vault_directories(
    document_type: str, directory: str
) -> None:
    definition = create_document_type_registry().resolve(document_type)

    assert definition.directory == directory
    assert definition.path_for("doc-1") == f"{directory}/doc-1.md"


def test_rendered_document_is_active_and_traceable() -> None:
    rendered = render_published_document(
        PublishedDocument(
            id="question-1",
            type="question",
            title="缓存穿透",
            markdown="# 缓存穿透\n\n使用缓存空值。\n",
            source_refs=("artifacts/review/sources/source-1.md",),
            relation_refs=("concept-cache",),
            published_at="2026-07-12T00:00:00Z",
            provenance=PublishedProvenance(
                agent_type="review",
                session_id="s1",
                run_id="r1",
                model_id="m1",
            ),
        )
    )
    parsed = frontmatter.loads(rendered)

    assert parsed["schema_version"] == 1
    assert parsed["id"] == "question-1"
    assert parsed["type"] == "question"
    assert parsed["status"] == "ingested"
    assert parsed["ingestion"] == {
        "confirmed_by_user": True,
        "published_at": "2026-07-12T00:00:00Z",
    }
    assert parsed["provenance"]["session_id"] == "s1"
    assert parsed["source_refs"] == ["artifacts/review/sources/source-1.md"]
    assert parsed.content == "# 缓存穿透\n\n使用缓存空值。"


@pytest.mark.parametrize(
    "key", ["api_key", "authorization", "system_prompt", "checkpoint"]
)
def test_published_document_rejects_forbidden_metadata(key: str) -> None:
    payload = {
        "id": "q1",
        "type": "question",
        "title": "Question",
        "markdown": "# Question",
        "source_refs": [],
        "relation_refs": [],
        "published_at": "2026-07-12T00:00:00Z",
        "provenance": {},
        key: "secret",
    }

    with pytest.raises(ValidationError):
        PublishedDocument.model_validate(payload)


def test_provenance_rejects_hidden_fields() -> None:
    with pytest.raises(ValidationError):
        PublishedProvenance.model_validate(
            {"session_id": "s1", "system_prompt": "hidden"}
        )

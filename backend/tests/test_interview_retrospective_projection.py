from __future__ import annotations

from app.interview_retrospectives.models import SourceVersionRecord
from app.interview_retrospectives.projection import source_version_resource


def test_source_projection_returns_body_only_for_explicit_detail() -> None:
    source = SourceVersionRecord(
        id="source-1",
        retrospective_id="retro-1",
        ordinal=1,
        source_kind="transcript",
        file_name="round.md",
        body="private interview transcript",
        content_sha256="a" * 64,
        cleared_at=None,
        created_at="2026-08-01T00:00:00Z",
    )

    summary = source_version_resource(source, include_body=False)
    detail = source_version_resource(source, include_body=True)

    assert "body" not in summary
    assert summary["bodyAvailable"] is True
    assert detail["body"] == "private interview transcript"


def test_cleared_source_detail_never_returns_an_empty_body_as_available() -> None:
    source = SourceVersionRecord(
        id="source-1",
        retrospective_id="retro-1",
        ordinal=1,
        source_kind="transcript",
        file_name=None,
        body="",
        content_sha256="a" * 64,
        cleared_at="2026-08-02T00:00:00Z",
        created_at="2026-08-01T00:00:00Z",
    )

    detail = source_version_resource(source, include_body=True)

    assert detail["bodyAvailable"] is False
    assert detail["body"] is None

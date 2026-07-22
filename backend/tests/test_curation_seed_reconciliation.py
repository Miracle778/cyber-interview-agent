from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from app.agents.question_curation_contracts import (
    QuestionCandidate,
    QuestionCandidateChunk,
    QuestionSeed,
    QuestionSeedChunk,
)
from app.infrastructure.runtime_database import connect_runtime_database
from app.review.curation_seed_reconciliation import reconcile_curation_seed_tasks
from app.review.repository import ReviewRepository


@pytest.fixture
def repository(tmp_path: Path) -> ReviewRepository:
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('session-1', 'workspace-1', 'question.curate', 1, 'Curation')"
    )
    connection.commit()
    repo = ReviewRepository(connection)
    repo.create_batch(
        workspace_id="workspace-1",
        session_id="session-1",
        run_id=None,
        source_refs=("source-1",),
        batch_id="batch-1",
    )
    yield repo
    connection.close()


def _complete_item(
    repository: ReviewRepository,
    *,
    stage: str,
    unit_index: int,
    output: dict[str, object],
) -> None:
    item = repository.plan_curation_work_item(
        batch_id="batch-1",
        stage=stage,
        unit_index=unit_index,
        input_digest=sha256(f"{stage}-{unit_index}".encode()).hexdigest(),
        source_refs=(f"source-1#section-{unit_index + 1}",),
    )
    repository.start_curation_work_item(item.id)
    repository.complete_curation_work_item(item.id, output=output)


def _candidate(index: int) -> QuestionCandidate:
    return QuestionCandidate(
        title=f"题目 {index}",
        question_text=f"问题 {index}？",
        reference_answer=f"答案 {index}",
        topics=["数据库"],
        difficulty="medium",
        key_points=["关键点"],
        follow_ups=[],
        source_refs=[f"source-1#section-{index}"],
        correction_note="无需修正",
    )


def test_reconciliation_restores_current_legacy_shape_once_without_replay(
    repository: ReviewRepository,
) -> None:
    for index in range(1, 81):
        _complete_item(
            repository,
            stage="discovery",
            unit_index=index - 1,
            output=QuestionSeedChunk(seeds=[QuestionSeed(
                question_text=f"问题 {index}？",
                source_ref=f"source-1#section-{index}",
            )]).model_dump(mode="json"),
        )
    restored_order = [2, 1, *range(3, 23)]
    for unit_index, candidate_index in enumerate(restored_order):
        _complete_item(
            repository,
            stage="enrichment",
            unit_index=unit_index,
            output=QuestionCandidateChunk(
                candidates=[_candidate(candidate_index)]
            ).model_dump(mode="json"),
        )

    first = reconcile_curation_seed_tasks(repository, "batch-1")
    rows_after_first = repository.list_curation_seed_tasks("batch-1")
    second = reconcile_curation_seed_tasks(repository, "batch-1")
    rows_after_second = repository.list_curation_seed_tasks("batch-1")

    assert (first.planned, first.restored_degraded, first.pending) == (80, 22, 58)
    assert (second.planned, second.restored_degraded, second.pending) == (0, 0, 58)
    assert rows_after_second == rows_after_first
    assert sum(row.status == "degraded" for row in rows_after_first) == 22
    assert sum(row.status == "pending" for row in rows_after_first) == 58
    assert all(
        row.normalization_issues == ("legacy_quality_unknown",)
        for row in rows_after_first
        if row.status == "degraded"
    )

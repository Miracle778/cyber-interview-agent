from __future__ import annotations

from dataclasses import replace

from app.agents.question_curation_normalization import (
    normalize_provider_candidate_observation,
)
from app.review.models import CurationSeedTaskRecord


def _task(index: int) -> CurationSeedTaskRecord:
    return CurationSeedTaskRecord(
        id=f"task-{index}",
        batch_id="batch-1",
        discovery_work_item_id=f"discovery-{index}",
        seed_key=str(index) * 64,
        seed_ordinal=index,
        question_text=f"问题 {index}？",
        primary_source_ref=f"source#section-{index}",
        source_refs=(f"source#section-{index}",),
        input_digest="a" * 64,
        status="running",
        automatic_attempt_count=1,
        manual_attempt_count=0,
        candidate=None,
        answer_basis="unknown",
        material_support="unknown",
        needs_review=True,
        normalization_issues=(),
        last_error_code=None,
        version=1,
        created_at="2026-07-22 00:00:00",
        updated_at="2026-07-22 00:00:00",
    )


def _observation(task: CurationSeedTaskRecord) -> dict[str, object]:
    return {
        "seed_key": task.seed_key,
        "title": "标题",
        "question_text": task.question_text,
        "source_answer": "材料答案",
        "topics": ["数据库"],
        "difficulty": "medium",
        "key_points": ["关键点"],
        "follow_ups": [],
        "source_refs": list(task.source_refs),
        "correction_note": "无需修正",
    }


def test_normalizer_associates_shuffled_candidates_without_position_guessing() -> None:
    first, second = _task(1), _task(2)
    rows = [_observation(second), _observation(first)]

    outcomes = normalize_provider_candidate_observation(
        {"candidates": rows}, seed_tasks=(first, second)
    )

    assert [(item.seed_task_id, item.status) for item in outcomes] == [
        (first.id, "completed"),
        (second.id, "completed"),
    ]


def test_normalizer_repairs_safe_metadata_and_tracks_mixed_answer() -> None:
    task = _task(1)
    row = {
        "seed_key": task.seed_key,
        "source_answer": "材料答案",
        "supplemental_answer": "模型补充",
        "topics": " 数据库 ",
        "difficulty": "中等",
        "key_points": " 关键点 ",
    }

    outcome = normalize_provider_candidate_observation(
        {"candidates": [row]}, seed_tasks=(task,)
    )[0]

    assert outcome.status == "degraded"
    assert (outcome.answer_basis, outcome.material_support) == ("mixed", "partial")
    assert outcome.candidate is not None
    assert outcome.candidate["question_text"] == task.question_text
    assert outcome.candidate["source_refs"] == list(task.source_refs)
    assert outcome.normalization_issues == (
        "source_refs_restored",
        "question_defaulted",
        "title_defaulted",
        "supplemental_answer_present",
        "topics_normalized",
        "difficulty_mapped",
        "key_points_normalized",
        "follow_ups_defaulted",
        "correction_note_defaulted",
    )


def test_normalizer_isolates_missing_content_and_untrusted_refs_per_seed() -> None:
    first, second = _task(1), _task(2)
    missing_answer = _observation(first)
    missing_answer.pop("source_answer")
    untrusted = _observation(second)
    untrusted["source_refs"] = [second.primary_source_ref, "source#section-999"]

    outcomes = normalize_provider_candidate_observation(
        {"candidates": [untrusted, missing_answer]}, seed_tasks=(first, second)
    )

    assert [(item.status, item.error_code) for item in outcomes] == [
        ("retryable", "missing_answer"),
        ("retryable", "untrusted_source_refs"),
    ]
    assert all(item.candidate is None for item in outcomes)


def test_invalid_top_level_and_unassociated_rows_retry_each_missing_seed() -> None:
    first, second = _task(1), _task(2)
    invalid = normalize_provider_candidate_observation(
        {"candidates": "truncated"}, seed_tasks=(first, second)
    )
    unrelated = _observation(replace(first, seed_key="f" * 64))
    unrelated["question_text"] = "完全无关的问题"
    unrelated["source_refs"] = ["other#section-1"]
    missing = normalize_provider_candidate_observation(
        {"candidates": [unrelated]}, seed_tasks=(first, second)
    )

    assert [item.error_code for item in invalid] == [
        "invalid_provider_response",
        "invalid_provider_response",
    ]
    assert [item.error_code for item in missing] == [
        "missing_candidate",
        "missing_candidate",
    ]

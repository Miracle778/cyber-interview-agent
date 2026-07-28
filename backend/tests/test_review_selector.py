from dataclasses import replace

import pytest

from app.review.errors import InsufficientQuestionsError
from app.review.models import (
    MasteryEntry,
    MasteryProjection,
    QuestionCatalogRecord,
    QuestionSnapshot,
    ReviewRoundSettings,
)
from app.review.selector import QuestionSelector


def _snapshot(
    question_id: str,
    *,
    topic: str = "database",
    difficulty: str = "medium",
) -> QuestionSnapshot:
    return QuestionSnapshot(
        question_id=question_id,
        document_id=f"doc-{question_id}",
        content_hash=question_id[0] * 64,
        title=f"Question {question_id}",
        question_text=f"Explain {question_id}",
        reference_answer=f"Answer {question_id}",
        topics=(topic,),
        difficulty=difficulty,
        key_points=("point",),
        follow_ups=("why",),
    )


def _catalog(*snapshots: QuestionSnapshot) -> tuple[QuestionCatalogRecord, ...]:
    return tuple(
        QuestionCatalogRecord(
            snapshot=snapshot,
            workspace_id="w1",
            draft_id=f"draft-{snapshot.question_id}",
            publication_id=f"publication-{snapshot.question_id}",
            active=True,
            published_at="2026-07-14T00:00:00Z",
        )
        for snapshot in snapshots
    )


def _settings(
    *,
    mode: str = "random-mixed",
    count: int = 2,
    topics: tuple[str, ...] = (),
) -> ReviewRoundSettings:
    return ReviewRoundSettings(
        topics=topics,
        difficulties=("easy", "medium", "hard"),
        mode=mode,
        question_count=count,
        allow_follow_up=True,
        seed=17,
        answer_model_id="model-1",
        reasoning_effort="medium",
    )


def _mastery(*entries: MasteryEntry) -> MasteryProjection:
    return MasteryProjection(
        workspace_id="w1",
        version=1,
        entries=entries,
        evidence_refs=("report-1",),
    )


def test_fixed_seed_produces_same_deduplicated_order() -> None:
    catalog = _catalog(_snapshot("a"), _snapshot("b"), _snapshot("c"))
    selector = QuestionSelector()

    first = selector.select(catalog, _mastery(), _settings(), seed=9)
    second = selector.select(catalog, _mastery(), _settings(), seed=9)

    assert [item.question_id for item in first] == [
        item.question_id for item in second
    ]
    assert len({item.question_id for item in first}) == 2


def test_weak_point_prioritizes_confirmed_weak_mastery() -> None:
    catalog = _catalog(_snapshot("a"), _snapshot("b"), _snapshot("c"))
    mastery = _mastery(
        MasteryEntry(subject_id="a", state="strong"),
        MasteryEntry(subject_id="b", state="weak"),
        MasteryEntry(subject_id="c", state="partial"),
    )

    selected = QuestionSelector().select(
        catalog, mastery, _settings(mode="weak-point"), seed=4
    )

    assert [item.question_id for item in selected] == ["b", "c"]


def test_recent_mistake_uses_confirmed_evidence() -> None:
    catalog = _catalog(_snapshot("a"), _snapshot("b"), _snapshot("c"))
    mastery = _mastery(
        MasteryEntry(subject_id="a", state="weak", recent_mistake=False),
        MasteryEntry(subject_id="b", state="stable", recent_mistake=True),
    )

    selected = QuestionSelector().select(
        catalog, mastery, _settings(mode="recent-mistake", count=1), seed=1
    )

    assert selected[0].question_id == "b"


def test_topic_focused_never_leaks_another_topic() -> None:
    catalog = _catalog(
        _snapshot("a", topic="database"),
        _snapshot("b", topic="redis"),
    )

    selected = QuestionSelector().select(
        catalog,
        _mastery(),
        _settings(mode="topic-focused", count=1, topics=("redis",)),
        seed=1,
    )

    assert [item.question_id for item in selected] == ["b"]


def test_source_file_never_leaks_questions_from_another_source() -> None:
    first, second, shared = _catalog(
        _snapshot("a"),
        _snapshot("b"),
        _snapshot("c"),
    )
    catalog = (
        replace(first, source_ids=("source-a",)),
        replace(second, source_ids=("source-b",)),
        replace(shared, source_ids=("source-a", "source-b")),
    )

    selected = QuestionSelector().select(
        catalog,
        _mastery(),
        replace(
            _settings(mode="random-mixed", count=2),
            mode="source-file",
            source_id="source-a",
        ),
        seed=1,
    )

    assert {item.question_id for item in selected} == {"a", "c"}


def test_insufficient_inventory_reports_available_and_requested() -> None:
    inactive = replace(_catalog(_snapshot("a"))[0], active=False)

    with pytest.raises(InsufficientQuestionsError) as error:
        QuestionSelector().select(
            (inactive,), _mastery(), _settings(count=1), seed=1
        )

    assert error.value.available == 0
    assert error.value.requested == 1


def test_round_snapshot_is_immutable_when_catalog_record_changes() -> None:
    original = _catalog(_snapshot("a"))[0]
    selected = QuestionSelector().select(
        (original,), _mastery(), _settings(count=1), seed=1
    )
    changed = replace(
        original,
        snapshot=replace(original.snapshot, question_text="Changed later"),
    )

    assert changed.snapshot.question_text == "Changed later"
    assert selected[0].question_text == "Explain a"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("question_count", 0),
        ("question_count", 51),
        ("answer_model_id", ""),
        ("reasoning_effort", "extreme"),
    ],
)
def test_round_settings_reject_invalid_values(field: str, value: object) -> None:
    values = {
        "topics": (),
        "difficulties": ("medium",),
        "mode": "random-mixed",
        "question_count": 10,
        "allow_follow_up": True,
        "seed": 1,
        "answer_model_id": "model-1",
        "reasoning_effort": "none",
    }
    values[field] = value

    with pytest.raises(ValueError):
        ReviewRoundSettings(**values)


def test_topic_focused_requires_topics() -> None:
    with pytest.raises(ValueError, match="topics"):
        _settings(mode="topic-focused", topics=())


def test_source_file_requires_source_id() -> None:
    with pytest.raises(ValueError, match="source_id"):
        _settings(mode="source-file")

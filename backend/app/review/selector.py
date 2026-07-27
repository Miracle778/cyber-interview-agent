from __future__ import annotations

import random

from app.review.errors import InsufficientQuestionsError
from app.review.models import (
    MasteryEntry,
    MasteryProjection,
    QuestionCatalogRecord,
    QuestionSnapshot,
    ReviewRoundSettings,
)


_MASTERY_PRIORITY = {
    "weak": 0,
    "partial": 1,
    "unknown": 2,
    "stable": 3,
    "strong": 4,
}


class QuestionSelector:
    def eligible_count(
        self,
        catalog: tuple[QuestionCatalogRecord, ...],
        settings: ReviewRoundSettings,
    ) -> int:
        return len(self._eligible(catalog, settings))

    def select(
        self,
        catalog: tuple[QuestionCatalogRecord, ...],
        mastery: MasteryProjection,
        settings: ReviewRoundSettings,
        seed: int | None = None,
    ) -> tuple[QuestionSnapshot, ...]:
        eligible = self._eligible(catalog, settings)
        if len(eligible) < settings.question_count:
            raise InsufficientQuestionsError(
                available=len(eligible), requested=settings.question_count
            )

        rng = random.Random(settings.seed if seed is None else seed)
        tie_breakers = {
            record.snapshot.question_id: rng.random() for record in eligible
        }
        entries = {entry.subject_id: entry for entry in mastery.entries}

        if settings.mode in {"random-mixed", "topic-focused", "source-file"}:
            ordered = list(eligible)
            rng.shuffle(ordered)
        elif settings.mode == "weak-point":
            ordered = sorted(
                eligible,
                key=lambda record: (
                    self._mastery_priority(record.snapshot, entries),
                    tie_breakers[record.snapshot.question_id],
                ),
            )
        else:
            ordered = sorted(
                eligible,
                key=lambda record: (
                    not self._is_recent_mistake(record.snapshot, entries),
                    self._mastery_priority(record.snapshot, entries),
                    tie_breakers[record.snapshot.question_id],
                ),
            )

        return tuple(
            record.snapshot for record in ordered[: settings.question_count]
        )

    @staticmethod
    def _eligible(
        catalog: tuple[QuestionCatalogRecord, ...],
        settings: ReviewRoundSettings,
    ) -> list[QuestionCatalogRecord]:
        seen: set[str] = set()
        eligible: list[QuestionCatalogRecord] = []
        topic_filter = set(settings.topics)
        difficulty_filter = set(settings.difficulties)
        for record in catalog:
            snapshot = record.snapshot
            if not record.active or snapshot.question_id in seen:
                continue
            if snapshot.difficulty not in difficulty_filter:
                continue
            if (
                settings.source_id is not None
                and settings.source_id not in record.source_ids
            ):
                continue
            if topic_filter and topic_filter.isdisjoint(snapshot.topics):
                continue
            seen.add(snapshot.question_id)
            eligible.append(record)
        return eligible

    @staticmethod
    def _matching_entries(
        snapshot: QuestionSnapshot,
        entries: dict[str, MasteryEntry],
    ) -> tuple[MasteryEntry, ...]:
        subjects = (snapshot.question_id, *snapshot.topics)
        return tuple(entries[subject] for subject in subjects if subject in entries)

    def _mastery_priority(
        self,
        snapshot: QuestionSnapshot,
        entries: dict[str, MasteryEntry],
    ) -> int:
        matches = self._matching_entries(snapshot, entries)
        if not matches:
            return _MASTERY_PRIORITY["unknown"]
        return min(_MASTERY_PRIORITY[entry.state] for entry in matches)

    def _is_recent_mistake(
        self,
        snapshot: QuestionSnapshot,
        entries: dict[str, MasteryEntry],
    ) -> bool:
        return any(
            entry.recent_mistake
            for entry in self._matching_entries(snapshot, entries)
        )

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256

from pydantic import ValidationError

from app.agents.question_curation_contracts import (
    QuestionCandidate,
    QuestionCandidateChunk,
    QuestionSeedBatch,
)
from app.review.models import CurationSeedTaskRecord
from app.review.repository import ReviewRepository


@dataclass(frozen=True, slots=True)
class SeedReconciliationResult:
    planned: int
    restored_completed: int
    restored_degraded: int
    pending: int
    warnings: tuple[dict[str, object], ...]


def reconcile_curation_seed_tasks(
    repository: ReviewRepository, batch_id: str
) -> SeedReconciliationResult:
    """Create the per-seed projection and restore completed legacy output once."""
    existing_ids = {
        task.id for task in repository.list_curation_seed_tasks(batch_id)
    }
    for item in repository.list_curation_work_items(batch_id, stage="discovery"):
        if item.status != "completed" or item.output is None:
            continue
        seeds = QuestionSeedBatch.model_validate(item.output).seeds
        for local_ordinal, seed in enumerate(seeds):
            ordinal = item.unit_index * 20 + local_ordinal
            encoded = json.dumps(
                seed.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            repository.plan_curation_seed_task(
                batch_id=batch_id,
                discovery_work_item_id=item.id,
                seed_ordinal=ordinal,
                question_text=seed.question_text,
                primary_source_ref=seed.source_ref,
                source_refs=tuple(seed.source_refs),
                input_digest=sha256(encoded.encode("utf-8")).hexdigest(),
            )

    tasks = repository.list_curation_seed_tasks(batch_id)
    by_primary: dict[str, list[CurationSeedTaskRecord]] = {}
    by_question: dict[str, list[CurationSeedTaskRecord]] = {}
    for task in tasks:
        by_primary.setdefault(task.primary_source_ref, []).append(task)
        by_question.setdefault(_question_key(task.question_text), []).append(task)

    restored_degraded = 0
    restored_completed = 0
    mapped: set[str] = {
        task.id for task in tasks if task.status in {"completed", "degraded"}
    }
    warnings: list[dict[str, object]] = []
    for item in repository.list_curation_work_items(batch_id, stage="enrichment"):
        if item.status != "completed" or item.output is None:
            continue
        try:
            candidates = QuestionCandidateChunk.model_validate(item.output).candidates
        except ValidationError:
            warnings.append({
                "code": "legacy_enrichment_invalid",
                "workItemId": item.id,
            })
            continue
        for candidate in candidates:
            task = _match_legacy_candidate(candidate, by_primary, by_question)
            if task is not None and task.id in mapped:
                current = repository.get_curation_seed_task(task.id)
                if current.candidate == candidate.model_dump(mode="json"):
                    continue
            if task is None or task.id in mapped:
                warnings.append({
                    "code": "legacy_candidate_unmapped",
                    "workItemId": item.id,
                })
                continue
            restored = repository.restore_legacy_curation_seed_task(
                task.id, candidate=candidate.model_dump(mode="json")
            )
            mapped.add(task.id)
            if restored.status == "completed":
                restored_completed += 1
            elif restored.status == "degraded":
                restored_degraded += 1

    current = repository.list_curation_seed_tasks(batch_id)
    return SeedReconciliationResult(
        planned=sum(task.id not in existing_ids for task in current),
        restored_completed=restored_completed,
        restored_degraded=restored_degraded,
        pending=sum(task.status in {"pending", "retryable"} for task in current),
        warnings=tuple(warnings),
    )


def _match_legacy_candidate(
    candidate: QuestionCandidate,
    by_primary: dict[str, list[CurationSeedTaskRecord]],
    by_question: dict[str, list[CurationSeedTaskRecord]],
) -> CurationSeedTaskRecord | None:
    primary_matches = by_primary.get(candidate.source_refs[0], ())
    if len(primary_matches) == 1:
        task = primary_matches[0]
        return task if set(candidate.source_refs).issubset(task.source_refs) else None
    question_matches = by_question.get(_question_key(candidate.question_text), ())
    if len(question_matches) != 1:
        return None
    task = question_matches[0]
    if candidate.source_refs and not set(candidate.source_refs).issubset(task.source_refs):
        return None
    return task


def _question_key(value: str) -> str:
    return re.sub(r"[\s？?。！!，,、：:；;]+", "", value).casefold()

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.knowledge.drafts import KnowledgeDraftRecord
from app.knowledge.publication import PublicationRecord
from app.review.errors import PublicationProjectionError
from app.review.models import (
    MasteryEntry,
    MasteryProjection,
    QuestionCatalogRecord,
    ReviewInputRequestRecord,
    ReviewRoundRecord,
    ReviewRoundSettings,
)
from app.review.repository import ReviewRepository
from app.review.selector import QuestionSelector


@dataclass(frozen=True, slots=True)
class RoundRuntimeRef:
    session_id: str
    execution_id: str | None


@dataclass(frozen=True, slots=True)
class CreateRoundResult:
    round: ReviewRoundRecord
    input_request: ReviewInputRequestRecord


@dataclass(frozen=True, slots=True)
class ConfirmedMasteryReport:
    report_id: str
    entries: tuple[MasteryEntry, ...]


CreateRoundRuntime = Callable[
    [str, ReviewRoundSettings], RoundRuntimeRef
]
LoadConfirmedReports = Callable[
    [str, int], tuple[ConfirmedMasteryReport, ...]
]


class ReviewDomainService:
    def __init__(
        self,
        *,
        repository: ReviewRepository,
        selector: QuestionSelector,
        create_round_runtime: CreateRoundRuntime,
        load_confirmed_mastery_reports: LoadConfirmedReports | None = None,
    ) -> None:
        self._repository = repository
        self._selector = selector
        self._create_round_runtime = create_round_runtime
        self._load_confirmed_mastery_reports = (
            load_confirmed_mastery_reports or (lambda _workspace, _limit: ())
        )

    def create_round(
        self,
        *,
        workspace_id: str,
        settings: ReviewRoundSettings,
    ) -> CreateRoundResult:
        mastery = self.refresh_mastery_from_recent_reports(
            workspace_id, limit=3
        )
        catalog = self._repository.list_active_questions(workspace_id)
        snapshots = self._selector.select(
            catalog, mastery, settings, seed=settings.seed
        )
        runtime = self._create_round_runtime(workspace_id, settings)
        round_record = self._repository.create_round(
            workspace_id=workspace_id,
            session_id=runtime.session_id,
            execution_id=runtime.execution_id,
            settings=settings,
            question_snapshots=snapshots,
            mastery_before=mastery,
        )
        first = snapshots[0]
        input_request = self._repository.create_input_request(
            round_id=round_record.id,
            ordinal=1,
            kind="answer",
            prompt=first.question_text,
        )
        return CreateRoundResult(round=round_record, input_request=input_request)

    def refresh_mastery_from_recent_reports(
        self, workspace_id: str, *, limit: int = 3
    ) -> MasteryProjection:
        current = self._repository.get_mastery(workspace_id)
        reports = self._load_confirmed_mastery_reports(workspace_id, limit)
        if not reports:
            return current

        entries = {entry.subject_id: entry for entry in current.entries}
        evidence_refs = list(current.evidence_refs)
        for report in reversed(reports[-limit:]):
            for entry in report.entries:
                entries[entry.subject_id] = entry
            if report.report_id not in evidence_refs:
                evidence_refs.append(report.report_id)
        proposal = MasteryProjection(
            workspace_id=workspace_id,
            version=current.version + 1,
            entries=tuple(entries[key] for key in sorted(entries)),
            evidence_refs=tuple(evidence_refs[-limit:]),
        )
        if (
            proposal.entries == current.entries
            and proposal.evidence_refs == current.evidence_refs
        ):
            return current
        return self._repository.update_mastery(
            proposal, expected_version=current.version
        )

    def activate_published_draft(
        self,
        draft: KnowledgeDraftRecord,
        publication: PublicationRecord,
    ) -> QuestionCatalogRecord | MasteryProjection | None:
        self._validate_publication(draft, publication)
        if draft.document_type == "question":
            candidate = self._repository.get_candidate_by_draft(draft.id)
            if candidate is None:
                return None
            if (
                candidate.question.document_id != draft.document_id
                or candidate.question.content_hash != draft.content_hash
            ):
                raise PublicationProjectionError(
                    "published draft does not match structured candidate"
                )
            return self._repository.activate_question(
                candidate_id=candidate.id,
                workspace_id=draft.workspace_id,
                document_id=draft.document_id,
                draft_id=draft.id,
                publication_id=publication.id,
                content_hash=draft.content_hash,
            )
        if draft.document_type == "mastery_report":
            try:
                proposal = self._repository.get_report_proposal(draft.id)
            except LookupError as error:
                raise PublicationProjectionError(
                    "published mastery report has no structured proposal"
                ) from error
            if (
                proposal.projection is None
                or proposal.expected_mastery_version is None
                or proposal.projection.workspace_id != draft.workspace_id
            ):
                raise PublicationProjectionError(
                    "mastery proposal does not match published draft"
                )
            return self._repository.update_mastery(
                proposal.projection,
                expected_version=proposal.expected_mastery_version,
            )
        return None

    @staticmethod
    def _validate_publication(
        draft: KnowledgeDraftRecord,
        publication: PublicationRecord,
    ) -> None:
        if publication.state not in {"completed", "index_stale"}:
            raise PublicationProjectionError(
                "publication is not durable enough for projection"
            )
        if (
            publication.draft_id != draft.id
            or publication.document_id != draft.document_id
            or publication.expected_draft_version != draft.version
            or publication.expected_content_hash != draft.content_hash
        ):
            raise PublicationProjectionError(
                "publication receipt does not match final draft"
            )

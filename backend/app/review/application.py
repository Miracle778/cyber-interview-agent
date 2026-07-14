from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from app.application.execution_service import AgentExecutionService
from app.application.session_service import AgentSessionService, ProductEventStream
from app.knowledge.drafts import KnowledgeDraftService, UpdateDraftCommand
from app.knowledge.source_registry import KnowledgeSourceService
from app.knowledge.publication import PublicationService
from app.review.errors import ReviewConflictError
from app.review.models import ReviewRoundSettings
from app.review.repository import ReviewRepository
from app.review.selector import QuestionSelector
from app.services.document_ingestion import extract_text


class ReviewApplication:
    def __init__(
        self,
        *,
        workspace_id: str,
        workspace_root: Path,
        repository: ReviewRepository,
        sessions: AgentSessionService,
        executions: AgentExecutionService,
        events: ProductEventStream,
        drafts: KnowledgeDraftService,
        publications: PublicationService,
        validate_model: Callable[[str, str], None],
    ) -> None:
        self.workspace_id = workspace_id
        self.workspace_root = workspace_root
        self.repository = repository
        self.sessions = sessions
        self.executions = executions
        self.events = events
        self.drafts = drafts
        self.publications = publications
        self.validate_model = validate_model
        self.selector = QuestionSelector()

    async def create_question_batch(
        self,
        *,
        source_refs: tuple[str, ...],
        rewrite_feedback: str | None = None,
        rewrite_of_batch_id: str | None = None,
    ):
        if not source_refs:
            raise ValueError("source_refs must not be empty")
        sources = KnowledgeSourceService(
            self.workspace_root, workspace_id=self.workspace_id
        )
        excerpts = []
        for source_id in source_refs:
            source = await sources.get(source_id)
            text = extract_text(self.workspace_root / source.stored_path)
            excerpts.append(
                f"{source.id}:{source.original_filename}\n{text[:20_000]}"
            )
        session = await self.sessions.create(
            workspace_id=self.workspace_id,
            kind="question.curate",
            title="AI 题库整理",
        )
        batch = self.repository.create_batch(
            workspace_id=self.workspace_id,
            session_id=session.id,
            run_id=None,
            source_refs=source_refs,
            rewrite_of_batch_id=rewrite_of_batch_id,
        )
        execution = await self.executions.start(
            session,
            input={
                "batchId": batch.id,
                "source_excerpts": excerpts,
                "similar_questions": [
                    item.snapshot.question_text
                    for item in self.repository.list_active_questions(
                        self.workspace_id
                    )
                ],
                "rewrite_feedback": rewrite_feedback,
            },
        )
        return self.repository.attach_batch_run(batch.id, execution.id)

    def list_batches(self, *, status: str | None = None):
        return self.repository.list_batches(self.workspace_id, status=status)

    async def batch_resource(self, batch_id: str) -> dict[str, Any]:
        batch = self.repository.get_batch(batch_id)
        if batch.workspace_id != self.workspace_id:
            raise LookupError(batch_id)
        candidates = self.repository.list_candidates(self.workspace_id)
        own = [item for item in candidates if item.batch_id == batch.id]
        return {
            **asdict(batch),
            "candidate_count": len(own),
            "pending_count": sum(
                item.status == "review_pending" for item in own
            ),
            "candidates": [
                await self.candidate_resource(item.id) for item in own
            ],
        }

    async def list_candidate_resources(self, **filters) -> tuple[dict[str, Any], ...]:
        records = self.repository.list_candidates(
            self.workspace_id, **filters
        )
        return tuple([await self.candidate_resource(item.id) for item in records])

    async def candidate_resource(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.repository.get_candidate(candidate_id)
        batch = self.repository.get_batch(candidate.batch_id)
        if batch.workspace_id != self.workspace_id:
            raise LookupError(candidate_id)
        draft = (
            None
            if candidate.draft_id is None
            else await self.drafts.get(candidate.draft_id)
        )
        duplicate = None
        if candidate.duplicate_of_question_id is not None:
            try:
                duplicate = self.repository.get_active_question(
                    candidate.duplicate_of_question_id
                ).snapshot
            except LookupError:
                duplicate = None
        return {
            "id": candidate.id,
            "batch_id": candidate.batch_id,
            "question": asdict(candidate.question),
            "source_refs": candidate.source_refs,
            "correction_note": candidate.correction_note,
            "duplicate_of_question_id": candidate.duplicate_of_question_id,
            "duplicate_question": (
                None if duplicate is None else asdict(duplicate)
            ),
            "status": candidate.status,
            "draft": (
                None
                if draft is None
                else {
                    "id": draft.id,
                    "title": draft.title,
                    "markdown": draft.markdown,
                    "status": draft.status,
                    "version": draft.version,
                    "content_hash": draft.content_hash,
                    "document_type": draft.document_type,
                }
            ),
            "created_at": candidate.created_at,
            "updated_at": candidate.updated_at,
        }

    async def update_candidate(
        self,
        candidate_id: str,
        *,
        expected_version: int,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate.draft_id is None:
            raise ReviewConflictError("candidate has no draft")
        current = candidate.question
        updated = replace(
            current,
            title=values.get("title", current.title),
            question_text=values.get("question_text", current.question_text),
            reference_answer=values.get(
                "reference_answer", current.reference_answer
            ),
            topics=tuple(values.get("topics", current.topics)),
            difficulty=values.get("difficulty", current.difficulty),
            key_points=tuple(values.get("key_points", current.key_points)),
            follow_ups=tuple(values.get("follow_ups", current.follow_ups)),
        )
        markdown = (
            f"# {updated.title}\n\n## 题目\n\n{updated.question_text}\n\n"
            f"## 参考答案\n\n{updated.reference_answer}\n\n## 关键点\n\n"
            + "\n".join(f"- {item}" for item in updated.key_points)
            + "\n"
        )
        draft = await self.drafts.update(
            candidate.draft_id,
            UpdateDraftCommand(
                expected_version=expected_version,
                title=updated.title,
                markdown=markdown,
            ),
        )
        updated = replace(
            updated,
            document_id=draft.document_id,
            content_hash=draft.content_hash,
        )
        self.repository.update_candidate(
            candidate_id, question=updated, status="review_pending"
        )
        return await self.candidate_resource(candidate_id)

    def list_questions(
        self, *, topic: str | None = None, difficulty: str | None = None
    ):
        return self.repository.list_active_questions(
            self.workspace_id, topic=topic, difficulty=difficulty
        )

    async def create_round(self, settings: ReviewRoundSettings):
        self.validate_model(settings.answer_model_id, settings.reasoning_effort)
        mastery = self.repository.get_mastery(self.workspace_id)
        snapshots = self.selector.select(
            self.repository.list_active_questions(self.workspace_id),
            mastery,
            settings,
            seed=settings.seed,
        )
        session = await self.sessions.create(
            workspace_id=self.workspace_id,
            kind="review.round",
            title=f"复习轮次 · {len(snapshots)} 题",
        )
        round_id = str(uuid4())
        execution = await self.executions.prepare(
            session, input={"roundId": round_id}
        )
        round_record = self.repository.create_round(
            workspace_id=self.workspace_id,
            session_id=session.id,
            execution_id=execution.id,
            settings=settings,
            question_snapshots=snapshots,
            mastery_before=mastery,
            round_id=round_id,
        )
        await self.events.publish(
            session.id,
            execution.id,
            "review.round.started",
            {"roundId": round_record.id, "questionCount": len(snapshots)},
        )
        self.executions.run_prepared(
            execution, graph_input={"round_id": round_record.id}
        )
        await self.executions.wait(execution.id)
        return self.repository.get_round(round_record.id)

    async def submit_answer(
        self,
        round_id: str,
        *,
        request_id: str,
        version: int,
        idempotency_key: str,
        value: str,
    ):
        round_record = self.repository.get_round(round_id)
        request = self.repository.get_input_request(request_id)
        if request.round_id != round_id or request.version != version:
            raise ReviewConflictError("input request changed")
        if round_record.execution_id is None:
            raise ReviewConflictError("round has no execution")
        await self.executions.resume_input(
            round_record.execution_id,
            request_id=request_id,
            value=value,
            receipt_id=idempotency_key,
        )
        await self.executions.wait(round_record.execution_id)
        return self.repository.get_round(round_id)

    async def skip(
        self, round_id: str, *, request_id: str, version: int, idempotency_key: str
    ):
        round_record = self.repository.get_round(round_id)
        request = self.repository.get_input_request(request_id)
        if request.round_id != round_id or request.version != version:
            raise ReviewConflictError("input request changed")
        if round_record.execution_id is None:
            raise ReviewConflictError("round has no execution")
        await self.executions.skip_input(
            round_record.execution_id,
            request_id=request_id,
            receipt_id=idempotency_key,
        )
        await self.executions.wait(round_record.execution_id)
        return self.repository.get_round(round_id)

    async def cancel(self, round_id: str):
        round_record = self.repository.cancel_round(round_id)
        if round_record.execution_id is not None:
            await self.executions.cancel(round_record.execution_id)
        await self.events.publish(
            round_record.session_id,
            round_record.execution_id,
            "review.round.cancelled",
            {"roundId": round_record.id},
        )
        return round_record

    async def create_discussion(
        self, round_id: str, *, ordinal: int, message: str
    ):
        round_record = self.repository.get_round(round_id)
        attempts = self.repository.list_attempts(round_id)
        attempt = next(
            (item for item in attempts if item.ordinal == ordinal), None
        )
        if attempt is None:
            raise LookupError(ordinal)
        session = await self.sessions.create(
            workspace_id=self.workspace_id,
            kind="review.discussion",
            title=f"深入讨论：{attempt.question_snapshot.title}",
            parent_session_id=round_record.session_id,
        )
        execution = await self.executions.start(
            session,
            input={
                "question_snapshot": asdict(attempt.question_snapshot),
                "attempt_evidence": {
                    "attemptId": attempt.id,
                    "evaluation": attempt.evaluation,
                    "masterySuggestion": attempt.mastery_suggestion,
                },
                "message": message,
                "parent_round_id": round_id,
            },
        )
        await self.executions.wait(execution.id)
        return session

    async def round_resource(self, round_id: str) -> dict[str, Any]:
        round_record = self.repository.get_round(round_id)
        pending = self.repository.pending_input(round_id)
        attempts = self.repository.list_attempts(round_id)
        execution = (
            None
            if round_record.execution_id is None
            else self.executions.execution(round_record.execution_id)
        )
        current_question = None
        if round_record.current_index < len(round_record.question_snapshots):
            question = round_record.question_snapshots[round_record.current_index]
            current_question = {
                "id": question.question_id,
                "title": question.title,
                "question_text": question.question_text,
                "topics": question.topics,
                "difficulty": question.difficulty,
            }
        reports = []
        for report_kind in ("session_report", "mastery_report"):
            proposal = self.repository.find_report_proposal(
                round_id, report_kind
            )
            if proposal is None:
                continue
            draft = await self.drafts.get(proposal.draft_id)
            publication = await self.publications.latest_for_draft(draft.id)
            reports.append(
                {
                    "id": draft.id,
                    "report_kind": report_kind,
                    "title": draft.title,
                    "status": draft.status,
                    "version": draft.version,
                    "publication": (
                        None
                        if publication is None
                        else {
                            "state": publication.state,
                            "target_path": publication.target_path,
                            "error_code": publication.error_code,
                        }
                    ),
                }
            )
        return {
            "id": round_record.id,
            "workspace_id": round_record.workspace_id,
            "session_id": round_record.session_id,
            "execution_id": round_record.execution_id,
            "settings": asdict(round_record.settings),
            "status": round_record.status,
            "current_index": round_record.current_index,
            "question_count": len(round_record.question_snapshots),
            "current_question": current_question,
            "current_input": None if pending is None else asdict(pending),
            "attempts": [asdict(item) for item in attempts],
            "reports": reports,
            "usage": self.executions.usage(round_record.session_id),
            "execution_status": None if execution is None else execution.status,
            "created_at": round_record.created_at,
            "updated_at": round_record.updated_at,
            "completed_at": round_record.completed_at,
        }

    async def list_round_resources(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            [
                await self.round_resource(item.id)
                for item in self.repository.list_rounds(self.workspace_id)
            ]
        )

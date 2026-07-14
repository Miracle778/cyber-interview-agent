from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from app.application.execution_service import AgentExecutionService
from app.application.session_service import AgentSessionService, ProductEventStream
from app.hitl.models import ResolveActionCommand
from app.hitl.repository import PendingActionRepository
from app.hitl.service import HitlService
from app.knowledge.drafts import KnowledgeDraftService, UpdateDraftCommand
from app.knowledge.source_registry import KnowledgeSourceService
from app.knowledge.publication import PublicationService
from app.review.errors import ReviewConflictError
from app.review.curation_commands import CurationCommandService
from app.review.models import CurationSummary, ReviewRoundSettings
from app.review.repository import ReviewRepository
from app.review.selector import QuestionSelector
from app.review.timeline import SessionTimelineProjector
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
        actions: PendingActionRepository,
        hitl: HitlService,
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
        self.actions = actions
        self.hitl = hitl
        self.selector = QuestionSelector()
        self.curation_commands = CurationCommandService()
        self.timeline = SessionTimelineProjector(
            self.sessions.repository, self.events
        )

    async def create_curation_session(
        self, *, source_refs: tuple[str, ...]
    ) -> dict[str, Any]:
        selected = tuple(dict.fromkeys(source_refs))
        if not selected:
            raise ValueError("source_refs must not be empty")
        source_service = KnowledgeSourceService(
            self.workspace_root, workspace_id=self.workspace_id
        )
        sources = [await source_service.get(source_id) for source_id in selected]
        existing = self.repository.list_curation_sessions(self.workspace_id)
        warnings: list[dict[str, object]] = []
        for source_id in selected:
            related = [item for item in existing if source_id in item.source_refs]
            if not related:
                continue
            in_progress = any(
                item.stage
                not in {"waiting_for_command", "completed", "failed"}
                for item in related
            )
            warnings.append(
                {
                    "sourceId": source_id,
                    "code": (
                        "source_curating"
                        if in_progress
                        else "source_previously_curated"
                    ),
                }
            )
        visible_names = [source.original_filename for source in sources[:2]]
        suffix = "" if len(sources) <= 2 else f" 等 {len(sources)} 份资料"
        session = await self.sessions.create(
            workspace_id=self.workspace_id,
            kind="question.curate",
            title=" + ".join(visible_names) + suffix,
        )
        self.repository.create_curation_session(
            workspace_id=self.workspace_id,
            session_id=session.id,
            source_refs=selected,
            warnings=tuple(warnings),
        )
        self.repository.update_curation_progress(
            session.id,
            stage="reading_sources",
            completed_units=0,
            total_units=len(sources),
        )
        await self.timeline.append(
            session_id=session.id,
            execution_id=None,
            role="assistant",
            message_kind="stage",
            content="正在读取所选资料",
            payload={
                "resourceId": session.id,
                "version": 0,
                "stage": "reading_sources",
            },
        )
        excerpts: list[str] = []
        for index, source in enumerate(sources, start=1):
            text = extract_text(self.workspace_root / source.stored_path)
            excerpts.append(
                f"{source.id}:{source.original_filename}\n{text[:20_000]}"
            )
            self.repository.update_curation_progress(
                session.id,
                stage="reading_sources",
                completed_units=index,
                total_units=len(sources),
            )
        batch = self.repository.create_batch(
            workspace_id=self.workspace_id,
            session_id=session.id,
            run_id=None,
            source_refs=selected,
        )
        self.repository.update_curation_progress(
            session.id,
            stage="generating",
            completed_units=0,
            total_units=max(1, len(excerpts)),
            active_batch_id=batch.id,
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
                "rewrite_feedback": None,
            },
        )
        self.repository.attach_batch_run(batch.id, execution.id)
        await self.timeline.append(
            session_id=session.id,
            execution_id=execution.id,
            role="assistant",
            message_kind="stage",
            content="正在生成候选题",
            payload={
                "resourceId": session.id,
                "version": 0,
                "stage": "generating",
            },
        )
        return await self.curation_resource(session.id)

    async def curation_resource(self, session_id: str) -> dict[str, Any]:
        record = self.repository.get_curation_session(session_id)
        if record.workspace_id != self.workspace_id:
            raise LookupError(session_id)
        session = self.sessions.get(session_id)
        source_service = KnowledgeSourceService(
            self.workspace_root, workspace_id=self.workspace_id
        )
        sources = [
            await source_service.get(source_id) for source_id in record.source_refs
        ]
        batches = [
            batch
            for batch in self.repository.list_batches(self.workspace_id)
            if batch.session_id == session_id
        ]
        candidates = [
            candidate
            for candidate in self.repository.list_candidates(self.workspace_id)
            if any(candidate.batch_id == batch.id for batch in batches)
        ]
        latest = self.sessions.repository.latest_execution(session_id)
        warnings_by_source = {
            str(item["sourceId"]): str(item["code"])
            for item in record.warnings
        }
        source_resources = []
        for source in sources:
            warning = warnings_by_source.get(source.id)
            state = (
                "in_progress"
                if warning == "source_curating"
                else "previously_curated"
                if warning == "source_previously_curated"
                else "not_curated"
            )
            source_resources.append(
                {
                    "id": source.id,
                    "filename": source.original_filename,
                    "organization_state": state,
                }
            )
        return {
            "id": record.session_id,
            "workspace_id": record.workspace_id,
            "title": session.title,
            "source_refs": record.source_refs,
            "sources": source_resources,
            "active_batch_id": record.active_batch_id,
            "execution_id": None if latest is None else latest.id,
            "execution_status": None if latest is None else latest.status,
            "stage": record.stage,
            "progress": {
                "completed": record.completed_units,
                "total": record.total_units,
            },
            "summary": asdict(record.summary),
            "summary_version": record.summary_version,
            "warnings": record.warnings,
            "candidate_count": len(candidates),
            "pending_count": sum(
                item.status == "review_pending" for item in candidates
            ),
            "published_count": sum(
                item.status == "published" for item in candidates
            ),
            "messages": [
                asdict(item)
                for item in self.sessions.repository.list_messages(session_id)
            ],
            "usage": self.executions.usage(session_id),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    async def list_curation_resources(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            [
                await self.curation_resource(record.session_id)
                for record in self.repository.list_curation_sessions(
                    self.workspace_id
                )
            ]
        )

    async def execute_curation_command(
        self,
        session_id: str,
        *,
        text: str,
        summary_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        curation = self.repository.get_curation_session(session_id)
        parsed = self.curation_commands.parse(
            text=text,
            summary=curation.summary,
            current_summary_version=curation.summary_version,
            expected_summary_version=summary_version,
        )
        command_payload: dict[str, object] = {
            "kind": parsed.kind,
            "candidateIds": parsed.candidate_ids,
            "feedback": parsed.feedback,
            "clarification": parsed.clarification,
        }
        receipt, created = self.repository.begin_curation_command(
            session_id=session_id,
            idempotency_key=idempotency_key,
            text=text,
            summary_version=summary_version,
            command=command_payload,
        )
        if not created:
            return self._curation_command_resource(receipt)
        latest = self.sessions.repository.latest_execution(session_id)
        execution_id = None if latest is None else latest.id
        await self.timeline.append(
            session_id=session_id,
            execution_id=execution_id,
            role="user",
            message_kind="text",
            content=text,
            payload={
                "resourceId": receipt.id,
                "version": summary_version,
            },
        )
        result: dict[str, object]
        terminal_status = "completed"
        if parsed.kind == "clarify":
            result = {"clarification": parsed.clarification}
            await self.timeline.append(
                session_id=session_id,
                execution_id=execution_id,
                role="assistant",
                message_kind="command_receipt",
                content=parsed.clarification,
                payload={
                    "resourceId": receipt.id,
                    "version": summary_version,
                },
            )
        elif parsed.kind == "reject":
            rejected = []
            for candidate_id in parsed.candidate_ids:
                candidate = self.repository.get_candidate(candidate_id)
                if candidate.draft_id is not None:
                    draft = await self.drafts.get(candidate.draft_id)
                    await self.drafts.mark_rejected(
                        draft.id,
                        expected_version=draft.version,
                        expected_hash=draft.content_hash,
                    )
                self.repository.update_candidate_status(
                    candidate_id, status="rejected"
                )
                rejected.append(candidate_id)
            result = {"rejectedIds": rejected, "rejectedCount": len(rejected)}
        elif parsed.kind == "confirm":
            published: list[str] = []
            failed: list[dict[str, str]] = []
            for candidate_id in parsed.candidate_ids:
                try:
                    await self._publish_curation_candidate(
                        candidate_id,
                        idempotency_key=(
                            f"{idempotency_key}:{candidate_id}"
                        ),
                    )
                    published.append(candidate_id)
                except Exception:
                    failed.append(
                        {
                            "candidateId": candidate_id,
                            "code": "publication_failed",
                        }
                    )
            result = {
                "publishedIds": published,
                "publishedCount": len(published),
                "failures": failed,
            }
            terminal_status = "partial_failure" if failed else "completed"
        elif parsed.kind == "rewrite":
            candidate = self.repository.get_candidate(parsed.candidate_ids[0])
            execution = await self._start_curation_execution(
                session_id=session_id,
                source_refs=curation.source_refs,
                rewrite_feedback=parsed.feedback,
                rewrite_of_batch_id=candidate.batch_id,
            )
            result = {"executionId": execution.id}
        else:
            refreshed = self._summarize_curation(session_id)
            result = {"summaryVersion": refreshed.summary_version}

        receipt = self.repository.complete_curation_command(
            receipt.id, result=result, status=terminal_status
        )
        if parsed.kind != "clarify":
            await self.timeline.append(
                session_id=session_id,
                execution_id=execution_id,
                role="assistant",
                message_kind="command_receipt",
                content=self._command_result_text(parsed.kind, result),
                payload={
                    "resourceId": receipt.id,
                    "version": summary_version,
                },
            )
        await self.events.publish(
            session_id,
            execution_id,
            "curation.command.resolved",
            {
                "resourceId": receipt.id,
                "kind": parsed.kind,
                "status": receipt.status,
                "count": len(parsed.candidate_ids),
                "version": summary_version,
            },
        )
        return self._curation_command_resource(receipt)

    async def _publish_curation_candidate(
        self, candidate_id: str, *, idempotency_key: str
    ) -> None:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate.status == "published":
            return
        if candidate.draft_id is None:
            raise ReviewConflictError("candidate has no draft")
        draft = await self.drafts.get(candidate.draft_id)
        publication_session = await self.sessions.create(
            workspace_id=self.workspace_id,
            kind="knowledge.publish",
            title=f"发布题目：{draft.title}",
        )
        execution = await self.executions.start(
            publication_session,
            input={
                "draftId": draft.id,
                "draftVersion": draft.version,
                "contentHash": draft.content_hash,
                "title": draft.title,
                "markdown": draft.markdown,
            },
        )
        await self.drafts.mark_review_pending(
            draft.id,
            expected_version=draft.version,
            expected_hash=draft.content_hash,
        )
        await self.executions.wait(execution.id)
        pending = await self.actions.list_pending(
            self.workspace_id, session_id=publication_session.id
        )
        if len(pending) != 1:
            raise ReviewConflictError("publication action was not created")
        await self.hitl.approve(
            pending[0].id,
            ResolveActionCommand(
                version=pending[0].version,
                idempotency_key=idempotency_key,
            ),
        )
        await self.executions.wait(execution.id)

    async def _start_curation_execution(
        self,
        *,
        session_id: str,
        source_refs: tuple[str, ...],
        rewrite_feedback: str | None,
        rewrite_of_batch_id: str | None,
    ):
        session = self.sessions.get(session_id)
        source_service = KnowledgeSourceService(
            self.workspace_root, workspace_id=self.workspace_id
        )
        excerpts = []
        for source_id in source_refs:
            source = await source_service.get(source_id)
            text = extract_text(self.workspace_root / source.stored_path)
            excerpts.append(
                f"{source.id}:{source.original_filename}\n{text[:20_000]}"
            )
        batch = self.repository.create_batch(
            workspace_id=self.workspace_id,
            session_id=session_id,
            run_id=None,
            source_refs=source_refs,
            rewrite_of_batch_id=rewrite_of_batch_id,
        )
        current = self.repository.get_curation_session(session_id)
        self.repository.update_curation_progress(
            session_id,
            stage="generating",
            completed_units=0,
            total_units=max(1, len(excerpts)),
            active_batch_id=batch.id,
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
        self.repository.attach_batch_run(batch.id, execution.id)
        await self.timeline.append(
            session_id=session_id,
            execution_id=execution.id,
            role="assistant",
            message_kind="stage",
            content="正在按要求重写候选题",
            payload={
                "resourceId": session_id,
                "version": current.summary_version,
                "stage": "generating",
            },
        )
        return execution

    def _summarize_curation(self, session_id: str):
        current = self.repository.get_curation_session(session_id)
        candidates = [
            item
            for item in self.repository.list_candidates(self.workspace_id)
            if self.repository.get_batch(item.batch_id).session_id == session_id
        ]
        summary = CurationSummary(
            items=tuple(
                {
                    "ordinal": index,
                    "candidateId": item.id,
                    "title": item.question.title,
                    "topics": item.question.topics,
                    "difficulty": item.question.difficulty,
                    "sourceCount": len(item.source_refs),
                    "recommendation": (
                        "suggest_reject"
                        if item.status == "rejected"
                        else "link_existing"
                        if item.duplicate_of_question_id
                        else "recommend_confirm"
                    ),
                }
                for index, item in enumerate(candidates, start=1)
            )
        )
        return self.repository.replace_curation_summary(
            session_id,
            expected_version=current.summary_version,
            summary=summary,
        )

    @staticmethod
    def _command_result_text(kind: str, result: dict[str, object]) -> str:
        if kind == "confirm":
            return f"已发布 {result.get('publishedCount', 0)} 道题。"
        if kind == "reject":
            return f"已拒绝 {result.get('rejectedCount', 0)} 道题。"
        if kind == "rewrite":
            return "已开始按要求重写。"
        return "已重新生成整理总结。"

    @staticmethod
    def _curation_command_resource(receipt) -> dict[str, Any]:
        candidate_ids = receipt.command.get("candidateIds", ())
        return {
            "id": receipt.id,
            "session_id": receipt.session_id,
            "summary_version": receipt.summary_version,
            "kind": receipt.command["kind"],
            "target_ids": candidate_ids,
            "status": receipt.status,
            "result": receipt.result,
            "created_at": receipt.created_at,
            "completed_at": receipt.completed_at,
        }

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

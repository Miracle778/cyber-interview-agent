from __future__ import annotations

import asyncio
import sqlite3
from contextlib import nullcontext
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal
from uuid import uuid4

from app.application.execution_service import (
    AgentExecutionService,
    ExecutionCancellation,
    ExecutionCancelled,
)
from app.agents.context import AgentContext
from app.agents.context_assembly import (
    ContextAssembler,
    ContextBudget,
    ContextBudgetExceededError,
    ContextSummary,
)
from app.agents.curation_command_agents import CurationCommandAgents
from app.agents.question_curation_contracts import (
    QuestionCandidate,
    QuestionCandidateChunk,
)
from app.agents.agent_factory import ModelOverride
from app.application.session_service import (
    AgentSessionService,
    MessageRecord,
    ProductRecordNotFoundError,
    ProductEventStream,
    ReasoningEffort,
)
from app.hitl.models import CreatePendingAction, ResolveActionCommand
from app.hitl.repository import PendingActionRepository
from app.hitl.service import HitlService
from app.knowledge.drafts import (
    CreateDraftCommand,
    KnowledgeDraftService,
    UpdateDraftCommand,
)
from app.knowledge.source_registry import KnowledgeSourceService
from app.knowledge.publication import PublicationService
from app.review.errors import InsufficientQuestionsError, ReviewConflictError
from app.review.turn_intent import classify_review_turn
from app.review.turn_intent import ReviewTurnIntent
from app.review.curation_commands import CurationCommandService
from app.review.curation_command_contracts import CurationCommandPlan
from app.review.curation_context import (
    CurationCommandInterpreter,
    CurationContextAdapter,
)
from app.review.curation_sources import prepare_curation_sources
from app.review.curation_seed_reconciliation import reconcile_curation_seed_tasks
from app.review.models import (
    BulkPublicationPreflight,
    CurationSummary,
    QuestionSnapshot,
    ReviewRoundSettings,
)
from app.review.repository import ReviewRepository
from app.review.selector import QuestionSelector
from app.review.timeline import SessionTimelineProjector
from app.middleware.usage_projection_middleware import ContextUsageProjection
from app.security.workspace_paths import PathPolicyError, WorkspacePathPolicy


_CURATION_TIMELINE_KINDS = frozenset(
    {
        "stage",
        "curation_summary",
        "question_card",
        "command_receipt",
        "error",
    }
)


def _is_curation_timeline_message(message: MessageRecord) -> bool:
    if message.message_kind in _CURATION_TIMELINE_KINDS:
        return True
    return (
        message.message_kind == "text"
        and message.role == "user"
        and isinstance(message.payload.get("resourceId"), str)
    )


def _is_transient_sqlite_lock(error: BaseException) -> bool:
    return isinstance(error, sqlite3.OperationalError) and any(
        marker in str(error).casefold()
        for marker in (
            "database is locked",
            "database table is locked",
            "database is busy",
        )
    )


def _publication_error_code(error: BaseException) -> str:
    if _is_transient_sqlite_lock(error):
        return "database_locked"
    if isinstance(error, ReviewConflictError):
        return "publication_conflict"
    stable_code = getattr(error, "code", None)
    if isinstance(stable_code, str) and stable_code in {
        "publication_failed",
        "publication_index_failed",
    }:
        return stable_code
    return "publication_failed"


def _seed_progress_resource(seed_tasks) -> dict[str, int]:
    statuses = [item.status for item in seed_tasks]
    return {
        "total": len(statuses),
        "completed": statuses.count("completed"),
        "degraded": statuses.count("degraded"),
        "retrying": sum(
            status in {"running", "retryable", "interrupted"} for status in statuses
        ),
        "skipped": statuses.count("skipped"),
        "pending": statuses.count("pending"),
    }


def _quality_summary_resource(seed_tasks) -> dict[str, int]:
    candidates = [item for item in seed_tasks if item.candidate is not None]
    return {
        basis: sum(item.answer_basis == basis for item in candidates)
        for basis in ("source", "mixed", "model", "unknown")
    } | {"needs_review": sum(item.needs_review for item in candidates)}


def _seed_event_payload(session_id: str, task) -> dict[str, object]:
    return {
        "sessionId": session_id,
        "batchId": task.batch_id,
        "seedTaskId": task.id,
        "status": task.status,
        "automaticAttemptCount": task.automatic_attempt_count,
        "manualAttemptCount": task.manual_attempt_count,
        "answerBasis": task.answer_basis,
        "materialSupport": task.material_support,
        "needsReview": task.needs_review,
        "errorCode": task.last_error_code,
    }


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
        curation_command_agents: CurationCommandAgents | None = None,
        curation_command_agents_factory: (
            Callable[[ModelOverride], CurationCommandAgents] | None
        ) = None,
        curation_context_projection=None,
        curation_context_factory: Callable[..., AgentContext] | None = None,
        review_turn_classifier: (
            Callable[..., Awaitable[ReviewTurnIntent]] | None
        ) = None,
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
        self.curation_command_agents = curation_command_agents
        self.curation_command_agents_factory = curation_command_agents_factory
        self.curation_context_projection = curation_context_projection
        self.curation_context_factory = curation_context_factory
        self.review_turn_classifier = review_turn_classifier
        self.selector = QuestionSelector()
        self._discussion_locks: dict[str, asyncio.Lock] = {}
        self._curation_control_locks: dict[str, asyncio.Lock] = {}
        self.curation_commands = CurationCommandService()
        self.timeline = SessionTimelineProjector(self.sessions.repository, self.events)

    async def create_curation_session(
        self, *, source_refs: tuple[str, ...]
    ) -> dict[str, Any]:
        selected = tuple(dict.fromkeys(source_refs))
        if not selected:
            raise ValueError("source_refs must not be empty")
        source_service = KnowledgeSourceService(
            self.workspace_root, workspace_id=self.workspace_id
        )
        sources = [
            await source_service.get(source_id, include_deleted=False)
            for source_id in selected
        ]
        prepared_sources, excerpts = self._prepare_curation_source_records(sources)
        existing = self.repository.list_curation_sessions(self.workspace_id)
        warnings: list[dict[str, object]] = []
        for source_id in selected:
            related = [item for item in existing if source_id in item.source_refs]
            if not related:
                continue
            in_progress = any(
                item.stage not in {"waiting_for_command", "completed", "failed"}
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
        warnings.extend(prepared_sources.warnings)
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
        for index, _source in enumerate(sources, start=1):
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
            status=("generating" if prepared_sources.has_usable_text else "completed"),
        )
        if not prepared_sources.has_usable_text:
            await self._complete_curation_without_text(
                session_id=session.id,
                batch_id=batch.id,
                source_count=len(sources),
            )
            return await self.curation_resource(session.id)
        self.repository.update_curation_progress(
            session.id,
            stage="generating",
            completed_units=0,
            total_units=max(1, len(excerpts)),
            active_batch_id=batch.id,
        )
        execution = await self.executions.prepare(
            session,
            input={
                "batchId": batch.id,
                "batch_id": batch.id,
                "source_excerpts": excerpts,
                "similar_questions": [
                    item.snapshot.question_text
                    for item in self.repository.list_active_questions(self.workspace_id)
                ],
                "rewrite_feedback": None,
            },
            project_input_message=False,
        )
        self.repository.attach_batch_run(batch.id, execution.id)
        self.repository.record_curation_attempt(
            batch.id, execution.id, reason="initial"
        )
        self.executions.run_prepared(execution, graph_input=execution.input)
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

    def _curation_source_path(self, stored_path: str) -> Path:
        filename = Path(stored_path).name
        expected = f"artifacts/review/sources/{filename}"
        if not filename or stored_path != expected:
            raise PathPolicyError("review.sources")
        return WorkspacePathPolicy(self.workspace_root).resolve_for_read(
            "review.sources", filename
        )

    def _prepare_curation_source_records(
        self, sources, *, character_limit: int | None = None
    ):
        prepared = prepare_curation_sources(
            tuple(
                (source.id, self._curation_source_path(source.stored_path))
                for source in sources
            )
        )
        filenames = {source.id: source.original_filename for source in sources}
        excerpts = [
            f"{source_id}:{filenames[source_id]}\n"
            + (text if character_limit is None else text[:character_limit])
            for source_id, text in prepared.excerpts
        ]
        return prepared, excerpts

    async def _complete_curation_without_text(
        self, *, session_id: str, batch_id: str, source_count: int
    ) -> None:
        self.repository.update_curation_progress(
            session_id,
            stage="completed",
            completed_units=source_count,
            total_units=source_count,
            active_batch_id=batch_id,
        )
        self.sessions.complete_idle(session_id)
        await self.timeline.append(
            session_id=session_id,
            execution_id=None,
            role="assistant",
            message_kind="stage",
            content="所选资料没有可提取文本，整理已完成",
            payload={
                "resourceId": session_id,
                "version": 0,
                "stage": "completed",
            },
        )

    async def curation_resource(self, session_id: str) -> dict[str, Any]:
        record = self.repository.get_curation_session(session_id)
        if record.workspace_id != self.workspace_id:
            raise LookupError(session_id)
        session = self.sessions.repository.get_session(session_id, include_deleted=True)
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
        candidates = list(
            self.repository.list_candidates(
                self.workspace_id,
                batch_ids=tuple(batch.id for batch in batches),
                limit=None,
            )
        )
        latest_command = self.repository.latest_curation_command_receipt(session_id)
        batch = (
            None
            if record.active_batch_id is None
            else self.repository.get_batch(record.active_batch_id)
        )
        seed_tasks = ()
        if batch is not None:
            reconciliation = reconcile_curation_seed_tasks(self.repository, batch.id)
            for warning in reconciliation.warnings:
                self.repository.append_curation_warning(session_id, warning)
            if reconciliation.warnings:
                record = self.repository.get_curation_session(session_id)
            seed_tasks = self.repository.list_curation_seed_tasks(batch.id)
        latest = (
            self.sessions.repository.latest_execution(session_id)
            if batch is None or batch.run_id is None
            else self.sessions.repository.get_execution(batch.run_id)
        )
        work_items = (
            () if batch is None else self.repository.list_curation_work_items(batch.id)
        )
        phase = self._active_curation_phase(record)
        phase_items = (
            seed_tasks
            if phase == "enrichment" and seed_tasks
            else tuple(item for item in work_items if item.stage == phase)
            if phase is not None
            else ()
        )
        provisional_candidates: list[dict[str, object]] = []
        generated_candidate_count = 0
        if seed_tasks:
            generated_candidate_count = sum(
                item.candidate is not None for item in seed_tasks
            )
            show_provisional = batch is not None and batch.status in {
                "generating",
                "paused",
                "interrupted",
                "failed",
            }
            formal_seed_ids = {
                candidate.seed_task_id
                for candidate in candidates
                if candidate.seed_task_id is not None
            }
            for item in seed_tasks:
                if not show_provisional and item.id in formal_seed_ids:
                    continue
                candidate = (
                    None
                    if item.candidate is None
                    else QuestionCandidate.model_validate(item.candidate)
                )
                if len(provisional_candidates) >= 200:
                    break
                provisional_candidates.append(
                    {
                        "id": item.id,
                        "title": (
                            item.question_text if candidate is None else candidate.title
                        ),
                        "question_text": item.question_text,
                        "source_refs": item.source_refs,
                        "seed_task_id": item.id,
                        "answer_basis": item.answer_basis,
                        "material_support": item.material_support,
                        "needs_review": item.needs_review,
                        "normalization_issues": item.normalization_issues,
                        "source_answer": item.source_answer,
                        "supplemental_answer": item.supplemental_answer,
                        "status": item.status,
                        "version": item.version,
                        "error_code": item.last_error_code,
                    }
                )
        else:
            for item in work_items:
                if (
                    item.stage != "enrichment"
                    or item.status != "completed"
                    or item.output is None
                ):
                    continue
                chunk = QuestionCandidateChunk.model_validate(item.output)
                generated_candidate_count += len(chunk.candidates)
                if batch is None or batch.status not in {
                    "generating",
                    "paused",
                    "interrupted",
                    "failed",
                }:
                    continue
                for ordinal, candidate in enumerate(chunk.candidates):
                    if len(provisional_candidates) >= 200:
                        break
                    provisional_candidates.append(
                        {
                            "id": f"{item.id}:{ordinal}",
                            "title": candidate.title,
                            "question_text": candidate.question_text,
                            "source_refs": candidate.source_refs,
                        }
                    )
        timing = (
            None if batch is None else self.repository.curation_batch_timing(batch.id)
        )
        controls = self._curation_controls(batch)
        projected_stage = (
            "pausing"
            if batch is not None
            and batch.status == "generating"
            and batch.control_intent == "pause"
            else record.stage
        )
        organization_warnings_by_source = {
            str(item["sourceId"]): str(item["code"])
            for item in record.warnings
            if item.get("code") in {"source_curating", "source_previously_curated"}
        }
        source_resources = []
        for source in sources:
            warning = organization_warnings_by_source.get(source.id)
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
            "deleted_at": session.deleted_at,
            "source_refs": record.source_refs,
            "sources": source_resources,
            "active_batch_id": record.active_batch_id,
            "batch_status": None if batch is None else batch.status,
            "batch_version": None if batch is None else batch.version,
            "execution_id": None if latest is None else latest.id,
            "execution_status": None if latest is None else latest.status,
            "execution_started_at": None if latest is None else latest.started_at,
            "execution_finished_at": None if latest is None else latest.finished_at,
            "execution_error_code": None if latest is None else latest.error_code,
            "execution_error_message": None if latest is None else latest.error_message,
            "context_compacted": self.sessions.repository.context_compacted(session_id),
            "context_usage": self.sessions.repository.context_usage(session_id),
            "stage": projected_stage,
            "progress": {
                "phase": phase,
                "completed": (
                    sum(
                        item.status in {"completed", "degraded", "skipped"}
                        for item in phase_items
                    )
                    if phase_items
                    else record.completed_units
                ),
                "total": len(phase_items) if phase_items else record.total_units,
                "generated_candidate_count": generated_candidate_count,
                "active_workers": sum(
                    item.status == "running"
                    for item in (
                        seed_tasks
                        if phase == "enrichment" and seed_tasks
                        else work_items
                    )
                ),
                "retryable_units": sum(
                    item.status in {"failed", "interrupted", "retryable"}
                    for item in phase_items
                ),
                "pending_units": sum(item.status == "pending" for item in phase_items),
            },
            "timing": {
                "current_elapsed_ms": (
                    0 if timing is None else timing.current_elapsed_ms
                ),
                "cumulative_elapsed_ms": (
                    0 if timing is None else timing.cumulative_elapsed_ms
                ),
            },
            "controls": controls,
            "provisional_candidates": provisional_candidates,
            "seed_progress": _seed_progress_resource(seed_tasks),
            "quality_summary": _quality_summary_resource(seed_tasks),
            "source_warnings": [
                warning
                for warning in record.warnings
                if isinstance(warning.get("sourceId"), str)
            ],
            "summary": asdict(record.summary),
            "summary_version": record.summary_version,
            "warnings": record.warnings,
            "preferred_model_id": record.preferred_model_id,
            "preferred_reasoning_effort": record.preferred_reasoning_effort,
            "latest_command": (
                None
                if latest_command is None
                else {
                    "command_id": latest_command.id,
                    "execution_id": latest_command.execution_id,
                    "lifecycle_status": latest_command.lifecycle_status,
                    "retry_count": latest_command.retry_count,
                }
            ),
            "candidate_count": len(candidates),
            "pending_count": sum(
                item.status == "review_pending" for item in candidates
            ),
            "published_count": sum(item.status == "published" for item in candidates),
            "messages": [
                asdict(item)
                for item in self.sessions.repository.list_messages(session_id)
                if _is_curation_timeline_message(item)
            ],
            "usage": self.executions.usage(session_id),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    async def pause_curation_session(
        self,
        session_id: str,
        *,
        expected_batch_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._control_curation_session(
            session_id,
            operation="pause",
            expected_batch_version=expected_batch_version,
            idempotency_key=idempotency_key,
        )

    async def terminate_curation_session(
        self,
        session_id: str,
        *,
        expected_batch_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._control_curation_session(
            session_id,
            operation="terminate",
            expected_batch_version=expected_batch_version,
            idempotency_key=idempotency_key,
        )

    async def _control_curation_session(
        self,
        session_id: str,
        *,
        operation: Literal["pause", "terminate"],
        expected_batch_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        curation = self.repository.get_curation_session(session_id)
        if curation.workspace_id != self.workspace_id:
            raise LookupError(session_id)
        if curation.active_batch_id is None:
            raise ReviewConflictError("curation session has no active batch")
        batch_id = curation.active_batch_id
        lock = self._curation_control_locks.setdefault(batch_id, asyncio.Lock())
        async with lock:
            return await self._control_curation_session_locked(
                session_id,
                batch_id=batch_id,
                operation=operation,
                expected_batch_version=expected_batch_version,
                idempotency_key=idempotency_key,
            )

    async def _control_curation_session_locked(
        self,
        session_id: str,
        *,
        batch_id: str,
        operation: Literal["pause", "terminate"],
        expected_batch_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        curation = self.repository.get_curation_session(session_id)
        if curation.active_batch_id != batch_id:
            raise ReviewConflictError("curation active batch changed")
        existing = self.repository.find_curation_control_receipt(
            batch_id, idempotency_key
        )
        try:
            receipt = self.repository.request_batch_control(
                batch_id,
                operation=operation,
                idempotency_key=idempotency_key,
                expected_version=expected_batch_version,
            )
        except ReviewConflictError:
            winner = self.repository.get_batch(batch_id)
            if existing is None and winner.status in {"review_pending", "completed"}:
                return await self.curation_resource(session_id)
            raise
        if receipt.result_status != "requested":
            return await self.curation_resource(session_id)
        intent = self.repository.get_batch(batch_id)
        transient_status = "pausing" if operation == "pause" else "terminating"
        await self.events.publish(
            session_id,
            intent.run_id,
            "curation.control.changed",
            {
                "resourceId": session_id,
                "batchId": batch_id,
                "status": transient_status,
                "operation": operation,
                "version": intent.version,
            },
        )
        if intent.run_id is not None:
            await self.executions.cancel(intent.run_id)
        self.repository.interrupt_running_curation_work_items(
            batch_id, error_code=f"curation_{operation}d"
        )
        try:
            terminal = self.repository.finalize_batch_control(receipt.id)
        except ReviewConflictError:
            winner = self.repository.get_batch(batch_id)
            if winner.status in {"review_pending", "completed"}:
                return await self.curation_resource(session_id)
            raise
        await self.events.publish(
            session_id,
            terminal.run_id,
            "curation.control.changed",
            {
                "resourceId": session_id,
                "batchId": batch_id,
                "status": terminal.status,
                "operation": operation,
                "version": terminal.version,
            },
        )
        return await self.curation_resource(session_id)

    async def resume_curation_session(
        self,
        session_id: str,
        *,
        expected_batch_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        curation = self.repository.get_curation_session(session_id)
        if curation.workspace_id != self.workspace_id:
            raise LookupError(session_id)
        if curation.active_batch_id is None:
            raise ReviewConflictError("curation session has no active batch")
        batch_id = curation.active_batch_id
        lock = self._curation_control_locks.setdefault(batch_id, asyncio.Lock())
        async with lock:
            return await self._resume_curation_session_locked(
                session_id,
                batch_id=batch_id,
                expected_batch_version=expected_batch_version,
                idempotency_key=idempotency_key,
            )

    async def _resume_curation_session_locked(
        self,
        session_id: str,
        *,
        batch_id: str,
        expected_batch_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        curation = self.repository.get_curation_session(session_id)
        if curation.active_batch_id != batch_id:
            raise ReviewConflictError("curation active batch changed")
        batch = self.repository.get_batch(batch_id)
        existing = self.repository.find_curation_control_receipt(
            batch.id, idempotency_key
        )
        if existing is not None and existing.execution_id is not None:
            if existing.operation != "resume":
                raise ReviewConflictError("control request changed")
            attempt = self.repository.get_curation_attempt_for_execution(
                existing.execution_id
            )
            if attempt.reason not in {"paused", "failed", "interrupted"}:
                raise ReviewConflictError("control request changed")
            self.repository.reserve_curation_resume(
                batch.id,
                idempotency_key=idempotency_key,
                expected_version=expected_batch_version,
                reason=attempt.reason,
            )
            return await self.curation_resource(session_id)
        if batch.status == "paused":
            reason: Literal["paused", "failed", "interrupted"] = "paused"
        elif batch.status == "failed":
            reason = "failed"
        elif batch.status == "interrupted":
            reason = "interrupted"
        else:
            raise ReviewConflictError("question batch cannot be resumed")
        reservation = self.repository.reserve_curation_resume(
            batch.id,
            idempotency_key=idempotency_key,
            expected_version=expected_batch_version,
            reason=reason,
        )
        if reservation.execution_id is not None:
            return await self.curation_resource(session_id)
        if reservation.reserved_execution_id is None:
            raise ReviewConflictError("curation resume has no reserved execution")
        reserved_execution_id = reservation.reserved_execution_id
        execution_input = self.repository.curation_batch_input(batch.id)
        session = self.sessions.get(session_id)
        try:
            self.executions.execution(reserved_execution_id)
        except ProductRecordNotFoundError:
            execution = await self.executions.prepare(
                session,
                input=execution_input,
                project_input_message=False,
                execution_id=reserved_execution_id,
            )
        else:
            self.repository.validate_unbound_reserved_curation_execution(
                batch.id,
                idempotency_key=idempotency_key,
                execution_id=reserved_execution_id,
            )
            execution = await self.executions.rearm_prepared(reserved_execution_id)
        try:
            resumed = self.repository.resume_curation_batch(
                batch.id,
                execution_id=execution.id,
                idempotency_key=idempotency_key,
                expected_version=expected_batch_version,
                reason=reason,
            )
        except Exception:
            await self.executions.cancel(execution.id)
            raise
        await self.events.publish(
            session_id,
            execution.id,
            "curation.control.changed",
            {
                "resourceId": session_id,
                "batchId": batch.id,
                "status": resumed.status,
                "operation": "resume",
                "version": resumed.version,
            },
        )
        self.executions.run_prepared(execution, graph_input=execution.input)
        return await self.curation_resource(session_id)

    async def retry_curation_session(self, session_id: str) -> dict[str, Any]:
        curation = self.repository.get_curation_session(session_id)
        if curation.workspace_id != self.workspace_id:
            raise LookupError(session_id)
        if curation.active_batch_id is None:
            raise ReviewConflictError("failed curation session has no active batch")
        batch = self.repository.get_batch(curation.active_batch_id)
        if batch.run_id is not None:
            replay = self.repository.find_curation_resume_receipt_for_execution(
                batch.id, batch.run_id
            )
            if (
                replay is not None
                and replay.idempotency_key.startswith("legacy-retry:")
                and batch.status != "failed"
            ):
                return await self.curation_resource(session_id)
        latest = self.sessions.repository.latest_execution(session_id)
        if curation.stage != "failed" or latest is None or latest.status != "failed":
            raise ReviewConflictError("only failed curation sessions can retry")
        if batch.status != "failed" or batch.control_intent is not None:
            raise ReviewConflictError("only failed question batches can retry")
        await self.timeline.append(
            session_id=session_id,
            execution_id=latest.id,
            role="assistant",
            message_kind="stage",
            content="正在重试失败的整理任务",
            payload={
                "resourceId": session_id,
                "version": curation.summary_version,
                "stage": "queued",
            },
        )
        return await self.resume_curation_session(
            session_id,
            expected_batch_version=batch.version,
            idempotency_key=f"legacy-retry:{latest.id}",
        )

    async def retry_curation_seed_task(
        self,
        session_id: str,
        *,
        seed_task_id: str,
        expected_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        curation = self.repository.get_curation_session(session_id)
        if curation.workspace_id != self.workspace_id:
            raise LookupError(session_id)
        task = self.repository.get_curation_seed_task(seed_task_id)
        if (
            curation.active_batch_id is None
            or task.batch_id != curation.active_batch_id
        ):
            raise LookupError(seed_task_id)
        digest = sha256(str(expected_version).encode("ascii")).hexdigest()
        existing = self.repository.find_curation_seed_retry_receipt(
            seed_task_id, idempotency_key
        )
        if existing is not None:
            if existing.request_digest != digest:
                raise ReviewConflictError("curation seed retry idempotency key changed")
            return self._accepted_seed_retry_resource(existing)

        session = self.sessions.get(session_id)
        execution_input = self.repository.curation_batch_input(task.batch_id)
        execution_input.update(
            {
                "manualSeedTaskId": task.id,
                "manual_seed_task_id": task.id,
                "manualSeedExpectedVersion": expected_version,
                "manual_seed_expected_version": expected_version,
                "manualSeedRetryKey": idempotency_key,
                "manual_seed_retry_key": idempotency_key,
            }
        )
        execution = await self.executions.prepare(
            session, input=execution_input, project_input_message=False
        )
        try:
            receipt, created = self.repository.begin_curation_seed_retry(
                task.id,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
                request_digest=digest,
                execution_id=execution.id,
            )
        except Exception:
            await self.executions.cancel(execution.id)
            raise
        if not created:
            await self.executions.cancel(execution.id)
            return self._accepted_seed_retry_resource(receipt)
        await self.events.publish(
            session_id,
            execution.id,
            "curation.seed.changed",
            _seed_event_payload(session_id, task),
        )
        self.executions.run_prepared(execution, graph_input=execution.input)
        return self._accepted_seed_retry_resource(receipt)

    @staticmethod
    def _accepted_seed_retry_resource(receipt) -> dict[str, str]:
        return {
            "receipt_id": receipt.id,
            "seed_task_id": receipt.seed_task_id,
            "execution_id": receipt.execution_id,
            "status": receipt.result_status,
        }

    async def list_curation_resources(
        self, *, deleted_only: bool = False
    ) -> tuple[dict[str, Any], ...]:
        return tuple(
            [
                await self.curation_resource(record.session_id)
                for record in self.repository.list_curation_sessions(
                    self.workspace_id, deleted_only=deleted_only
                )
            ]
        )

    def preflight_bulk_publication(self, session_id: str) -> BulkPublicationPreflight:
        curation = self.repository.get_curation_session(session_id)
        publishable: list[str] = []
        already_published: list[str] = []
        needs_review: list[str] = []
        blocked: list[str] = []
        for item in curation.summary.items:
            candidate_id = str(item["candidateId"])
            try:
                candidate = self.repository.get_candidate(candidate_id)
            except LookupError:
                blocked.append(candidate_id)
                continue
            recommendation = str(item.get("recommendation") or "")
            if candidate.status == "published":
                already_published.append(candidate_id)
            elif (
                candidate.status == "review_pending"
                and recommendation == "recommend_confirm"
                and candidate.draft_id is not None
            ):
                publishable.append(candidate_id)
            elif candidate.status == "rejected" or recommendation in {
                "link_existing",
                "suggest_reject",
            }:
                needs_review.append(candidate_id)
            else:
                blocked.append(candidate_id)
        return BulkPublicationPreflight(
            session_id=session_id,
            summary_version=curation.summary_version,
            publishable=tuple(publishable),
            already_published=tuple(already_published),
            needs_review=tuple(needs_review),
            blocked=tuple(blocked),
        )

    async def start_bulk_publication(
        self,
        session_id: str,
        *,
        summary_version: int,
        idempotency_key: str,
        candidate_ids: tuple[str, ...],
        confirmed_ai_candidate_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        preflight = self.preflight_bulk_publication(session_id)
        if preflight.summary_version != summary_version:
            raise ReviewConflictError(
                "curation summary changed before bulk publication"
            )
        if candidate_ids != preflight.publishable:
            raise ReviewConflictError("bulk publication eligibility changed")
        confirmed = set(confirmed_ai_candidate_ids)
        if not confirmed.issubset(candidate_ids):
            raise ReviewConflictError("AI confirmation candidate set changed")
        for candidate_id in candidate_ids:
            self._assert_candidate_publishable(
                self.repository.get_candidate(candidate_id),
                confirm_ai_supplement=candidate_id in confirmed,
            )
        operation, created = self.repository.create_bulk_publication(
            session_id=session_id,
            summary_version=summary_version,
            idempotency_key=idempotency_key,
            candidate_ids=candidate_ids,
        )
        if not created:
            return self._accepted_bulk_publication_resource(operation)
        session = self.sessions.get(session_id)
        execution = await self.executions.prepare(
            session,
            input={
                "operation": "curation.bulk_publish",
                "operationId": operation.id,
            },
            project_input_message=False,
        )
        operation = self.repository.attach_bulk_publication_execution(
            operation.id, execution.id
        )
        self._schedule_bulk_publication(operation)
        return self._accepted_bulk_publication_resource(operation)

    def _schedule_bulk_publication(self, operation) -> None:
        if operation.execution_id is None:
            raise ReviewConflictError("bulk publication has no execution")
        execution = self.sessions.repository.get_execution(operation.execution_id)

        async def handler(current, cancellation):
            self.repository.transition_bulk_publication(
                operation.id, expected=("accepted",), target="running"
            )
            try:
                for item in self.repository.list_bulk_publication_items(operation.id):
                    if item.status == "completed":
                        continue
                    cancellation.raise_if_requested()
                    item = self.repository.transition_bulk_publication_item(
                        item.id, expected=("pending",), target="running"
                    )
                    await self.events.publish(
                        operation.session_id,
                        current.id,
                        "publication.changed",
                        {
                            "operationId": operation.id,
                            "candidateId": item.candidate_id,
                            "status": "running",
                        },
                    )
                    try:
                        with cancellation.critical_section():
                            await self._publish_preconfirmed_curation_candidate(
                                item.candidate_id,
                                idempotency_key=item.idempotency_key,
                                session_id=operation.session_id,
                                execution_id=current.id,
                                confirm_ai_supplement=True,
                            )
                            item = self.repository.transition_bulk_publication_item(
                                item.id,
                                expected=("running",),
                                target="completed",
                            )
                    except Exception as error:
                        item = self.repository.transition_bulk_publication_item(
                            item.id,
                            expected=("running",),
                            target="failed",
                            error_code=_publication_error_code(error),
                        )
                    await self.events.publish(
                        operation.session_id,
                        current.id,
                        "publication.changed",
                        {
                            "operationId": operation.id,
                            "candidateId": item.candidate_id,
                            "status": item.status,
                            "errorCode": item.error_code,
                        },
                    )
                    cancellation.raise_if_requested()
                self.repository.complete_bulk_publication_from_items(operation.id)
            except (ExecutionCancelled, asyncio.CancelledError):
                latest = self.sessions.repository.get_execution(current.id)
                self.repository.reset_running_bulk_publication_items(operation.id)
                self.repository.transition_bulk_publication(
                    operation.id,
                    expected=("running",),
                    target=(
                        "cancelled" if latest.cancellation_requested else "interrupted"
                    ),
                )
                raise

        self.executions.run_background(execution, handler)

    async def retry_bulk_publication(
        self, operation_id: str, *, idempotency_key: str
    ) -> dict[str, Any]:
        operation = self.repository.reconcile_bulk_publication(operation_id)
        if operation.retry_idempotency_key == idempotency_key:
            return self._accepted_bulk_publication_resource(operation)
        if operation.status not in {
            "partial_failure",
            "failed",
            "cancelled",
            "interrupted",
        }:
            raise ReviewConflictError("bulk publication cannot be retried")
        session = self.sessions.get(operation.session_id)
        execution = await self.executions.prepare(
            session,
            input={
                "operation": "curation.bulk_publish.retry",
                "operationId": operation.id,
            },
            project_input_message=False,
        )
        operation, _created = self.repository.requeue_bulk_publication(
            operation.id,
            execution_id=execution.id,
            idempotency_key=idempotency_key,
        )
        self._schedule_bulk_publication(operation)
        return self._accepted_bulk_publication_resource(operation)

    def bulk_publication_resource(self, operation_id: str) -> dict[str, Any]:
        operation = self.repository.reconcile_bulk_publication(operation_id)
        return self._bulk_publication_resource(operation)

    def latest_bulk_publication_resource(
        self, session_id: str
    ) -> dict[str, Any] | None:
        operation = self.repository.get_latest_bulk_publication(session_id)
        if operation is None:
            return None
        operation = self.repository.reconcile_bulk_publication(operation.id)
        return self._bulk_publication_resource(operation)

    def _bulk_publication_resource(self, operation) -> dict[str, Any]:
        return {
            "id": operation.id,
            "session_id": operation.session_id,
            "execution_id": operation.execution_id,
            "summary_version": operation.summary_version,
            "status": operation.status,
            "retry_count": operation.retry_count,
            "items": [
                asdict(item)
                for item in self.repository.list_bulk_publication_items(operation.id)
            ],
            "created_at": operation.created_at,
            "completed_at": operation.completed_at,
        }

    @staticmethod
    def _accepted_bulk_publication_resource(operation) -> dict[str, Any]:
        if operation.execution_id is None:
            raise ReviewConflictError("bulk publication has no execution")
        return {
            "operation_id": operation.id,
            "execution_id": operation.execution_id,
            "status": "accepted",
        }

    async def submit_curation_command(
        self,
        session_id: str,
        *,
        text: str,
        summary_version: int,
        idempotency_key: str,
        provider_model_id: str | None,
        reasoning_effort: ReasoningEffort,
    ) -> dict[str, Any]:
        existing = self.repository.find_curation_command_receipt(
            session_id=session_id,
            idempotency_key=idempotency_key,
            text=text,
            summary_version=summary_version,
        )
        if existing is not None:
            if existing.execution_id is None:
                raise ReviewConflictError("curation command has no execution")
            return self._accepted_curation_command_resource(existing)
        curation = self.repository.get_curation_session(session_id)
        if curation.summary_version != summary_version:
            raise ReviewConflictError(
                "curation summary changed before command submission"
            )
        if provider_model_id is not None:
            self.validate_model(provider_model_id, reasoning_effort)
        command_agents = self.curation_command_agents
        if (
            provider_model_id is not None
            and self.curation_command_agents_factory is not None
        ):
            command_agents = self.curation_command_agents_factory(
                ModelOverride(
                    provider_model_id=provider_model_id,
                    reasoning_effort=reasoning_effort,
                )
            )
        submitted_at = datetime.now(timezone.utc).isoformat()
        receipt, created = self.repository.begin_curation_command(
            session_id=session_id,
            idempotency_key=idempotency_key,
            text=text,
            summary_version=summary_version,
            command={"kind": "pending", "candidateIds": []},
        )
        if not created:
            if receipt.execution_id is None:
                raise ReviewConflictError("curation command has no execution")
            return self._accepted_curation_command_resource(receipt)
        session = self.sessions.get(session_id)
        execution = await self.executions.prepare(
            session,
            input={"operation": "curation.command", "commandId": receipt.id},
            project_input_message=False,
            configuration={
                "providerModelId": provider_model_id,
                "reasoningEffort": reasoning_effort,
            },
        )
        receipt = self.repository.attach_curation_command_execution(
            receipt.id, execution.id
        )
        if provider_model_id is not None:
            self.repository.save_curation_preference(
                session_id,
                provider_model_id=provider_model_id,
                reasoning_effort=reasoning_effort,
            )
        await self.timeline.append(
            session_id=session_id,
            execution_id=execution.id,
            role="user",
            message_kind="text",
            content=text,
            payload={
                "resourceId": receipt.id,
                "version": summary_version,
                "submittedAt": submitted_at,
            },
        )

        self._schedule_curation_command(
            receipt=receipt,
            text=text,
            command_agents=command_agents,
            submitted_at=submitted_at,
        )
        return self._accepted_curation_command_resource(receipt)

    def _schedule_curation_command(
        self,
        *,
        receipt,
        text: str,
        command_agents: CurationCommandAgents | None,
        submitted_at: str,
    ) -> None:
        if receipt.execution_id is None:
            raise ReviewConflictError("curation command has no execution")
        execution = self.sessions.repository.get_execution(receipt.execution_id)

        async def handler(current, cancellation):
            self.repository.transition_curation_command_lifecycle(
                receipt.id, expected=("accepted",), target="running"
            )
            try:
                await self.execute_curation_command(
                    receipt.session_id,
                    text=text,
                    summary_version=receipt.summary_version,
                    idempotency_key=receipt.idempotency_key,
                    _prepared_receipt_id=receipt.id,
                    _execution_id=current.id,
                    _cancellation=cancellation,
                    _submitted_at=submitted_at,
                    _command_agents=command_agents,
                )
            except (ExecutionCancelled, asyncio.CancelledError):
                latest = self.sessions.repository.get_execution(current.id)
                target = "cancelled" if latest.cancellation_requested else "interrupted"
                self.repository.transition_curation_command_lifecycle(
                    receipt.id,
                    expected=("running",),
                    target=target,
                )
                raise
            except Exception:
                self.repository.transition_curation_command_lifecycle(
                    receipt.id,
                    expected=("running",),
                    target="failed",
                )
                raise

        self.executions.run_background(execution, handler)

    async def retry_curation_command(self, command_id: str) -> dict[str, Any]:
        receipt = self.repository.get_curation_command_receipt(command_id)
        if receipt.lifecycle_status not in {"interrupted", "failed"}:
            raise ReviewConflictError("curation command cannot be retried")
        curation = self.repository.get_curation_session(receipt.session_id)
        command_agents = self.curation_command_agents
        if (
            curation.preferred_model_id is not None
            and self.curation_command_agents_factory is not None
        ):
            command_agents = self.curation_command_agents_factory(
                ModelOverride(
                    provider_model_id=curation.preferred_model_id,
                    reasoning_effort=curation.preferred_reasoning_effort,
                )
            )
        session = self.sessions.get(receipt.session_id)
        execution = await self.executions.prepare(
            session,
            input={"operation": "curation.command", "commandId": receipt.id},
            project_input_message=False,
            configuration={
                "providerModelId": curation.preferred_model_id,
                "reasoningEffort": curation.preferred_reasoning_effort,
            },
        )
        receipt = self.repository.requeue_curation_command(receipt.id, execution.id)
        self._schedule_curation_command(
            receipt=receipt,
            text=receipt.original_text,
            command_agents=command_agents,
            submitted_at=receipt.created_at,
        )
        return self._accepted_curation_command_resource(receipt)

    async def abandon_curation_command(self, command_id: str) -> None:
        receipt = self.repository.get_curation_command_receipt(command_id)
        if receipt.lifecycle_status in {"completed", "partial_failure", "cancelled"}:
            return
        if receipt.lifecycle_status in {"accepted", "running"}:
            if receipt.execution_id is None:
                raise ReviewConflictError("curation command has no execution")
            await self.executions.cancel(receipt.execution_id)
            latest = self.repository.get_curation_command_receipt(receipt.id)
            if latest.lifecycle_status in {"accepted", "running"}:
                self.repository.transition_curation_command_lifecycle(
                    receipt.id,
                    expected=("accepted", "running"),
                    target="cancelled",
                )
            return
        self.repository.transition_curation_command_lifecycle(
            receipt.id,
            expected=("interrupted", "failed"),
            target="cancelled",
        )

    async def execute_curation_command(
        self,
        session_id: str,
        *,
        text: str,
        summary_version: int,
        idempotency_key: str,
        _prepared_receipt_id: str | None = None,
        _execution_id: str | None = None,
        _cancellation: ExecutionCancellation | None = None,
        _submitted_at: str | None = None,
        _command_agents: CurationCommandAgents | None = None,
    ) -> dict[str, Any]:
        command_started_at = _submitted_at or datetime.now(timezone.utc).isoformat()
        if _prepared_receipt_id is None:
            existing = self.repository.find_curation_command_receipt(
                session_id=session_id,
                idempotency_key=idempotency_key,
                text=text,
                summary_version=summary_version,
            )
            if existing is not None:
                return self._curation_command_resource(existing)
        else:
            existing = None
        curation = self.repository.get_curation_session(session_id)
        if curation.summary_version != summary_version:
            raise ReviewConflictError(
                "curation summary changed before command resolution"
            )
        candidate_resources = tuple(
            [
                await self.candidate_resource(str(item["candidateId"]))
                | {
                    "ordinal": item["ordinal"],
                    "recommendation": item.get("recommendation"),
                    "title": item.get("title", ""),
                }
                for item in curation.summary.items
            ]
        )
        valid_candidate_ids = {
            str(item["candidateId"]) for item in curation.summary.items
        }
        messages = self.sessions.repository.list_messages(session_id)
        context_record = self.repository.get_or_create_curation_context(session_id)
        focused_candidate_ids = context_record.focused_candidate_ids
        if context_record.version == 0 and not focused_candidate_ids:
            focused_candidate_ids = CurationContextAdapter.recover_focus(
                messages, valid_candidate_ids
            )

        deterministic = self.curation_commands.try_parse(
            text, curation.summary, focused_candidate_ids
        )
        command_agents = _command_agents or self.curation_command_agents
        plan: CurationCommandPlan
        if deterministic is not None:
            plan = deterministic
        elif command_agents is None:
            plan = CurationCommandPlan(
                clarification=(
                    "我还不能安全确定要处理哪些题目，请明确题号和要执行的操作。"
                )
            )
        else:
            response_context = None
            response_invocation_context = None

            async def context_provider(*, compact_overflow: bool = True):
                nonlocal context_record, response_context, response_invocation_context
                latest_execution = self.sessions.repository.latest_execution(session_id)
                if latest_execution is None:
                    raise ReviewConflictError("curation session has no execution")
                invocation_context = self._curation_invocation_context(
                    session_id=session_id,
                    run_id=latest_execution.id,
                    idempotency_key=idempotency_key,
                )
                prior_summary = self._context_summary(context_record)
                material = CurationContextAdapter.build_material(
                    current_input=text,
                    summary_version=curation.summary_version,
                    focused_candidate_ids=focused_candidate_ids,
                    prior_summary=prior_summary,
                    summarized_through_message_id=(
                        context_record.summarized_through_message_id
                    ),
                    messages=messages,
                    candidates=candidate_resources,
                )
                assembler = ContextAssembler()
                budget = self._curation_context_budget(
                    command_agents.context_limit_tokens
                )
                try:
                    assembled = assembler.assemble(
                        material,
                        budget,
                        command_agents.token_counter,
                    )
                except ContextBudgetExceededError as error:
                    raise ReviewConflictError(error.code) from error
                if assembled.overflow_turns and compact_overflow:
                    try:
                        compacted = await command_agents.summarizer.summarize(
                            prior_summary=prior_summary,
                            overflow_turns=assembled.overflow_turns,
                            context=invocation_context,
                        )
                        context_record = self.repository.replace_curation_context(
                            session_id,
                            expected_version=context_record.version,
                            focused_candidate_ids=focused_candidate_ids,
                            last_intent=context_record.last_intent,
                            last_result_candidate_ids=(
                                context_record.last_result_candidate_ids
                            ),
                            dialogue_summary=self._summary_payload(compacted),
                            summarized_through_message_id=(
                                compacted.through_message_id
                            ),
                        )
                        material = CurationContextAdapter.build_material(
                            current_input=text,
                            summary_version=curation.summary_version,
                            focused_candidate_ids=focused_candidate_ids,
                            prior_summary=compacted,
                            summarized_through_message_id=(
                                compacted.through_message_id
                            ),
                            messages=messages,
                            candidates=candidate_resources,
                        )
                        assembled = assembler.assemble(
                            material,
                            budget,
                            command_agents.token_counter,
                        )
                        if self.curation_context_projection is not None:
                            self.curation_context_projection.mark_context_compacted(
                                invocation_context
                            )
                    except Exception:
                        if self.curation_context_projection is not None:
                            self.curation_context_projection.warning(
                                invocation_context,
                                "curation_context_summary_failed",
                            )
                if self.curation_context_projection is not None:
                    self.curation_context_projection.record_context_usage(
                        invocation_context,
                        ContextUsageProjection(
                            current_tokens=assembled.estimated_input_tokens,
                            threshold_tokens=assembled.threshold_tokens,
                            estimated=True,
                        ),
                    )
                response_context = assembled
                response_invocation_context = invocation_context
                return assembled, invocation_context

            if _cancellation is not None:
                _cancellation.raise_if_requested()
            await self.events.publish(
                session_id,
                _execution_id,
                "curation.command.interpreting",
                {"resourceId": _prepared_receipt_id or idempotency_key},
            )
            if self.curation_commands.route_input(text) == "conversation":
                response_context, response_invocation_context = await context_provider(
                    compact_overflow=False
                )
                response_chunks: list[str] = []
                async for chunk in command_agents.responder.astream(
                    response_context.render(),
                    context=response_invocation_context,
                ):
                    if _cancellation is not None:
                        _cancellation.raise_if_requested()
                    response_chunks.append(chunk)
                    await self.events.publish(
                        session_id,
                        _execution_id,
                        "assistant.delta",
                        {"text": chunk},
                    )
                plan = CurationCommandPlan(
                    clarification=(
                        "".join(response_chunks).strip()
                        or "我暂时没有生成有效回复，请换一种方式提问。"
                    )
                )
                if response_context.overflow_turns:
                    await context_provider()
            else:
                interpreter = CurationCommandInterpreter(
                    self.curation_commands,
                    command_agents.classifier,
                )
                plan = await interpreter.interpret(
                    text=text,
                    summary=curation.summary,
                    focused_candidate_ids=focused_candidate_ids,
                    context_provider=context_provider,
                )
            if _cancellation is not None:
                _cancellation.raise_if_requested()
        parsed = self.curation_commands.resolve_plan(
            plan=plan,
            summary=curation.summary,
            candidates=candidate_resources,
            current_summary_version=curation.summary_version,
            expected_summary_version=summary_version,
        )
        command_payload: dict[str, object] = {
            "kind": parsed.kind,
            "candidateIds": parsed.candidate_ids,
            "feedback": parsed.feedback,
            "clarification": parsed.clarification,
            "rewriteCandidateIds": parsed.rewrite_candidate_ids,
        }
        if _prepared_receipt_id is None:
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
                    "submittedAt": command_started_at,
                },
            )
        else:
            receipt = self.repository.replace_curation_command_plan(
                _prepared_receipt_id, command_payload
            )
            execution_id = _execution_id
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
                    "startedAt": command_started_at,
                    "candidateIds": parsed.candidate_ids,
                },
            )
        elif parsed.kind == "reject":
            rejected = []
            for candidate_id in parsed.candidate_ids:
                if _cancellation is not None:
                    _cancellation.raise_if_requested()
                critical = (
                    _cancellation.critical_section()
                    if _cancellation is not None
                    else nullcontext()
                )
                with critical:
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
                if _cancellation is not None:
                    _cancellation.raise_if_requested()
            result = {"rejectedIds": rejected, "rejectedCount": len(rejected)}
        elif parsed.kind in {"confirm", "mixed"}:
            published: list[str] = []
            failed: list[dict[str, str]] = []
            for candidate_id in parsed.candidate_ids:
                if _cancellation is not None:
                    _cancellation.raise_if_requested()
                try:
                    critical = (
                        _cancellation.critical_section()
                        if _cancellation is not None
                        else nullcontext()
                    )
                    with critical:
                        await self._publish_curation_candidate(
                            candidate_id,
                            idempotency_key=(f"{idempotency_key}:{candidate_id}"),
                            confirm_ai_supplement=True,
                        )
                    published.append(candidate_id)
                except Exception:
                    failed.append(
                        {
                            "candidateId": candidate_id,
                            "code": "publication_failed",
                        }
                    )
                if _cancellation is not None:
                    _cancellation.raise_if_requested()
            result = {
                "publishedIds": published,
                "publishedCount": len(published),
                "failures": failed,
            }
            terminal_status = "partial_failure" if failed else "completed"
            if parsed.kind == "mixed" and parsed.rewrite_candidate_ids:
                if _cancellation is not None:
                    _cancellation.raise_if_requested()
                rewrite_feedback = self._candidate_notes_feedback(
                    parsed.rewrite_candidate_ids, parsed.feedback
                )
                candidate = self.repository.get_candidate(
                    parsed.rewrite_candidate_ids[0]
                )
                if execution_id is not None:
                    await self.executions.complete_background_execution(execution_id)
                rewrite_execution = await self._start_curation_execution(
                    session_id=session_id,
                    source_refs=curation.source_refs,
                    rewrite_feedback=rewrite_feedback,
                    rewrite_of_batch_id=candidate.batch_id,
                )
                result["rewriteExecutionId"] = (
                    None if rewrite_execution is None else rewrite_execution.id
                )
                result["rewriteCandidateIds"] = list(parsed.rewrite_candidate_ids)
        elif parsed.kind == "rewrite":
            if _cancellation is not None:
                _cancellation.raise_if_requested()
            candidate = self.repository.get_candidate(parsed.candidate_ids[0])
            rewrite_feedback = self._candidate_notes_feedback(
                parsed.candidate_ids, parsed.feedback
            )
            if execution_id is not None:
                await self.executions.complete_background_execution(execution_id)
            execution = await self._start_curation_execution(
                session_id=session_id,
                source_refs=curation.source_refs,
                rewrite_feedback=rewrite_feedback,
                rewrite_of_batch_id=candidate.batch_id,
            )
            result = {"executionId": None if execution is None else execution.id}
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
                    "startedAt": command_started_at,
                    "candidateIds": parsed.candidate_ids,
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
        result_candidate_ids = self._result_candidate_ids(parsed, result)
        if result_candidate_ids:
            latest_context = self.repository.get_or_create_curation_context(session_id)
            focus = CurationContextAdapter.focus_after(
                result_candidate_ids, valid_candidate_ids
            )
            if focus:
                self.repository.replace_curation_context(
                    session_id,
                    expected_version=latest_context.version,
                    focused_candidate_ids=focus,
                    last_intent=(
                        "inspect" if plan.inspect.scope != "none" else parsed.kind
                    ),
                    last_result_candidate_ids=focus,
                    dialogue_summary=latest_context.dialogue_summary,
                    summarized_through_message_id=(
                        latest_context.summarized_through_message_id
                    ),
                )
        return self._curation_command_resource(receipt)

    def _curation_invocation_context(
        self,
        *,
        session_id: str,
        run_id: str,
        idempotency_key: str,
    ) -> AgentContext:
        if self.curation_context_factory is not None:
            return self.curation_context_factory(
                session_id=session_id,
                run_id=run_id,
                idempotency_key=idempotency_key,
                invocation_id=str(uuid4()),
            )
        return AgentContext(
            workspace_id=self.workspace_id,
            workspace_root=self.workspace_root,
            session_id=session_id,
            run_id=run_id,
            allowed_tools=frozenset(),
            allowed_scopes=frozenset(),
            progress_scope=(
                "curation_command",
                idempotency_key,
                str(uuid4()),
            ),
        )

    @staticmethod
    def _curation_context_budget(context_limit_tokens: int) -> ContextBudget:
        return ContextBudget(
            max_input_tokens=max(1, int(context_limit_tokens * 0.70)),
            reserved_output_tokens=max(1, int(context_limit_tokens * 0.10)),
            reserved_system_tokens=max(1, int(context_limit_tokens * 0.05)),
            reserved_schema_tokens=max(1, int(context_limit_tokens * 0.05)),
        )

    @staticmethod
    def _context_summary(context_record) -> ContextSummary:
        stored = context_record.dialogue_summary
        return ContextSummary(
            text=str(stored.get("text") or ""),
            resource_refs=tuple(stored.get("resource_refs") or ()),
            decisions=tuple(stored.get("decisions") or ()),
            open_items=tuple(stored.get("open_items") or ()),
            through_message_id=context_record.summarized_through_message_id,
        )

    @staticmethod
    def _summary_payload(summary: ContextSummary) -> dict[str, object]:
        return {
            "text": summary.text,
            "resource_refs": summary.resource_refs,
            "decisions": summary.decisions,
            "open_items": summary.open_items,
        }

    @staticmethod
    def _result_candidate_ids(parsed, result) -> tuple[str, ...]:
        if parsed.kind == "clarify":
            return parsed.candidate_ids
        if parsed.kind == "reject":
            return tuple(result.get("rejectedIds", ()))
        if parsed.kind in {"confirm", "mixed"}:
            return tuple(result.get("publishedIds", ())) + tuple(
                result.get("rewriteCandidateIds", ())
            )
        if parsed.kind == "rewrite":
            return parsed.candidate_ids
        return ()

    def _candidate_notes_feedback(
        self, candidate_ids: tuple[str, ...], extra: str | None
    ) -> str:
        lines = ["请按以下候选题备注重新生成，并保留其余未指定题目："]
        for candidate_id in candidate_ids:
            candidate = self.repository.get_candidate(candidate_id)
            lines.append(
                f"- {candidate.question.title}（{candidate_id}）：{candidate.review_note or extra or '重新整理'}"
            )
        if extra:
            lines.append(f"补充要求：{extra}")
        return "\n".join(lines)

    async def _publish_curation_candidate(
        self,
        candidate_id: str,
        *,
        idempotency_key: str,
        confirm_ai_supplement: bool = False,
    ) -> None:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate.status == "published":
            return
        self._assert_candidate_publishable(
            candidate, confirm_ai_supplement=confirm_ai_supplement
        )
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
            project_input_message=False,
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
        command = ResolveActionCommand(
            version=pending[0].version,
            idempotency_key=idempotency_key,
        )
        for retry_delay in (0.05, 0.15, None):
            try:
                await self.hitl.approve(pending[0].id, command)
                break
            except sqlite3.OperationalError as error:
                if retry_delay is None or not _is_transient_sqlite_lock(error):
                    raise
                await asyncio.sleep(retry_delay)
        await self.executions.wait(execution.id)

    async def _publish_preconfirmed_curation_candidate(
        self,
        candidate_id: str,
        *,
        idempotency_key: str,
        session_id: str,
        execution_id: str,
        confirm_ai_supplement: bool = False,
    ) -> None:
        """Publish one item inside a user-confirmed bulk operation.

        The bulk command is the user approval boundary.  Each item keeps an
        idempotent authorization receipt for crash recovery, while sharing the
        single bulk session/execution instead of spawning a publication Agent.
        """
        candidate = self.repository.get_candidate(candidate_id)
        if candidate.status == "published":
            return
        self._assert_candidate_publishable(
            candidate, confirm_ai_supplement=confirm_ai_supplement
        )
        if candidate.draft_id is None:
            raise ReviewConflictError("candidate has no draft")
        draft = await self.drafts.get(candidate.draft_id)
        await self.drafts.mark_review_pending(
            draft.id,
            expected_version=draft.version,
            expected_hash=draft.content_hash,
        )
        await self.hitl.approve_preconfirmed(
            CreatePendingAction(
                workspace_id=self.workspace_id,
                session_id=session_id,
                run_id=execution_id,
                action_type="knowledge.publish",
                payload={
                    "draftId": draft.id,
                    "draftVersion": draft.version,
                    "contentHash": draft.content_hash,
                    "title": draft.title,
                    "markdown": draft.markdown,
                },
                preview={
                    "draftId": draft.id,
                    "title": draft.title,
                    "markdown": draft.markdown,
                },
                editable_fields=(),
                idempotency_key=f"preconfirmed:{idempotency_key}",
            ),
            resolution_key=idempotency_key,
        )

    def _assert_candidate_publishable(
        self, candidate, *, confirm_ai_supplement: bool = False
    ) -> None:
        if candidate.status == "rejected":
            raise ReviewConflictError("rejected candidate cannot be published")
        question = candidate.question
        if not all(
            (
                question.title.strip(),
                question.question_text.strip(),
                question.reference_answer.strip(),
                question.topics,
                question.key_points,
                candidate.source_refs,
            )
        ):
            raise ReviewConflictError("candidate has incomplete required fields")
        if question.difficulty not in {"easy", "medium", "hard"}:
            raise ReviewConflictError("candidate difficulty is invalid")
        if (
            candidate.duplicate_of_question_id is not None
            and candidate.revision_of_question_id != candidate.duplicate_of_question_id
        ):
            raise ReviewConflictError(
                "duplicate candidate must be resolved before publication"
            )
        if (
            candidate.answer_basis in {"mixed", "model", "unknown"}
            and not confirm_ai_supplement
        ):
            raise ReviewConflictError(
                "candidate AI supplement requires explicit confirmation"
            )
        from app.review.question_similarity import same_question

        for active in self.repository.list_active_questions(self.workspace_id):
            if active.snapshot.question_id == candidate.question.question_id:
                if (
                    candidate.revision_of_question_id is not None
                    and active.snapshot.content_hash != candidate.revision_base_hash
                    and active.draft_id != candidate.draft_id
                ):
                    raise ReviewConflictError(
                        "active question changed before revision publication"
                    )
                continue
            if same_question(
                candidate.question.question_text,
                active.snapshot.question_text,
                left_topics=candidate.question.topics,
                right_topics=active.snapshot.topics,
                threshold=0.9,
            ):
                raise ReviewConflictError("an equivalent question is already published")

    async def _start_curation_execution(
        self,
        *,
        session_id: str,
        source_refs: tuple[str, ...],
        rewrite_feedback: str | None,
        rewrite_of_batch_id: str | None,
        revision_candidate_id: str | None = None,
        revision_context: str | None = None,
        expected_revision_draft_id: str | None = None,
        expected_revision_draft_version: int | None = None,
        expected_revision_draft_hash: str | None = None,
        resume_batch_id: str | None = None,
    ):
        session = self.sessions.get(session_id)
        batch = (
            self.repository.get_batch(resume_batch_id)
            if resume_batch_id is not None
            else None
        )
        if batch is not None and (
            batch.status != "failed" or batch.control_intent is not None
        ):
            raise ReviewConflictError("question batch cannot be retried")
        execution_input: dict[str, Any]
        current = self.repository.get_curation_session(session_id)
        if batch is not None:
            execution_input = self.repository.curation_batch_input(batch.id)
            raw_excerpts = execution_input.get("source_excerpts", [])
            excerpts = raw_excerpts if isinstance(raw_excerpts, list) else []
        else:
            source_service = KnowledgeSourceService(
                self.workspace_root, workspace_id=self.workspace_id
            )
            excerpts = [revision_context] if revision_context is not None else []
            prepared_sources = None
            if revision_context is None:
                source_records = [
                    await source_service.get(source_id) for source_id in source_refs
                ]
                prepared_sources, excerpts = self._prepare_curation_source_records(
                    source_records
                )
                for warning in prepared_sources.warnings:
                    self.repository.append_curation_warning(session_id, dict(warning))
            batch = self.repository.create_batch(
                workspace_id=self.workspace_id,
                session_id=session_id,
                run_id=None,
                source_refs=source_refs,
                rewrite_of_batch_id=rewrite_of_batch_id,
                status=(
                    "completed"
                    if prepared_sources is not None
                    and not prepared_sources.has_usable_text
                    else "generating"
                ),
            )
            if prepared_sources is not None and not prepared_sources.has_usable_text:
                await self._complete_curation_without_text(
                    session_id=session_id,
                    batch_id=batch.id,
                    source_count=len(source_refs),
                )
                return None
            execution_input = {
                "batchId": batch.id,
                "batch_id": batch.id,
                "sourceRefs": list(batch.source_refs),
                "source_refs": list(batch.source_refs),
                "source_excerpts": excerpts,
                "similar_questions": [
                    item.snapshot.question_text
                    for item in self.repository.list_active_questions(self.workspace_id)
                ],
                "rewrite_feedback": rewrite_feedback,
                "revisionCandidateId": revision_candidate_id,
                "revision_candidate_id": revision_candidate_id,
                "expectedRevisionDraftId": expected_revision_draft_id,
                "expected_revision_draft_id": expected_revision_draft_id,
                "expectedRevisionDraftVersion": expected_revision_draft_version,
                "expected_revision_draft_version": expected_revision_draft_version,
                "expectedRevisionDraftHash": expected_revision_draft_hash,
                "expected_revision_draft_hash": expected_revision_draft_hash,
            }
        self.repository.update_curation_progress(
            session_id,
            stage="generating",
            completed_units=0,
            total_units=max(1, len(excerpts)),
            active_batch_id=batch.id,
        )
        execution = await self.executions.prepare(
            session,
            input=execution_input,
            project_input_message=False,
        )
        if resume_batch_id is not None:
            self.repository.reattach_batch_run(batch.id, execution.id)
        else:
            self.repository.attach_batch_run(batch.id, execution.id)
            self.repository.record_curation_attempt(
                batch.id, execution.id, reason="initial"
            )
        self.executions.run_prepared(execution, graph_input=execution.input)
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

    def _active_curation_phase(self, record) -> str | None:
        if record.active_batch_id is None or record.stage not in {
            "generating",
            "paused",
            "interrupted",
            "failed",
        }:
            return None
        items = self.repository.list_curation_work_items(record.active_batch_id)
        discovery_items = tuple(item for item in items if item.stage == "discovery")
        audit_items = tuple(item for item in items if item.stage == "audit")
        if audit_items and not all(
            item.status == "completed" for item in audit_items
        ):
            return "audit"
        if discovery_items and all(
            item.status == "completed" for item in discovery_items
        ):
            seed_tasks = self.repository.list_curation_seed_tasks(
                record.active_batch_id
            )
            if seed_tasks:
                return "enrichment"
        if any(item.stage == "enrichment" for item in items):
            return "enrichment"
        if audit_items:
            return "audit"
        return "discovery" if items else None

    @staticmethod
    def _curation_controls(batch) -> dict[str, bool]:
        if batch is None or batch.control_intent is not None:
            return {
                "can_pause": False,
                "can_resume": False,
                "can_terminate": False,
            }
        return {
            "can_pause": batch.status == "generating",
            "can_resume": batch.status in {"paused", "interrupted", "failed"},
            "can_terminate": batch.status
            in {"generating", "paused", "interrupted", "failed"},
        }

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
        if kind in {"confirm", "mixed"}:
            if kind == "mixed":
                return f"已发布 {result.get('publishedCount', 0)} 道题，并开始按备注重新生成。"
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

    @staticmethod
    def _accepted_curation_command_resource(receipt) -> dict[str, Any]:
        if receipt.execution_id is None:
            raise ReviewConflictError("curation command has no execution")
        return {
            "command_id": receipt.id,
            "execution_id": receipt.execution_id,
            "status": "accepted",
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
        source_records = [await sources.get(source_id) for source_id in source_refs]
        prepared_sources, excerpts = self._prepare_curation_source_records(
            source_records, character_limit=20_000
        )
        session = await self.sessions.create(
            workspace_id=self.workspace_id,
            kind="question.curate",
            title="AI 题库整理",
        )
        self.repository.create_curation_session(
            workspace_id=self.workspace_id,
            session_id=session.id,
            source_refs=source_refs,
            warnings=prepared_sources.warnings,
        )
        batch = self.repository.create_batch(
            workspace_id=self.workspace_id,
            session_id=session.id,
            run_id=None,
            source_refs=source_refs,
            rewrite_of_batch_id=rewrite_of_batch_id,
            status="completed"
            if not prepared_sources.has_usable_text
            else "generating",
        )
        if not prepared_sources.has_usable_text:
            await self._complete_curation_without_text(
                session_id=session.id,
                batch_id=batch.id,
                source_count=len(source_records),
            )
            return batch
        self.repository.update_curation_progress(
            session.id,
            stage="generating",
            completed_units=0,
            total_units=max(1, len(excerpts)),
            active_batch_id=batch.id,
        )
        execution = await self.executions.prepare(
            session,
            input={
                "batchId": batch.id,
                "batch_id": batch.id,
                "source_excerpts": excerpts,
                "similar_questions": [
                    item.snapshot.question_text
                    for item in self.repository.list_active_questions(self.workspace_id)
                ],
                "rewrite_feedback": rewrite_feedback,
            },
            project_input_message=False,
        )
        attached = self.repository.attach_batch_run(batch.id, execution.id)
        self.repository.record_curation_attempt(
            batch.id, execution.id, reason="initial"
        )
        self.executions.run_prepared(execution, graph_input=execution.input)
        return attached

    def list_batches(self, *, status: str | None = None):
        return self.repository.list_batches(self.workspace_id, status=status)

    async def batch_resource(self, batch_id: str) -> dict[str, Any]:
        batch = self.repository.get_batch(batch_id)
        if batch.workspace_id != self.workspace_id:
            raise LookupError(batch_id)
        own = self.repository.list_candidates(
            self.workspace_id,
            batch_ids=(batch.id,),
            limit=None,
        )
        return {
            "id": batch.id,
            "workspace_id": batch.workspace_id,
            "session_id": batch.session_id,
            "origin_session_id": batch.origin_session_id,
            "run_id": batch.run_id,
            "source_refs": list(batch.source_refs),
            "rewrite_of_batch_id": batch.rewrite_of_batch_id,
            "status": batch.status,
            "version": batch.version,
            "control_intent": batch.control_intent,
            "concurrency_limit": batch.concurrency_limit,
            "created_at": batch.created_at,
            "updated_at": batch.updated_at,
            "candidate_count": len(own),
            "pending_count": sum(item.status == "review_pending" for item in own),
            "candidates": [await self.candidate_resource(item.id) for item in own],
        }

    async def list_candidate_resources(self, **filters) -> tuple[dict[str, Any], ...]:
        records = self.repository.list_candidates(self.workspace_id, **filters)
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
        is_active_version = False
        try:
            active = self.repository.get_active_question(candidate.question.question_id)
            is_active_version = active.draft_id == candidate.draft_id
        except LookupError:
            pass
        return {
            "id": candidate.id,
            "batch_id": candidate.batch_id,
            "curation_session_id": batch.origin_session_id,
            "live_curation_session_id": batch.session_id,
            "question": asdict(candidate.question),
            "source_refs": candidate.source_refs,
            "correction_note": candidate.correction_note,
            "review_note": candidate.review_note,
            "review_note_updated_at": candidate.review_note_updated_at,
            "rejection_reason": candidate.rejection_reason,
            "rejected_at": candidate.rejected_at,
            "rejection_action_id": candidate.rejection_action_id,
            "duplicate_of_question_id": candidate.duplicate_of_question_id,
            "duplicate_question": (None if duplicate is None else asdict(duplicate)),
            "revision_of_question_id": candidate.revision_of_question_id,
            "seed_task_id": candidate.seed_task_id,
            "answer_basis": candidate.answer_basis,
            "material_support": candidate.material_support,
            "needs_review": candidate.needs_review,
            "normalization_issues": candidate.normalization_issues,
            "source_answer": candidate.source_answer,
            "supplemental_answer": candidate.supplemental_answer,
            "confirmation_status": candidate.confirmation_status,
            "confirmation_version": candidate.confirmation_version,
            "confirmed_at": candidate.confirmed_at,
            "is_active_version": is_active_version,
            "status": candidate.status,
            "deleted_at": candidate.deleted_at,
            "deletion_reason": candidate.deletion_reason,
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

    async def candidate_origin_session_resource(
        self, candidate_id: str
    ) -> dict[str, Any]:
        candidate = self.repository.get_candidate(candidate_id)
        batch = self.repository.get_batch(candidate.batch_id)
        if batch.workspace_id != self.workspace_id:
            raise LookupError(candidate_id)
        session_id = batch.session_id
        if session_id is None:
            return {
                "status": "missing",
                "session_id": batch.origin_session_id,
                "session": None,
            }
        try:
            session = self.sessions.repository.get_session(
                session_id, include_deleted=True
            )
        except ProductRecordNotFoundError:
            return {
                "status": "missing",
                "session_id": session_id,
                "session": None,
            }
        try:
            self.repository.get_curation_session(session_id)
        except LookupError:
            return {
                "status": "projection_missing",
                "session_id": session_id,
                "session": None,
            }
        return {
            "status": "recycled" if session.deleted_at is not None else "available",
            "session_id": session_id,
            "session": await self.curation_resource(session_id),
        }

    def delete_candidates(
        self,
        items: tuple[tuple[str, int | None], ...],
        *,
        idempotency_key: str,
        reason: str = "",
    ) -> dict[str, object]:
        return self.repository.delete_candidates(
            self.workspace_id,
            items=items,
            idempotency_key=idempotency_key,
            reason=reason.strip(),
        )

    def confirm_candidates(
        self,
        candidate_ids: tuple[str, ...],
        *,
        idempotency_key: str,
    ) -> dict[str, object]:
        return self.repository.confirm_candidates(
            self.workspace_id,
            candidate_ids=candidate_ids,
            idempotency_key=idempotency_key,
        )

    async def restore_candidate(self, candidate_id: str) -> dict[str, Any]:
        self.repository.restore_candidate(self.workspace_id, candidate_id)
        return await self.candidate_resource(candidate_id)

    def restore_all_candidates(self) -> int:
        return self.repository.restore_all_candidates(self.workspace_id)

    def permanently_delete_candidate(self, candidate_id: str) -> None:
        self.repository.permanently_delete_candidate(
            self.workspace_id, candidate_id
        )

    def empty_candidate_recycle_bin(self) -> int:
        return self.repository.empty_candidate_recycle_bin(self.workspace_id)

    async def update_candidate_review_note(
        self, candidate_id: str, *, note: str
    ) -> dict[str, Any]:
        candidate = self.repository.get_candidate(candidate_id)
        batch = self.repository.get_batch(candidate.batch_id)
        if batch.workspace_id != self.workspace_id:
            raise LookupError(candidate_id)
        self.repository.update_candidate_review_note(
            candidate_id, review_note=note.strip()
        )
        return await self.candidate_resource(candidate_id)

    async def publish_candidate(
        self,
        candidate_id: str,
        *,
        idempotency_key: str,
        confirm_ai_supplement: bool = False,
    ) -> dict[str, Any]:
        candidate = self.repository.get_candidate(candidate_id)
        batch = self.repository.get_batch(candidate.batch_id)
        if batch.workspace_id != self.workspace_id:
            raise LookupError(candidate_id)
        if candidate.status == "published":
            return await self.candidate_resource(candidate_id)
        self._assert_candidate_publishable(
            candidate, confirm_ai_supplement=confirm_ai_supplement
        )
        await self._publish_curation_candidate(
            candidate_id,
            idempotency_key=idempotency_key,
            confirm_ai_supplement=confirm_ai_supplement,
        )
        return await self.candidate_resource(candidate_id)

    async def update_active_question_version(
        self,
        candidate_id: str,
        *,
        target_question_id: str,
        expected_active_hash: str,
        idempotency_key: str,
        confirm_ai_supplement: bool = False,
    ) -> dict[str, Any]:
        candidate = self.repository.prepare_candidate_revision(
            workspace_id=self.workspace_id,
            candidate_id=candidate_id,
            target_question_id=target_question_id,
            expected_active_hash=expected_active_hash,
        )
        if candidate.status == "published":
            return await self.candidate_resource(candidate_id)
        self._assert_candidate_publishable(
            candidate, confirm_ai_supplement=confirm_ai_supplement
        )
        await self._publish_curation_candidate(
            candidate_id,
            idempotency_key=idempotency_key,
            confirm_ai_supplement=confirm_ai_supplement,
        )
        return await self.candidate_resource(candidate_id)

    async def rewrite_candidate_in_context(
        self, candidate_id: str, *, feedback: str
    ) -> dict[str, Any]:
        candidate = self.repository.get_candidate(candidate_id)
        batch = self.repository.get_batch(candidate.batch_id)
        if batch.workspace_id != self.workspace_id:
            raise LookupError(candidate_id)
        clean_feedback = feedback.strip()
        if not clean_feedback:
            raise ValueError("feedback must not be empty")
        session_id = batch.session_id
        session = None
        if session_id is not None:
            try:
                session = self.sessions.repository.get_session(
                    session_id, include_deleted=True
                )
            except ProductRecordNotFoundError:
                session = None
        if session is None:
            session = await self.sessions.create(
                workspace_id=self.workspace_id,
                kind="question.revise",
                title=f"修订：{candidate.question.title}",
                parent_session_id=None,
            )
            session_id = session.id
            self.repository.create_curation_session(
                workspace_id=self.workspace_id,
                session_id=session_id,
                source_refs=batch.source_refs,
            )
        else:
            if session.deleted_at is not None:
                self.sessions.restore(session.id)
            try:
                self.repository.get_curation_session(session_id)
            except LookupError:
                self.repository.create_curation_session(
                    workspace_id=self.workspace_id,
                    session_id=session_id,
                    source_refs=batch.source_refs,
                )
        curation = self.repository.get_curation_session(session_id)
        draft = (
            None
            if candidate.draft_id is None
            else await self.drafts.get(candidate.draft_id)
        )
        revision_context = "\n".join(
            (
                "只修订下面这一道题；只返回一个候选，并保持 logical question 不变。",
                f"candidate_id: {candidate.id}",
                f"origin_session_id: {batch.origin_session_id}",
                f"当前题目: {candidate.question.question_text}",
                f"当前答案: {candidate.question.reference_answer}",
                f"关键点: {'；'.join(candidate.question.key_points)}",
                f"当前 Markdown:\n{'' if draft is None else draft.markdown}",
                f"持久备注: {candidate.review_note}",
                f"退回原因: {candidate.rejection_reason or ''}",
                f"来源引用: {'；'.join(candidate.source_refs)}",
                f"重复题关联: {candidate.duplicate_of_question_id or '无'}",
                f"发布状态: {candidate.status}",
                f"本次修改要求: {clean_feedback}",
            )
        )
        await self.timeline.append(
            session_id=session_id,
            execution_id=None,
            role="user",
            message_kind="text",
            content=f"重写题目「{candidate.question.title}」：{clean_feedback}",
            payload={
                "resourceId": candidate.id,
                "version": curation.summary_version,
                "action": "rewrite_candidate",
            },
        )
        await self._start_curation_execution(
            session_id=session_id,
            source_refs=curation.source_refs,
            rewrite_feedback=clean_feedback,
            rewrite_of_batch_id=candidate.batch_id,
            revision_candidate_id=candidate.id,
            revision_context=revision_context,
            expected_revision_draft_id=(None if draft is None else draft.id),
            expected_revision_draft_version=(None if draft is None else draft.version),
            expected_revision_draft_hash=(
                None if draft is None else draft.content_hash
            ),
        )
        return await self.curation_resource(session_id)

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
            reference_answer=values.get("reference_answer", current.reference_answer),
            topics=tuple(values.get("topics", current.topics)),
            difficulty=values.get("difficulty", current.difficulty),
            key_points=tuple(values.get("key_points", current.key_points)),
            required_key_points=tuple(
                values.get("required_key_points", current.required_key_points)
            ),
            bonus_key_points=tuple(
                values.get("bonus_key_points", current.bonus_key_points)
            ),
            follow_ups=tuple(values.get("follow_ups", current.follow_ups)),
        )
        markdown = (
            f"# {updated.title}\n\n## 题目\n\n{updated.question_text}\n\n"
            f"## 参考答案\n\n{updated.reference_answer}\n\n## 必答点\n\n"
            + "\n".join(f"- {item}" for item in updated.required_key_points)
            + "\n\n## 加分点\n\n"
            + (
                "\n".join(f"- {item}" for item in updated.bonus_key_points)
                if updated.bonus_key_points
                else "- 暂无"
            )
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

    def get_confirmed_question(self, question_id: str):
        return self.repository.get_active_question(question_id)

    async def create_retrospective_candidate(
        self,
        *,
        retrospective_id: str,
        payload: dict[str, object],
        target_question_id: str | None,
        edited_payload: dict[str, object],
    ):
        """Import a user-approved retrospective suggestion into Review review_pending.

        This creates a normal Review draft and candidate; it intentionally does
        not activate the question or bypass Review publication.
        """
        question_text = str(
            edited_payload.get("questionText", payload.get("questionText", ""))
        ).strip()
        answer = str(
            edited_payload.get("suggestedAnswer", payload.get("suggestedAnswer", ""))
        ).strip()
        points = tuple(
            str(item).strip()
            for item in edited_payload.get("keyPoints", payload.get("keyPoints", ()))
            if str(item).strip()
        )
        if not question_text or not answer:
            raise ValueError("复盘题目和参考回答不能为空")
        if not points:
            points = ("能够完整说明核心思路",)
        source_ref = f"retrospective:{retrospective_id}"
        session = await self.sessions.create(
            workspace_id=self.workspace_id,
            kind="question.curate",
            title="面试复盘题目候选",
        )
        self.repository.create_curation_session(
            workspace_id=self.workspace_id,
            session_id=session.id,
            source_refs=(source_ref,),
        )
        batch = self.repository.create_batch(
            workspace_id=self.workspace_id,
            session_id=session.id,
            run_id=None,
            source_refs=(source_ref,),
            status="review_pending",
        )
        question_id = str(uuid4())
        document_id = f"question_{uuid4().hex}"
        markdown = (
            f"# {question_text}\n\n"
            f"## 题目\n\n{question_text}\n\n"
            f"## 参考回答\n\n{answer}\n\n"
            "## 必答点\n\n" + "\n".join(f"- {item}" for item in points) + "\n"
        )
        draft = await self.drafts.create(
            CreateDraftCommand(
                domain="review",
                document_type="question",
                title=question_text[:120],
                markdown=markdown,
                source_refs=(source_ref,),
                relation_refs=(f"retrospective:{retrospective_id}",),
                session_id=session.id,
                agent_type="interview_retrospective",
                document_id=document_id,
            )
        )
        snapshot = QuestionSnapshot(
            question_id=question_id,
            document_id=document_id,
            content_hash=draft.content_hash,
            title=question_text[:120],
            question_text=question_text,
            reference_answer=answer,
            topics=("面试复盘",),
            difficulty="medium",
            key_points=points,
            follow_ups=(),
            required_key_points=points,
        )
        candidate = self.repository.save_candidate(
            batch_id=batch.id,
            question=snapshot,
            draft_id=draft.id,
            source_refs=(source_ref,),
            duplicate_of_question_id=target_question_id,
            status="review_pending",
        )
        self.repository.update_curation_progress(
            session.id,
            stage="waiting_for_command",
            completed_units=1,
            total_units=1,
            active_batch_id=batch.id,
        )
        return candidate

    async def create_round(self, settings: ReviewRoundSettings):
        self.validate_model(settings.answer_model_id, settings.reasoning_effort)
        mastery = self.repository.get_mastery(self.workspace_id)
        catalog = self.repository.list_active_questions(self.workspace_id)
        if settings.mode == "source-file":
            assert settings.source_id is not None
            try:
                await KnowledgeSourceService(
                    self.workspace_root,
                    workspace_id=self.workspace_id,
                ).get(settings.source_id, include_deleted=False)
            except LookupError as error:
                raise InsufficientQuestionsError(
                    available=0,
                    requested=settings.question_count,
                ) from error
            available = self.selector.eligible_count(catalog, settings)
            if available < settings.question_count and available > 0:
                settings = replace(settings, question_count=available)
        snapshots = self.selector.select(
            catalog,
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
            session,
            input={"roundId": round_id},
            project_input_message=False,
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
        provider_model_id: str | None = None,
        reasoning_effort: ReasoningEffort | None = None,
    ):
        round_record = self.repository.get_round(round_id)
        request = self.repository.get_input_request(request_id)
        if request.round_id != round_id or request.version != version:
            raise ReviewConflictError("input request changed")
        if round_record.execution_id is None:
            raise ReviewConflictError("round has no execution")
        resolved_model_id = provider_model_id or round_record.settings.answer_model_id
        resolved_reasoning = reasoning_effort or round_record.settings.reasoning_effort
        self.validate_model(resolved_model_id, resolved_reasoning)
        receipt = self.repository.accept_review_answer(
            request_id=request_id,
            expected_version=version,
            idempotency_key=idempotency_key,
            value=value,
            receipt_id=idempotency_key,
            answer_model_id=resolved_model_id,
            reasoning_effort=resolved_reasoning,
        )
        await self.executions.resume_accepted_input(
            round_record.execution_id,
            receipt=receipt,
            value=value,
        )
        return receipt

    async def submit_turn(
        self,
        round_id: str,
        *,
        request_id: str,
        version: int,
        idempotency_key: str,
        value: str,
        provider_model_id: str | None = None,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> dict[str, Any]:
        round_record = self.repository.get_round(round_id)
        request = self.repository.get_input_request(request_id)
        if (
            request.round_id != round_id
            or request.version != version
            or request.status != "pending"
        ):
            raise ReviewConflictError("input request changed")
        intent = classify_review_turn(value)
        if intent is None and self.review_turn_classifier is not None:
            resolved_model_id = (
                provider_model_id or round_record.settings.answer_model_id
            )
            resolved_reasoning = (
                reasoning_effort or round_record.settings.reasoning_effort
            )
            self.validate_model(resolved_model_id, resolved_reasoning)
            intent = await self.review_turn_classifier(
                question=round_record.question_snapshots[request.ordinal - 1],
                message=value,
                provider_model_id=resolved_model_id,
                reasoning_effort=resolved_reasoning,
                session_id=round_record.session_id,
                execution_id=round_record.execution_id,
            )
        intent = intent or "answer"
        if intent == "answer":
            receipt = await self.submit_answer(
                round_id,
                request_id=request_id,
                version=version,
                idempotency_key=idempotency_key,
                value=value,
                provider_model_id=provider_model_id,
                reasoning_effort=reasoning_effort,
            )
            return {
                "kind": "answer",
                "intent": "answer",
                "round_id": round_id,
                "input_request_id": request_id,
                "attempt_id": receipt.attempt_id,
                "receipt_id": receipt.id,
                "status": receipt.status,
            }
        if intent == "skip":
            await self.skip(
                round_id,
                request_id=request_id,
                version=version,
                idempotency_key=idempotency_key,
            )
            return {
                "kind": "skipped",
                "intent": "skip",
                "round_id": round_id,
                "input_request_id": request_id,
                "attempt_id": None,
                "receipt_id": idempotency_key,
                "status": "completed",
            }
        question = round_record.question_snapshots[request.ordinal - 1]
        if intent == "show_question":
            response = f"当前题目：{question.question_text}\n\n请继续回答这道题。"
        elif intent == "request_hint":
            attempts = self.repository.list_attempts(round_id)
            current = next(
                (item for item in attempts if item.ordinal == request.ordinal),
                None,
            )
            uncovered = (
                [item.point for item in current.coverage if item.status != "covered"]
                if current is not None
                else list(question.required_key_points)
            )
            direction = uncovered[0] if uncovered else question.topics[0]
            response = (
                f"提示：先从“{direction}”这个方向组织你的回答。"
                "\n\n不用一次答得完，回答后我会告诉你还缺哪个方向。"
            )
        elif intent == "reveal_answer":
            response = (
                f"参考答案：{question.reference_answer}"
                "\n\n这次会记为“查看答案”，请再用自己的话复述一遍。"
            )
        elif intent == "explain":
            response = (
                f"这道题主要考察：{'、'.join(question.topics)}。"
                "你可以先说明核心概念，再讲判断或处理步骤。"
                "\n\n回到当前题，请继续作答。"
            )
        else:
            response = (
                "我先帮你守住当前复习进度。请继续回答当前题；"
                "如果暂时不想答，可以点击“跳过此题”。"
            )
        receipt = self.repository.record_auxiliary_turn(
            round_id=round_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            value=value,
            intent=intent,
            response=response,
        )
        await self.events.publish(
            round_record.session_id,
            round_record.execution_id,
            "review.turn.responded",
            {"roundId": round_id, "intent": intent},
        )
        return {
            "kind": "auxiliary",
            "intent": intent,
            "round_id": round_id,
            "input_request_id": request_id,
            "attempt_id": None,
            "receipt_id": receipt["id"],
            "status": "waiting_for_answer",
        }

    @staticmethod
    def answer_receipt_resource(receipt) -> dict[str, Any]:
        return {
            "receipt_id": receipt.id,
            "round_id": receipt.round_id,
            "attempt_id": receipt.attempt_id,
            "input_request_id": receipt.input_request_id,
            "status": receipt.status,
            "accepted_at": receipt.accepted_at,
            "version": receipt.version,
        }

    async def retry_evaluation(self, round_id: str, *, idempotency_key: str):
        round_record = self.repository.get_round(round_id)
        existing = self.repository.find_evaluation_retry_receipt(
            round_id, idempotency_key=idempotency_key
        )
        if existing is not None:
            return existing
        if round_record.execution_id is None:
            raise ReviewConflictError("round has no execution")
        attempt = next(
            (
                item
                for item in reversed(self.repository.list_attempts(round_id))
                if item.ordinal == round_record.current_index + 1
                and item.status == "evaluation_failed"
            ),
            None,
        )
        if attempt is None:
            raise ReviewConflictError("current attempt is not retryable")
        receipt = self.repository.retry_attempt_evaluation(
            attempt.id, idempotency_key=idempotency_key
        )
        await self.executions.retry_evaluation(
            round_record.execution_id, receipt=receipt
        )
        return receipt

    async def retry_round(self, round_id: str):
        round_record = self.repository.get_round(round_id)
        if round_record.status in {"completed", "cancelled", "failed"}:
            raise ReviewConflictError("round is already terminal")
        if round_record.execution_id is None:
            raise ReviewConflictError("round has no execution")
        await self.executions.retry_failed_review_round(round_record.execution_id)
        return self.repository.get_round(round_id)

    async def skip(
        self,
        round_id: str,
        *,
        request_id: str | None,
        version: int | None,
        idempotency_key: str,
    ):
        round_record = self.repository.get_round(round_id)
        if round_record.execution_id is None:
            raise ReviewConflictError("round has no execution")
        pending = self.repository.pending_input(round_id)
        if pending is not None:
            if request_id is not None and request_id != pending.id:
                raise ReviewConflictError("input request changed")
            if version is not None and version != pending.version:
                raise ReviewConflictError("input request changed")
            await self.executions.skip_input(
                round_record.execution_id,
                request_id=pending.id,
                receipt_id=idempotency_key,
            )
            await self.executions.wait(round_record.execution_id)
            return self.repository.get_round(round_id)

        if self.repository.has_round_control_receipt(
            round_id,
            operation="skip_current",
            idempotency_key=idempotency_key,
        ):
            return self.repository.get_round(round_id)
        attempt = next(
            (
                item
                for item in reversed(self.repository.list_attempts(round_id))
                if item.ordinal == round_record.current_index + 1
                and item.status
                in {
                    "evaluating",
                    "evaluation_failed",
                    "waiting_for_follow_up",
                }
            ),
            None,
        )
        if attempt is None:
            raise ReviewConflictError("current question cannot be skipped")
        execution = self.executions.execution(round_record.execution_id)
        if execution.status == "running":
            await self.executions.interrupt_review_evaluation(execution.id)
        elif execution.status != "interrupted":
            raise ReviewConflictError("review evaluation cannot be skipped")
        next_index = round_record.current_index + 1
        next_status = (
            "report_pending"
            if next_index >= len(round_record.question_snapshots)
            else "waiting_for_input"
        )
        next_question = (
            None
            if next_status == "report_pending"
            else round_record.question_snapshots[next_index]
        )
        self.repository.skip_current_attempt(
            round_id,
            attempt_id=attempt.id,
            idempotency_key=idempotency_key,
            expected_version=round_record.version,
            current_index=next_index,
            status=next_status,
            next_input_ordinal=(None if next_question is None else next_index + 1),
            next_input_prompt=(
                None if next_question is None else next_question.question_text
            ),
            next_input_version=(None if next_question is None else next_index * 2 + 1),
        )
        await self.executions.resume_review_after_skip(
            execution.id,
            round_id=round_id,
        )
        await self.executions.wait(round_record.execution_id)
        return self.repository.get_round(round_id)

    async def interrupt_evaluation(self, round_id: str, *, idempotency_key: str):
        round_record = self.repository.get_round(round_id)
        if round_record.execution_id is None:
            raise ReviewConflictError("round has no execution")
        if self.repository.has_round_control_receipt(
            round_id,
            operation="interrupt_evaluation",
            idempotency_key=idempotency_key,
        ):
            return self.repository.get_round(round_id)
        attempt = next(
            (
                item
                for item in reversed(self.repository.list_attempts(round_id))
                if item.ordinal == round_record.current_index + 1
                and item.status in {"evaluating", "evaluation_failed"}
            ),
            None,
        )
        if attempt is None:
            raise ReviewConflictError("current evaluation is not interruptible")
        execution = self.executions.execution(round_record.execution_id)
        if execution.status == "running":
            await self.executions.interrupt_review_evaluation(execution.id)
        elif not (
            execution.status == "interrupted"
            and attempt.status == "evaluation_failed"
            and attempt.evaluation_error_code == "evaluation_interrupted"
        ):
            raise ReviewConflictError("current evaluation is not interruptible")
        self.repository.interrupt_attempt_evaluation(
            attempt.id, idempotency_key=idempotency_key
        )
        await self.events.publish(
            round_record.session_id,
            execution.id,
            "review.evaluation.failed",
            {
                "roundId": round_id,
                "attemptId": attempt.id,
                "code": "evaluation_interrupted",
                "version": round_record.version,
            },
        )
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

    async def create_discussion(self, round_id: str, *, ordinal: int):
        round_record = self.repository.get_round(round_id)
        attempts = self.repository.list_attempts(round_id)
        attempt = next((item for item in attempts if item.ordinal == ordinal), None)
        if attempt is None:
            raise LookupError(ordinal)
        lock = self._discussion_locks.setdefault(attempt.id, asyncio.Lock())
        async with lock:
            existing_id = self.repository.find_discussion_session(
                parent_session_id=round_record.session_id,
                attempt_id=attempt.id,
            )
            if existing_id is not None:
                existing = self.sessions.repository.get_session(
                    existing_id, include_deleted=True
                )
                return (
                    self.sessions.restore(existing.id)
                    if existing.deleted_at is not None
                    else existing
                )
            session = await self.sessions.create(
                workspace_id=self.workspace_id,
                kind="review.discussion",
                title=f"深入讨论：{attempt.question_snapshot.title}",
                parent_session_id=round_record.session_id,
            )
            initialization = await self.executions.start(
                session,
                input={
                    "question_snapshot": asdict(attempt.question_snapshot),
                    "attempt_evidence": {
                        "attemptId": attempt.id,
                        "answer": attempt.answer,
                        "followUpAnswer": attempt.follow_up_answer,
                        "evaluation": attempt.evaluation,
                        "masterySuggestion": attempt.mastery_suggestion,
                        "skipped": attempt.skipped,
                    },
                    "message": "",
                    "parent_round_id": round_id,
                },
                project_input_message=False,
            )
            await self.executions.wait(initialization.id)
            return self.sessions.get(session.id)

    async def retry_discussion(self, round_id: str, *, session_id: str):
        round_record = self.repository.get_round(round_id)
        session = self.sessions.get(session_id)
        if (
            session.kind != "review.discussion"
            or session.parent_session_id != round_record.session_id
        ):
            raise ReviewConflictError("discussion session does not belong to round")
        latest = self.sessions.repository.latest_execution(session.id)
        if latest is None or latest.status != "failed":
            raise ReviewConflictError("discussion execution is not retryable")
        message = latest.input.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ReviewConflictError("discussion retry message is missing")
        return await self.executions.start(
            session,
            input={"message": message.strip()},
            project_input_message=False,
        )

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
            attempt = next(
                (
                    item
                    for item in attempts
                    if item.ordinal == round_record.current_index + 1
                ),
                None,
            )
            coverage = () if attempt is None else attempt.coverage
            hint_level, _revealed = self.repository.question_assistance(
                round_id, round_record.current_index + 1
            )
            source_links = self.repository.list_question_source_links(
                question.question_id
            )
            source_ids = tuple(dict.fromkeys(link.source_id for link in source_links))
            source_service = (
                KnowledgeSourceService(
                    self.workspace_root,
                    workspace_id=self.workspace_id,
                )
                if source_ids
                else None
            )

            async def load_source(source_id: str):
                assert source_service is not None
                try:
                    return await source_service.get(source_id)
                except LookupError:
                    return None

            source_records = (
                await asyncio.gather(
                    *(load_source(source_id) for source_id in source_ids),
                )
                if source_ids
                else ()
            )
            sources_by_id = {
                source_id: record
                for source_id, record in zip(source_ids, source_records, strict=True)
                if record is not None
            }
            source_resources = []
            for source_id in source_ids:
                links = [link for link in source_links if link.source_id == source_id]
                section_numbers = []
                for link in links:
                    suffix = link.evidence_ref.rpartition("#section-")[2]
                    if suffix.isdigit():
                        section_numbers.append(int(suffix))
                source = sources_by_id.get(source_id)
                source_resources.append(
                    {
                        "source_id": source_id,
                        "filename": (
                            None if source is None else source.original_filename
                        ),
                        "section_numbers": tuple(dict.fromkeys(section_numbers)),
                        "evidence_count": len(links),
                        "availability": (
                            "missing"
                            if source is None
                            else "deleted"
                            if source.deleted_at is not None
                            else "available"
                        ),
                    }
                )
            current_question = {
                "id": question.question_id,
                "document_id": question.document_id,
                "title": question.title,
                "question_text": question.question_text,
                "topics": question.topics,
                "difficulty": question.difficulty,
                "required_key_point_count": len(question.required_key_points),
                "covered_key_point_count": sum(
                    item.status == "covered" for item in coverage
                ),
                "missing_directions": (
                    [item.point for item in coverage if item.status != "covered"]
                    if attempt is not None and attempt.evaluation is not None
                    else []
                ),
                "has_answer": bool(attempt is not None and attempt.answer_revisions),
                "hint_level": hint_level,
                "sources": source_resources,
            }
        reports = []
        for report_kind in ("session_report", "mastery_report"):
            proposal = self.repository.find_report_proposal(round_id, report_kind)
            if proposal is None:
                continue
            draft = await self.drafts.get(proposal.draft_id)
            publication = await self.publications.latest_for_draft(draft.id)
            reports.append(
                {
                    "id": draft.id,
                    "report_kind": report_kind,
                    "title": draft.title,
                    "markdown": draft.markdown,
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
            "attempts": [
                {
                    **asdict(item),
                    "discussion_session_id": self.repository.find_discussion_session(
                        parent_session_id=round_record.session_id,
                        attempt_id=item.id,
                    ),
                }
                for item in attempts
            ],
            "messages": [
                asdict(message)
                for message in self.sessions.repository.list_messages(
                    round_record.session_id
                )
                if message.message_kind
                in {"review_prompt", "review_answer", "evaluation_card", "error"}
            ],
            "reports": reports,
            "usage": self.executions.usage(round_record.session_id),
            "context_usage": self.sessions.repository.context_usage(
                round_record.session_id
            ),
            "execution_status": None if execution is None else execution.status,
            "created_at": round_record.created_at,
            "updated_at": round_record.updated_at,
            "completed_at": round_record.completed_at,
            "archived_at": round_record.archived_at,
        }

    async def list_round_resources(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            [
                await self.round_resource(item.id)
                for item in self.repository.list_rounds(self.workspace_id)
            ]
        )

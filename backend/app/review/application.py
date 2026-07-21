from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
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
from app.agents.agent_factory import ModelOverride
from app.application.session_service import (
    AgentSessionService,
    MessageRecord,
    ProductRecordNotFoundError,
    ProductEventStream,
    ReasoningEffort,
)
from app.hitl.models import ResolveActionCommand
from app.hitl.repository import PendingActionRepository
from app.hitl.service import HitlService
from app.knowledge.drafts import KnowledgeDraftService, UpdateDraftCommand
from app.knowledge.source_registry import KnowledgeSourceService
from app.knowledge.publication import PublicationService
from app.review.errors import ReviewConflictError
from app.review.curation_commands import CurationCommandService
from app.review.curation_command_contracts import CurationCommandPlan
from app.review.curation_context import (
    CurationCommandInterpreter,
    CurationContextAdapter,
)
from app.review.models import (
    BulkPublicationPreflight,
    CurationSummary,
    ReviewRoundSettings,
)
from app.review.repository import ReviewRepository
from app.review.selector import QuestionSelector
from app.review.timeline import SessionTimelineProjector
from app.middleware.usage_projection_middleware import ContextUsageProjection
from app.services.document_ingestion import extract_text


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
        self.selector = QuestionSelector()
        self._discussion_locks: dict[str, asyncio.Lock] = {}
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
        sources = [
            await source_service.get(source_id, include_deleted=False)
            for source_id in selected
        ]
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
                f"{source.id}:{source.original_filename}\n{text}"
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
                "batch_id": batch.id,
                "source_excerpts": excerpts,
                "similar_questions": [
                    item.snapshot.question_text
                    for item in self.repository.list_active_questions(
                        self.workspace_id
                    )
                ],
                "rewrite_feedback": None,
            },
            project_input_message=False,
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
        session = self.sessions.repository.get_session(
            session_id, include_deleted=True
        )
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
        latest_command = self.repository.latest_curation_command_receipt(
            session_id
        )
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
            "deleted_at": session.deleted_at,
            "source_refs": record.source_refs,
            "sources": source_resources,
            "active_batch_id": record.active_batch_id,
            "execution_id": None if latest is None else latest.id,
            "execution_status": None if latest is None else latest.status,
            "execution_started_at": None if latest is None else latest.started_at,
            "execution_finished_at": None if latest is None else latest.finished_at,
            "execution_error_code": None if latest is None else latest.error_code,
            "execution_error_message": None if latest is None else latest.error_message,
            "context_compacted": self.sessions.repository.context_compacted(
                session_id
            ),
            "context_usage": self.sessions.repository.context_usage(session_id),
            "stage": record.stage,
            "progress": {
                "phase": self._active_curation_phase(record),
                "completed": record.completed_units,
                "total": record.total_units,
            },
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
            "published_count": sum(
                item.status == "published" for item in candidates
            ),
            "messages": [
                asdict(item)
                for item in self.sessions.repository.list_messages(session_id)
                if _is_curation_timeline_message(item)
            ],
            "usage": self.executions.usage(session_id),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    async def retry_curation_session(self, session_id: str) -> dict[str, Any]:
        curation = self.repository.get_curation_session(session_id)
        latest = self.sessions.repository.latest_execution(session_id)
        if curation.workspace_id != self.workspace_id:
            raise LookupError(session_id)
        if curation.stage != "failed" or latest is None or latest.status != "failed":
            raise ReviewConflictError("only failed curation sessions can retry")
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
        await self._start_curation_execution(
            session_id=session_id,
            source_refs=curation.source_refs,
            rewrite_feedback=None,
            rewrite_of_batch_id=None,
            resume_batch_id=curation.active_batch_id,
        )
        return await self.curation_resource(session_id)

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

    def preflight_bulk_publication(
        self, session_id: str
    ) -> BulkPublicationPreflight:
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
    ) -> dict[str, Any]:
        preflight = self.preflight_bulk_publication(session_id)
        if preflight.summary_version != summary_version:
            raise ReviewConflictError(
                "curation summary changed before bulk publication"
            )
        if candidate_ids != preflight.publishable:
            raise ReviewConflictError(
                "bulk publication eligibility changed"
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
        execution = self.sessions.repository.get_execution(
            operation.execution_id
        )

        async def handler(current, cancellation):
            self.repository.transition_bulk_publication(
                operation.id, expected=("accepted",), target="running"
            )
            try:
                for item in self.repository.list_bulk_publication_items(
                    operation.id
                ):
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
                            await self._publish_curation_candidate(
                                item.candidate_id,
                                idempotency_key=item.idempotency_key,
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
                            error_code=str(
                                getattr(error, "code", "publication_failed")
                            ),
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
                self.repository.complete_bulk_publication_from_items(
                    operation.id
                )
            except (ExecutionCancelled, asyncio.CancelledError):
                latest = self.sessions.repository.get_execution(current.id)
                self.repository.reset_running_bulk_publication_items(
                    operation.id
                )
                self.repository.transition_bulk_publication(
                    operation.id,
                    expected=("running",),
                    target=(
                        "cancelled"
                        if latest.cancellation_requested
                        else "interrupted"
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

    def bulk_publication_resource(
        self, operation_id: str
    ) -> dict[str, Any]:
        operation = self.repository.reconcile_bulk_publication(operation_id)
        return {
            "id": operation.id,
            "session_id": operation.session_id,
            "execution_id": operation.execution_id,
            "summary_version": operation.summary_version,
            "status": operation.status,
            "retry_count": operation.retry_count,
            "items": [
                asdict(item)
                for item in self.repository.list_bulk_publication_items(
                    operation.id
                )
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
                raise ReviewConflictError(
                    "curation command has no execution"
                )
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
                raise ReviewConflictError(
                    "curation command has no execution"
                )
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
                target = (
                    "cancelled"
                    if latest.cancellation_requested
                    else "interrupted"
                )
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

    async def retry_curation_command(
        self, command_id: str
    ) -> dict[str, Any]:
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
        receipt = self.repository.requeue_curation_command(
            receipt.id, execution.id
        )
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
        command_started_at = (
            _submitted_at or datetime.now(timezone.utc).isoformat()
        )
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
            raise ReviewConflictError("curation summary changed before command resolution")
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
        context_record = self.repository.get_or_create_curation_context(
            session_id
        )
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
                latest_execution = self.sessions.repository.latest_execution(
                    session_id
                )
                if latest_execution is None:
                    raise ReviewConflictError(
                        "curation session has no execution"
                    )
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
                response_context, response_invocation_context = (
                    await context_provider(compact_overflow=False)
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
                rewrite_feedback = self._candidate_notes_feedback(parsed.rewrite_candidate_ids, parsed.feedback)
                candidate = self.repository.get_candidate(parsed.rewrite_candidate_ids[0])
                if execution_id is not None:
                    await self.executions.complete_background_execution(
                        execution_id
                    )
                rewrite_execution = await self._start_curation_execution(session_id=session_id, source_refs=curation.source_refs, rewrite_feedback=rewrite_feedback, rewrite_of_batch_id=candidate.batch_id)
                result["rewriteExecutionId"] = rewrite_execution.id
                result["rewriteCandidateIds"] = list(parsed.rewrite_candidate_ids)
        elif parsed.kind == "rewrite":
            if _cancellation is not None:
                _cancellation.raise_if_requested()
            candidate = self.repository.get_candidate(parsed.candidate_ids[0])
            rewrite_feedback = self._candidate_notes_feedback(parsed.candidate_ids, parsed.feedback)
            if execution_id is not None:
                await self.executions.complete_background_execution(
                    execution_id
                )
            execution = await self._start_curation_execution(
                session_id=session_id,
                source_refs=curation.source_refs,
                rewrite_feedback=rewrite_feedback,
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
            latest_context = self.repository.get_or_create_curation_context(
                session_id
            )
            focus = CurationContextAdapter.focus_after(
                result_candidate_ids, valid_candidate_ids
            )
            if focus:
                self.repository.replace_curation_context(
                    session_id,
                    expected_version=latest_context.version,
                    focused_candidate_ids=focus,
                    last_intent=(
                        "inspect"
                        if plan.inspect.scope != "none"
                        else parsed.kind
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

    def _candidate_notes_feedback(self, candidate_ids: tuple[str, ...], extra: str | None) -> str:
        lines = ["请按以下候选题备注重新生成，并保留其余未指定题目："]
        for candidate_id in candidate_ids:
            candidate = self.repository.get_candidate(candidate_id)
            lines.append(f"- {candidate.question.title}（{candidate_id}）：{candidate.review_note or extra or '重新整理'}")
        if extra:
            lines.append(f"补充要求：{extra}")
        return "\n".join(lines)

    async def _publish_curation_candidate(
        self, candidate_id: str, *, idempotency_key: str
    ) -> None:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate.status == "published":
            return
        self._assert_candidate_publishable(candidate)
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
        await self.hitl.approve(
            pending[0].id,
            ResolveActionCommand(
                version=pending[0].version,
                idempotency_key=idempotency_key,
            ),
        )
        await self.executions.wait(execution.id)

    def _assert_candidate_publishable(self, candidate) -> None:
        if candidate.status == "rejected":
            raise ReviewConflictError("rejected candidate cannot be published")
        if (
            candidate.duplicate_of_question_id is not None
            and candidate.revision_of_question_id
            != candidate.duplicate_of_question_id
        ):
            raise ReviewConflictError(
                "duplicate candidate must be resolved before publication"
            )
        from app.review.question_similarity import same_question

        for active in self.repository.list_active_questions(self.workspace_id):
            if active.snapshot.question_id == candidate.question.question_id:
                if (
                    candidate.revision_of_question_id is not None
                    and active.snapshot.content_hash
                    != candidate.revision_base_hash
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
                raise ReviewConflictError(
                    "an equivalent question is already published"
                )

    async def _start_curation_execution(
        self,
        *,
        session_id: str,
        source_refs: tuple[str, ...],
        rewrite_feedback: str | None,
        rewrite_of_batch_id: str | None,
        revision_candidate_id: str | None = None,
        revision_context: str | None = None,
        resume_batch_id: str | None = None,
    ):
        session = self.sessions.get(session_id)
        source_service = KnowledgeSourceService(
            self.workspace_root, workspace_id=self.workspace_id
        )
        excerpts = [revision_context] if revision_context is not None else []
        if revision_context is None:
            for source_id in source_refs:
                source = await source_service.get(source_id)
                text = extract_text(self.workspace_root / source.stored_path)
                excerpts.append(
                    f"{source.id}:{source.original_filename}\n{text}"
                )
        batch = (
            self.repository.get_batch(resume_batch_id)
            if resume_batch_id is not None
            else self.repository.create_batch(
                workspace_id=self.workspace_id,
                session_id=session_id,
                run_id=None,
                source_refs=source_refs,
                rewrite_of_batch_id=rewrite_of_batch_id,
            )
        )
        current = self.repository.get_curation_session(session_id)
        self.repository.update_curation_progress(
            session_id,
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
                    for item in self.repository.list_active_questions(
                        self.workspace_id
                    )
                ],
                "rewrite_feedback": rewrite_feedback,
                "revisionCandidateId": revision_candidate_id,
                "revision_candidate_id": revision_candidate_id,
            },
            project_input_message=False,
        )
        if resume_batch_id is not None:
            self.repository.reattach_batch_run(batch.id, execution.id)
        else:
            self.repository.attach_batch_run(batch.id, execution.id)
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
        if record.stage != "generating" or record.active_batch_id is None:
            return None
        items = self.repository.list_curation_work_items(record.active_batch_id)
        if any(item.stage == "enrichment" for item in items):
            return "enrichment"
        return "discovery" if items else None

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
            project_input_message=False,
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
        is_active_version = False
        try:
            active = self.repository.get_active_question(
                candidate.question.question_id
            )
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
            "duplicate_question": (
                None if duplicate is None else asdict(duplicate)
            ),
            "revision_of_question_id": candidate.revision_of_question_id,
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

    async def restore_candidate(self, candidate_id: str) -> dict[str, Any]:
        self.repository.restore_candidate(self.workspace_id, candidate_id)
        return await self.candidate_resource(candidate_id)

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
        self, candidate_id: str, *, idempotency_key: str
    ) -> dict[str, Any]:
        candidate = self.repository.get_candidate(candidate_id)
        batch = self.repository.get_batch(candidate.batch_id)
        if batch.workspace_id != self.workspace_id:
            raise LookupError(candidate_id)
        self._assert_candidate_publishable(candidate)
        await self._publish_curation_candidate(
            candidate_id, idempotency_key=idempotency_key
        )
        return await self.candidate_resource(candidate_id)

    async def update_active_question_version(
        self,
        candidate_id: str,
        *,
        target_question_id: str,
        expected_active_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        candidate = self.repository.prepare_candidate_revision(
            workspace_id=self.workspace_id,
            candidate_id=candidate_id,
            target_question_id=target_question_id,
            expected_active_hash=expected_active_hash,
        )
        self._assert_candidate_publishable(candidate)
        await self._publish_curation_candidate(
            candidate_id, idempotency_key=idempotency_key
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
        draft = None if candidate.draft_id is None else await self.drafts.get(candidate.draft_id)
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

    async def retry_evaluation(
        self, round_id: str, *, idempotency_key: str
    ):
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
        self, round_id: str, *, ordinal: int
    ):
        round_record = self.repository.get_round(round_id)
        attempts = self.repository.list_attempts(round_id)
        attempt = next(
            (item for item in attempts if item.ordinal == ordinal), None
        )
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

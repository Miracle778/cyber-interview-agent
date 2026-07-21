from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from langgraph.types import Command

from app.agents.context import AgentContext
from app.agents.agent_factory import ModelOverride
from app.diagnostics.agent_trace import AgentTraceWriter, TraceIdentity
from app.middleware.agent_trace_middleware import safe_error_payload
from app.application.event_projector import AgentEventProjector
from app.application.session_service import (
    ExecutionRecord,
    ProductEventStream,
    ProductRepository,
    SessionRecord,
)
from app.hitl.models import CreatePendingAction, PendingActionRecord
from app.infrastructure.checkpoints import AgentCheckpointer
from app.knowledge.drafts import (
    CreateDraftCommand,
    DraftNotEditableError,
    KnowledgeDraftRecord,
    KnowledgeDraftService,
    UpdateDraftCommand,
)
from app.graphs.review_round import DraftRef
from app.review.models import (
    MasteryEntry,
    MasteryProjection,
    QuestionSnapshot,
)
from app.review.models import ReviewAnswerReceipt, ReviewInputReceipt
from app.review.errors import ReviewConflictError
from app.review.repository import ReviewRepository
from app.review.timeline import SessionTimelineProjector
from app.profile.repository import ProfileRepository
from app.profile.storage import MaterialStorage


logger = logging.getLogger(__name__)


class UnsupportedInterruptError(ValueError):
    code = "unsupported_interrupt"


class ExecutionCancelled(RuntimeError):
    code = "execution_cancelled"


class CurationFinalizationRejected(RuntimeError):
    code = "curation_finalization_rejected"

    def __init__(
        self,
        message: str,
        *,
        outcome: Literal["cancelled", "interrupted", "failed"],
    ) -> None:
        super().__init__(message)
        self.outcome = outcome


@dataclass(slots=True)
class ExecutionControl:
    interruptible: bool = True
    shutdown_requested: bool = False


@dataclass(frozen=True, slots=True)
class ExecutionCancellation:
    repository: ProductRepository
    execution_id: str
    control: ExecutionControl

    def raise_if_requested(self) -> None:
        if self.repository.get_execution(self.execution_id).cancellation_requested:
            raise ExecutionCancelled()

    @contextmanager
    def critical_section(self):
        self.control.interruptible = False
        try:
            yield
        finally:
            self.control.interruptible = True
        if self.control.shutdown_requested:
            raise asyncio.CancelledError()


ExecutionHandler = Callable[
    [ExecutionRecord, ExecutionCancellation], Awaitable[None]
]


def _classify_interrupt(value: Mapping[str, Any]) -> Literal["input", "approval"]:
    if "inputRequestId" in value:
        return "input"
    if "actionId" in value or "action_requests" in value:
        return "approval"
    raise UnsupportedInterruptError("unsupported_interrupt")


class GraphFactory(Protocol):
    def __call__(self, kind: str, **dependencies): ...


class AgentExecutionService:
    def __init__(
        self,
        *,
        workspace_id: str,
        workspace_root: Path,
        repository: ProductRepository,
        events: ProductEventStream,
        graph_factory: GraphFactory,
        model_bindings: Callable[[], Mapping[str, str]],
        create_action: Callable[[CreatePendingAction], Awaitable[PendingActionRecord]],
        create_draft: Callable[[CreateDraftCommand], Awaitable[KnowledgeDraftRecord]],
        mark_draft_review_pending: Callable[..., Awaitable[KnowledgeDraftRecord]],
        review_repository: ReviewRepository | None = None,
        get_draft: Callable[[str], Awaitable[KnowledgeDraftRecord]] | None = None,
        update_draft: Callable[[str, UpdateDraftCommand], Awaitable[KnowledgeDraftRecord]] | None = None,
        profile_repository: ProfileRepository | None = None,
        profile_storage: MaterialStorage | None = None,
        trace_writer: AgentTraceWriter | None = None,
        trace_warning: Callable[[AgentContext, str], None] | None = None,
    ) -> None:
        self._workspace_id = workspace_id
        self._workspace_root = workspace_root
        self._repository = repository
        self._events = events
        self._graph_factory = graph_factory
        self._model_bindings = model_bindings
        self._create_action = create_action
        self._create_draft = create_draft
        self._mark_draft_review_pending = mark_draft_review_pending
        self._review_repository = review_repository
        self._get_draft = get_draft
        self._update_draft = update_draft
        self._profile_repository = profile_repository
        self._profile_storage = profile_storage
        self._trace_writer = trace_writer or AgentTraceWriter()
        self._trace_warning = trace_warning
        self._trace_warned_runs: set[str] = set()
        self._checkpointer = AgentCheckpointer(workspace_root)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._controls: dict[str, ExecutionControl] = {}

    def execution(self, execution_id: str) -> ExecutionRecord:
        return self._repository.get_execution(execution_id)

    def usage(self, session_id: str) -> dict[str, int]:
        return self._repository.usage(session_id)

    async def start(
        self,
        session: SessionRecord,
        *,
        input: dict[str, Any],
        project_input_message: bool = True,
        configuration: dict[str, Any] | None = None,
    ) -> ExecutionRecord:
        execution = await self.prepare(
            session,
            input=input,
            project_input_message=project_input_message,
            configuration=configuration,
        )
        self.run_prepared(execution, graph_input=input)
        return execution

    async def prepare(
        self,
        session: SessionRecord,
        *,
        input: dict[str, Any],
        project_input_message: bool = True,
        configuration: dict[str, Any] | None = None,
    ) -> ExecutionRecord:
        bindings = dict(self._model_bindings())
        execution = self._repository.create_execution(
            session.id,
            input=input,
            model_bindings=bindings,
            configuration=configuration,
        )
        if project_input_message:
            self._repository.append_message(
                session.id,
                execution_id=execution.id,
                role="user",
                content=_user_content(input),
            )
        await self._events.publish(
            session.id,
            execution.id,
            "execution.started",
            {"executionId": execution.id},
        )
        return execution

    def run_prepared(
        self, execution: ExecutionRecord, *, graph_input: object
    ) -> None:
        if execution.status != "running":
            raise ValueError("prepared execution must be running")
        self._spawn(execution.id, graph_input=graph_input)

    def run_background(
        self, execution: ExecutionRecord, handler: ExecutionHandler
    ) -> None:
        if execution.status != "running":
            raise ValueError("prepared execution must be running")
        if execution.id in self._tasks:
            raise ValueError("execution already has a running task")
        control = ExecutionControl()
        cancellation = ExecutionCancellation(
            repository=self._repository,
            execution_id=execution.id,
            control=control,
        )
        task = asyncio.create_task(
            self._execute_background(execution.id, handler, cancellation)
        )
        self._register_task(execution.id, task, control)

    async def resume_approval(
        self, execution_id: str, decision: dict[str, Any], _receipt_id: str
    ) -> None:
        execution = self._repository.transition_execution(
            execution_id,
            expected=("waiting_for_approval", "interrupted"),
            target="running",
            increment_resume=True,
        )
        await self._events.publish(
            execution.session_id,
            execution.id,
            "execution.started",
            {"executionId": execution.id, "resumed": True},
        )
        self._spawn(execution.id, graph_input=Command(resume=decision))

    async def resume_input(
        self,
        execution_id: str,
        *,
        request_id: str,
        value: str,
        receipt_id: str,
    ) -> ReviewInputReceipt:
        if self._review_repository is None:
            raise RuntimeError("review input recovery is not configured")
        request = self._review_repository.get_input_request(request_id)
        round_record = self._review_repository.get_round(request.round_id)
        if round_record.execution_id != execution_id:
            raise ValueError("input request does not belong to execution")
        if request.status == "resolved":
            return self._review_repository.resolve_input(
                request_id,
                idempotency_key=receipt_id,
                value=value,
                receipt={"accepted": True},
                receipt_id=receipt_id,
            )
        receipt = self._review_repository.resolve_input(
            request_id,
            idempotency_key=receipt_id,
            value=value,
            receipt={"accepted": True},
            receipt_id=receipt_id,
        )
        execution = self._repository.transition_execution(
            execution_id,
            expected=("waiting_for_input", "interrupted"),
            target="running",
            increment_resume=True,
        )
        await self._events.publish(
            execution.session_id,
            execution.id,
            "review.input.resolved",
            {"inputRequestId": request_id, "receiptId": receipt.id},
        )
        await self._events.publish(
            execution.session_id,
            execution.id,
            "execution.started",
            {"executionId": execution.id, "resumed": True},
        )
        self._spawn(
            execution.id,
            graph_input=Command(
                resume={
                    "inputRequestId": request_id,
                    "value": value,
                    "receiptId": receipt.id,
                }
            ),
        )
        return receipt

    async def resume_accepted_input(
        self,
        execution_id: str,
        *,
        receipt: ReviewAnswerReceipt,
        value: str,
    ) -> None:
        """Schedule model work after the answer transaction has committed."""
        execution = self._repository.get_execution(execution_id)
        if execution.status != "running" or execution_id in self._tasks:
            return
        await self._events.publish(
            execution.session_id,
            execution.id,
            "review.answer.accepted",
            {
                "receiptId": receipt.id,
                "roundId": receipt.round_id,
                "attemptId": receipt.attempt_id,
                "inputRequestId": receipt.input_request_id,
                "version": receipt.version,
            },
        )
        await self._events.publish(
            execution.session_id,
            execution.id,
            "review.evaluation.started",
            {
                "roundId": receipt.round_id,
                "attemptId": receipt.attempt_id,
                "inputRequestId": receipt.input_request_id,
                "version": receipt.version,
            },
        )
        self._spawn(
            execution.id,
            graph_input=Command(
                resume={
                    "inputRequestId": receipt.input_request_id,
                    "value": value,
                    "receiptId": receipt.id,
                }
            ),
        )

    async def skip_input(
        self,
        execution_id: str,
        *,
        request_id: str,
        receipt_id: str,
    ) -> ReviewInputReceipt:
        if self._review_repository is None:
            raise RuntimeError("review input recovery is not configured")
        request = self._review_repository.get_input_request(request_id)
        round_record = self._review_repository.get_round(request.round_id)
        if round_record.execution_id != execution_id:
            raise ValueError("input request does not belong to execution")
        if request.status == "resolved":
            return self._review_repository.resolve_input(
                request_id,
                idempotency_key=receipt_id,
                value="__skip__",
                receipt={"accepted": True, "operation": "skip"},
                receipt_id=receipt_id,
            )
        receipt = self._review_repository.resolve_input(
            request_id,
            idempotency_key=receipt_id,
            value="__skip__",
            receipt={"accepted": True, "operation": "skip"},
            receipt_id=receipt_id,
        )
        execution = self._repository.transition_execution(
            execution_id,
            expected=("waiting_for_input", "interrupted"),
            target="running",
            increment_resume=True,
        )
        await self._events.publish(
            execution.session_id,
            execution.id,
            "review.input.resolved",
            {
                "inputRequestId": request_id,
                "receiptId": receipt.id,
                "operation": "skip",
            },
        )
        await self._events.publish(
            execution.session_id,
            execution.id,
            "execution.started",
            {"executionId": execution.id, "resumed": True},
        )
        self._spawn(
            execution.id,
            graph_input=Command(
                resume={
                    "inputRequestId": request_id,
                    "operation": "skip",
                    "value": "",
                    "receiptId": receipt.id,
                }
            ),
        )
        return receipt

    async def cancel(self, execution_id: str) -> ExecutionRecord:
        current = self._repository.get_execution(execution_id)
        if current.status in {"completed", "failed", "cancelled"}:
            return current
        first_request = not current.cancellation_requested
        requested = self._repository.request_execution_cancel(execution_id)
        if first_request:
            await self._events.publish(
                requested.session_id,
                requested.id,
                "execution.cancelling",
                {"executionId": requested.id},
            )
        task = self._tasks.get(execution_id)
        control = self._controls.get(execution_id)
        if task is not None and (control is None or control.interruptible):
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        elif task is not None:
            return requested
        return await self._finish_cancel(execution_id)

    async def wait(self, execution_id: str) -> ExecutionRecord:
        task = self._tasks.get(execution_id)
        if task is not None:
            await task
        return self._repository.get_execution(execution_id)

    async def complete_background_execution(
        self, execution_id: str
    ) -> ExecutionRecord:
        current = self._repository.get_execution(execution_id)
        if current.status != "running":
            return current
        completed = self._repository.transition_execution(
            execution_id,
            expected=("running",),
            target="completed",
        )
        await self._events.publish(
            completed.session_id,
            completed.id,
            "execution.completed",
            {"executionId": completed.id},
        )
        return completed

    async def close(self) -> None:
        tasks = tuple(self._tasks.items())
        for execution_id, task in tasks:
            control = self._controls.get(execution_id)
            if control is not None and not control.interruptible:
                control.shutdown_requested = True
            else:
                task.cancel()
        if tasks:
            await asyncio.gather(
                *(task for _execution_id, task in tasks),
                return_exceptions=True,
            )
        self._repository.interrupt_running()
        self._tasks.clear()
        self._controls.clear()

    def recover(self) -> tuple[str, ...]:
        return self._repository.interrupt_running()

    async def resume_evaluating_attempts(self) -> tuple[str, ...]:
        if self._review_repository is None:
            return ()
        resumed: list[str] = []
        for attempt in self._review_repository.list_evaluating_attempts():
            round_record = self._review_repository.get_round(attempt.round_id)
            if round_record.execution_id is None:
                continue
            execution = self._repository.get_execution(round_record.execution_id)
            if execution.status != "interrupted":
                continue
            request, receipt = self._review_repository.resolved_input_for_attempt(
                attempt
            )
            value = (
                attempt.follow_up_answer
                if request.kind == "follow_up"
                else attempt.answer
            )
            if value is None:
                continue
            execution = self._repository.transition_execution(
                execution.id,
                expected=("interrupted",),
                target="running",
                increment_resume=True,
            )
            await self._events.publish(
                execution.session_id,
                execution.id,
                "review.evaluation.started",
                {
                    "roundId": receipt.round_id,
                    "attemptId": receipt.attempt_id,
                    "inputRequestId": receipt.input_request_id,
                    "version": receipt.version,
                    "recovered": True,
                },
            )
            self._spawn(
                execution.id,
                graph_input=Command(
                    resume={
                        "inputRequestId": receipt.input_request_id,
                        "value": value,
                        "receiptId": receipt.id,
                    }
                ),
            )
            resumed.append(attempt.id)
        return tuple(resumed)

    async def retry_evaluation(
        self, execution_id: str, *, receipt: ReviewAnswerReceipt
    ) -> None:
        execution = self._repository.get_execution(execution_id)
        if execution.status != "running" or execution_id in self._tasks:
            return
        await self._events.publish(
            execution.session_id,
            execution.id,
            "review.evaluation.started",
            {
                "roundId": receipt.round_id,
                "attemptId": receipt.attempt_id,
                "inputRequestId": receipt.input_request_id,
                "version": receipt.version,
                "retried": True,
            },
        )
        self._spawn(execution.id, graph_input=None)

    async def retry_failed_review_round(self, execution_id: str) -> ExecutionRecord:
        execution = self._repository.transition_execution(
            execution_id,
            expected=("failed",),
            target="running",
            increment_resume=True,
        )
        await self._events.publish(
            execution.session_id,
            execution.id,
            "execution.started",
            {"executionId": execution.id, "resumed": True, "recovery": True},
        )
        self._spawn(execution.id, graph_input=None)
        return execution

    def _round_model_override(self, session_id: str) -> ModelOverride:
        if self._review_repository is None:
            raise RuntimeError("review model override is not configured")
        settings = self._review_repository.get_round_by_session(
            session_id
        ).settings
        return ModelOverride(
            provider_model_id=settings.answer_model_id,
            reasoning_effort=settings.reasoning_effort,
        )

    def _spawn(self, execution_id: str, *, graph_input: object) -> None:
        task = asyncio.create_task(self._execute(execution_id, graph_input))
        self._register_task(execution_id, task, ExecutionControl())

    def _register_task(
        self,
        execution_id: str,
        task: asyncio.Task[None],
        control: ExecutionControl,
    ) -> None:
        self._tasks[execution_id] = task
        self._controls[execution_id] = control

        def discard(completed: asyncio.Task[None]) -> None:
            if self._tasks.get(execution_id) is completed:
                self._tasks.pop(execution_id, None)
                self._controls.pop(execution_id, None)

        task.add_done_callback(discard)

    async def _execute_background(
        self,
        execution_id: str,
        handler: ExecutionHandler,
        cancellation: ExecutionCancellation,
    ) -> None:
        execution = self._repository.get_execution(execution_id)
        context = self._execution_context(execution)
        await self._trace_execution(
            context, "execution.started", {"status": "running"}
        )
        try:
            cancellation.raise_if_requested()
            await handler(execution, cancellation)
            cancellation.raise_if_requested()
        except ExecutionCancelled:
            await self._finish_cancel(execution_id)
            return
        except asyncio.CancelledError:
            if self._repository.get_execution(execution_id).cancellation_requested:
                await self._finish_cancel(execution_id)
                return
            raise
        except Exception as error:
            current = self._repository.get_execution(execution_id)
            if current.status == "running":
                failed = self._repository.transition_execution(
                    execution_id,
                    expected=("running",),
                    target="failed",
                    error_code=str(
                        getattr(error, "code", "agent_execution_failed")
                    ),
                    error_message="Agent 执行失败",
                )
                await self._events.publish(
                    failed.session_id,
                    failed.id,
                    "execution.failed",
                    {"code": failed.error_code or "agent_execution_failed"},
                )
                await self._trace_execution(
                    context,
                    "execution.failed",
                    safe_error_payload(error),
                    terminal=True,
                )
            return
        current = self._repository.get_execution(execution_id)
        if current.status == "running":
            completed = self._repository.transition_execution(
                execution_id,
                expected=("running",),
                target="completed",
            )
            await self._events.publish(
                completed.session_id,
                completed.id,
                "execution.completed",
                {"executionId": completed.id},
            )
            await self._trace_execution(
                context,
                "execution.completed",
                {"status": "completed"},
                terminal=True,
            )

    async def _finish_cancel(self, execution_id: str) -> ExecutionRecord:
        current = self._repository.get_execution(execution_id)
        if current.status in {"completed", "failed", "cancelled"}:
            return current
        cancelled = self._repository.transition_execution(
            execution_id,
            expected=(
                "running",
                "waiting_for_input",
                "waiting_for_approval",
                "interrupted",
            ),
            target="cancelled",
        )
        await self._events.publish(
            cancelled.session_id,
            cancelled.id,
            "execution.cancelled",
            {"executionId": cancelled.id},
        )
        await self._trace_execution(
            self._execution_context(cancelled),
            "execution.failed",
            {"status": "cancelled", "code": "execution_cancelled"},
            terminal=True,
        )
        return cancelled

    async def _execute(self, execution_id: str, graph_input: object) -> None:
        execution = self._repository.get_execution(execution_id)
        session = self._repository.get_session(execution.session_id)
        context = AgentContext(
            workspace_id=self._workspace_id,
            workspace_root=self._workspace_root,
            session_id=session.id,
            run_id=execution.id,
            allowed_tools=frozenset(),
            allowed_scopes=frozenset(),
            agent_role=(
                "profile_extraction"
                if session.kind == "profile.ingest"
                else "profile_assessment"
                if session.kind == "profile.assess"
                else None
            ),
        )
        context = replace(
            context,
            trace_warning=lambda code, bound=context: self._record_trace_warning(
                bound, code
            ),
        )
        await self._trace_execution(
            context, "execution.started", {"status": "running"}
        )

        async def project_profile_card(
            assessment_id: str,
            proposal_ids: list[str],
            summary: dict[str, object],
        ) -> None:
            existing = any(
                message.message_kind == "assessment_card"
                and message.payload.get("resourceId") == assessment_id
                for message in self._repository.list_messages(session.id)
            )
            if existing:
                return
            self._repository.append_message(
                session.id,
                execution_id=execution.id,
                role="assistant",
                message_kind="assessment_card",
                content="个人画像评估已生成。",
                payload={
                    "resourceId": assessment_id,
                    "version": 1,
                    "assessmentId": assessment_id,
                    "proposalIds": proposal_ids,
                    **summary,
                },
            )

        async def create_action(**values):
            return await self._create_action(
                CreatePendingAction(
                    workspace_id=self._workspace_id,
                    session_id=session.id,
                    run_id=execution.id,
                    action_type=values["action_type"],
                    payload=values["payload"],
                    preview=values["preview"],
                    editable_fields=tuple(values.get("editable_fields", ())),
                    idempotency_key=values["idempotency_key"],
                )
            )

        async def create_draft(**values):
            draft = await self._create_draft(
                CreateDraftCommand(
                    domain="review",
                    document_type=values.get("document_type", "session_report"),
                    title=values["title"],
                    markdown=values["markdown"],
                    source_refs=tuple(values.get("source_refs", ())),
                    relation_refs=tuple(values.get("relation_refs", ())),
                    session_id=session.id,
                    run_id=execution.id,
                    agent_type=session.kind,
                    document_id=values.get("document_id"),
                )
            )
            return await self._mark_draft_review_pending(
                draft.id,
                expected_version=draft.version,
                expected_hash=draft.content_hash,
            )

        async def create_report_drafts(**values):
            if self._review_repository is None or self._get_draft is None:
                raise RuntimeError("review report persistence is not configured")
            round_record = values["round_record"]
            attempts = values["attempts"]
            report = values["report"]
            existing_session = self._review_repository.find_report_proposal(
                round_record.id, "session_report"
            )
            existing_mastery = self._review_repository.find_report_proposal(
                round_record.id, "mastery_report"
            )
            if existing_session is not None and existing_mastery is not None:
                session_draft = await self._get_draft(existing_session.draft_id)
                mastery_draft = await self._get_draft(existing_mastery.draft_id)
                return (
                    DraftRef(
                        session_draft.id,
                        session_draft.version,
                        session_draft.content_hash,
                        "session_report",
                    ),
                    DraftRef(
                        mastery_draft.id,
                        mastery_draft.version,
                        mastery_draft.content_hash,
                        "mastery_report",
                    ),
                )

            session_draft = await create_draft(
                document_type="session_report",
                document_id=f"review_session_{round_record.id}",
                title=report.title,
                markdown=report.markdown,
                source_refs=tuple(attempt.id for attempt in attempts),
                relation_refs=round_record.settings.topics,
            )
            entries = {
                entry.subject_id: entry
                for entry in round_record.mastery_before.entries
            }
            evidence_refs = list(round_record.mastery_before.evidence_refs)
            for attempt in attempts:
                if attempt.mastery_suggestion is None:
                    continue
                entries[attempt.question_snapshot.question_id] = MasteryEntry(
                    subject_id=attempt.question_snapshot.question_id,
                    state=attempt.mastery_suggestion,
                    recent_mistake=(
                        attempt.mastery_suggestion in {"weak", "partial"}
                    ),
                    evidence_refs=(attempt.id,),
                )
                if attempt.id not in evidence_refs:
                    evidence_refs.append(attempt.id)
            proposal = MasteryProjection(
                workspace_id=round_record.workspace_id,
                version=round_record.mastery_before.version + 1,
                entries=tuple(entries[key] for key in sorted(entries)),
                evidence_refs=tuple(evidence_refs),
            )
            mastery_markdown = (
                f"# {report.title} · 掌握度更新\n\n"
                f"{report.mastery_explanation}\n"
            )
            mastery_draft = await create_draft(
                document_type="mastery_report",
                document_id=f"review_mastery_{round_record.id}",
                title=f"{report.title} · 掌握度更新",
                markdown=mastery_markdown,
                source_refs=tuple(attempt.id for attempt in attempts),
                relation_refs=round_record.settings.topics,
            )
            self._review_repository.save_report_proposal(
                draft_id=session_draft.id,
                round_id=round_record.id,
                report_kind="session_report",
                projection=None,
                expected_mastery_version=None,
            )
            self._review_repository.save_report_proposal(
                draft_id=mastery_draft.id,
                round_id=round_record.id,
                report_kind="mastery_report",
                projection=proposal,
                expected_mastery_version=round_record.mastery_before.version,
            )
            return (
                DraftRef(
                    session_draft.id,
                    session_draft.version,
                    session_draft.content_hash,
                    "session_report",
                ),
                DraftRef(
                    mastery_draft.id,
                    mastery_draft.version,
                    mastery_draft.content_hash,
                    "mastery_report",
                ),
            )

        async def request_publication_action(draft_ref: DraftRef):
            if self._get_draft is None:
                raise RuntimeError("review publication is not configured")
            draft = await self._get_draft(draft_ref.id)
            return await create_action(
                action_type="knowledge.publish",
                payload={
                    "draftId": draft.id,
                    "draftVersion": draft.version,
                    "contentHash": draft.content_hash,
                    "title": draft.title,
                    "markdown": draft.markdown,
                },
                preview={
                    "title": draft.title,
                    "markdown": draft.markdown,
                    "draftId": draft.id,
                    "reportKind": draft_ref.report_kind,
                },
                editable_fields=("title", "markdown"),
                idempotency_key=(
                    f"knowledge.publish:{draft.id}:{draft.version}:"
                    f"{draft.content_hash}"
                ),
            )

        async def persist_question_candidates(state: dict[str, Any]) -> None:
            if self._review_repository is None:
                raise RuntimeError("question curation is not configured")
            batch_id = str(
                execution.input.get("batch_id")
                or execution.input.get("batchId", "")
            )
            if not batch_id:
                raise ValueError("question curation batch is missing")
            batch = self._review_repository.get_batch(batch_id)

            def rejected_outcome() -> Literal[
                "cancelled", "interrupted", "failed"
            ]:
                current_batch = self._review_repository.get_batch(batch_id)
                if (
                    current_batch.control_intent in {"pause", "terminate"}
                    or current_batch.status in {"paused", "terminated"}
                ):
                    return "cancelled"
                try:
                    active_batch_id = (
                        self._review_repository.get_curation_session(
                            session.id
                        ).active_batch_id
                    )
                except LookupError:
                    active_batch_id = None
                if (
                    current_batch.run_id != execution.id
                    or active_batch_id != batch_id
                ):
                    return "interrupted"
                return "failed"

            try:
                finalization = self._review_repository.claim_curation_finalization(
                    batch_id, execution.id
                )
            except ReviewConflictError as error:
                raise CurationFinalizationRejected(
                    str(error), outcome=rejected_outcome()
                ) from error
            if finalization[3] == "committed":
                return
            curation_drafts = KnowledgeDraftService(
                self._workspace_root, workspace_id=self._workspace_id
            )
            timeline = SessionTimelineProjector(self._repository, self._events)
            try:
                curation = self._review_repository.get_curation_session(
                    session.id
                )
            except LookupError:
                curation = None
            raw_candidates = tuple(state.get("candidates", ()))
            active = self._review_repository.list_active_questions(
                self._workspace_id
            )
            from app.review.question_similarity import same_question

            def similar_active(raw: dict[str, Any]) -> str | None:
                for item in active:
                    if same_question(
                        str(raw["question_text"]),
                        item.snapshot.question_text,
                        left_topics=raw["topics"],
                        right_topics=item.snapshot.topics,
                        threshold=0.78,
                    ):
                        return item.snapshot.question_id
                return None
            candidate_specs: list[dict[str, object]] = []
            revision_candidate_id = (
                execution.input.get("revision_candidate_id")
                or execution.input.get("revisionCandidateId")
            )
            for index, raw in enumerate(raw_candidates, start=1):
                markdown = (
                    f"# {raw['title']}\n\n"
                    f"## 题目\n\n{raw['question_text']}\n\n"
                    f"## 参考答案\n\n{raw['reference_answer']}\n\n"
                    f"## 关键点\n\n"
                    + "\n".join(f"- {item}" for item in raw["key_points"])
                    + "\n"
                )
                if revision_candidate_id:
                    if index > 1:
                        break
                    original = self._review_repository.get_candidate(str(revision_candidate_id))
                    if original.draft_id is None or self._get_draft is None:
                        raise RuntimeError("question revision draft is not configured")
                    expected_revision_draft_id = str(
                        execution.input.get("expected_revision_draft_id")
                        or execution.input.get("expectedRevisionDraftId")
                        or ""
                    )
                    expected_revision_draft_version = execution.input.get(
                        "expected_revision_draft_version",
                        execution.input.get("expectedRevisionDraftVersion"),
                    )
                    expected_revision_draft_hash = str(
                        execution.input.get("expected_revision_draft_hash")
                        or execution.input.get("expectedRevisionDraftHash")
                        or ""
                    )
                    if (
                        not expected_revision_draft_id
                        or not isinstance(expected_revision_draft_version, int)
                        or len(expected_revision_draft_hash) != 64
                    ):
                        raise ReviewConflictError(
                            "revision execution is missing its immutable base"
                        )
                    current_draft = await self._get_draft(
                        expected_revision_draft_id
                    )
                    draft_id = str(
                        uuid5(
                            NAMESPACE_URL,
                            f"review-curation:{batch_id}:{execution.id}:revision:draft",
                        )
                    )
                    try:
                        draft = await curation_drafts.stage_curation_draft(
                            batch_id,
                            CreateDraftCommand(
                                domain="review",
                                document_type="question",
                                title=raw["title"],
                                markdown=markdown,
                                source_refs=original.source_refs,
                                relation_refs=tuple(raw["topics"]),
                                session_id=session.id,
                                run_id=execution.id,
                                agent_type=session.kind,
                                draft_id=draft_id,
                                document_id=current_draft.document_id,
                            ),
                        )
                    except DraftNotEditableError as error:
                        raise CurationFinalizationRejected(
                            str(error), outcome=rejected_outcome()
                        ) from error
                    snapshot = QuestionSnapshot(
                        question_id=original.question.question_id,
                        document_id=draft.document_id,
                        content_hash=draft.content_hash,
                        title=raw["title"],
                        question_text=raw["question_text"],
                        reference_answer=raw["reference_answer"],
                        topics=tuple(raw["topics"]),
                        difficulty=raw["difficulty"],
                        key_points=tuple(raw["key_points"]),
                        follow_ups=tuple(raw["follow_ups"]),
                    )
                    draft_spec = asdict(draft)
                    draft_spec["version"] = current_draft.version + 1
                    candidate_specs.append(
                        {
                            "candidate_id": original.id,
                            "revision_candidate_id": original.id,
                            "expected_revision_draft_id": (
                                expected_revision_draft_id
                            ),
                            "expected_revision_draft_version": (
                                expected_revision_draft_version
                            ),
                            "expected_revision_draft_hash": (
                                expected_revision_draft_hash
                            ),
                            "draft_id": draft.id,
                            "draft": draft_spec,
                            "question": snapshot,
                            "source_refs": original.source_refs,
                            "correction_note": original.correction_note,
                            "duplicate_of_question_id": (
                                original.duplicate_of_question_id
                            ),
                            "source_links": (),
                        }
                    )
                    continue
                identity = f"review-curation:{batch_id}:{execution.id}:{index}"
                question_id = str(uuid5(NAMESPACE_URL, f"{identity}:question"))
                draft_id = str(uuid5(NAMESPACE_URL, f"{identity}:draft"))
                candidate_id = str(
                    uuid5(NAMESPACE_URL, f"{identity}:candidate")
                )
                proposed_refs = tuple(
                    str(ref)
                    for ref in raw["source_refs"]
                    if any(
                        str(ref) == source_id
                        or str(ref).startswith(f"{source_id}#")
                        for source_id in batch.source_refs
                    )
                )
                source_refs = proposed_refs or batch.source_refs
                try:
                    draft = await curation_drafts.stage_curation_draft(
                        batch_id,
                        CreateDraftCommand(
                            domain="review",
                            document_type="question",
                            title=raw["title"],
                            markdown=markdown,
                            source_refs=source_refs,
                            relation_refs=tuple(raw["topics"]),
                            session_id=session.id,
                            run_id=execution.id,
                            agent_type=session.kind,
                            draft_id=draft_id,
                            document_id=f"question_{question_id}",
                        ),
                    )
                except DraftNotEditableError as error:
                    raise CurationFinalizationRejected(
                        str(error), outcome=rejected_outcome()
                    ) from error
                snapshot = QuestionSnapshot(
                    question_id=question_id,
                    document_id=draft.document_id,
                    content_hash=draft.content_hash,
                    title=raw["title"],
                    question_text=raw["question_text"],
                    reference_answer=raw["reference_answer"],
                    topics=tuple(raw["topics"]),
                    difficulty=raw["difficulty"],
                    key_points=tuple(raw["key_points"]),
                    follow_ups=tuple(raw["follow_ups"]),
                )
                duplicate_of_question_id = similar_active(raw)
                source_links: list[dict[str, object]] = []
                for source_ref in source_refs:
                    source_id = str(source_ref).split("#", 1)[0]
                    source_links.append(
                        {
                            "link_id": str(
                                uuid5(
                                    NAMESPACE_URL,
                                    f"{identity}:source:{source_ref}",
                                )
                            ),
                            # Duplicate evidence belongs to the existing logical
                            # question rather than the transient candidate question.
                            "question_id": (
                                duplicate_of_question_id or snapshot.question_id
                            ),
                            "source_id": source_id,
                            "evidence_ref": str(source_ref),
                            "merge_reason": (
                                "linked_to_active_question"
                                if duplicate_of_question_id
                                else "generated_from_source"
                            ),
                        }
                    )
                candidate_specs.append(
                    {
                        "candidate_id": candidate_id,
                        "draft_id": draft.id,
                        "draft": asdict(draft),
                        "question": snapshot,
                        "source_refs": source_refs,
                        "correction_note": raw["correction_note"],
                        "duplicate_of_question_id": duplicate_of_question_id,
                        "source_links": tuple(source_links),
                    }
                )
            try:
                persisted = list(
                    self._review_repository.finalize_curation_candidates(
                        batch_id,
                        execution.id,
                        candidates=tuple(candidate_specs),
                    )
                )
            except ReviewConflictError as error:
                raise CurationFinalizationRejected(
                    str(error), outcome=rejected_outcome()
                ) from error
            if curation is not None:
                curation = self._review_repository.get_curation_session(
                    session.id
                )
            for warning in state.get("warnings", ()):
                if isinstance(warning, dict):
                    self._review_repository.append_curation_warning(
                        session.id, warning
                    )
            if curation is not None:
                await self._events.publish(
                    session.id,
                    execution.id,
                    "curation.stage.changed",
                    {
                        "resourceId": session.id,
                        "stage": "merging",
                        "version": curation.summary_version,
                    },
                )
                await timeline.append(
                    session_id=session.id,
                    execution_id=execution.id,
                    role="assistant",
                    message_kind="stage",
                    content="正在合并相似题并整理来源",
                    payload={
                        "resourceId": session.id,
                        "version": curation.summary_version,
                        "stage": "merging",
                    },
                )
                for index, _candidate in enumerate(persisted, start=1):
                    await self._events.publish(
                        session.id,
                        execution.id,
                        "curation.progress.changed",
                        {
                            "resourceId": session.id,
                            "completed": index,
                            "total": max(1, len(raw_candidates)),
                        },
                    )
            if curation is None:
                return
            curation = self._review_repository.get_curation_session(session.id)
            await self._events.publish(
                session.id,
                execution.id,
                "curation.stage.changed",
                {
                    "resourceId": session.id,
                    "stage": "summarizing",
                    "version": curation.summary_version,
                },
            )
            await timeline.append(
                session_id=session.id,
                execution_id=execution.id,
                role="assistant",
                message_kind="curation_summary",
                content=(
                    f"已整理 {len(curation.summary.items)} 道候选题，"
                    "请确认处理方式。"
                ),
                payload={
                    "resourceId": session.id,
                    "version": curation.summary_version,
                },
            )
            await self._events.publish(
                session.id,
                execution.id,
                "curation.summary.ready",
                {
                    "resourceId": session.id,
                    "count": len(curation.summary.items),
                    "version": curation.summary_version,
                },
            )

        final_state: dict[str, Any] = {}
        interrupted = False
        interrupt_kind: Literal["input", "approval"] | None = None
        projected_text = False
        projected_attempts: dict[str, str] = {}
        projected_drafts: set[str] = set()
        projected_progress: tuple[int, str] | None = None
        projected_curation_progress: tuple[str, int, int] | None = None
        projector = AgentEventProjector()
        review_timeline = SessionTimelineProjector(
            self._repository, self._events
        )
        try:
            async with self._checkpointer.open() as saver:
                graph = self._graph_factory(
                    session.kind,
                    model_bindings=dict(self._model_bindings()),
                    checkpointer=saver,
                    context=context,
                    create_action=create_action,
                    create_draft=create_draft,
                    review_repository=self._review_repository,
                    create_report_drafts=create_report_drafts,
                    request_publication_action=request_publication_action,
                    answer_model_override=(
                        self._round_model_override(session.id)
                        if session.kind == "review.round"
                        else None
                    ),
                    discussion_model_override=(
                        ModelOverride(
                            provider_model_id=execution.configuration.provider_model_id,
                            reasoning_effort=execution.configuration.reasoning_effort,
                        )
                        if session.kind == "review.discussion"
                        and execution.configuration.provider_model_id is not None
                        else None
                    ),
                    profile_repository=self._profile_repository,
                    profile_storage=self._profile_storage,
                    project_profile_card=project_profile_card,
                )
                async for part in graph.astream(
                    graph_input,
                    config={"configurable": {"thread_id": session.id}},
                    context=context,
                    stream_mode=["values", "messages", "custom", "tasks"],
                    version="v2",
                ):
                    if part.get("type") == "values":
                        data = part.get("data")
                        if isinstance(data, dict):
                            final_state = data
                            if session.kind in {"question.curate", "question.revise"}:
                                phase = data.get("generation_phase")
                                if phase in {"discovery", "enrichment"}:
                                    progress = (
                                        str(phase),
                                        int(data.get("completed_units", 0)),
                                        int(data.get("total_units", 0)),
                                    )
                                    if progress != projected_curation_progress:
                                        projected_curation_progress = progress
                                        self._review_repository.update_curation_progress(
                                            session.id,
                                            stage="generating",
                                            completed_units=progress[1],
                                            total_units=progress[2],
                                        )
                                        await self._events.publish(
                                            session.id,
                                            execution.id,
                                            "curation.progress.changed",
                                            {
                                                "resourceId": session.id,
                                                "phase": progress[0],
                                                "completed": progress[1],
                                                "total": progress[2],
                                            },
                                        )
                            if session.kind == "review.round":
                                for attempt_id in data.get("attempt_ids", ()):
                                    attempt = self._review_repository.get_attempt(
                                        attempt_id
                                    )
                                    if projected_attempts.get(attempt_id) == attempt.status:
                                        continue
                                    projected_attempts[attempt_id] = attempt.status
                                    if attempt.status not in {
                                        "waiting_for_follow_up",
                                        "completed",
                                    }:
                                        continue
                                    evaluation = attempt.evaluation or {}
                                    await self._events.publish(
                                        session.id,
                                        execution.id,
                                        "review.evaluation.completed",
                                        {
                                            "roundId": attempt.round_id,
                                            "attemptId": attempt_id,
                                            "ordinal": attempt.ordinal,
                                            "status": attempt.status,
                                            "score": evaluation.get("score"),
                                            "version": self._review_repository.get_round(
                                                attempt.round_id
                                            ).version,
                                        },
                                    )
                                    existing_card = any(
                                        message.message_kind == "evaluation_card"
                                        and message.payload.get("attemptId") == attempt_id
                                        and message.payload.get("status") == attempt.status
                                        for message in self._repository.list_messages(
                                            session.id
                                        )
                                    )
                                    if not existing_card:
                                        await review_timeline.append(
                                            session_id=session.id,
                                            execution_id=execution.id,
                                            role="assistant",
                                            message_kind="evaluation_card",
                                            content=(
                                                "评价完成，Agent 需要一次必要追问。"
                                                if attempt.status == "waiting_for_follow_up"
                                                else "本题评价已完成。"
                                            ),
                                            payload={
                                                "resourceId": attempt.id,
                                                "version": self._review_repository.get_round(
                                                    attempt.round_id
                                                ).version,
                                                "roundId": attempt.round_id,
                                                "attemptId": attempt.id,
                                                "ordinal": attempt.ordinal,
                                                "status": attempt.status,
                                                "evaluation": evaluation,
                                                "masterySuggestion": attempt.mastery_suggestion,
                                            },
                                        )
                                progress = (
                                    int(data.get("current_index", 0)),
                                    str(data.get("status", "running")),
                                )
                                if progress != projected_progress:
                                    projected_progress = progress
                                    await self._events.publish(
                                        session.id,
                                        execution.id,
                                        "review.progress.changed",
                                        {
                                            "currentIndex": progress[0],
                                            "status": progress[1],
                                        },
                                    )
                                for draft_id in data.get(
                                    "report_draft_ids", ()
                                ):
                                    if draft_id in projected_drafts:
                                        continue
                                    projected_drafts.add(draft_id)
                                    await self._events.publish(
                                        session.id,
                                        execution.id,
                                        "review.report.draft_created",
                                        {"draftId": draft_id},
                                    )
                        if part.get("interrupts"):
                            interrupted = True
                            for item in part["interrupts"]:
                                value = getattr(item, "value", None)
                                if not isinstance(value, Mapping):
                                    raise UnsupportedInterruptError(
                                        "unsupported_interrupt"
                                    )
                                current_kind = _classify_interrupt(value)
                                if (
                                    interrupt_kind is not None
                                    and current_kind != interrupt_kind
                                ):
                                    raise UnsupportedInterruptError(
                                        "unsupported_interrupt"
                                    )
                                interrupt_kind = current_kind
                                if (
                                    current_kind == "input"
                                    and self._review_repository is not None
                                ):
                                    request_id = str(value["inputRequestId"])
                                    already_projected = any(
                                        message.message_kind == "review_prompt"
                                        and message.payload.get("inputRequestId") == request_id
                                        for message in self._repository.list_messages(
                                            session.id
                                        )
                                    )
                                    if not already_projected:
                                        request = self._review_repository.get_input_request(
                                            request_id
                                        )
                                        await review_timeline.append(
                                            session_id=session.id,
                                            execution_id=execution.id,
                                            role="assistant",
                                            message_kind="review_prompt",
                                            content=request.prompt,
                                            payload={
                                                "resourceId": request.id,
                                                "version": request.version,
                                                "roundId": request.round_id,
                                                "inputRequestId": request.id,
                                                "ordinal": request.ordinal,
                                                "kind": request.kind,
                                            },
                                        )
                    for event in projector.project(part):
                        if event.type == "assistant.delta":
                            projected_text = True
                        await self._events.publish(
                            session.id,
                            execution.id,
                            event.type,
                            event.payload,
                        )
            if interrupted:
                if interrupt_kind is None:
                    raise UnsupportedInterruptError("unsupported_interrupt")
                self._repository.transition_execution(
                    execution.id,
                    expected=("running",),
                    target=(
                        "waiting_for_input"
                        if interrupt_kind == "input"
                        else "waiting_for_approval"
                    ),
                )
                await self._events.publish(
                    session.id,
                    execution.id,
                    "execution.interrupted",
                    {"executionId": execution.id},
                )
                return

            if session.kind in {"question.curate", "question.revise"}:
                await persist_question_candidates(final_state)

            response = _assistant_content(final_state)
            if response:
                self._repository.append_message(
                    session.id,
                    execution_id=execution.id,
                    role="assistant",
                    content=response,
                )
                if not projected_text:
                    await self._events.publish(
                        session.id,
                        execution.id,
                        "assistant.delta",
                        {"text": response},
                    )
            self._repository.transition_execution(
                execution.id,
                expected=("running",),
                target="completed",
            )
            await self._events.publish(
                session.id,
                execution.id,
                "execution.completed",
                {"executionId": execution.id},
            )
            await self._trace_execution(
                context,
                "execution.completed",
                {"status": "completed"},
                terminal=True,
            )
            if session.kind == "review.round":
                await self._events.publish(
                    session.id,
                    execution.id,
                    "review.round.completed",
                    {"executionId": execution.id},
                )
        except asyncio.CancelledError:
            if session.kind in {"question.curate", "question.revise"}:
                batch_id = str(
                    execution.input.get("batch_id")
                    or execution.input.get("batchId", "")
                )
                if batch_id:
                    await KnowledgeDraftService(
                        self._workspace_root, workspace_id=self._workspace_id
                    ).cleanup_curation_staging(
                        batch_id=batch_id, execution_id=execution.id
                    )
            raise
        except CurationFinalizationRejected as error:
            batch_id = str(
                execution.input.get("batch_id")
                or execution.input.get("batchId", "")
            )
            if batch_id:
                await KnowledgeDraftService(
                    self._workspace_root, workspace_id=self._workspace_id
                ).cleanup_curation_staging(
                    batch_id=batch_id, execution_id=execution.id
                )
            if error.outcome == "failed" and self._review_repository is not None:
                failed_batch = self._review_repository.update_batch_status(
                    batch_id, "failed", expected_run_id=execution.id
                )
                if (
                    failed_batch.status == "failed"
                    and failed_batch.run_id == execution.id
                ):
                    curation = self._review_repository.get_curation_session(
                        session.id
                    )
                    self._review_repository.update_curation_progress(
                        session.id,
                        stage="failed",
                        completed_units=curation.completed_units,
                        total_units=curation.total_units,
                    )
            current = self._repository.get_execution(execution.id)
            if current.status == "running":
                terminal = self._repository.transition_execution(
                    execution.id,
                    expected=("running",),
                    target=error.outcome,
                    error_code=error.code,
                    error_message=(
                        "整理结果已被更新状态取代"
                        if error.outcome != "failed"
                        else "整理结果提交失败"
                    ),
                )
                event_type = {
                    "cancelled": "execution.cancelled",
                    "interrupted": "execution.interrupted",
                    "failed": "execution.failed",
                }[error.outcome]
                await self._events.publish(
                    session.id,
                    execution.id,
                    event_type,
                    {
                        "executionId": execution.id,
                        "code": error.code,
                    },
                )
                await self._trace_execution(
                    context,
                    "execution.failed",
                    {
                        "status": terminal.status,
                        "code": error.code,
                    },
                    terminal=True,
                )
            return
        except Exception as error:
            if session.kind in {"question.curate", "question.revise"}:
                batch_id = str(
                    execution.input.get("batch_id")
                    or execution.input.get("batchId", "")
                )
                if batch_id:
                    await KnowledgeDraftService(
                        self._workspace_root, workspace_id=self._workspace_id
                    ).cleanup_curation_staging(
                        batch_id=batch_id, execution_id=execution.id
                    )
            if session.kind == "review.round" and self._review_repository is not None:
                try:
                    round_record = self._review_repository.get_round_by_session(
                        session.id
                    )
                    evaluating = [
                        attempt
                        for attempt in self._review_repository.list_attempts(
                            round_record.id
                        )
                        if attempt.status == "evaluating"
                    ]
                    if evaluating:
                        attempt = evaluating[-1]
                        error_code = str(
                            getattr(error, "code", "evaluation_failed")
                        )[:100]
                        self._review_repository.fail_attempt_evaluation(
                            attempt.id, error_code=error_code
                        )
                        await review_timeline.append(
                            session_id=session.id,
                            execution_id=execution.id,
                            role="assistant",
                            message_kind="error",
                            content="评价暂时失败，回答已保存，可以直接重试评价。",
                            payload={
                                "resourceId": attempt.id,
                                "version": round_record.version,
                                "roundId": round_record.id,
                                "attemptId": attempt.id,
                                "code": error_code,
                            },
                        )
                        await self._events.publish(
                            session.id,
                            execution.id,
                            "review.evaluation.failed",
                            {
                                "roundId": round_record.id,
                                "attemptId": attempt.id,
                                "code": error_code,
                                "version": round_record.version,
                            },
                        )
                        current = self._repository.get_execution(execution.id)
                        if current.status == "running":
                            self._repository.transition_execution(
                                execution.id,
                                expected=("running",),
                                target="interrupted",
                                error_code=error_code,
                                error_message="评价失败，可重试",
                            )
                        logger.warning(
                            "review evaluation failed",
                            extra={
                                "execution_id": execution.id,
                                "session_id": session.id,
                                "error_code": error_code,
                            },
                        )
                        await self._trace_execution(
                            context,
                            "execution.failed",
                            {"status": "interrupted", **safe_error_payload(error)},
                            terminal=True,
                        )
                        return
                except Exception as persistence_error:
                    logger.error(
                        "failed to persist review evaluation failure",
                        extra={
                            "execution_id": execution.id,
                            "error_code": str(
                                getattr(
                                    persistence_error,
                                    "code",
                                    "failure_persistence_failed",
                                )
                            ),
                        },
                    )

            logger.exception(
                "agent execution failed",
                extra={
                    "execution_id": execution.id,
                    "session_id": session.id,
                    "error_code": str(
                        getattr(error, "code", "agent_execution_failed")
                    ),
                },
            )
            try:
                if (
                    session.kind in {"question.curate", "question.revise"}
                    and self._review_repository is not None
                    and (
                        execution.input.get("batch_id")
                        or execution.input.get("batchId")
                    )
                ):
                    failed_batch = self._review_repository.update_batch_status(
                        str(
                            execution.input.get("batch_id")
                            or execution.input["batchId"]
                        ),
                        "failed",
                        expected_run_id=execution.id,
                    )
                    if (
                        failed_batch.status == "failed"
                        and failed_batch.run_id == execution.id
                    ):
                        curation = self._review_repository.get_curation_session(
                            session.id
                        )
                        self._review_repository.update_curation_progress(
                            session.id,
                            stage="failed",
                            completed_units=curation.completed_units,
                            total_units=curation.total_units,
                        )
                current = self._repository.get_execution(execution.id)
                if current.status == "running":
                    self._repository.transition_execution(
                        execution.id,
                        expected=("running",),
                        target="failed",
                        error_code=str(
                            getattr(error, "code", "agent_execution_failed")
                        ),
                        error_message="Agent 执行失败",
                    )
                    await self._events.publish(
                        session.id,
                        execution.id,
                        "execution.failed",
                        {
                            "code": str(
                                getattr(error, "code", "agent_execution_failed")
                            )
                        },
                    )
                    await self._trace_execution(
                        context,
                        "execution.failed",
                        safe_error_payload(error),
                        terminal=True,
                    )
                    if session.kind == "review.round":
                        await self._events.publish(
                            session.id,
                            execution.id,
                            "review.round.failed",
                            {
                                "executionId": execution.id,
                                "code": str(
                                    getattr(
                                        error,
                                        "code",
                                        "agent_execution_failed",
                                    )
                                ),
                            },
                        )
            except Exception:
                logger.exception(
                    "failed to persist agent execution failure",
                    extra={"execution_id": execution.id},
                )

    def _execution_context(self, execution: ExecutionRecord) -> AgentContext:
        context = AgentContext(
            workspace_id=self._workspace_id,
            workspace_root=self._workspace_root,
            session_id=execution.session_id,
            run_id=execution.id,
            allowed_tools=frozenset(),
            allowed_scopes=frozenset(),
        )
        return replace(
            context,
            trace_warning=lambda code, bound=context: self._record_trace_warning(
                bound, code
            ),
        )

    def _record_trace_warning(self, context: AgentContext, code: str) -> None:
        if context.run_id in self._trace_warned_runs:
            return
        self._trace_warned_runs.add(context.run_id)
        if self._trace_warning is None:
            return
        try:
            self._trace_warning(context, code)
        except Exception:
            pass

    async def _trace_execution(
        self,
        context: AgentContext,
        event_type: str,
        payload: dict[str, object],
        *,
        terminal: bool = False,
    ) -> None:
        identity = TraceIdentity(
            workspace_id=context.workspace_id,
            workspace_root=context.workspace_root,
            session_id=context.session_id,
            run_id=context.run_id,
            agent_role=context.agent_role or "execution",
            agent_name="execution_runtime",
            invocation_id=context.run_id,
        )
        try:
            written = await asyncio.to_thread(
                self._trace_writer.append,
                identity,
                event_type,
                payload,
                terminal=terminal,
            )
            if written:
                return
        except Exception:
            pass
        self._record_trace_warning(context, "agent_trace_write_failed")


def _user_content(input: dict[str, Any]) -> str:
    for key in ("userAnswer", "user_answer", "text", "message"):
        value = input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return json.dumps(input, ensure_ascii=False, sort_keys=True)


def _assistant_content(state: dict[str, Any]) -> str:
    for key in ("response", "report_markdown"):
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""

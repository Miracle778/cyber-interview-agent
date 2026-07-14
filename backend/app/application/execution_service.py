from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol

from langgraph.types import Command

from app.agents.context import AgentContext
from app.agents.factory import ModelOverride
from app.application.event_projector import AgentEventProjector
from app.application.session_service import (
    ExecutionRecord,
    ProductEventStream,
    ProductRepository,
    SessionRecord,
)
from app.hitl.models import CreatePendingAction, PendingActionRecord
from app.infrastructure.checkpoints import AgentCheckpointer
from app.knowledge.drafts import CreateDraftCommand, KnowledgeDraftRecord
from app.graphs.review_round import DraftRef
from app.review.models import MasteryEntry, MasteryProjection
from app.review.models import ReviewInputReceipt
from app.review.repository import ReviewRepository


logger = logging.getLogger(__name__)


class UnsupportedInterruptError(ValueError):
    code = "unsupported_interrupt"


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
        self._checkpointer = AgentCheckpointer(workspace_root)
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def start(
        self, session: SessionRecord, *, input: dict[str, Any]
    ) -> ExecutionRecord:
        bindings = dict(self._model_bindings())
        execution = self._repository.create_execution(
            session.id,
            input=input,
            model_bindings=bindings,
        )
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
        self._spawn(execution.id, graph_input=input)
        return execution

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

    async def cancel(self, execution_id: str) -> ExecutionRecord:
        current = self._repository.get_execution(execution_id)
        if current.status in {"completed", "failed", "cancelled"}:
            return current
        task = self._tasks.get(execution_id)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
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
        return cancelled

    async def wait(self, execution_id: str) -> ExecutionRecord:
        task = self._tasks.get(execution_id)
        if task is not None:
            await task
        return self._repository.get_execution(execution_id)

    async def close(self) -> None:
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._repository.interrupt_running()
        self._tasks.clear()

    def recover(self) -> tuple[str, ...]:
        return self._repository.interrupt_running()

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
        self._tasks[execution_id] = task

        def discard(completed: asyncio.Task[None]) -> None:
            if self._tasks.get(execution_id) is completed:
                self._tasks.pop(execution_id, None)

        task.add_done_callback(discard)

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

        final_state: dict[str, Any] = {}
        interrupted = False
        interrupt_kind: Literal["input", "approval"] | None = None
        projected_text = False
        projector = AgentEventProjector()
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
        except asyncio.CancelledError:
            raise
        except Exception as error:
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
            except Exception:
                logger.exception(
                    "failed to persist agent execution failure",
                    extra={"execution_id": execution.id},
                )


def _user_content(input: dict[str, Any]) -> str:
    for key in ("userAnswer", "user_answer", "text"):
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

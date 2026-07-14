from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.application.execution_service import AgentExecutionService, GraphFactory
from app.application.session_service import (
    AgentSessionService,
    EventRecord,
    ExecutionRecord,
    ProductEventStream,
    ProductRecordNotFoundError,
    ProductRepository,
    SessionRecord,
    encode_sse_event,
)
from app.hitl.handlers import create_default_action_handler_registry
from app.hitl.models import CreatePendingAction, ResolveActionCommand
from app.hitl.repository import PendingActionNotFoundError, PendingActionRepository
from app.hitl.service import HitlService
from app.infrastructure.runtime_database import connect_runtime_database
from app.infrastructure.observability import NoopObservabilitySink
from app.knowledge.drafts import (
    DraftNotFoundError,
    KnowledgeDraftRecord,
    KnowledgeDraftService,
    UpdateDraftCommand,
)
from app.knowledge.publication import PublicationService
from app.knowledge.publication_handler import KnowledgePublishActionHandler
from app.middleware.usage import UsageProjection
from app.review.application import ReviewApplication
from app.review.service import ReviewDomainService
from app.review.selector import QuestionSelector
from app.review.repository import ReviewRepository
from app.tools.audit import ToolAuditRepository


class SqliteMiddlewareProjection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def record_usage(self, context, usage: UsageProjection) -> bool:
        cursor = self._connection.execute(
            "INSERT INTO model_invocation_usage "
            "(workspace_id, session_id, run_id, operation_key, input_tokens, "
            "output_tokens, total_tokens, estimated) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id, operation_key) DO NOTHING",
            (
                context.workspace_id,
                context.session_id,
                context.run_id,
                usage.operation_key,
                usage.input_tokens,
                usage.output_tokens,
                usage.total_tokens,
                int(usage.estimated),
            ),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def ensure_title(self, context, candidate: str) -> bool:
        cursor = self._connection.execute(
            "UPDATE agent_sessions SET title = ?, title_source = 'generated', "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND title_source = 'placeholder'",
            (candidate, context.session_id),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def observe_progress(self, context, fingerprint: str) -> int:
        self._connection.execute(
            "INSERT INTO runtime_guard_observations(run_id, fingerprint) VALUES (?, ?)",
            (context.run_id, fingerprint),
        )
        self._connection.commit()
        return self._connection.execute(
            "SELECT COUNT(*) FROM runtime_guard_observations "
            "WHERE run_id = ? AND fingerprint = ?",
            (context.run_id, fingerprint),
        ).fetchone()[0]

    def warning(self, context, code: str) -> None:
        self._connection.execute(
            "INSERT INTO runtime_warnings(session_id, run_id, code) VALUES (?, ?, ?)",
            (context.session_id, context.run_id, code),
        )
        self._connection.commit()

    def mark_context_compacted(self, context) -> bool:
        cursor = self._connection.execute(
            "UPDATE agent_sessions SET summary = 'context_compacted', "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND summary IS NULL",
            (context.session_id,),
        )
        self._connection.commit()
        return cursor.rowcount == 1


@dataclass(slots=True)
class WorkspaceRuntime:
    workspace_id: str
    root: Path
    connection: sqlite3.Connection
    repository: ProductRepository
    sessions: AgentSessionService
    executions: AgentExecutionService
    events: ProductEventStream
    actions: PendingActionRepository
    hitl: HitlService
    drafts: KnowledgeDraftService
    publications: PublicationService
    review: ReviewApplication

    @classmethod
    def create(
        cls,
        *,
        workspace_id: str,
        root: Path,
        model_bindings: Callable[[], Mapping[str, str]],
        graph_factory: GraphFactory,
        observability,
        validate_review_model: Callable[[str, str], None],
    ) -> "WorkspaceRuntime":
        connection = connect_runtime_database(root)
        repository = ProductRepository(connection)
        events = ProductEventStream(repository, workspace_root=root)
        sessions = AgentSessionService(repository, events)
        actions = PendingActionRepository(root)
        drafts = KnowledgeDraftService(root, workspace_id=workspace_id)
        publications = PublicationService(root, workspace_id=workspace_id)
        audit = ToolAuditRepository(root)
        projection = SqliteMiddlewareProjection(connection)
        reviews = ReviewRepository(connection)
        holder: dict[str, HitlService] = {}

        def build(kind: str, **dependencies):
            return graph_factory(
                kind,
                projection=projection,
                audit=audit,
                observability=observability,
                **dependencies,
            )

        async def create_action(command: CreatePendingAction):
            return await holder["hitl"].create_action(command)

        executions = AgentExecutionService(
            workspace_id=workspace_id,
            workspace_root=root,
            repository=repository,
            events=events,
            graph_factory=build,
            model_bindings=model_bindings,
            create_action=create_action,
            create_draft=drafts.create,
            mark_draft_review_pending=drafts.mark_review_pending,
            review_repository=reviews,
            get_draft=drafts.get,
        )
        projection_service = ReviewDomainService(
            repository=reviews,
            selector=QuestionSelector(),
            create_round_runtime=lambda _workspace, _settings: None,  # type: ignore[arg-type]
        )
        handlers = create_default_action_handler_registry(
            knowledge_publish_handler=KnowledgePublishActionHandler(
                drafts=drafts,
                publications=publications,
                event_stream=events,
                after_publication=projection_service.activate_published_draft,
            )
        )
        hitl = HitlService(
            repository=actions,
            handlers=handlers,
            event_stream=events,
            resume_action=executions.resume_approval,
        )
        holder["hitl"] = hitl
        review = ReviewApplication(
            workspace_id=workspace_id,
            workspace_root=root,
            repository=reviews,
            sessions=sessions,
            executions=executions,
            events=events,
            drafts=drafts,
            publications=publications,
            validate_model=validate_review_model,
            actions=actions,
            hitl=hitl,
        )
        return cls(
            workspace_id=workspace_id,
            root=root,
            connection=connection,
            repository=repository,
            sessions=sessions,
            executions=executions,
            events=events,
            actions=actions,
            hitl=hitl,
            drafts=drafts,
            publications=publications,
            review=review,
        )

    async def close(self) -> None:
        await self.executions.close()
        self.connection.close()


class AgentApplication:
    def __init__(
        self,
        *,
        workspace_resolver: Callable[[str], Path],
        workspace_ids: Callable[[], tuple[str, ...]],
        model_bindings: Callable[[str], Mapping[str, str]],
        graph_factory: GraphFactory,
        observability=None,
        observability_flush_timeout_ms: int = 2_000,
        validate_review_model: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self._workspace_resolver = workspace_resolver
        self._workspace_ids = workspace_ids
        self._model_bindings = model_bindings
        self._graph_factory = graph_factory
        self._observability = observability or NoopObservabilitySink()
        self._observability_flush_timeout_ms = observability_flush_timeout_ms
        self._validate_review_model = validate_review_model or (
            lambda _workspace, _model, _effort: None
        )
        self._workspaces: dict[str, WorkspaceRuntime] = {}

    async def create_session(
        self, *, workspace_id: str, kind: str, title: str | None = None
    ) -> SessionRecord:
        return await self._context(workspace_id).sessions.create(
            workspace_id=workspace_id, kind=kind, title=title
        )

    def list_sessions(self, workspace_id: str) -> tuple[SessionRecord, ...]:
        return self._context(workspace_id).sessions.list(workspace_id)

    async def session_detail(self, session_id: str) -> dict[str, Any]:
        context, session = self._locate_session(session_id)
        pending = await context.actions.list_pending(
            session.workspace_id, session_id=session.id
        )
        action = pending[0] if pending else None
        latest = context.repository.latest_execution(session.id)
        return {
            **asdict(session),
            "context_compacted": context.repository.context_compacted(session.id),
            "usage": context.repository.usage(session.id),
            "latest_warning": context.repository.latest_warning(session.id),
            "messages": [asdict(item) for item in context.repository.list_messages(session.id)],
            "latest_execution": None if latest is None else asdict(latest),
            "current_action": (
                None
                if action is None
                else {
                    "id": action.id,
                    "action_type": action.action_type,
                    "preview": action.preview,
                    "status": action.status,
                    "version": action.version,
                }
            ),
        }

    async def start_execution(
        self, session_id: str, *, input: dict[str, Any]
    ) -> ExecutionRecord:
        context, session = self._locate_session(session_id)
        return await context.executions.start(session, input=input)

    async def wait_execution(self, execution_id: str) -> ExecutionRecord:
        context = self._locate_execution(execution_id)
        return await context.executions.wait(execution_id)

    async def cancel_execution(self, execution_id: str) -> ExecutionRecord:
        return await self._locate_execution(execution_id).executions.cancel(execution_id)

    def replay_events(
        self, session_id: str, *, after_id: int | None
    ) -> tuple[EventRecord, ...]:
        context, _session = self._locate_session(session_id)
        return context.repository.list_events(session_id, after_id=after_id)

    async def events(
        self, session_id: str, *, after_id: int | None
    ) -> AsyncIterator[str]:
        context, _session = self._locate_session(session_id)
        async for event in context.events.subscribe(session_id, after_id=after_id):
            yield ": keepalive\n\n" if event is None else encode_sse_event(event)

    async def list_actions(self, workspace_id: str, **filters):
        return await self._context(workspace_id).actions.list_actions(
            workspace_id, **filters
        )

    async def get_action(self, action_id: str):
        context, action = await self._locate_action(action_id)
        del context
        return action

    async def approve_action(self, action_id: str, command: ResolveActionCommand):
        context, _action = await self._locate_action(action_id)
        return await context.hitl.approve(action_id, command)

    async def reject_action(self, action_id: str, command: ResolveActionCommand):
        context, _action = await self._locate_action(action_id)
        return await context.hitl.reject(action_id, command)

    async def request_draft_publication(self, draft_id: str) -> ExecutionRecord:
        context, draft = await self._locate_draft(draft_id)
        session = await context.sessions.create(
            workspace_id=context.workspace_id,
            kind="knowledge.publish",
            title=f"知识发布：{draft.title}",
        )
        execution = await context.executions.start(
            session,
            input={
                "draftId": draft.id,
                "draftVersion": draft.version,
                "contentHash": draft.content_hash,
                "title": draft.title,
                "markdown": draft.markdown,
            },
        )
        await context.drafts.mark_review_pending(
            draft.id,
            expected_version=draft.version,
            expected_hash=draft.content_hash,
        )
        return execution

    async def list_drafts(self, workspace_id: str):
        context = self._context(workspace_id)
        return tuple([await self._draft_resource(context, item) for item in await context.drafts.list()])

    async def get_draft(self, draft_id: str):
        context, draft = await self._locate_draft(draft_id)
        return await self._draft_resource(context, draft)

    async def update_draft(self, draft_id: str, command: UpdateDraftCommand):
        context, _draft = await self._locate_draft(draft_id)
        return await self._draft_resource(context, await context.drafts.update(draft_id, command))

    def review(self, workspace_id: str) -> ReviewApplication:
        return self._context(workspace_id).review

    def locate_review_round(self, round_id: str) -> ReviewApplication:
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            try:
                context.review.repository.get_round(round_id)
                return context.review
            except Exception as error:
                if error.__class__.__name__ != "ReviewRoundNotFoundError":
                    raise
        raise ProductRecordNotFoundError("复习轮次不存在")

    def locate_review_candidate(self, candidate_id: str) -> ReviewApplication:
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            try:
                context.review.repository.get_candidate(candidate_id)
                return context.review
            except LookupError:
                continue
        raise ProductRecordNotFoundError("题目候选不存在")

    def locate_review_batch(self, batch_id: str) -> ReviewApplication:
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            try:
                context.review.repository.get_batch(batch_id)
                return context.review
            except LookupError:
                continue
        raise ProductRecordNotFoundError("题目批次不存在")

    def locate_review_session(self, session_id: str) -> ReviewApplication:
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            try:
                context.review.repository.get_curation_session(session_id)
                return context.review
            except LookupError:
                continue
        raise ProductRecordNotFoundError("题库整理会话不存在")

    async def recover(self) -> tuple[str, ...]:
        recovered = []
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            recovered.extend(context.executions.recover())
            context.review.repository.reconcile_abandoned_work()
            await context.executions.resume_evaluating_attempts()
            await context.hitl.reconcile()
        return tuple(recovered)

    async def close(self) -> None:
        for context in tuple(self._workspaces.values()):
            await context.close()
        self._workspaces.clear()
        self._observability.force_flush(self._observability_flush_timeout_ms)

    def _context(self, workspace_id: str) -> WorkspaceRuntime:
        if workspace_id in self._workspaces:
            return self._workspaces[workspace_id]
        root = self._workspace_resolver(workspace_id)
        if not root.is_dir():
            raise ProductRecordNotFoundError("Workspace 不存在或不可用")
        context = WorkspaceRuntime.create(
            workspace_id=workspace_id,
            root=root,
            model_bindings=lambda: self._model_bindings(workspace_id),
            graph_factory=self._graph_factory,
            observability=self._observability,
            validate_review_model=lambda model_id, effort: self._validate_review_model(
                workspace_id, model_id, effort
            ),
        )
        self._workspaces[workspace_id] = context
        return context

    def _locate_session(self, session_id: str) -> tuple[WorkspaceRuntime, SessionRecord]:
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            try:
                return context, context.repository.get_session(session_id)
            except ProductRecordNotFoundError:
                continue
        raise ProductRecordNotFoundError("Agent Session 不存在")

    def _locate_execution(self, execution_id: str) -> WorkspaceRuntime:
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            try:
                context.repository.get_execution(execution_id)
                return context
            except ProductRecordNotFoundError:
                continue
        raise ProductRecordNotFoundError("Agent Execution 不存在")

    async def _locate_action(self, action_id: str):
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            try:
                return context, await context.actions.get(action_id)
            except Exception as error:
                if error.__class__.__name__ != "PendingActionNotFoundError":
                    raise
        raise PendingActionNotFoundError(action_id)

    async def _locate_draft(self, draft_id: str) -> tuple[WorkspaceRuntime, KnowledgeDraftRecord]:
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            try:
                return context, await context.drafts.get(draft_id)
            except Exception as error:
                if error.__class__.__name__ != "DraftNotFoundError":
                    raise
        raise DraftNotFoundError(draft_id)

    @staticmethod
    async def _draft_resource(context: WorkspaceRuntime, draft: KnowledgeDraftRecord):
        publication = await context.publications.latest_for_draft(draft.id)
        return {
            **asdict(draft),
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

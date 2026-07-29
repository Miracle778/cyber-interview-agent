from __future__ import annotations

import asyncio
import re
import sqlite3
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.application.execution_service import AgentExecutionService, GraphFactory
from app.agents.agent_factory import ModelOverride
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
from app.graphs.publication import publication_action_key
from app.hitl.models import (
    CreatePendingAction,
    PendingActionRecord,
    ResolveActionCommand,
)
from app.hitl.repository import PendingActionNotFoundError, PendingActionRepository
from app.hitl.service import HitlService
from app.infrastructure.runtime_database import (
    ThreadLocalRuntimeConnection,
    connect_thread_local_runtime_database,
)
from app.infrastructure.observability import NoopObservabilitySink
from app.knowledge.drafts import (
    DraftNotEditableError,
    DraftNotFoundError,
    KnowledgeDraftRecord,
    KnowledgeDraftService,
    UpdateDraftCommand,
)
from app.knowledge.publication import PublicationService
from app.knowledge.publication_handler import KnowledgePublishActionHandler
from app.knowledge.workspace_layout import initialize_knowledge_artifacts
from app.middleware.usage_projection_middleware import ContextUsageProjection, UsageProjection
from app.review.application import ReviewApplication
from app.review.service import ReviewDomainService
from app.review.selector import QuestionSelector
from app.review.repository import ReviewRepository
from app.tools.audit import ToolAuditRepository
from app.agents.context import AgentContext
from app.diagnostics.agent_trace import AgentTraceWriter, initialize_agent_trace_directory
from app.profile.repository import ProfileRepository
from app.profile.service import ProfileService
from app.profile.storage import MaterialStorage
from app.job_targets.repository import JobTargetRepository
from app.job_targets.service import JobTargetService
from app.job_targets.application import JobTargetApplication
from app.observability.indexer import TraceLedgerIndexer
from app.observability.repository import TraceIndexRepository
from app.observability.service import AgentObservabilityService


def _compact_session_title(content: str) -> str:
    text = re.sub(r"\s+", " ", content).strip()
    intent_titles = (
        ("自我介绍", "生成一分钟自我介绍"),
        ("简历", "完整", "检查简历信息完整性"),
        ("冲突", "检查资料冲突"),
        ("后端开发经历", "整理后端开发经历"),
        ("项目经历", "整理项目经历"),
    )
    for rule in intent_titles:
        *keywords, title = rule
        if all(keyword in text for keyword in keywords):
            return title
    text = re.sub(r"^(?:请|麻烦|帮我|请你)\s*", "", text)
    text = re.sub(r"^基于[^，。！？]{0,40}[，,]\s*", "", text)
    first_clause = re.split(r"[。！？；;\n]", text, maxsplit=1)[0].strip(" ，,：:")
    if not first_clause:
        return "画像资料对话"
    return first_clause if len(first_clause) <= 28 else f"{first_clause[:27]}…"


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

    def record_context_usage(
        self, context, usage: ContextUsageProjection
    ) -> bool:
        self._connection.execute(
            "INSERT INTO agent_context_usage "
            "(session_id, run_id, current_tokens, threshold_tokens, estimated) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET "
            "run_id = excluded.run_id, current_tokens = excluded.current_tokens, "
            "threshold_tokens = excluded.threshold_tokens, estimated = excluded.estimated, "
            "updated_at = CURRENT_TIMESTAMP",
            (
                context.session_id,
                context.run_id,
                usage.current_tokens,
                usage.threshold_tokens,
                int(usage.estimated),
            ),
        )
        self._connection.commit()
        return True

    def ensure_title(self, context, candidate: str) -> bool:
        user_message = self._connection.execute(
            "SELECT content FROM agent_messages "
            "WHERE session_id = ? AND role = 'user' "
            "AND resolution_status IN ('active', 'unresolved') "
            "ORDER BY created_at, rowid LIMIT 1",
            (context.session_id,),
        ).fetchone()
        title = candidate
        if user_message is not None:
            title = _compact_session_title(user_message["content"])
        cursor = self._connection.execute(
            "UPDATE agent_sessions SET title = ?, title_source = 'generated', "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND "
            "(title_source = 'placeholder' OR "
            "(graph_id = 'profile.manage' AND title LIKE '当前画像快照：%'))",
            (title, context.session_id),
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


def build_curation_command_context(
    *,
    workspace_id: str,
    workspace_root: Path,
    session_id: str,
    run_id: str,
    idempotency_key: str,
    invocation_id: str,
) -> AgentContext:
    return AgentContext(
        workspace_id=workspace_id,
        workspace_root=workspace_root,
        session_id=session_id,
        run_id=run_id,
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
        progress_scope=("curation_command", idempotency_key, invocation_id),
    )


@dataclass(slots=True)
class WorkspaceRuntime:
    workspace_id: str
    root: Path
    connection: ThreadLocalRuntimeConnection
    repository: ProductRepository
    sessions: AgentSessionService
    executions: AgentExecutionService
    events: ProductEventStream
    actions: PendingActionRepository
    hitl: HitlService
    drafts: KnowledgeDraftService
    publications: PublicationService
    review: ReviewApplication
    profile: ProfileService
    job_targets: JobTargetService
    job_training: JobTargetApplication
    agent_observability: AgentObservabilityService
    publication_locks: dict[str, asyncio.Lock] = field(
        default_factory=dict, repr=False
    )

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
        advanced_diagnostics_enabled: Callable[[], bool],
    ) -> "WorkspaceRuntime":
        connection = connect_thread_local_runtime_database(root)
        initialize_agent_trace_directory(root)
        repository = ProductRepository(connection)
        trace_repository = TraceIndexRepository(connection)
        trace_indexer = TraceLedgerIndexer(
            workspace_id=workspace_id,
            workspace_root=root,
            repository=trace_repository,
        )
        agent_observability = AgentObservabilityService(
            workspace_id=workspace_id,
            workspace_root=root,
            connection=connection,
            trace_repository=trace_repository,
            indexer=trace_indexer,
            advanced_diagnostics_enabled=advanced_diagnostics_enabled,
        )
        agent_observability.sync()
        events = ProductEventStream(repository, workspace_root=root)
        sessions = AgentSessionService(repository, events)
        actions = PendingActionRepository(root)
        drafts = KnowledgeDraftService(root, workspace_id=workspace_id)
        publications = PublicationService(root, workspace_id=workspace_id)
        initialize_knowledge_artifacts(root, domain="profile")
        profile_repository = ProfileRepository(connection)
        profile_storage = MaterialStorage(root)
        audit = ToolAuditRepository(root)
        projection = SqliteMiddlewareProjection(connection)
        reviews = ReviewRepository(
            connection,
            validate_curation_artifact=drafts.validate_curation_artifact,
        )
        holder: dict[str, HitlService] = {}
        trace_writer = getattr(graph_factory, "trace_writer", None) or AgentTraceWriter()

        def build(kind: str, **dependencies):
            return graph_factory(
                kind,
                projection=projection,
                audit=audit,
                observability=observability,
                publish_event=events.publish,
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
            update_draft=drafts.update,
            profile_repository=profile_repository,
            profile_storage=profile_storage,
            trace_writer=trace_writer,
            trace_warning=projection.warning,
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
                after_rejection=projection_service.reject_candidate_draft,
            )
        )
        hitl = HitlService(
            repository=actions,
            handlers=handlers,
            event_stream=events,
            resume_action=executions.resume_approval,
        )
        holder["hitl"] = hitl
        command_agents_factory = getattr(
            graph_factory, "create_curation_command_agents", None
        )
        configured_model_bindings = model_bindings()
        command_agents_available = (
            command_agents_factory is not None
            and {
                "question_generation",
                "report_summarization",
            }.issubset(configured_model_bindings)
        )
        command_agents = (
            None
            if not command_agents_available
            else command_agents_factory(
                model_bindings=configured_model_bindings,
                projection=projection,
                audit=audit,
                observability=observability,
                publish_event=events.publish,
            )
        )

        job_agents_factory = getattr(
            graph_factory, "create_job_target_agents", None
        )
        review_agents_factory = getattr(
            graph_factory, "create_review_round_agents", None
        )
        job_agents_available = (
            job_agents_factory is not None
            and {
                "job_analysis",
                "project_deep_dive",
                "report_summarization",
            }.issubset(configured_model_bindings)
        )
        job_agents = (
            None
            if not job_agents_available
            else job_agents_factory(
                model_bindings=configured_model_bindings,
                projection=projection,
                audit=audit,
                observability=observability,
                publish_event=events.publish,
            )
        )

        def create_job_agents(override: ModelOverride):
            if job_agents_factory is None:
                raise RuntimeError("job target agents are not configured")
            return job_agents_factory(
                model_bindings=configured_model_bindings,
                projection=projection,
                audit=audit,
                observability=observability,
                publish_event=events.publish,
                interaction_override=override,
            )

        def create_command_agents(
            override: ModelOverride,
        ):
            if command_agents_factory is None:
                raise RuntimeError("curation command agents are not configured")
            return command_agents_factory(
                model_bindings=configured_model_bindings,
                projection=projection,
                audit=audit,
                observability=observability,
                publish_event=events.publish,
                interaction_override=override,
            )

        def curation_context_factory(**values):
            return build_curation_command_context(
                workspace_id=workspace_id,
                workspace_root=root,
                **values,
            )

        async def classify_review_turn_with_model(
            *,
            question,
            message: str,
            provider_model_id: str,
            reasoning_effort: str,
            session_id: str,
            execution_id: str | None,
        ):
            if review_agents_factory is None:
                return "answer"
            agents = review_agents_factory(
                model_bindings=configured_model_bindings,
                projection=projection,
                audit=audit,
                observability=observability,
                publish_event=events.publish,
                interaction_override=ModelOverride(
                    provider_model_id, reasoning_effort
                ),
            )
            result = await agents.classify_turn(
                question=question,
                message=message,
                context=AgentContext(
                    workspace_id=workspace_id,
                    workspace_root=root,
                    session_id=session_id,
                    run_id=execution_id or str(uuid4()),
                    allowed_tools=frozenset(),
                    allowed_scopes=frozenset(),
                    progress_scope=("review_turn_classification",),
                ),
                config={"configurable": {"thread_id": session_id}},
            )
            return result.intent

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
            curation_command_agents=command_agents,
            curation_command_agents_factory=(
                create_command_agents
                if command_agents_factory is not None
                and "report_summarization" in configured_model_bindings
                else None
            ),
            curation_context_projection=projection,
            curation_context_factory=curation_context_factory,
            review_turn_classifier=(
                classify_review_turn_with_model
                if review_agents_factory is not None
                else None
            ),
        )
        profile = ProfileService(
            workspace_id=workspace_id,
            root=root,
            repository=profile_repository,
            storage=profile_storage,
            product_repository=repository,
            run_ingest=lambda execution: executions.run_prepared(
                execution, graph_input=execution.input
            ),
            publish_event=lambda session_id, execution_id, event_type, payload: repository.append_event(
                session_id, execution_id, event_type, payload
            ),
        )
        job_targets = JobTargetService(
            workspace_id=workspace_id,
            repository=JobTargetRepository(connection),
            profile_repository=profile_repository,
            product_repository=repository,
        )
        job_training = JobTargetApplication(
            workspace_id=workspace_id,
            service=job_targets,
            repository=job_targets.repository,
            profile=profile,
            sessions=sessions,
            executions=executions,
            product_repository=repository,
            agents=job_agents,
            agents_factory=(
                create_job_agents if job_agents_available else None
            ),
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
            profile=profile,
            job_targets=job_targets,
            job_training=job_training,
            agent_observability=agent_observability,
        )

    async def close(self) -> None:
        await self.executions.close()
        self.connection.close()


@dataclass(frozen=True, slots=True)
class DraftPublicationRequest:
    execution: ExecutionRecord
    action: PendingActionRecord
    reused: bool


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
        advanced_diagnostics_enabled: Callable[[], bool] | None = None,
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
        self._advanced_diagnostics_enabled = (
            advanced_diagnostics_enabled or (lambda: False)
        )
        self._workspaces: dict[str, WorkspaceRuntime] = {}

    async def create_session(
        self, *, workspace_id: str, kind: str, title: str | None = None
    ) -> SessionRecord:
        if kind in {"profile.ingest", "profile.assess"}:
            raise ValueError("该画像系统会话不能由用户创建")
        return await self._context(workspace_id).sessions.create(
            workspace_id=workspace_id, kind=kind, title=title
        )

    async def create_profile_session(
        self, *, workspace_id: str, title: str | None = None
    ) -> SessionRecord:
        return await self._context(workspace_id).sessions.create(
            workspace_id=workspace_id,
            kind="profile.manage",
            title=title,
        )

    def list_profile_sessions(
        self, workspace_id: str, *, deleted_only: bool = False
    ) -> tuple[SessionRecord, ...]:
        return tuple(
            session
            for session in self._context(workspace_id).sessions.list(
                workspace_id, deleted_only=deleted_only
            )
            if session.kind == "profile.manage"
        )

    def list_sessions(self, workspace_id: str) -> tuple[SessionRecord, ...]:
        return self._context(workspace_id).sessions.list(workspace_id)

    def delete_session(self, session_id: str, *, hard: bool = False) -> None:
        context, session = self._locate_session_including_deleted(session_id)
        context.sessions.delete(session.id, hard=hard)

    def restore_session(self, session_id: str) -> SessionRecord:
        context, session = self._locate_session_including_deleted(session_id)
        return context.sessions.restore(session.id)

    async def rename_session(
        self, session_id: str, *, workspace_id: str, title: str
    ) -> SessionRecord:
        context, session = self._locate_session(session_id)
        if session.workspace_id != workspace_id:
            raise ProductRecordNotFoundError("Agent Session 不存在")
        return await context.sessions.rename(session.id, title)

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
            "context_usage": context.repository.context_usage(session.id),
            "usage": context.repository.usage(session.id),
            "latest_warning": context.repository.latest_warning(session.id),
            "messages": [asdict(item) for item in context.repository.list_messages(session.id)],
            "executions": [asdict(item) for item in context.repository.list_executions(session.id)],
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
        self,
        session_id: str,
        *,
        input: dict[str, Any],
        configuration: dict[str, Any] | None = None,
    ) -> ExecutionRecord:
        context, session = self._locate_session(session_id)
        if configuration and configuration.get("providerModelId"):
            self._validate_review_model(
                session.workspace_id,
                str(configuration["providerModelId"]),
                str(configuration.get("reasoningEffort", "none")),
            )
        return await context.executions.start(
            session, input=input, configuration=configuration
        )

    async def retry_execution(
        self,
        execution_id: str,
        *,
        replacement_message: str | None = None,
    ) -> ExecutionRecord:
        context = self._locate_execution(execution_id)
        previous = context.repository.get_execution(execution_id)
        if previous.status not in {"failed", "interrupted", "cancelled"}:
            raise ValueError("只有失败或已停止的执行可以重试")
        session = context.repository.get_session(previous.session_id)
        message = self._execution_input_message(context.repository, previous)
        retry_input = previous.input
        input_message_id = message.id
        if replacement_message is None:
            if message.resolution_status == "unresolved":
                context.repository.resolve_message(
                    message.id, expected=("unresolved",), target="active"
                )
        else:
            if message.resolution_status not in {"active", "unresolved"}:
                raise ValueError("这条消息已经处理，不能再编辑重试")
            replacement = context.repository.append_user_message(
                session.id,
                content=replacement_message,
                replaces_message_id=message.id,
            )
            retry_input = {**previous.input, "message": replacement.content}
            for alias in ("text", "userAnswer", "user_answer"):
                if alias in retry_input:
                    retry_input[alias] = replacement.content
            input_message_id = replacement.id
        configuration = {
            "providerModelId": previous.configuration.provider_model_id,
            "reasoningEffort": previous.configuration.reasoning_effort,
        }
        retry = await context.executions.prepare_for_message(
            session,
            input_message_id=input_message_id,
            input=retry_input,
            retry_of_execution_id=previous.id,
            configuration=configuration,
        )
        context.executions.run_prepared(retry, graph_input=retry_input)
        return retry

    def abandon_execution(self, execution_id: str):
        context = self._locate_execution(execution_id)
        execution = context.repository.get_execution(execution_id)
        if execution.status not in {"failed", "interrupted", "cancelled"}:
            raise ValueError("只有失败或已停止的执行可以放弃")
        message = self._execution_input_message(context.repository, execution)
        if message.resolution_status == "abandoned":
            return message
        if message.resolution_status not in {"active", "unresolved"}:
            raise ValueError("这条消息已经处理")
        return context.repository.resolve_message(
            message.id,
            expected=(message.resolution_status,),
            target="abandoned",
        )

    @staticmethod
    def _execution_input_message(repository, execution: ExecutionRecord):
        messages = repository.list_messages(execution.session_id)
        if execution.input_message_id is not None:
            message = next(
                (
                    item
                    for item in messages
                    if item.id == execution.input_message_id
                ),
                None,
            )
        else:
            message = next(
                (
                    item
                    for item in messages
                    if item.role == "user"
                    and item.execution_id == execution.id
                ),
                None,
            )
        if message is None:
            raise ProductRecordNotFoundError("未找到本次执行对应的用户消息")
        return message

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

    async def request_draft_publication(
        self, draft_id: str
    ) -> DraftPublicationRequest:
        context, draft = await self._locate_draft(draft_id)
        lock = context.publication_locks.setdefault(draft.id, asyncio.Lock())
        async with lock:
            # Re-read inside the lock so concurrent callers use the same version/hash.
            draft = await context.drafts.get(draft.id)
            if draft.status == "superseded":
                raise DraftNotEditableError(
                    f"draft {draft.id!r} is superseded and cannot be published"
                )
            action_key = publication_action_key(
                draft_id=draft.id,
                draft_version=draft.version,
                content_hash=draft.content_hash,
            )
            existing = await context.actions.get_by_idempotency_key(action_key)
            if existing is not None and existing.status == "pending":
                return DraftPublicationRequest(
                    execution=context.executions.execution(existing.run_id),
                    action=existing,
                    reused=True,
                )

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
            execution = await context.executions.wait(execution.id)
            action = await context.actions.get_by_idempotency_key(action_key)
            if (
                execution.status != "waiting_for_approval"
                or action is None
                or action.status != "pending"
                or action.run_id != execution.id
            ):
                raise RuntimeError("发布审批动作创建失败")
            await context.drafts.mark_review_pending(
                draft.id,
                expected_version=draft.version,
                expected_hash=draft.content_hash,
            )
            return DraftPublicationRequest(
                execution=execution,
                action=action,
                reused=False,
            )

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

    def profile(self, workspace_id: str) -> ProfileService:
        return self._context(workspace_id).profile

    def job_targets(self, workspace_id: str) -> JobTargetService:
        return self._context(workspace_id).job_targets

    def job_training(self, workspace_id: str) -> JobTargetApplication:
        return self._context(workspace_id).job_training

    def agent_observability(
        self, workspace_id: str
    ) -> AgentObservabilityService:
        return self._context(workspace_id).agent_observability

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

    def locate_curation_command(self, command_id: str) -> ReviewApplication:
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            try:
                context.review.repository.get_curation_command_receipt(
                    command_id
                )
                return context.review
            except LookupError:
                continue
        raise ProductRecordNotFoundError("题库整理命令不存在")

    def locate_bulk_publication(
        self, operation_id: str
    ) -> ReviewApplication:
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            try:
                context.review.repository.get_bulk_publication(operation_id)
                return context.review
            except LookupError:
                continue
        raise ProductRecordNotFoundError("批量发布操作不存在")

    async def recover(self) -> tuple[str, ...]:
        recovered = []
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            interrupted_executions = context.executions.recover()
            recovered.extend(interrupted_executions)
            # Domain reconciliation observes durable interrupted executions;
            # it never schedules Provider work without an explicit resume.
            context.review.repository.reconcile_abandoned_work()
            await context.drafts.reconcile_curation_staging()
            await context.publications.recover_transient_runs()
            await context.executions.resume_evaluating_attempts()
            await context.hitl.reconcile()
        return tuple(recovered)

    async def close(self) -> None:
        for context in tuple(self._workspaces.values()):
            await context.close()
        self._workspaces.clear()
        self._observability.force_flush(self._observability_flush_timeout_ms)

    async def unload_workspace(self, workspace_id: str) -> None:
        context = self._workspaces.pop(workspace_id, None)
        if context is not None:
            await context.close()

    def _context(self, workspace_id: str) -> WorkspaceRuntime:
        if workspace_id not in self._workspace_ids():
            raise ProductRecordNotFoundError("Workspace 不存在或不可用")
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
            advanced_diagnostics_enabled=self._advanced_diagnostics_enabled,
        )
        self._workspaces[workspace_id] = context
        return context

    def _locate_session(self, session_id: str) -> tuple[WorkspaceRuntime, SessionRecord]:
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            try:
                session = context.repository.get_session(session_id)
            except ProductRecordNotFoundError:
                continue
            # Generic API routes must not expose hidden profile.ingest system
            # sessions; internal Runtime services access them via the repository.
            if session.visibility == "system":
                continue
            return context, session
        raise ProductRecordNotFoundError("Agent Session 不存在")

    def _locate_session_including_deleted(
        self, session_id: str
    ) -> tuple[WorkspaceRuntime, SessionRecord]:
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            try:
                session = context.repository.get_session(
                    session_id, include_deleted=True
                )
                if session.visibility == "system":
                    continue
                return context, session
            except ProductRecordNotFoundError:
                continue
        raise ProductRecordNotFoundError("Agent Session 不存在")

    def _locate_execution(self, execution_id: str) -> WorkspaceRuntime:
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            try:
                execution = context.repository.get_execution(execution_id)
                session = context.repository.get_session(execution.session_id)
                if session.visibility == "system":
                    continue
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

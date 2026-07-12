import sqlite3
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.db.runtime_database import connect_runtime_database
from app.hitl.handlers import create_default_action_handler_registry
from app.hitl.models import (
    CreatePendingAction,
    PendingActionRecord,
    ResolveActionCommand,
)
from app.hitl.repository import PendingActionNotFoundError, PendingActionRepository
from app.hitl.service import HitlService
from app.knowledge.drafts import (
    DraftNotFoundError,
    KnowledgeDraftRecord,
    KnowledgeDraftService,
    UpdateDraftCommand,
)
from app.knowledge.publication import PublicationService
from app.knowledge.publication_handler import KnowledgePublishActionHandler
from app.providers.chat_gateway import ChatModelGateway, ResolvedModelBinding
from app.runtime.checkpoints import RuntimeCheckpointer
from app.runtime.event_stream import EventStream, encode_sse_event
from app.runtime.graph_registry import GraphRegistry, GraphVersionNotFoundError
from app.runtime.models import RunRecord, SessionRecord
from app.runtime.repository import RuntimeRecordNotFoundError, RuntimeRepository
from app.runtime.run_manager import RunManager
from app.services.workspace import WorkspaceError
from app.tools.audit import ToolAuditRepository
from app.tools.defaults import create_default_tool_registry
from app.tools.registry import ToolRegistry


@dataclass(slots=True)
class _WorkspaceRuntime:
    connection: sqlite3.Connection
    repository: RuntimeRepository
    event_stream: EventStream
    manager: RunManager
    hitl_repository: PendingActionRepository
    hitl_service: HitlService
    draft_service: KnowledgeDraftService
    publication_service: PublicationService


class AgentRuntime:
    def __init__(
        self,
        *,
        graph_registry: GraphRegistry,
        workspace_resolver: Callable[[str], Path],
        model_binding_resolver: Callable[[str], dict[str, str]],
        workspace_ids: Callable[[], tuple[str, ...]],
        tool_registry: ToolRegistry | None = None,
        chat_gateway: ChatModelGateway | None = None,
        resolve_model_binding: Callable[
            [str, str], ResolvedModelBinding
        ] | None = None,
    ) -> None:
        self._graph_registry = graph_registry
        self._workspace_resolver = workspace_resolver
        self._model_binding_resolver = model_binding_resolver
        self._workspace_ids = workspace_ids
        self._tool_registry = tool_registry or create_default_tool_registry()
        self._chat_gateway = chat_gateway
        self._resolve_model_binding = resolve_model_binding
        self._workspaces: dict[str, _WorkspaceRuntime] = {}

    async def create_session(
        self,
        *,
        workspace_id: str,
        graph_id: str,
        graph_version: int,
        title: str,
    ) -> SessionRecord:
        self._graph_registry.get(graph_id, graph_version)
        context = self._context(workspace_id)
        session = context.repository.create_session(
            workspace_id=workspace_id,
            graph_id=graph_id,
            graph_version=graph_version,
            title=title,
        )
        await context.event_stream.publish(
            session.id, None, "session.created", {"title": title}
        )
        return session

    def list_sessions(self, workspace_id: str) -> tuple[SessionRecord, ...]:
        return self._context(workspace_id).repository.list_sessions(workspace_id)

    async def session_detail(self, session_id: str) -> dict[str, Any]:
        context, session = self._locate_session(session_id)
        pending = await context.hitl_repository.list_pending(
            session.workspace_id, session_id=session.id
        )
        pending_action = pending[0] if pending else None
        return {
            **self._session_resource(session),
            "messages": [
                {
                    "id": item.id,
                    "runId": item.run_id,
                    "role": item.role,
                    "content": item.content,
                    "createdAt": item.created_at,
                }
                for item in context.repository.list_messages(session.id)
            ],
            "latestRun": self._run_resource(
                context.repository.latest_run(session.id)
            ),
            "pendingAction": (
                None
                if pending_action is None
                else {
                    "id": pending_action.id,
                    "actionType": pending_action.action_type,
                    "preview": pending_action.preview,
                    "status": pending_action.status,
                    "version": pending_action.version,
                }
            ),
        }

    def ensure_session(self, session_id: str) -> None:
        self._locate_session(session_id)

    async def start_run(
        self, session_id: str, *, input: dict[str, Any]
    ) -> RunRecord:
        context, session = self._locate_session(session_id)
        try:
            self._graph_registry.get(session.graph_id, session.graph_version)
        except GraphVersionNotFoundError:
            context.repository.set_session_status(
                session.id, "migration_required"
            )
            raise
        bindings = self._model_binding_resolver(session.workspace_id)
        return await context.manager.start(
            session.id, input=input, model_bindings=bindings
        )

    async def resume_run(self, run_id: str) -> RunRecord:
        context = self._locate_run(run_id)
        return await context.manager.resume(run_id)

    async def cancel_run(self, run_id: str) -> RunRecord:
        context = self._locate_run(run_id)
        return await context.manager.cancel(run_id)

    async def wait_run(self, run_id: str) -> RunRecord:
        return await self._locate_run(run_id).manager.wait(run_id)

    async def request_draft_publication(self, draft_id: str) -> RunRecord:
        context, draft = await self._locate_draft(draft_id)
        for action in await context.hitl_repository.list_pending(
            draft.workspace_id
        ):
            if (
                action.action_type == "knowledge.publish"
                and action.payload.get("draftId") == draft.id
                and action.payload.get("draftVersion") == draft.version
                and action.payload.get("contentHash") == draft.content_hash
            ):
                run = context.repository.get_run(action.run_id)
                if run.status == "waiting_for_approval":
                    await context.draft_service.mark_review_pending(
                        draft.id,
                        expected_version=draft.version,
                        expected_hash=draft.content_hash,
                    )
                    return run
        session = await self.create_session(
            workspace_id=draft.workspace_id,
            graph_id="knowledge.publish",
            graph_version=1,
            title=f"知识发布：{draft.title}",
        )
        run = await context.manager.start(
            session.id,
            input={
                "draftId": draft.id,
                "draftVersion": draft.version,
                "contentHash": draft.content_hash,
                "title": draft.title,
                "markdown": draft.markdown,
            },
            model_bindings=self._model_binding_resolver(draft.workspace_id),
        )
        try:
            await context.draft_service.mark_review_pending(
                draft.id,
                expected_version=draft.version,
                expected_hash=draft.content_hash,
            )
        except Exception:
            await context.manager.cancel(run.id)
            raise
        return run

    async def list_drafts(
        self, workspace_id: str
    ) -> tuple[dict[str, Any], ...]:
        context = self._context(workspace_id)
        drafts = await context.draft_service.list()
        return tuple(
            [await self._draft_resource(context, draft) for draft in drafts]
        )

    async def get_draft(self, draft_id: str) -> dict[str, Any]:
        context, draft = await self._locate_draft(draft_id)
        return await self._draft_resource(context, draft)

    async def update_draft(
        self, draft_id: str, command: UpdateDraftCommand
    ) -> dict[str, Any]:
        context, _draft = await self._locate_draft(draft_id)
        updated = await context.draft_service.update(draft_id, command)
        return await self._draft_resource(context, updated)

    @staticmethod
    async def _draft_resource(
        context: _WorkspaceRuntime, draft: KnowledgeDraftRecord
    ) -> dict[str, Any]:
        publication = await context.publication_service.latest_for_draft(
            draft.id
        )
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

    async def list_actions(
        self,
        workspace_id: str,
        *,
        status: str | None = None,
        session_id: str | None = None,
    ) -> tuple[PendingActionRecord, ...]:
        return await self._context(workspace_id).hitl_repository.list_actions(
            workspace_id, status=status, session_id=session_id
        )

    async def get_action(self, action_id: str) -> PendingActionRecord:
        context, action = await self._locate_action(action_id)
        del context
        return action

    async def approve_action(
        self, action_id: str, command: ResolveActionCommand
    ) -> PendingActionRecord:
        context, _action = await self._locate_action(action_id)
        return await context.hitl_service.approve(action_id, command)

    async def reject_action(
        self, action_id: str, command: ResolveActionCommand
    ) -> PendingActionRecord:
        context, _action = await self._locate_action(action_id)
        return await context.hitl_service.reject(action_id, command)

    async def events(
        self, session_id: str, *, after_id: int | None
    ) -> AsyncIterator[str]:
        context, _session = self._locate_session(session_id)
        async for event in context.event_stream.subscribe(
            session_id, after_id=after_id
        ):
            yield ": keepalive\n\n" if event is None else encode_sse_event(event)

    async def recover_interrupted_runs(self) -> tuple[str, ...]:
        recovered: list[str] = []
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            recovered.extend(await context.manager.recover_interrupted_runs())
            await context.hitl_service.reconcile()
        return tuple(recovered)

    async def close(self) -> None:
        for context in self._workspaces.values():
            await context.manager.shutdown()
            context.connection.close()
        self._workspaces.clear()

    def _context(self, workspace_id: str) -> _WorkspaceRuntime:
        context = self._workspaces.get(workspace_id)
        if context is not None:
            return context
        root = self._workspace_resolver(workspace_id)
        if not root.is_dir():
            raise WorkspaceError("Workspace 路径不可用，请重新关联")
        (root / ".cyber-interview-agent" / "diagnostics").mkdir(
            parents=True, exist_ok=True
        )
        connection = connect_runtime_database(root)
        repository = RuntimeRepository(connection)
        event_stream = EventStream(repository, workspace_root=root)
        hitl_repository = PendingActionRepository(root)
        draft_service = KnowledgeDraftService(root, workspace_id=workspace_id)
        publication_service = PublicationService(
            root, workspace_id=workspace_id
        )
        handlers = create_default_action_handler_registry(
            knowledge_publish_handler=KnowledgePublishActionHandler(
                drafts=draft_service,
                publications=publication_service,
                event_stream=event_stream,
            )
        )
        service_holder: dict[str, HitlService] = {}

        async def request_action(
            request: CreatePendingAction,
        ) -> PendingActionRecord:
            return await service_holder["service"].create_action(request)

        manager = RunManager(
            repository=repository,
            event_stream=event_stream,
            graph_registry=self._graph_registry,
            checkpointer=RuntimeCheckpointer(root),
            workspace_root=root,
            tool_registry=self._tool_registry,
            audit_repository=ToolAuditRepository(root),
            request_action=request_action,
            cancel_pending_action=hitl_repository.cancel_pending_for_run,
            chat_gateway=self._chat_gateway,
            resolve_model_binding=self._resolve_model_binding,
            create_draft=draft_service.create,
            mark_draft_review_pending=draft_service.mark_review_pending,
        )
        hitl_service = HitlService(
            repository=hitl_repository,
            handlers=handlers,
            event_stream=event_stream,
            resume_action=manager.resume_approval,
        )
        context = _WorkspaceRuntime(
            connection=connection,
            repository=repository,
            event_stream=event_stream,
            manager=manager,
            hitl_repository=hitl_repository,
            hitl_service=hitl_service,
            draft_service=draft_service,
            publication_service=publication_service,
        )
        service_holder["service"] = hitl_service
        self._workspaces[workspace_id] = context
        return context

    def _locate_session(
        self, session_id: str
    ) -> tuple[_WorkspaceRuntime, SessionRecord]:
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            try:
                return context, context.repository.get_session(session_id)
            except RuntimeRecordNotFoundError:
                continue
        raise RuntimeRecordNotFoundError(f"session {session_id!r} not found")

    def _locate_run(self, run_id: str) -> _WorkspaceRuntime:
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            try:
                context.repository.get_run(run_id)
                return context
            except RuntimeRecordNotFoundError:
                continue
        raise RuntimeRecordNotFoundError(f"run {run_id!r} not found")

    async def _locate_draft(
        self, draft_id: str
    ) -> tuple[_WorkspaceRuntime, KnowledgeDraftRecord]:
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            try:
                return context, await context.draft_service.get(draft_id)
            except DraftNotFoundError:
                continue
        raise DraftNotFoundError(f"draft {draft_id!r} not found")

    async def _locate_action(
        self, action_id: str
    ) -> tuple[_WorkspaceRuntime, PendingActionRecord]:
        for workspace_id in self._workspace_ids():
            context = self._context(workspace_id)
            try:
                return context, await context.hitl_repository.get(action_id)
            except PendingActionNotFoundError:
                continue
        raise PendingActionNotFoundError(f"action {action_id!r} not found")

    @staticmethod
    def _session_resource(session: SessionRecord) -> dict[str, Any]:
        return {
            "id": session.id,
            "workspaceId": session.workspace_id,
            "graphId": session.graph_id,
            "graphVersion": session.graph_version,
            "title": session.title,
            "status": session.status,
            "createdAt": session.created_at,
            "updatedAt": session.updated_at,
            "lastRunId": session.last_run_id,
        }

    @staticmethod
    def _run_resource(run: RunRecord | None) -> dict[str, Any] | None:
        if run is None:
            return None
        return {
            "id": run.id,
            "sessionId": run.session_id,
            "status": run.status,
            "resumeCount": run.resume_count,
            "errorCode": run.error_code,
            "errorMessage": run.error_message,
            "createdAt": run.created_at,
            "startedAt": run.started_at,
            "finishedAt": run.finished_at,
        }

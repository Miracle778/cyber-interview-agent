from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes_agent import router as agent_router
from app.api.routes_hitl import router as hitl_router
from app.api.routes_knowledge import router as knowledge_router
from app.api.routes_review import router as review_router
from app.api.routes_settings import router as settings_router
from app.core.errors import (
    ErrorResponse,
    ProviderModelInUseError,
    ProviderModelNotFoundError,
    ProviderNotFoundError,
    WorkspaceBindingError,
    WorkspaceNotFoundError,
)
from app.db.app_database import connect_app_database
from app.runtime.default_graphs import create_default_graph_registry
from app.runtime.graph_registry import GraphVersionNotFoundError
from app.hitl.handlers import ActionPayloadValidationError, UnknownActionTypeError
from app.hitl.repository import (
    ActionAlreadyResolvedError,
    ActionIdempotencyConflictError,
    ActionVersionConflictError,
    PendingActionNotFoundError,
)
from app.knowledge.sources import SourceTooLargeError
from app.runtime.repository import RuntimeRecordNotFoundError, SessionBusyError
from app.runtime.service import AgentRuntime
from app.security.workspace_paths import PathPolicyError
from app.services.secrets import SecretStoreUnavailableError
from app.services.workspace import WorkspaceError
from app.services.workspace_service import WorkspaceService
from app.tools.registry import ToolError


@asynccontextmanager
async def lifespan(application: FastAPI):
    connection = connect_app_database()
    runtime: AgentRuntime | None = None
    try:
        workspaces = WorkspaceService(connection)

        def workspace_record(workspace_id: str):
            record = workspaces.workspaces.get(workspace_id)
            if record is None:
                raise WorkspaceNotFoundError(workspace_id)
            return record

        runtime = AgentRuntime(
            graph_registry=create_default_graph_registry(),
            workspace_resolver=lambda workspace_id: Path(
                workspace_record(workspace_id).root_path
            ),
            model_binding_resolver=lambda workspace_id: {
                binding.role: binding.provider_model_id
                for binding in workspaces.workspaces.get_model_bindings(workspace_id)
            },
            workspace_ids=lambda: tuple(
                item.id
                for item in workspaces.workspaces.list_workspaces()
                if item.available and Path(item.root_path).is_dir()
            ),
        )
        application.state.agent_runtime = runtime
        await runtime.recover_interrupted_runs()
        yield
    finally:
        if runtime is not None:
            await runtime.close()
        connection.close()


app = FastAPI(title="Cyber Interview Agent API", lifespan=lifespan)
app.include_router(agent_router)
app.include_router(hitl_router)
app.include_router(settings_router)
app.include_router(knowledge_router)
app.include_router(review_router)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    content = ErrorResponse(code=code, message=message).model_dump()
    return JSONResponse(status_code=status_code, content=content)


@app.exception_handler(ProviderNotFoundError)
async def provider_not_found(
    _request: Request, _error_value: ProviderNotFoundError
) -> JSONResponse:
    return _error(404, "provider_not_found", "Provider 不存在")


@app.exception_handler(ProviderModelNotFoundError)
async def provider_model_not_found(
    _request: Request, _error_value: ProviderModelNotFoundError
) -> JSONResponse:
    return _error(404, "provider_model_not_found", "Provider Model 不存在")


@app.exception_handler(WorkspaceNotFoundError)
async def workspace_not_found(
    _request: Request, _error_value: WorkspaceNotFoundError
) -> JSONResponse:
    return _error(404, "workspace_not_found", "Workspace 不存在")


@app.exception_handler(ProviderModelInUseError)
async def resource_in_use(
    _request: Request, error_value: ProviderModelInUseError
) -> JSONResponse:
    return _error(409, "resource_in_use", str(error_value))


@app.exception_handler(WorkspaceBindingError)
async def invalid_workspace_binding(
    _request: Request, error_value: WorkspaceBindingError
) -> JSONResponse:
    return _error(422, "invalid_model_bindings", str(error_value))


@app.exception_handler(WorkspaceError)
async def invalid_workspace(
    _request: Request, error_value: WorkspaceError
) -> JSONResponse:
    return _error(400, "invalid_workspace", str(error_value))


@app.exception_handler(SecretStoreUnavailableError)
async def secret_store_unavailable(
    _request: Request, _error_value: SecretStoreUnavailableError
) -> JSONResponse:
    return _error(503, "secret_store_unavailable", "系统密钥存储暂不可用")


@app.exception_handler(RuntimeRecordNotFoundError)
async def runtime_record_not_found(
    _request: Request, _error_value: RuntimeRecordNotFoundError
) -> JSONResponse:
    return _error(404, "runtime_record_not_found", "Agent 运行记录不存在")


@app.exception_handler(PendingActionNotFoundError)
async def pending_action_not_found(
    _request: Request, _error_value: PendingActionNotFoundError
) -> JSONResponse:
    return _error(404, "action_not_found", "待确认动作不存在")


@app.exception_handler(ActionVersionConflictError)
async def action_version_conflict(
    _request: Request, _error_value: ActionVersionConflictError
) -> JSONResponse:
    return _error(409, "action_version_conflict", "待确认内容已经更新，请刷新后重试")


@app.exception_handler(ActionAlreadyResolvedError)
async def action_already_resolved(
    _request: Request, _error_value: ActionAlreadyResolvedError
) -> JSONResponse:
    return _error(409, "action_already_resolved", "待确认动作已经处理")


@app.exception_handler(ActionIdempotencyConflictError)
async def action_idempotency_conflict(
    _request: Request, _error_value: ActionIdempotencyConflictError
) -> JSONResponse:
    return _error(409, "action_idempotency_conflict", "本次确认内容与重复请求不一致")


@app.exception_handler(ActionPayloadValidationError)
async def invalid_action_payload(
    _request: Request, _error_value: ActionPayloadValidationError
) -> JSONResponse:
    return _error(422, "invalid_action_payload", "待确认内容不符合编辑要求")


@app.exception_handler(UnknownActionTypeError)
async def unknown_action_type(
    _request: Request, _error_value: UnknownActionTypeError
) -> JSONResponse:
    return _error(422, "unknown_action_type", "待确认动作类型不受支持")


@app.exception_handler(SourceTooLargeError)
async def source_too_large(
    _request: Request, _error_value: SourceTooLargeError
) -> JSONResponse:
    return _error(413, "source_too_large", "上传资料超过 10 MiB 限制")


@app.exception_handler(SessionBusyError)
async def session_busy(
    _request: Request, _error_value: SessionBusyError
) -> JSONResponse:
    return _error(409, "session_busy", "当前 Session 已有运行中的任务")


@app.exception_handler(GraphVersionNotFoundError)
async def graph_migration_required(
    _request: Request, _error_value: GraphVersionNotFoundError
) -> JSONResponse:
    return _error(409, "graph_migration_required", "当前 Agent 版本需要迁移")


@app.exception_handler(PathPolicyError)
async def workspace_path_denied(
    _request: Request, _error_value: PathPolicyError
) -> JSONResponse:
    return _error(400, "workspace_path_denied", "Workspace 路径不在授权范围内")


@app.exception_handler(ToolError)
async def tool_request_rejected(
    _request: Request, error_value: ToolError
) -> JSONResponse:
    return _error(400, error_value.code, "工具调用被安全策略拒绝")

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

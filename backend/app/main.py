from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes_agent import router as agent_router
from app.api.routes_drafts import router as drafts_router
from app.api.routes_hitl import router as hitl_router
from app.api.routes_knowledge import router as knowledge_router
from app.api.routes_profile import router as profile_router
from app.api.routes_job_targets import router as job_targets_router
from app.api.routes_review import router as review_router
from app.api.routes_settings import router as settings_router
from app.agents.agent_factory import AgentFactory
from app.agents.agent_model_resolver import ChatModelResolver, ModelResolutionError
from app.application.graph_factory import ProductionGraphFactory
from app.application.session_service import ProductRecordNotFoundError, SessionBusyError
from app.application.workspace_runtime import AgentApplication
from app.infrastructure.observability import (
    ObservabilitySettings,
    create_observability_sink,
)
from app.core.errors import (
    ErrorResponse,
    ProviderModelInUseError,
    ProviderModelNotFoundError,
    ProviderNotFoundError,
    WorkspaceBindingError,
    WorkspaceNotFoundError,
)
from app.db.app_database import connect_app_database
from app.repositories.provider_repository import ProviderRepository
from app.hitl.handlers import ActionPayloadValidationError, UnknownActionTypeError
from app.hitl.repository import (
    ActionAlreadyResolvedError,
    ActionIdempotencyConflictError,
    ActionVersionConflictError,
    PendingActionNotFoundError,
)
from app.knowledge.sources import SourceTooLargeError
from app.knowledge.atomic_writer import ExternalDocumentChangedError
from app.knowledge.drafts import (
    DraftContentChangedError,
    DraftNotEditableError,
    DraftNotFoundError,
    DraftVersionChangedError,
)
from app.security.workspace_paths import PathPolicyError
from app.review.errors import (
    InputAlreadyResolvedError,
    InsufficientQuestionsError,
    ReviewConflictError,
    ReviewRoundNotFoundError,
)
from app.profile.errors import (
    ProfileActionPlanInvalid,
    ProfileActionPlanNotFound,
    ProfileAssessmentNotFound,
    ProfileClaimNotFound,
    ProfileClaimSelectedForPublication,
    ProfileClaimVersionConflict,
    ProfileDeletionPlanConflict,
    ProfileDeletionPlanNotFound,
    ProfileDocumentNotReady,
    ProfileProposalNotFound,
    ProfilePublicationRevocationUnavailable,
    ProfileDomainError,
    ProfileEncryptedDocument,
    ProfileFileNameInvalid,
    ProfileIdempotencyConflict,
    ProfileIngestBusy,
    ProfileMaterialNotFound,
    ProfileMaterialRoleConflict,
    ProfileMaterialVersionConflict,
    ProfileMaterialVersionNotFound,
    ProfileNoExtractableText,
    ProfileParseError,
    ProfileStorageError,
    ProfileSnapshotChanged,
    ProfileUnsupportedFileType,
    ProfileUploadTooLarge,
    ProfileValueInvalid,
)
from app.job_targets.errors import (
    JobTargetDomainError,
    JobTargetNotFound,
    JobTargetConflict,
    JobTargetBusy,
)
from app.services.secrets import (
    EnvironmentSecretStore,
    KeyringSecretStore,
    SecretStoreUnavailableError,
)
from app.services.workspace import WorkspaceError
from app.services.workspace_service import WorkspaceService


@asynccontextmanager
async def lifespan(application: FastAPI):
    connection = connect_app_database()
    agent_application: AgentApplication | None = None
    try:
        workspaces = WorkspaceService(connection)
        resolved_models = ChatModelResolver(
            ProviderRepository(connection),
            {
                "keyring": KeyringSecretStore(),
                "environment": EnvironmentSecretStore(),
            },
        )

        def workspace_record(workspace_id: str):
            record = workspaces.workspaces.get(workspace_id)
            if record is None:
                raise WorkspaceNotFoundError(workspace_id)
            return record

        observability_settings = ObservabilitySettings.from_env()
        observability = create_observability_sink(
            observability_settings,
            lambda code: logging.getLogger(__name__).warning("runtime warning: %s", code),
        )
        agent_application = AgentApplication(
            workspace_resolver=lambda workspace_id: Path(
                workspace_record(workspace_id).root_path
            ),
            model_bindings=lambda workspace_id: {
                binding.role: binding.provider_model_id
                for binding in workspaces.workspaces.get_model_bindings(workspace_id)
            },
            workspace_ids=lambda: tuple(
                item.id
                for item in workspaces.workspaces.list_workspaces()
                if item.available and Path(item.root_path).is_dir()
            ),
            graph_factory=ProductionGraphFactory(AgentFactory(resolved_models)),
            observability=observability,
            observability_flush_timeout_ms=observability_settings.flush_timeout_ms,
            validate_review_model=lambda _workspace_id, model_id, effort: resolved_models.resolve(
                role="answer_evaluation",
                provider_model_id=model_id,
                reasoning_effort=effort,
            ),
        )
        application.state.agent_application = agent_application
        await agent_application.recover()
        yield
    finally:
        if agent_application is not None:
            await agent_application.close()
        connection.close()


app = FastAPI(title="Cyber Interview Agent API", lifespan=lifespan)
app.include_router(agent_router)
app.include_router(hitl_router)
app.include_router(settings_router)
app.include_router(knowledge_router)
app.include_router(drafts_router)
app.include_router(review_router)
app.include_router(profile_router)
app.include_router(job_targets_router)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    content = ErrorResponse(code=code, message=message).model_dump()
    return JSONResponse(status_code=status_code, content=content)


def _profile_error(
    status_code: int, code: str, message: str, *, retryable: bool
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "retryable": retryable},
    )


@app.exception_handler(RequestValidationError)
async def invalid_request(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    path = request.url.path
    is_profile_path = path.startswith("/api/profile/") or (
        path.startswith("/api/workspaces/") and "/profile/" in path
    )
    is_job_target_path = "/job-targets" in path
    if not is_profile_path and not is_job_target_path:
        return JSONResponse(
            status_code=422,
            content={"detail": jsonable_encoder(error.errors())},
        )
    return _profile_error(
        422,
        "invalid_request",
        "请求参数不完整或格式错误",
        retryable=False,
    )


@app.exception_handler(JobTargetDomainError)
async def job_target_domain_error(
    _request: Request, error: JobTargetDomainError
) -> JSONResponse:
    if isinstance(error, JobTargetNotFound):
        return _profile_error(404, error.code, "求职目标记录不存在或无权访问", retryable=False)
    if isinstance(error, (JobTargetConflict, JobTargetBusy)):
        return _profile_error(409, error.code, str(error), retryable=True)
    return _profile_error(422, error.code, str(error), retryable=False)


@app.exception_handler(ProfileDomainError)
async def profile_domain_error(
    _request: Request, error: ProfileDomainError
) -> JSONResponse:
    if isinstance(error, ProfileMaterialNotFound):
        return _profile_error(
            404, error.code, "个人材料不存在或无权访问", retryable=False
        )
    if isinstance(error, ProfileMaterialVersionNotFound):
        return _profile_error(
            404, error.code, "材料版本不存在或无权访问", retryable=False
        )
    if isinstance(
        error,
        (
            ProfileClaimNotFound,
            ProfileProposalNotFound,
            ProfileDeletionPlanNotFound,
            ProfileActionPlanNotFound,
            ProfileAssessmentNotFound,
        ),
    ):
        return _profile_error(
            404, error.code, "画像记录不存在或无权访问", retryable=False
        )
    if isinstance(error, ProfileUploadTooLarge):
        return _profile_error(
            413, error.code, "上传文件超过 10 MiB 限制", retryable=False
        )
    if isinstance(error, ProfileUnsupportedFileType):
        return _profile_error(
            422,
            error.code,
            "仅支持 PDF、DOCX、Markdown 和 UTF-8 文本",
            retryable=False,
        )
    if isinstance(error, ProfileFileNameInvalid):
        return _profile_error(
            422, error.code, "文件名不符合上传要求", retryable=False
        )
    if isinstance(error, (ProfileEncryptedDocument, ProfileNoExtractableText)):
        return _profile_error(
            422, error.code, "材料无法提取可用文本", retryable=False
        )
    if isinstance(error, ProfileParseError):
        return _profile_error(
            422, error.code, "材料解析失败，请检查文件后重试", retryable=True
        )
    if isinstance(error, ProfileStorageError):
        return _profile_error(
            500, error.code, "材料暂时无法保存，请稍后重试", retryable=True
        )
    if isinstance(
        error,
        (
            ProfileMaterialRoleConflict,
            ProfileMaterialVersionConflict,
            ProfileDocumentNotReady,
            ProfileClaimVersionConflict,
            ProfileDeletionPlanConflict,
            ProfileIdempotencyConflict,
            ProfileIngestBusy,
            ProfileSnapshotChanged,
        ),
    ):
        messages = {
            "profile_material_role_conflict": (
                "同一用途已有活动材料，请先归档或更新现有材料"
            ),
            "profile_material_version_conflict": "材料版本已变化，请刷新后重试",
            "profile_document_not_ready": "简历文本尚未提取完成，请稍后再试",
            "profile_claim_version_conflict": "画像状态已变化，请刷新后重试",
            "profile_claim_selected_for_publication": "该画像仍在发布选择中，请先调整发布范围",
            "profile_deletion_plan_conflict": "删除影响已变化，请重新预检",
            "profile_deletion_plan_expired": "删除预检已过期，请重新预检",
            "profile_publication_revocation_required": "必须先确认撤销受影响的已发布知识",
            "profile_idempotency_conflict": "重复请求的内容不一致",
            "profile_ingest_busy": "该材料版本仍在处理中",
            "profile_snapshot_changed": "画像已变化，请刷新方案后重试",
        }
        return _profile_error(
            409,
            error.code,
            messages[error.code],
            retryable=error.code in {
                "profile_material_version_conflict",
                "profile_claim_version_conflict",
                "profile_ingest_busy",
            },
        )
    if isinstance(error, ProfileActionPlanInvalid):
        return _profile_error(
            422, error.code, "画像修改方案无效，请重新生成", retryable=False
        )
    if isinstance(error, ProfileValueInvalid):
        return _profile_error(
            422, error.code, "画像内容不完整或格式错误", retryable=False
        )
    if isinstance(error, ProfilePublicationRevocationUnavailable):
        return _profile_error(
            409,
            error.code,
            "已发布知识暂时无法安全撤销，请稍后重试",
            retryable=True,
        )
    return _profile_error(
        400, error.code, "个人画像请求无法处理", retryable=False
    )


@app.exception_handler(ModelResolutionError)
async def model_resolution_error(
    _request: Request, error: ModelResolutionError
) -> JSONResponse:
    return _error(409, str(error.code.value), str(error))


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


@app.exception_handler(ProductRecordNotFoundError)
async def product_record_not_found(
    _request: Request, _error_value: ProductRecordNotFoundError
) -> JSONResponse:
    return _error(404, "agent_resource_not_found", str(_error_value))


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


@app.exception_handler(DraftNotFoundError)
async def draft_not_found(
    _request: Request, _error_value: DraftNotFoundError
) -> JSONResponse:
    return _error(404, "draft_not_found", "知识草稿不存在")


@app.exception_handler(DraftVersionChangedError)
async def draft_version_changed(
    _request: Request, _error_value: DraftVersionChangedError
) -> JSONResponse:
    return _error(409, "draft_version_changed", "草稿已更新，请刷新后重试")


@app.exception_handler(DraftNotEditableError)
async def draft_not_editable(
    _request: Request, _error_value: DraftNotEditableError
) -> JSONResponse:
    return _error(409, "draft_not_editable", "当前草稿状态不允许编辑")


@app.exception_handler(DraftContentChangedError)
async def draft_content_changed(
    _request: Request, _error_value: DraftContentChangedError
) -> JSONResponse:
    return _error(409, "draft_content_changed", "草稿文件已被外部修改，请刷新后处理")


@app.exception_handler(ExternalDocumentChangedError)
async def external_document_changed(
    _request: Request, _error_value: ExternalDocumentChangedError
) -> JSONResponse:
    return _error(409, "external_document_changed", "Vault 文档已被外部修改，请先处理冲突")


@app.exception_handler(SessionBusyError)
async def session_busy(
    _request: Request, _error_value: SessionBusyError
) -> JSONResponse:
    return _error(409, "session_busy", "当前 Session 已有运行中的任务")


@app.exception_handler(ReviewRoundNotFoundError)
async def review_round_not_found(
    _request: Request, _error_value: ReviewRoundNotFoundError
) -> JSONResponse:
    return _error(404, "review_round_not_found", "复习轮次不存在")


@app.exception_handler(InsufficientQuestionsError)
async def insufficient_review_questions(
    _request: Request, error_value: InsufficientQuestionsError
) -> JSONResponse:
    return _error(
        422,
        "insufficient_questions",
        f"当前只有 {error_value.available} 道可用题目，无法创建本轮复习",
    )


@app.exception_handler(InputAlreadyResolvedError)
async def review_input_already_resolved(
    _request: Request, _error_value: InputAlreadyResolvedError
) -> JSONResponse:
    return _error(409, "review_input_already_resolved", "本题输入已处理")


@app.exception_handler(ReviewConflictError)
async def review_conflict(
    _request: Request, _error_value: ReviewConflictError
) -> JSONResponse:
    return _error(409, "review_conflict", "复习状态已变化，请刷新后重试")


@app.exception_handler(PathPolicyError)
async def workspace_path_denied(
    _request: Request, _error_value: PathPolicyError
) -> JSONResponse:
    return _error(400, "workspace_path_denied", "Workspace 路径不在授权范围内")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

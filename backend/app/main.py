from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

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
from app.services.secrets import SecretStoreUnavailableError
from app.services.workspace import WorkspaceError

app = FastAPI(title="Cyber Interview Agent API")
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

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

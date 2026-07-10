from pydantic import BaseModel

class ErrorResponse(BaseModel):
    code: str
    message: str


class ProviderError(Exception):
    """Base class for typed provider service errors."""


class ProviderNotFoundError(ProviderError):
    pass


class ProviderModelNotFoundError(ProviderError):
    pass


class ProviderModelInUseError(ProviderError):
    """Raised when deleting a provider/model still bound to a workspace."""

    def __init__(
        self,
        resource_id: str,
        bindings: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.resource_id = resource_id
        self.bindings = bindings
        details = ", ".join(
            f"workspace={workspace_id} role={role}"
            for workspace_id, role in bindings
        )
        message = "资源仍被 Workspace 模型绑定使用"
        super().__init__(f"{message}: {details}" if details else message)


class WorkspaceNotFoundError(LookupError):
    pass


class WorkspaceBindingError(ValueError):
    pass

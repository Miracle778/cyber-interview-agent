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

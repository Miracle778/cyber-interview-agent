from pydantic import BaseModel

from cyber_interview.domain.errors import ErrorCategory


class ErrorEnvelope(BaseModel):
    code: str
    category: ErrorCategory
    retryable: bool
    safe_message: str
    diagnostic_id: str
    next_actions: list[str] = []


class ErrorResponse(BaseModel):
    envelope: ErrorEnvelope


class DomainError(Exception):
    """Business exception that API can map to ErrorEnvelope."""

    def __init__(
        self,
        code: str,
        category: ErrorCategory,
        safe_message: str,
        *,
        retryable: bool = False,
        next_actions: list[str] | None = None,
    ):
        self.code = code
        self.category = category
        self.safe_message = safe_message
        self.retryable = retryable
        self.next_actions = next_actions or []
        super().__init__(safe_message)

from dataclasses import dataclass
from enum import StrEnum


class ErrorCategory(StrEnum):
    INPUT = "input"
    PERMISSION = "permission"
    CONTEXT = "context"
    MODEL = "model"
    TOOL = "tool"
    PERSISTENCE = "persistence"
    POLICY = "policy"
    INTERNAL = "internal"


@dataclass(frozen=True)
class OutputError:
    category: ErrorCategory
    safe_message: str
    finish_reason: str | None = None

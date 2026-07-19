from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptSpec:
    id: str
    version: str
    system: str

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("prompt id must not be empty")
        if not self.version.strip():
            raise ValueError("prompt version must not be empty")
        if not self.system.strip():
            raise ValueError("prompt system text must not be empty")

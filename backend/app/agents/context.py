from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AgentContext:
    workspace_id: str
    workspace_root: Path
    session_id: str
    run_id: str
    allowed_tools: frozenset[str]
    allowed_scopes: frozenset[str]

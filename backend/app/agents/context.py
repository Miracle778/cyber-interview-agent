from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentContext:
    workspace_id: str
    session_id: str
    run_id: str
    allowed_tools: frozenset[str]
    allowed_scopes: frozenset[str]

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    workspace_id: str
    workspace_root: Path
    session_id: str
    run_id: str
    graph_id: str
    graph_version: int
    allowed_tools: frozenset[str]
    allowed_scopes: frozenset[str]
    agent_role: str | None = None

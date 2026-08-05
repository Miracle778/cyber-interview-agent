from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AgentContext:
    workspace_id: str
    workspace_root: Path
    session_id: str
    run_id: str
    allowed_tools: frozenset[str]
    allowed_scopes: frozenset[str]
    progress_scope: tuple[str, ...] = ()
    agent_role: str | None = None
    profile_claim_ids: tuple[str, ...] = ()
    profile_claim_types: tuple[str, ...] = ()
    tool_result_item_limit: int = 50
    tool_excerpt_char_limit: int = 2000
    retrospective_id: str | None = None
    trace_warning: Callable[[str], None] | None = field(
        default=None, repr=False, compare=False
    )

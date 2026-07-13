from __future__ import annotations

from collections.abc import Mapping

from langchain.agents.middleware import (
    ContextEditingMiddleware,
    HumanInTheLoopMiddleware,
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.language_models import BaseChatModel

from app.middleware.no_progress import NoProgressMiddleware
from app.middleware.observability import ObservabilityMiddleware, ObservabilitySink
from app.middleware.session_title import SessionTitleMiddleware
from app.middleware.summarization import ProjectingSummarizationMiddleware
from app.middleware.usage import MiddlewareProjection, UsageProjectionMiddleware


def build_default_middleware(
    *,
    summary_model: BaseChatModel,
    projection: MiddlewareProjection,
    policy,
    observability: ObservabilitySink,
    interrupt_on: Mapping[str, bool | dict],
):
    """Build the one explicit default stack using official middleware hooks."""

    return (
        ProjectingSummarizationMiddleware(
            model=summary_model,
            trigger=("messages", 30),
            keep=("messages", 12),
            projection=projection,
        ),
        ContextEditingMiddleware(),
        ModelCallLimitMiddleware(
            thread_limit=40,
            run_limit=12,
            exit_behavior="error",
        ),
        ToolCallLimitMiddleware(
            thread_limit=80,
            run_limit=20,
            exit_behavior="error",
        ),
        policy,
        HumanInTheLoopMiddleware(interrupt_on=dict(interrupt_on)),
        UsageProjectionMiddleware(projection),
        SessionTitleMiddleware(projection),
        NoProgressMiddleware(projection),
        ObservabilityMiddleware(observability),
    )

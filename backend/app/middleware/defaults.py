from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class MiddlewareBudgetProfile:
    summary_trigger_messages: int = 30
    summary_keep_messages: int = 12
    model_thread_limit: int = 40
    model_run_limit: int = 12
    tool_thread_limit: int = 80
    tool_run_limit: int = 20
    no_progress_warning_limit: int = 2
    no_progress_hard_limit: int = 3
    include_progress_scope: bool = False


DEFAULT_BUDGET = MiddlewareBudgetProfile()
REVIEW_ROUND_BUDGET = MiddlewareBudgetProfile(
    summary_trigger_messages=24,
    summary_keep_messages=10,
    model_thread_limit=160,
    model_run_limit=12,
    tool_thread_limit=160,
    tool_run_limit=20,
    include_progress_scope=True,
)


def build_default_middleware(
    *,
    summary_model: BaseChatModel,
    projection: MiddlewareProjection,
    policy,
    observability: ObservabilitySink,
    interrupt_on: Mapping[str, bool | dict],
    budget_profile: MiddlewareBudgetProfile = DEFAULT_BUDGET,
):
    """Build the one explicit default stack using official middleware hooks."""

    return (
        ProjectingSummarizationMiddleware(
            model=summary_model,
            trigger=("messages", budget_profile.summary_trigger_messages),
            keep=("messages", budget_profile.summary_keep_messages),
            projection=projection,
        ),
        ContextEditingMiddleware(),
        ModelCallLimitMiddleware(
            thread_limit=budget_profile.model_thread_limit,
            run_limit=budget_profile.model_run_limit,
            exit_behavior="error",
        ),
        ToolCallLimitMiddleware(
            thread_limit=budget_profile.tool_thread_limit,
            run_limit=budget_profile.tool_run_limit,
            exit_behavior="error",
        ),
        policy,
        HumanInTheLoopMiddleware(interrupt_on=dict(interrupt_on)),
        UsageProjectionMiddleware(projection),
        SessionTitleMiddleware(projection),
        NoProgressMiddleware(
            projection,
            warning_limit=budget_profile.no_progress_warning_limit,
            hard_limit=budget_profile.no_progress_hard_limit,
            include_context_scope=budget_profile.include_progress_scope,
        ),
        ObservabilityMiddleware(observability),
    )

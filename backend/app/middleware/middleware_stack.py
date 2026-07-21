from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from langchain.agents.middleware import (
    AgentMiddleware,
    ContextEditingMiddleware,
    HumanInTheLoopMiddleware,
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.language_models import BaseChatModel

from app.middleware.no_progress_middleware import NoProgressMiddleware
from app.middleware.observability_middleware import ObservabilityMiddleware, ObservabilitySink
from app.middleware.session_title_middleware import SessionTitleMiddleware
from app.middleware.summarization_middleware import ProjectingSummarizationMiddleware
from app.middleware.usage_projection_middleware import MiddlewareProjection, UsageProjectionMiddleware


@dataclass(frozen=True, slots=True)
class MiddlewareBudgetProfile:
    summary_trigger_fraction: float = 0.70
    summary_keep_fraction: float = 0.20
    summary_fallback_messages: int = 100
    model_thread_limit: int = 40
    model_run_limit: int = 12
    tool_thread_limit: int = 80
    tool_run_limit: int = 20
    no_progress_warning_limit: int = 2
    no_progress_hard_limit: int = 3
    include_progress_scope: bool = False


DEFAULT_BUDGET = MiddlewareBudgetProfile()
REVIEW_ROUND_BUDGET = MiddlewareBudgetProfile(
    model_thread_limit=160,
    model_run_limit=12,
    tool_thread_limit=160,
    tool_run_limit=20,
    include_progress_scope=True,
)
PROFILE_CHAT_BUDGET_PROFILE = MiddlewareBudgetProfile(
    tool_run_limit=6,
)


def build_default_middleware(
    *,
    summary_model: BaseChatModel,
    summary_provider_model_id: str = "unknown",
    trace_writer=None,
    projection: MiddlewareProjection,
    policy,
    observability: ObservabilitySink,
    interrupt_on: Mapping[str, bool | dict],
    budget_profile: MiddlewareBudgetProfile = DEFAULT_BUDGET,
    tool_guards: tuple[AgentMiddleware, ...] = (),
    context_limit_tokens: int = 128000,
):
    """Build the one explicit default stack using official middleware hooks."""

    summary_threshold_tokens = int(
        context_limit_tokens * budget_profile.summary_trigger_fraction
    )
    summary_keep_tokens = int(
        context_limit_tokens * budget_profile.summary_keep_fraction
    )
    return (
        ProjectingSummarizationMiddleware(
            model=summary_model,
            trigger=[
                ("tokens", summary_threshold_tokens),
                ("messages", budget_profile.summary_fallback_messages),
            ],
            keep=("tokens", summary_keep_tokens),
            projection=projection,
            threshold_tokens=summary_threshold_tokens,
            trace_writer=trace_writer,
            provider_model_id=summary_provider_model_id,
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
        *tool_guards,
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

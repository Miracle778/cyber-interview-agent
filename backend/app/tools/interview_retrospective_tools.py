from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from app.agents.context import AgentContext
from app.interview_retrospectives.errors import RetrospectiveNotFound
from app.interview_retrospectives.repository import InterviewRetrospectiveRepository


RETROSPECTIVE_TOOL_NAMES = (
    "read_retrospective_summary",
    "read_question_analysis",
    "read_source_excerpt",
    "search_target_requirements",
    "search_confirmed_profile",
    "search_review_questions",
    "search_active_knowledge",
)
RETROSPECTIVE_TOOL_SCOPE = "interview_retrospective.read"
MAX_ITEMS = 20
MAX_EXCERPT_CHARS = 2_000


class _StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, arbitrary_types_allowed=True)
    runtime: ToolRuntime[AgentContext]


class NoInput(_StrictInput):
    pass


class QuestionInput(_StrictInput):
    question_id: str = Field(min_length=1, max_length=128)


class SearchInput(_StrictInput):
    query: str = Field(min_length=1, max_length=200)


def _error(code: str) -> dict[str, Any]:
    return {"status": "error", "items": [], "errorCode": code}


def _authorized(context: AgentContext, name: str) -> dict[str, Any] | None:
    if name not in context.allowed_tools:
        return _error("tool_not_allowed")
    if RETROSPECTIVE_TOOL_SCOPE not in context.allowed_scopes:
        return _error("tool_scope_denied")
    if not context.retrospective_id:
        return _error("retrospective_context_required")
    return None


def _limit(context: AgentContext) -> int:
    return max(1, min(MAX_ITEMS, context.tool_result_item_limit))


def _excerpt(context: AgentContext, value: str) -> tuple[str, bool]:
    limit = max(1, min(MAX_EXCERPT_CHARS, context.tool_excerpt_char_limit))
    if len(value) <= limit:
        return value, False
    return value[:limit].rstrip() + "…", True


def read_retrospective_summary(
    repository: InterviewRetrospectiveRepository, context: AgentContext
) -> dict[str, Any]:
    if denied := _authorized(context, "read_retrospective_summary"):
        return denied
    retrospective = repository.get_retrospective(context.retrospective_id or "")
    if retrospective.workspace_id != context.workspace_id:
        return _error("retrospective_context_mismatch")
    run = repository.current_analysis_run(retrospective.id)
    summary = (
        {} if run is None or run.summary_json is None else json.loads(run.summary_json)
    )
    return {
        "status": "ok",
        "items": [
            {
                "id": retrospective.id,
                "title": retrospective.title,
                "roundLabel": retrospective.round_label,
                "interviewDate": retrospective.interview_date,
                "outcome": retrospective.outcome,
                "analysisRunId": None if run is None else run.id,
                "summary": summary,
            }
        ],
        "truncated": False,
    }


def read_question_analysis(
    repository: InterviewRetrospectiveRepository,
    context: AgentContext,
    *,
    question_id: str,
) -> dict[str, Any]:
    if denied := _authorized(context, "read_question_analysis"):
        return denied
    try:
        question = repository.get_question(question_id)
    except RetrospectiveNotFound:
        return _error("question_context_mismatch")
    if question.retrospective_id != context.retrospective_id:
        return _error("question_context_mismatch")
    run = repository.current_analysis_run(question.retrospective_id)
    analysis = None
    if run is not None:
        try:
            analysis = repository.get_question_analysis(run.id, question.id)
        except RetrospectiveNotFound:
            analysis = None
    items: list[dict[str, Any]] = [
        {
            "id": question.id,
            "questionText": question.question_text,
            "origin": question.origin,
            "decisionStatus": question.decision_status,
            "version": question.version,
            "analysis": None
            if analysis is None
            else {
                "verdict": analysis.verdict,
                "strengths": list(analysis.strengths),
                "improvements": list(analysis.improvements),
                "omissions": list(analysis.omissions),
                "evidenceLevel": analysis.evidence_level,
                "improvementOutline": list(analysis.improvement_outline),
                "suggestedAnswer": _excerpt(context, analysis.suggested_answer)[0],
            },
        }
    ]
    return {"status": "ok", "items": items, "truncated": False}


def read_source_excerpt(
    repository: InterviewRetrospectiveRepository,
    context: AgentContext,
    *,
    question_id: str,
) -> dict[str, Any]:
    if denied := _authorized(context, "read_source_excerpt"):
        return denied
    try:
        question = repository.get_question(question_id)
    except RetrospectiveNotFound:
        return _error("question_context_mismatch")
    if question.retrospective_id != context.retrospective_id:
        return _error("question_context_mismatch")
    segment_ids = question.question_segment_ids + question.answer_segment_ids
    segments = {
        item.id: item for item in repository.list_segments(question.cleanup_version_id)
    }
    values: list[dict[str, Any]] = []
    clipped = False
    for segment_id in segment_ids[: _limit(context)]:
        segment = segments.get(segment_id)
        if segment is None or segment.ignored:
            continue
        body, was_clipped = _excerpt(context, segment.body)
        clipped = clipped or was_clipped
        values.append(
            {
                "id": segment.id,
                "speakerRole": segment.speaker_role,
                "displayName": segment.display_name,
                "body": body,
            }
        )
    return {
        "status": "ok",
        "items": values,
        "truncated": len(segment_ids) > _limit(context) or clipped,
    }


def _search(
    context: AgentContext,
    name: str,
    query: str,
    searcher: Callable[[str, int, int], list[dict[str, Any]]],
) -> dict[str, Any]:
    if denied := _authorized(context, name):
        return denied
    clean = query.strip()
    if not clean:
        return _error("tool_input_invalid")
    limit = _limit(context)
    rows = searcher(
        clean, limit + 1, min(MAX_EXCERPT_CHARS, context.tool_excerpt_char_limit)
    )
    return {"status": "ok", "items": rows[:limit], "truncated": len(rows) > limit}


def create_interview_retrospective_tools(
    repository: InterviewRetrospectiveRepository,
    *,
    target_search: Callable[[AgentContext, str, int, int], list[dict[str, Any]]],
    profile_search: Callable[[AgentContext, str, int, int], list[dict[str, Any]]],
    review_search: Callable[[AgentContext, str, int, int], list[dict[str, Any]]],
    knowledge_search: Callable[[AgentContext, str, int, int], list[dict[str, Any]]],
):
    @tool("read_retrospective_summary", args_schema=NoInput)
    def summary_tool(runtime: ToolRuntime[AgentContext]) -> dict[str, Any]:
        """Read the current retrospective's bounded summary."""
        return read_retrospective_summary(repository, runtime.context)

    @tool("read_question_analysis", args_schema=QuestionInput)
    def analysis_tool(
        question_id: str, runtime: ToolRuntime[AgentContext]
    ) -> dict[str, Any]:
        """Read one question and its current analysis in this retrospective."""
        return read_question_analysis(
            repository, runtime.context, question_id=question_id
        )

    @tool("read_source_excerpt", args_schema=QuestionInput)
    def excerpt_tool(
        question_id: str, runtime: ToolRuntime[AgentContext]
    ) -> dict[str, Any]:
        """Read bounded source excerpts belonging to one current question."""
        return read_source_excerpt(repository, runtime.context, question_id=question_id)

    def search_tool(name: str, searcher):
        @tool(
            name,
            args_schema=SearchInput,
            description="Search one bounded, current-Workspace retrospective context source.",
        )
        def wrapped(query: str, runtime: ToolRuntime[AgentContext]) -> dict[str, Any]:
            return _search(
                runtime.context,
                name,
                query,
                lambda q, limit, chars: searcher(runtime.context, q, limit, chars),
            )

        return wrapped

    return (
        summary_tool,
        analysis_tool,
        excerpt_tool,
        search_tool("search_target_requirements", target_search),
        search_tool("search_confirmed_profile", profile_search),
        search_tool("search_review_questions", review_search),
        search_tool("search_active_knowledge", knowledge_search),
    )

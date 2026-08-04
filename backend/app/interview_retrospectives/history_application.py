from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Iterable

from app.agents.interview_retrospective_agents import InterviewRetrospectiveAgents
from app.application.execution_service import AgentExecutionService
from app.application.session_service import AgentSessionService, ProductRepository
from app.interview_retrospectives.errors import RetrospectiveModelNotConfigured
from app.interview_retrospectives.history_search import (
    HistoricalSearchService,
    RetrospectiveSearchFilters,
    RetrospectiveSearchPlan,
)
from app.interview_retrospectives.repository import InterviewRetrospectiveRepository


logger = logging.getLogger(__name__)


class RetrospectiveHistoryApplication:
    def __init__(
        self,
        *,
        workspace_id: str,
        repository: InterviewRetrospectiveRepository,
        sessions: AgentSessionService,
        executions: AgentExecutionService,
        products: ProductRepository,
        agents: InterviewRetrospectiveAgents | None,
    ) -> None:
        self.workspace_id = workspace_id
        self.repository = repository
        self.sessions = sessions
        self.executions = executions
        self.products = products
        self.agents = agents
        self.search_service = HistoricalSearchService(repository)

    async def start_search(
        self,
        *,
        query_text: str,
        filters: RetrospectiveSearchFilters,
    ):
        query = query_text.strip()
        if not query:
            raise ValueError("历史检索问题不能为空")
        session = await self.sessions.create(
            workspace_id=self.workspace_id,
            kind="interview.retrospective.history",
            title=f"历史复盘检索：{query[:80]}",
            visibility="system",
        )
        execution = await self.executions.prepare(
            session,
            input={"query": query, "filters": filters.to_dict()},
            project_input_message=False,
        )
        search_set = self.repository.create_search_set(
            workspace_id=self.workspace_id,
            query_text=query,
            filters=filters.to_dict(),
            search_plan=RetrospectiveSearchPlan.from_query(query).to_dict(),
            session_id=session.id,
            execution_id=execution.id,
            status="searching",
        )

        async def handler(current, cancellation) -> None:
            cancellation.raise_if_requested()
            plan = RetrospectiveSearchPlan.from_query(query)
            if self.agents is not None:
                try:
                    output = await self.agents.plan_history_search(
                        query_text=query,
                        context=_history_context(
                            self.executions.context(current), "search_plan"
                        ),
                        config={"configurable": {"thread_id": session.id}},
                    )
                    plan = RetrospectiveSearchPlan(
                        terms=tuple(output.search_terms),
                        project_aliases=tuple(output.project_aliases),
                    )
                except Exception:
                    # Query understanding is an optional enrichment. The fixed
                    # repository search remains available without a provider.
                    plan = RetrospectiveSearchPlan.from_query(query)
            try:
                self.search_service.search_existing(
                    search_set_id=search_set.id,
                    plan=plan,
                    filters=filters,
                )
            except Exception as error:
                logger.exception(
                    "Historical retrospective search failed",
                    extra={"search_set_id": search_set.id},
                )
                self.repository.fail_search_set(
                    search_set.id, error_code=_error_code(error, "history_search_failed")
                )
                raise

        self.executions.run_background(execution, handler)
        return self.repository.get_search_set(search_set.id)

    def get_search(self, search_set_id: str):
        return self.repository.get_search_set(
            search_set_id, workspace_id=self.workspace_id
        )

    def list_searches(self, *, limit: int = 20):
        return self.repository.list_search_sets(
            workspace_id=self.workspace_id, limit=limit
        )

    def list_results(
        self, search_set_id: str, *, offset: int = 0, limit: int = 20
    ):
        self.get_search(search_set_id)
        return self.repository.list_search_results(
            search_set_id, offset=offset, limit=limit
        )

    async def summarize_search(self, search_set_id: str):
        search_set = self.get_search(search_set_id)
        if self.agents is None:
            raise RetrospectiveModelNotConfigured("请先配置面试复盘分析模型")
        if search_set.status != "completed":
            raise ValueError("历史检索尚未完成")
        session = await self.sessions.create(
            workspace_id=self.workspace_id,
            kind="interview.retrospective.history",
            title=f"历史复盘总结：{search_set.query_text[:80]}",
            visibility="system",
        )
        execution = await self.executions.prepare(
            session,
            input={"searchSetId": search_set.id, "action": "summary"},
            project_input_message=False,
        )
        self.repository.attach_search_summary_execution(
            search_set.id, execution_id=execution.id
        )

        async def handler(current, cancellation) -> None:
            try:
                cancellation.raise_if_requested()
                results = self.repository.list_search_results(search_set.id)
                if not results:
                    self.repository.complete_search_summary(
                        search_set.id,
                        markdown="没有找到符合当前条件的历史面试问题。",
                        citation_question_ids=(),
                    )
                    return
                batches = await self._summarize_batches(
                    search_set=search_set,
                    results=results,
                    execution=current,
                    cancellation=cancellation,
                )
                output = await self.agents.reduce_history_summary(
                    query_text=search_set.query_text,
                    batch_summaries=batches,
                    context=_history_context(
                        self.executions.context(current), "summary_reduce"
                    ),
                    config={"configurable": {"thread_id": session.id}},
                )
                allowed = {str(item.question_unit_id) for item in results}
                _validate_citations(output.citation_question_ids, allowed)
                self.repository.complete_search_summary(
                    search_set.id,
                    markdown=output.answer_markdown,
                    citation_question_ids=output.citation_question_ids,
                )
            except Exception as error:
                self.repository.fail_search_summary(
                    search_set.id,
                    error_code=_error_code(error, "history_summary_failed"),
                )
                raise

        self.executions.run_background(execution, handler)
        return self.repository.get_search_set(search_set.id)

    async def create_report(
        self,
        search_set_id: str,
        *,
        title: str,
        focus: str,
        selected_result_ids: tuple[str, ...],
        include_answer_excerpts: bool,
        include_action_plan: bool,
    ):
        search_set = self.get_search(search_set_id)
        if self.agents is None:
            raise RetrospectiveModelNotConfigured("请先配置面试复盘分析模型")
        if search_set.status != "completed":
            raise ValueError("历史检索尚未完成")
        all_results = self.repository.list_search_results(search_set.id)
        allowed_result_ids = {item.id for item in all_results}
        selected = selected_result_ids or tuple(item.id for item in all_results)
        if not set(selected) <= allowed_result_ids:
            raise ValueError("报告范围包含当前检索结果集之外的问题")
        session = self.products.get_session(str(search_set.session_id))
        execution = await self.executions.prepare(
            session,
            input={
                "searchSetId": search_set.id,
                "action": "report",
                "focus": focus,
            },
            project_input_message=False,
        )
        report = self.repository.create_search_report(
            workspace_id=self.workspace_id,
            search_set_id=search_set.id,
            title=title,
            focus=focus,
            selected_result_ids=selected,
            include_answer_excerpts=include_answer_excerpts,
            include_action_plan=include_action_plan,
            execution_id=execution.id,
        )

        async def handler(current, cancellation) -> None:
            chosen = tuple(item for item in all_results if item.id in set(selected))
            try:
                batches = await self._summarize_batches(
                    search_set=search_set,
                    results=chosen,
                    execution=current,
                    cancellation=cancellation,
                )
                output = await self.agents.generate_history_report(
                    title=title,
                    focus=focus,
                    batch_summaries=batches,
                    include_answer_excerpts=include_answer_excerpts,
                    include_action_plan=include_action_plan,
                    context=_history_context(
                        self.executions.context(current), "report_reduce"
                    ),
                    config={"configurable": {"thread_id": session.id}},
                )
                allowed = {str(item.question_unit_id) for item in chosen}
                _validate_citations(output.citation_question_ids, allowed)
                self.repository.complete_search_report(
                    report.id,
                    title=output.title,
                    body=output.model_dump(by_alias=True),
                    markdown=output.markdown,
                    citation_question_ids=output.citation_question_ids,
                )
            except Exception as error:
                self.repository.fail_search_report(
                    report.id,
                    error_code=_error_code(error, "history_report_failed"),
                )
                raise

        self.executions.run_background(execution, handler)
        return report

    def get_report(self, report_id: str):
        return self.repository.get_search_report(
            report_id, workspace_id=self.workspace_id
        )

    def list_reports(self):
        return self.repository.list_search_reports(workspace_id=self.workspace_id)

    def update_report(
        self,
        report_id: str,
        *,
        expected_version: int,
        title: str,
        markdown: str,
    ):
        if not title.strip():
            raise ValueError("报告名称不能为空")
        if not markdown.strip():
            raise ValueError("报告正文不能为空")
        return self.repository.update_search_report(
            report_id,
            workspace_id=self.workspace_id,
            expected_version=expected_version,
            title=title,
            markdown=markdown,
        )

    async def _summarize_batches(
        self,
        *,
        search_set,
        results: Iterable,
        execution,
        cancellation,
    ) -> list[dict[str, object]]:
        assert self.agents is not None
        summaries: list[dict[str, object]] = []
        for index, batch in enumerate(_result_batches(results), start=1):
            cancellation.raise_if_requested()
            payload = [_result_payload(item) for item in batch]
            output = await self.agents.summarize_history_batch(
                query_text=search_set.query_text,
                results=payload,
                batch_index=index,
                context=_history_context(
                    self.executions.context(execution), f"summary_batch:{index}"
                ),
                config={
                    "configurable": {
                        "thread_id": f"{execution.session_id}:{search_set.id}"
                    }
                },
            )
            allowed = {str(item.question_unit_id) for item in batch}
            _validate_citations(output.citation_question_ids, allowed)
            summaries.append(output.model_dump(by_alias=True))
        return summaries


def _history_context(context, stage: str):
    return replace(
        context,
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
        progress_scope=("interview_retrospective_history", stage),
    )


def _result_payload(item) -> dict[str, object]:
    return {
        "resultId": item.id,
        "questionId": item.question_unit_id,
        "rank": item.rank,
        "source": item.source_metadata,
        "question": item.question_snapshot,
        "answerExcerpt": item.answer_excerpt,
        "analysis": item.analysis_snapshot,
    }


def _result_batches(results: Iterable) -> tuple[tuple, ...]:
    batches: list[tuple] = []
    current: list = []
    characters = 0
    for item in results:
        size = len(json.dumps(_result_payload(item), ensure_ascii=False))
        if current and (len(current) >= 12 or characters + size > 24_000):
            batches.append(tuple(current))
            current = []
            characters = 0
        current.append(item)
        characters += size
    if current:
        batches.append(tuple(current))
    return tuple(batches)


def _validate_citations(values: Iterable[str], allowed: set[str]) -> None:
    if not set(values) <= allowed:
        raise ValueError("模型引用了当前冻结结果集之外的问题")


def _error_code(error: Exception, fallback: str) -> str:
    value = getattr(error, "code", None)
    if isinstance(value, str) and value:
        return value
    return fallback

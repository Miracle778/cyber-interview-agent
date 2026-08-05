from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.agents.interview_retrospective_contracts import (
    CleanupWindowOutput,
    QuestionAnalysisOutput,
    QuestionExtractionOutput,
)
from app.api.dependencies import get_agent_application
from app.application.workspace_runtime import AgentApplication
from app.graphs.interview_retrospective_cleanup import (
    create_source_windows,
)
from app.interview_retrospectives.projection import cleanup_version_resource
from app.interview_retrospectives.history_search import RetrospectiveSearchFilters
from app.main import app


ASYNC_TEST_TIMEOUT_SECONDS = 5.0


class FakeRetrospectiveAgents:
    async def cleanup_window(
        self,
        *,
        source_kind,
        recording_coverage="mixed_unknown",
        target_start,
        target_end,
        before_context,
        target_text,
        after_context,
        terminology_hints=(),
        context,
        config,
    ):
        del (
            source_kind,
            recording_coverage,
            target_start,
            target_end,
            before_context,
            after_context,
            terminology_hints,
            context,
            config,
        )
        return CleanupWindowOutput.model_validate(
            {
                "correctedTarget": target_text,
                "uncertainItems": [],
            }
        )

    async def extract_questions(self, *, segments, recording_coverage="mixed_unknown", work_key="question_extraction", context, config):
        del recording_coverage, work_key, context, config
        interviewer = next(
            (item for item in segments if item["speakerRole"] == "interviewer"),
            segments[0],
        )
        candidate = next(
            (item for item in segments if item["speakerRole"] == "candidate"),
            segments[-1],
        )
        return QuestionExtractionOutput.model_validate(
            {
                "questions": [
                    {
                        "ordinal": 1,
                        "questionKind": "project_experience",
                        "origin": "original",
                        "questionText": interviewer["body"],
                        "questionSegmentIds": [interviewer["id"]],
                        "answerSegmentIds": [candidate["id"]],
                        "inferenceBasis": "",
                        "confidence": 0.98,
                    }
                ]
            }
        )

    async def analyze_question(
        self, *, question, segments, context_snapshot, context, config
    ):
        del question, segments, context_snapshot, context, config
        return QuestionAnalysisOutput.model_validate(
            {
                "verdict": "improvable",
                "strengths": [],
                "improvements": [{"summary": "补充量化结果", "evidenceSegmentIds": []}],
                "omissions": [],
                "gaps": [
                    {
                        "kind": "expression",
                        "summary": "结果表达不够具体",
                        "evidenceSegmentIds": [],
                    }
                ],
                "evidenceLevel": "model_judgment",
                "confidence": 0.75,
                "improvementOutline": ["补充背景", "量化结果"],
                "suggestedAnswer": "我负责缓存治理，并将故障率降低到明确指标。",
            }
        )


class RetrospectiveGraphFactory:
    def __call__(self, _kind: str, **_dependencies):
        raise AssertionError("cleanup uses the bounded background handler")

    def create_interview_retrospective_agents(self, **_dependencies):
        return FakeRetrospectiveAgents()


class FailingTraceWriter:
    def append(self, *_args, **_kwargs):
        raise OSError("trace storage unavailable")


class GatedRetrospectiveAgents(FakeRetrospectiveAgents):
    def __init__(self) -> None:
        self.analysis_started = asyncio.Event()
        self.release_analysis = asyncio.Event()

    async def analyze_question(self, **values):
        self.analysis_started.set()
        await self.release_analysis.wait()
        return await super().analyze_question(**values)


class APITimeoutError(RuntimeError):
    pass


class CleanupWindowError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class PartialTimeoutRetrospectiveAgents(FakeRetrospectiveAgents):
    async def cleanup_window(self, **values):
        if values["target_start"] > 0:
            raise APITimeoutError("private provider timeout detail")
        return await super().cleanup_window(**values)


class ConcurrentRetrospectiveAgents(FakeRetrospectiveAgents):
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.parallel_started = asyncio.Event()
        self.release = asyncio.Event()

    async def cleanup_window(self, **values):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.active == 2:
            self.parallel_started.set()
        try:
            await self.release.wait()
            return await super().cleanup_window(**values)
        finally:
            self.active -= 1


class SplitTimeoutRetrospectiveAgents(FakeRetrospectiveAgents):
    def __init__(self, error_code: str = "provider_timeout") -> None:
        self.error_code = error_code
        self.timed_out_ranges: list[tuple[int, int]] = []

    async def cleanup_window(self, **values):
        if values["target_start"] == 0 and len(values["target_text"]) > 1_200:
            self.timed_out_ranges.append(
                (values["target_start"], values["target_end"])
            )
            raise CleanupWindowError(self.error_code)
        return await super().cleanup_window(**values)


class OneWindowFailureRetrospectiveAgents(FakeRetrospectiveAgents):
    async def cleanup_window(self, **values):
        if values["target_start"] == 2_400:
            raise RuntimeError("private malformed response")
        return await super().cleanup_window(**values)


class QuestionExtractionContractFailureAgents(FakeRetrospectiveAgents):
    def __init__(self) -> None:
        self.extraction_calls = 0

    async def extract_questions(self, **_values):
        self.extraction_calls += 1
        raise CleanupWindowError("schema_validation_error")


class IsolatedQuestionTimeoutAgents(FakeRetrospectiveAgents):
    def __init__(self) -> None:
        self.fail_first_question = True
        self.analysis_calls: list[int] = []

    async def extract_questions(self, *, segments, **_values):
        return QuestionExtractionOutput.model_validate(
            {
                "questions": [
                    {
                        "ordinal": 1,
                        "questionKind": "project_experience",
                        "origin": "original",
                        "questionText": segments[0]["body"],
                        "questionSegmentIds": [segments[0]["id"]],
                        "answerSegmentIds": [segments[1]["id"]],
                        "inferenceBasis": "",
                        "confidence": 0.98,
                    },
                    {
                        "ordinal": 2,
                        "questionKind": "technical_knowledge",
                        "origin": "original",
                        "questionText": segments[2]["body"],
                        "questionSegmentIds": [segments[2]["id"]],
                        "answerSegmentIds": [segments[3]["id"]],
                        "inferenceBasis": "",
                        "confidence": 0.98,
                    },
                ]
            }
        )

    async def analyze_question(self, **values):
        ordinal = int(values["question"]["ordinal"])
        self.analysis_calls.append(ordinal)
        if ordinal == 1 and self.fail_first_question:
            raise APITimeoutError("provider timeout")
        return await super().analyze_question(**values)


@pytest_asyncio.fixture
async def retrospective_application(tmp_path: Path):
    root = tmp_path / "w1"
    root.mkdir()
    application = AgentApplication(
        workspace_resolver=lambda _workspace_id: root,
        workspace_ids=lambda: ("w1",),
        model_bindings=lambda _workspace_id: {
            "retrospective_analysis": "model-1",
            "retrospective_chat": "model-1",
            "report_summarization": "model-2",
        },
        graph_factory=RetrospectiveGraphFactory(),
    )
    try:
        yield application
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_create_retrospective_owns_visible_chat_and_system_analysis_sessions(
    retrospective_application: AgentApplication,
) -> None:
    target = retrospective_application.job_targets("w1").create_target(
        role_name="后端工程师",
        seniority="3-5 年",
        company_name="示例公司",
        source_url=None,
        idempotency_key="target-create-1",
    )

    retrospective = await retrospective_application.interview_retrospectives(
        "w1"
    ).create_retrospective(
        job_target_id=target.id,
        title="示例公司后端一面",
        round_label="一面",
        interview_date="2026-08-01",
        outcome="unrecorded",
        note="",
        idempotency_key="retrospective-create-1",
    )
    context = retrospective_application._context("w1")
    sessions = context.repository.list_sessions("w1", include_system=True)

    assert (
        context.repository.get_session(retrospective.chat_session_id).visibility
        == "user"
    )
    assert (
        context.repository.get_session(retrospective.analysis_session_id).visibility
        == "system"
    )
    assert {item.kind for item in sessions} >= {"interview.retrospective"}


@pytest.mark.asyncio
async def test_history_search_completes_with_deterministic_fallback_when_planner_is_unavailable(
    retrospective_application: AgentApplication,
) -> None:
    context = retrospective_application._context("w1")
    history = retrospective_application.interview_retrospectives("w1").history

    started = await history.start_search(
        query_text="找出之前所有关于数字签名项目的问题",
        filters=RetrospectiveSearchFilters(),
    )
    execution = await context.executions.wait(str(started.execution_id))
    completed = history.get_search(started.id)

    assert completed.status == "completed", (
        completed.last_error_code,
        execution.error_code,
        execution.error_message,
    )
    assert completed.total_questions == 0
    assert context.repository.get_execution(str(started.execution_id)).status == "completed"

    summarizing = await history.summarize_search(started.id)
    summary_execution = context.repository.get_execution(
        str(summarizing.summary_execution_id)
    )
    summary_session = context.repository.get_session(summary_execution.session_id)
    assert summary_session.title.startswith("历史复盘总结：")
    assert summary_session.id != started.session_id


@pytest.mark.asyncio
async def test_cleanup_start_returns_execution_before_background_finishes_and_persists_review(
    retrospective_application: AgentApplication,
) -> None:
    target = retrospective_application.job_targets("w1").create_target(
        role_name="后端工程师",
        seniority="3-5 年",
        company_name="示例公司",
        source_url=None,
        idempotency_key="target-create-2",
    )
    retrospectives = retrospective_application.interview_retrospectives("w1")
    retrospective = await retrospectives.create_retrospective(
        job_target_id=target.id,
        title="示例公司后端二面",
        round_label="二面",
        interview_date=None,
        outcome="unrecorded",
        note="",
        idempotency_key="retrospective-create-2",
    )
    source = retrospectives.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="面试官：介绍一下你做过的缓存治理。",
        file_name=None,
        idempotency_key="retrospective-source-2",
    )
    context = retrospective_application._context("w1")
    context.executions._trace_writer = FailingTraceWriter()

    receipt = await retrospectives.start_cleanup(
        retrospective.id,
        source_version_id=source.id,
        idempotency_key="retrospective-cleanup-2",
    )
    initial = retrospectives.get_cleanup(retrospective.id, receipt["cleanupVersionId"])
    await context.executions.wait(receipt["executionId"])
    completed = retrospectives.get_cleanup(
        retrospective.id, receipt["cleanupVersionId"]
    )

    assert initial.execution_id == receipt["executionId"]
    assert initial.status in {"running", "review_pending"}
    assert completed.status == "review_pending"
    assert completed.document_body == source.body
    assert retrospectives.list_segments(retrospective.id, completed.id) == ()
    assert (
        context.repository.get_execution(receipt["executionId"]).status == "completed"
    )


@pytest.mark.asyncio
async def test_failed_cleanup_exposes_saved_window_progress_and_timeout(
    retrospective_application: AgentApplication,
) -> None:
    retrospectives = retrospective_application.interview_retrospectives("w1")
    retrospectives.agents = PartialTimeoutRetrospectiveAgents()
    target = retrospective_application.job_targets("w1").create_target(
        role_name="后端工程师",
        seniority="",
        company_name="示例公司",
        source_url=None,
        idempotency_key="target-partial-cleanup",
    )
    retrospective = await retrospectives.create_retrospective(
        job_target_id=target.id,
        title="示例公司后端二面",
        round_label="二面",
        interview_date=None,
        outcome="unrecorded",
        note="",
        idempotency_key="retrospective-partial-cleanup",
    )
    source = retrospectives.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="字" * 50_000,
        file_name=None,
        idempotency_key="source-partial-cleanup",
    )
    started = await retrospectives.start_cleanup(
        retrospective.id,
        source_version_id=source.id,
        idempotency_key="start-partial-cleanup",
    )
    await retrospective_application._context("w1").executions.wait(
        started["executionId"]
    )
    app.dependency_overrides[get_agent_application] = lambda: retrospective_application
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                f"/api/interview-retrospectives/{retrospective.id}/cleanup-runs/{started['cleanupVersionId']}",
                params={"workspaceId": "w1"},
            )
    finally:
        app.dependency_overrides.pop(get_agent_application, None)

    assert response.status_code == 200
    cleanup = response.json()
    assert cleanup["status"] == "failed"
    assert cleanup["completedItems"] == 1
    assert cleanup["totalItems"] > 1
    assert cleanup["currentWorkKey"].startswith("target:")
    assert cleanup["lastErrorCode"] == "provider_timeout"
    assert cleanup["activeItems"] == 0
    assert cleanup["failedItems"] >= 1
    assert cleanup["segments"] == []


@pytest.mark.asyncio
async def test_long_cleanup_runs_two_target_windows_concurrently(
    retrospective_application: AgentApplication,
) -> None:
    retrospectives = retrospective_application.interview_retrospectives("w1")
    agents = ConcurrentRetrospectiveAgents()
    retrospectives.agents = agents
    target = retrospective_application.job_targets("w1").create_target(
        role_name="后端工程师",
        seniority="",
        company_name="示例公司",
        source_url=None,
        idempotency_key="target-concurrent-cleanup",
    )
    retrospective = await retrospectives.create_retrospective(
        job_target_id=target.id,
        title="长文本并发整理",
        round_label="二面",
        interview_date=None,
        outcome="unrecorded",
        note="",
        idempotency_key="retrospective-concurrent-cleanup",
    )
    source = retrospectives.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="字" * 12_000,
        file_name=None,
        idempotency_key="source-concurrent-cleanup",
    )

    started = await retrospectives.start_cleanup(
        retrospective.id,
        source_version_id=source.id,
        idempotency_key="start-concurrent-cleanup",
    )
    try:
        await asyncio.wait_for(
            agents.parallel_started.wait(), timeout=ASYNC_TEST_TIMEOUT_SECONDS
        )
        current = retrospectives.get_cleanup(
            retrospective.id, started["cleanupVersionId"]
        )
        resource = cleanup_version_resource(
            current,
            segments=retrospectives.list_segments(retrospective.id, current.id),
            work_items=retrospectives.repository.list_cleanup_work_items(current.id),
        )
        assert resource["activeItems"] == 2
        assert resource["failedItems"] == 0
    finally:
        agents.release.set()
    await retrospective_application._context("w1").executions.wait(
        started["executionId"]
    )

    cleanup = retrospectives.get_cleanup(
        retrospective.id, started["cleanupVersionId"]
    )
    assert agents.max_active == 2
    assert cleanup.status == "review_pending"
    assert all(
        item.status == "completed"
        for item in retrospectives.repository.list_cleanup_work_items(cleanup.id)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_code",
    ["provider_timeout", "output_truncated"],
)
async def test_timeout_splits_only_failed_window_and_finishes_children(
    retrospective_application: AgentApplication,
    error_code: str,
) -> None:
    retrospectives = retrospective_application.interview_retrospectives("w1")
    agents = SplitTimeoutRetrospectiveAgents(error_code)
    retrospectives.agents = agents
    target = retrospective_application.job_targets("w1").create_target(
        role_name="后端工程师",
        seniority="",
        company_name="示例公司",
        source_url=None,
        idempotency_key="target-split-cleanup",
    )
    retrospective = await retrospectives.create_retrospective(
        job_target_id=target.id,
        title="超时窗口拆分",
        round_label="二面",
        interview_date=None,
        outcome="unrecorded",
        note="",
        idempotency_key="retrospective-split-cleanup",
    )
    source = retrospectives.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="字" * 8_000,
        file_name=None,
        idempotency_key="source-split-cleanup",
    )

    started = await retrospectives.start_cleanup(
        retrospective.id,
        source_version_id=source.id,
        idempotency_key="start-split-cleanup",
    )
    await retrospective_application._context("w1").executions.wait(
        started["executionId"]
    )

    cleanup = retrospectives.get_cleanup(
        retrospective.id, started["cleanupVersionId"]
    )
    items = retrospectives.repository.list_cleanup_work_items(cleanup.id)
    assert agents.timed_out_ranges == [(0, 2_400)]
    assert (0, 2_400) not in {
        (item.source_start, item.source_end) for item in items
    }
    assert all(item.status == "completed" for item in items)
    assert cleanup.status == "review_pending"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_code",
    ["schema_validation_error", "structured_output_missing"],
)
async def test_contract_failure_is_not_split_or_automatically_retried(
    retrospective_application: AgentApplication,
    error_code: str,
) -> None:
    retrospectives = retrospective_application.interview_retrospectives("w1")
    agents = SplitTimeoutRetrospectiveAgents(error_code)
    retrospectives.agents = agents
    target = retrospective_application.job_targets("w1").create_target(
        role_name="后端工程师",
        seniority="",
        company_name="示例公司",
        source_url=None,
        idempotency_key="target-schema-cleanup",
    )
    retrospective = await retrospectives.create_retrospective(
        job_target_id=target.id,
        title="格式错误不盲重试",
        round_label="二面",
        interview_date=None,
        outcome="unrecorded",
        note="",
        idempotency_key="retrospective-schema-cleanup",
    )
    source = retrospectives.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="字" * 8_000,
        file_name=None,
        idempotency_key="source-schema-cleanup",
    )

    started = await retrospectives.start_cleanup(
        retrospective.id,
        source_version_id=source.id,
        idempotency_key="start-schema-cleanup",
    )
    await retrospective_application._context("w1").executions.wait(
        started["executionId"]
    )

    cleanup = retrospectives.get_cleanup(
        retrospective.id, started["cleanupVersionId"]
    )
    items = retrospectives.repository.list_cleanup_work_items(cleanup.id)
    failed = next(item for item in items if item.source_start == 0)
    assert agents.timed_out_ranges == [(0, 2_400)]
    assert (failed.source_start, failed.source_end) == (0, 2_400)
    assert failed.status == "retryable"
    assert failed.attempt_count == 1
    assert failed.last_error_code == error_code
    assert cleanup.status == "failed"


@pytest.mark.asyncio
async def test_exhausted_window_does_not_block_later_window_results(
    retrospective_application: AgentApplication,
) -> None:
    retrospectives = retrospective_application.interview_retrospectives("w1")
    retrospectives.agents = OneWindowFailureRetrospectiveAgents()
    target = retrospective_application.job_targets("w1").create_target(
        role_name="后端工程师",
        seniority="",
        company_name="示例公司",
        source_url=None,
        idempotency_key="target-partial-window-cleanup",
    )
    retrospective = await retrospectives.create_retrospective(
        job_target_id=target.id,
        title="部分窗口失败",
        round_label="二面",
        interview_date=None,
        outcome="unrecorded",
        note="",
        idempotency_key="retrospective-partial-window-cleanup",
    )
    source = retrospectives.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="字" * 9_000,
        file_name=None,
        idempotency_key="source-partial-window-cleanup",
    )

    started = await retrospectives.start_cleanup(
        retrospective.id,
        source_version_id=source.id,
        idempotency_key="start-partial-window-cleanup",
    )
    await retrospective_application._context("w1").executions.wait(
        started["executionId"]
    )

    cleanup = retrospectives.get_cleanup(
        retrospective.id, started["cleanupVersionId"]
    )
    items = retrospectives.repository.list_cleanup_work_items(cleanup.id)
    failed = next(item for item in items if item.source_start == 2_400)
    later = next(item for item in items if item.source_start == 4_800)
    assert cleanup.status == "failed"
    assert failed.status == "retryable"
    assert failed.attempt_count == 2
    assert later.status == "completed"

    retrospectives.agents = FakeRetrospectiveAgents()
    resumed = await retrospectives.resume_cleanup(
        retrospective.id,
        cleanup.id,
        idempotency_key="resume-partial-window-cleanup",
    )
    await retrospective_application._context("w1").executions.wait(
        resumed["executionId"]
    )
    resumed_cleanup = retrospectives.get_cleanup(retrospective.id, cleanup.id)
    resumed_items = retrospectives.repository.list_cleanup_work_items(cleanup.id)
    assert resumed_cleanup.status == "review_pending"
    assert all(item.status == "completed" for item in resumed_items)
    assert next(item for item in resumed_items if item.source_start == 2_400).attempt_count == 1


@pytest.mark.asyncio
async def test_cleanup_stop_preserves_work_and_resume_finishes_pending_windows(
    retrospective_application: AgentApplication,
) -> None:
    target = retrospective_application.job_targets("w1").create_target(
        role_name="后端工程师",
        seniority="3-5 年",
        company_name="示例公司",
        source_url=None,
        idempotency_key="target-create-stop",
    )
    retrospectives = retrospective_application.interview_retrospectives("w1")
    retrospective = await retrospectives.create_retrospective(
        job_target_id=target.id,
        title="示例公司后端终面",
        round_label="终面",
        interview_date=None,
        outcome="unrecorded",
        note="",
        idempotency_key="retrospective-create-stop",
    )
    source = retrospectives.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="字" * 50_000,
        file_name=None,
        idempotency_key="retrospective-source-stop",
    )
    started = await retrospectives.start_cleanup(
        retrospective.id,
        source_version_id=source.id,
        idempotency_key="retrospective-cleanup-stop",
    )

    stopped = await retrospectives.stop_cleanup(
        retrospective.id,
        started["cleanupVersionId"],
        idempotency_key="retrospective-cleanup-stop-command",
    )
    stopped_replay = await retrospectives.stop_cleanup(
        retrospective.id,
        started["cleanupVersionId"],
        idempotency_key="retrospective-cleanup-stop-command",
    )
    completed_before_resume = sum(
        item.status == "completed"
        for item in retrospectives.repository.list_cleanup_work_items(stopped.id)
    )
    resumed = await retrospectives.resume_cleanup(
        retrospective.id,
        stopped.id,
        idempotency_key="retrospective-cleanup-resume-command",
    )
    resumed_replay = await retrospectives.resume_cleanup(
        retrospective.id,
        stopped.id,
        idempotency_key="retrospective-cleanup-resume-command",
    )
    await retrospective_application._context("w1").executions.wait(
        resumed["executionId"]
    )
    final = retrospectives.get_cleanup(retrospective.id, stopped.id)

    assert stopped.status == "stopped"
    assert stopped_replay.id == stopped.id
    assert completed_before_resume >= 0
    assert resumed_replay == resumed
    assert final.status == "review_pending"
    assert all(
        item.status == "completed"
        for item in retrospectives.repository.list_cleanup_work_items(final.id)
    )


@pytest.mark.asyncio
async def test_resume_replans_legacy_failed_cleanup_before_any_window_completed(
    retrospective_application: AgentApplication,
) -> None:
    target = retrospective_application.job_targets("w1").create_target(
        role_name="后端工程师",
        seniority="3-5 年",
        company_name="示例公司",
        source_url=None,
        idempotency_key="target-create-legacy-cleanup",
    )
    retrospectives = retrospective_application.interview_retrospectives("w1")
    retrospective = await retrospectives.create_retrospective(
        job_target_id=target.id,
        title="示例公司后端二面",
        round_label="二面",
        interview_date=None,
        outcome="unrecorded",
        note="",
        idempotency_key="retrospective-create-legacy-cleanup",
    )
    source = retrospectives.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="字" * 9_850,
        file_name=None,
        idempotency_key="retrospective-source-legacy-cleanup",
    )
    cleanup = retrospectives.repository.insert_cleanup_run(
        retrospective.id,
        source_version_id=source.id,
        input_digest=source.content_sha256,
        windows=create_source_windows(source.body, window_size=24_000, overlap=1_000),
    )
    retrospectives.repository.connection.execute(
        "UPDATE interview_cleanup_versions SET status = 'failed', stage = 'failed' "
        "WHERE id = ?",
        (cleanup.id,),
    )
    retrospectives.repository.connection.execute(
        "UPDATE interview_cleanup_work_items SET status = 'retryable', "
        "last_error_code = 'retrospective_cleanup_failed' "
        "WHERE cleanup_version_id = ?",
        (cleanup.id,),
    )
    retrospectives.repository.connection.commit()

    resumed = await retrospectives.resume_cleanup(retrospective.id, cleanup.id)
    await retrospective_application._context("w1").executions.wait(
        resumed["executionId"]
    )

    work_items = retrospectives.repository.list_cleanup_work_items(cleanup.id)
    assert [(item.source_start, item.source_end) for item in work_items] == [
        (0, 2_400),
        (2_400, 4_800),
        (4_800, 7_200),
        (7_200, 9_600),
        (9_600, 9_850),
    ]
    assert all(item.status == "completed" for item in work_items)


@pytest.mark.asyncio
async def test_retrospective_capture_cleanup_and_confirm_api(
    retrospective_application: AgentApplication,
) -> None:
    app.dependency_overrides[get_agent_application] = lambda: retrospective_application
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            target_response = await client.post(
                "/api/workspaces/w1/job-targets",
                json={
                    "roleName": "后端工程师",
                    "seniority": "3-5 年",
                    "companyName": "示例公司",
                },
                headers={"Idempotency-Key": "api-target-create-1"},
            )
            target_id = target_response.json()["id"]
            created = await client.post(
                "/api/interview-retrospectives",
                json={
                    "workspaceId": "w1",
                    "jobTargetId": target_id,
                    "title": "示例公司后端一面",
                    "roundLabel": "一面",
                    "outcome": "unrecorded",
                    "note": "",
                },
                headers={"Idempotency-Key": "api-retrospective-create-1"},
            )
            assert created.status_code == 201, created.text
            retrospective = created.json()
            assert "analysisSessionId" not in retrospective
            assert "chatSessionId" not in retrospective

            source_response = await client.post(
                f"/api/interview-retrospectives/{retrospective['id']}/sources",
                json={
                    "workspaceId": "w1",
                    "sourceKind": "transcript",
                    "recordingCoverage": "candidate_only",
                    "body": "面试官：介绍一下缓存治理。",
                },
                headers={"Idempotency-Key": "api-retrospective-source-1"},
            )
            assert source_response.status_code == 201, source_response.text
            source = source_response.json()
            assert "body" not in source
            assert source["recordingCoverage"] == "candidate_only"

            source_detail = await client.get(
                f"/api/interview-retrospectives/{retrospective['id']}/sources/{source['id']}",
                params={"workspaceId": "w1"},
            )
            assert source_detail.json()["body"] == "面试官：介绍一下缓存治理。"
            assert source_detail.json()["recordingCoverage"] == "candidate_only"

            started = await client.post(
                f"/api/interview-retrospectives/{retrospective['id']}/cleanup-runs",
                json={
                    "workspaceId": "w1",
                    "sourceVersionId": source["id"],
                },
                headers={"Idempotency-Key": "api-retrospective-cleanup-1"},
            )
            assert started.status_code == 202, started.text
            receipt = started.json()
            await retrospective_application._context("w1").executions.wait(
                receipt["executionId"]
            )

            cleanup_response = await client.get(
                f"/api/interview-retrospectives/{retrospective['id']}/cleanup-runs/{receipt['cleanupVersionId']}",
                params={"workspaceId": "w1"},
            )
            assert cleanup_response.status_code == 200
            cleanup = cleanup_response.json()
            assert cleanup["status"] == "review_pending"
            assert cleanup["documentBody"] == "面试官：介绍一下缓存治理。"
            assert cleanup["segments"] == []

            current_cleanup = await client.get(
                f"/api/interview-retrospectives/{retrospective['id']}/cleanup-runs/current",
                params={"workspaceId": "w1"},
            )
            assert current_cleanup.status_code == 200
            assert current_cleanup.json()["id"] == cleanup["id"]

            edited = await client.put(
                f"/api/interview-retrospectives/{retrospective['id']}/cleanup-runs/{cleanup['id']}/document",
                json={
                    "workspaceId": "w1",
                    "expectedVersion": cleanup["version"],
                    "documentBody": "面试官：介绍一下缓存治理。\n\n候选人：我负责缓存治理。",
                    "reviewIssueDecisions": [],
                },
                headers={"Idempotency-Key": "api-retrospective-document-1"},
            )
            assert edited.status_code == 200, edited.text
            cleanup = edited.json()
            assert cleanup["documentBody"] == (
                "面试官：介绍一下缓存治理。\n\n候选人：我负责缓存治理。"
            )

            confirmed = await client.post(
                f"/api/interview-retrospectives/{retrospective['id']}/cleanup-runs/{cleanup['id']}/confirm",
                json={
                    "workspaceId": "w1",
                    "expectedVersion": cleanup["version"],
                },
                headers={"Idempotency-Key": "api-retrospective-confirm-1"},
            )
            assert confirmed.status_code == 200, confirmed.text
            assert confirmed.json()["status"] == "confirmed"
            assert [segment["speakerRole"] for segment in confirmed.json()["segments"]] == [
                "interviewer",
                "candidate",
            ]
            assert "".join(
                segment["body"] for segment in confirmed.json()["segments"]
            ) == "面试官：介绍一下缓存治理。候选人：我负责缓存治理。"

            listed = await client.get(
                "/api/interview-retrospectives",
                params={"workspaceId": "w1"},
            )
            assert [item["id"] for item in listed.json()] == [retrospective["id"]]
    finally:
        app.dependency_overrides.pop(get_agent_application, None)


@pytest.mark.asyncio
async def test_progressive_analysis_api_returns_questions_and_report_without_score(
    retrospective_application: AgentApplication,
) -> None:
    target = retrospective_application.job_targets("w1").create_target(
        role_name="后端工程师",
        seniority="3-5 年",
        company_name="示例公司",
        source_url=None,
        idempotency_key="target-analysis-api",
    )
    service = retrospective_application.interview_retrospectives("w1")
    retrospective = await service.create_retrospective(
        job_target_id=target.id,
        title="示例公司分析接口",
        round_label="一面",
        interview_date=None,
        outcome="unrecorded",
        note="",
        idempotency_key="retrospective-analysis-api",
    )
    source = service.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="面试官：介绍缓存治理。候选人：我负责双写一致性。",
        file_name=None,
        idempotency_key="source-analysis-api",
    )
    cleanup_receipt = await service.start_cleanup(
        retrospective.id,
        source_version_id=source.id,
        idempotency_key="cleanup-analysis-api",
    )
    context = retrospective_application._context("w1")
    await context.executions.wait(cleanup_receipt["executionId"])
    cleanup = service.get_cleanup(retrospective.id, cleanup_receipt["cleanupVersionId"])
    cleanup = service.replace_segments(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        segments=(
            {
                "speaker_role": "interviewer",
                "raw_speaker_label": "面试官",
                "display_name": "面试官",
                "body": "介绍缓存治理",
                "source_start": 0,
                "source_end": 10,
                "confidence": 1.0,
                "uncertainty_reason": None,
                "ignored": False,
            },
            {
                "speaker_role": "candidate",
                "raw_speaker_label": "候选人",
                "display_name": "候选人",
                "body": "我负责双写一致性",
                "source_start": 11,
                "source_end": 22,
                "confidence": 1.0,
                "uncertainty_reason": None,
                "ignored": False,
            },
        ),
    )
    service.confirm_cleanup(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        idempotency_key="confirm-analysis-api",
    )

    app.dependency_overrides[get_agent_application] = lambda: retrospective_application
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            started = await client.post(
                f"/api/interview-retrospectives/{retrospective.id}/analysis-runs",
                json={"workspaceId": "w1", "cleanupVersionId": cleanup.id},
                headers={"Idempotency-Key": "analysis-api-start"},
            )
            assert started.status_code == 202, started.text
            receipt = started.json()
            frozen_run = service.get_analysis_run(
                retrospective.id, receipt["analysisRunId"]
            )
            frozen_context = json.loads(frozen_run.context_snapshot_json)
            assert frozen_context["target"]["id"] == target.id
            assert frozen_context["model"] == {
                "role": "retrospective_analysis",
                "providerModelId": "model-1",
            }
            assert len(frozen_run.input_digest) == 64
            assert "storagePath" not in frozen_run.context_snapshot_json
            await context.executions.wait(receipt["executionId"])

            questions = await client.get(
                f"/api/interview-retrospectives/{retrospective.id}/questions",
                params={"workspaceId": "w1"},
            )
            report = await client.get(
                f"/api/interview-retrospectives/{retrospective.id}/report",
                params={"workspaceId": "w1"},
            )
            candidates = await client.get(
                f"/api/interview-retrospectives/{retrospective.id}/candidates",
                params={"workspaceId": "w1"},
            )
            review_candidates = [
                item
                for item in candidates.json()
                if item["candidateKind"] == "review_question"
            ]
            assert review_candidates, {
                "questions": questions.json(),
                "report": report.json(),
                "candidates": candidates.json(),
                "run": service.get_analysis_run(
                    retrospective.id, receipt["analysisRunId"]
                ),
                "items": service.repository.list_analysis_work_items(
                    receipt["analysisRunId"]
                ),
                "itemErrors": [
                    (item.work_key, item.status, item.last_error_code, item.output)
                    for item in service.repository.list_analysis_work_items(
                        receipt["analysisRunId"]
                    )
                ],
            }
            review_candidate = review_candidates[0]
            review_decision = await client.post(
                f"/api/interview-retrospectives/{retrospective.id}/candidates/{review_candidate['id']}/decision",
                json={
                    "workspaceId": "w1",
                    "action": "create_new",
                    "expectedVersion": review_candidate["version"],
                    "actionPayload": {},
                },
                headers={"Idempotency-Key": "analysis-api-review-candidate"},
            )
            actions = await client.get(
                f"/api/interview-retrospectives/{retrospective.id}/actions",
                params={"workspaceId": "w1"},
            )
            publication = await client.post(
                f"/api/interview-retrospectives/{retrospective.id}/publication-drafts",
                json={
                    "workspaceId": "w1",
                    "selectedSections": [
                        "basic_info",
                        "confirmed_questions",
                        "action_items",
                    ],
                },
                headers={"Idempotency-Key": "analysis-api-publication"},
            )

        assert questions.status_code == 200, questions.text
        assert questions.json()[0]["origin"] == "original"
        assert questions.json()[0]["decisionStatus"] == "confirmed"
        assert report.status_code == 200, report.text
        assert report.json()["analysisRun"]["status"] == "completed"
        assert report.json()["items"][0]["status"] == "completed"
        assert report.json()["analyses"][0]["gaps"] == [
            {
                "kind": "expression",
                "summary": "结果表达不够具体",
                "evidenceSegmentIds": [],
            }
        ]
        assert "overallScore" not in report.json()["summary"]
        assert candidates.status_code == 200, candidates.text
        assert {item["candidateKind"] for item in candidates.json()} == {
            "review_question",
            "project_narrative",
            "summary",
        }
        assert review_decision.status_code == 200, review_decision.text
        assert review_decision.json()["status"] == "confirmed"
        assert (
            review_decision.json()["targetResourceType"] == "review_question_candidate"
        )
        assert actions.status_code == 200, actions.text
        assert actions.json()[0]["status"] == "pending"
        assert publication.status_code == 201, publication.text
        assert publication.json()["documentType"] == "interview_retrospective"
        assert "介绍缓存治理" in publication.json()["markdown"]
    finally:
        app.dependency_overrides.pop(get_agent_application, None)


@pytest.mark.asyncio
async def test_question_timeout_isolated_and_resume_reuses_completed_work(
    retrospective_application: AgentApplication,
) -> None:
    target = retrospective_application.job_targets("w1").create_target(
        role_name="后端工程师",
        seniority="3-5 年",
        company_name="示例公司",
        source_url=None,
        idempotency_key="target-isolated-question-timeout",
    )
    service = retrospective_application.interview_retrospectives("w1")
    retrospective = await service.create_retrospective(
        job_target_id=target.id,
        title="逐题超时隔离",
        round_label="一面",
        interview_date=None,
        outcome="unrecorded",
        note="",
        idempotency_key="retrospective-isolated-question-timeout",
    )
    source = service.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="原始转写" * 30,
        file_name=None,
        idempotency_key="source-isolated-question-timeout",
    )
    cleanup = service.service.create_cleanup_version(
        retrospective.id,
        source_version_id=source.id,
        input_digest="f" * 64,
        idempotency_key="cleanup-isolated-question-timeout",
    )
    context = retrospective_application._context("w1")
    cleanup = service.replace_segments(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        segments=tuple(
            {
                "speaker_role": role,
                "raw_speaker_label": label,
                "display_name": label,
                "body": body,
                "source_start": index * 10,
                "source_end": index * 10 + len(body),
                "confidence": 1.0,
                "uncertainty_reason": None,
                "ignored": False,
            }
            for index, (role, label, body) in enumerate(
                (
                    ("interviewer", "面试官", "介绍项目"),
                    ("candidate", "候选人", "我负责项目治理"),
                    ("interviewer", "面试官", "缓存如何恢复"),
                    ("candidate", "候选人", "使用日志补偿"),
                )
            )
        ),
    )
    service.confirm_cleanup(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        idempotency_key="confirm-isolated-question-timeout",
    )
    agents = IsolatedQuestionTimeoutAgents()
    service.agents = agents  # type: ignore[assignment]

    started = await service.start_analysis(
        retrospective.id,
        cleanup_version_id=cleanup.id,
        idempotency_key="analysis-isolated-question-timeout",
    )
    await context.executions.wait(started["executionId"])

    first_run = service.get_analysis_run(retrospective.id, started["analysisRunId"])
    first_items = service.repository.list_analysis_work_items(first_run.id)
    analyses = {
        item.question_unit_id: item
        for item in first_items
        if item.work_key.startswith("question_analysis:")
    }
    ordered_questions = service.list_questions(retrospective.id)

    assert first_run.status == "failed"
    assert agents.analysis_calls == [1, 2, 1], [
        (item.work_key, item.status, item.last_error_code, item.output)
        for item in first_items
    ]
    assert analyses[ordered_questions[0].id].status == "retryable"
    assert analyses[ordered_questions[0].id].attempt_count == 2
    assert analyses[ordered_questions[0].id].last_error_code == "provider_timeout"
    assert analyses[ordered_questions[1].id].status == "completed"
    assert analyses[ordered_questions[1].id].attempt_count == 1
    assert all(
        item.status == "pending"
        for item in first_items
        if item.work_key in {"gap_verification", "candidate_generation", "final_projection"}
    )

    agents.fail_first_question = False
    resumed = await service.resume_analysis(
        retrospective.id,
        first_run.id,
        idempotency_key="resume-isolated-question-timeout",
    )
    await context.executions.wait(resumed["executionId"])
    final = service.get_analysis_run(retrospective.id, first_run.id)
    final_items = service.repository.list_analysis_work_items(first_run.id)
    final_by_key = {item.work_key: item for item in final_items}

    assert final.status == "completed"
    assert agents.analysis_calls == [1, 2, 1, 1]
    assert final_by_key[f"question_analysis:{ordered_questions[0].id}"].attempt_count == 3
    assert final_by_key[f"question_analysis:{ordered_questions[1].id}"].attempt_count == 1
    assert final_by_key["question_extraction:1:4"].attempt_count == 1


@pytest.mark.asyncio
async def test_question_extraction_contract_failure_does_not_retry_full_window(
    retrospective_application: AgentApplication,
) -> None:
    target = retrospective_application.job_targets("w1").create_target(
        role_name="后端工程师",
        seniority="3-5 年",
        company_name=None,
        source_url=None,
        idempotency_key="target-extraction-contract-failure",
    )
    application = retrospective_application.interview_retrospectives("w1")
    retrospective = await application.create_retrospective(
        job_target_id=target.id,
        title="问题提取格式失败",
        round_label="一面",
        interview_date=None,
        outcome="unrecorded",
        note="",
        idempotency_key="retrospective-extraction-contract-failure",
    )
    source = application.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="问：介绍项目。答：我负责缓存治理。",
        file_name=None,
        idempotency_key="source-extraction-contract-failure",
    )
    cleanup = application.service.create_cleanup_version(
        retrospective.id,
        source_version_id=source.id,
        input_digest="e" * 64,
        idempotency_key="cleanup-extraction-contract-failure",
    )
    cleanup = application.replace_segments(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        segments=(
            {
                "speaker_role": "interviewer",
                "raw_speaker_label": "问",
                "display_name": "面试官",
                "body": "介绍项目",
                "source_start": 0,
                "source_end": 6,
                "confidence": 1.0,
                "uncertainty_reason": None,
                "ignored": False,
            },
            {
                "speaker_role": "candidate",
                "raw_speaker_label": "答",
                "display_name": "候选人",
                "body": "我负责缓存治理",
                "source_start": 7,
                "source_end": 15,
                "confidence": 1.0,
                "uncertainty_reason": None,
                "ignored": False,
            },
        ),
    )
    application.confirm_cleanup(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        idempotency_key="confirm-extraction-contract-failure",
    )
    agents = QuestionExtractionContractFailureAgents()
    application.agents = agents  # type: ignore[assignment]

    started = await application.start_analysis(
        retrospective.id,
        cleanup_version_id=cleanup.id,
        idempotency_key="analysis-extraction-contract-failure",
    )
    await retrospective_application._context("w1").executions.wait(
        started["executionId"]
    )

    run = application.get_analysis_run(retrospective.id, started["analysisRunId"])
    extraction = application.repository.list_analysis_work_items(run.id)[0]
    assert run.status == "failed"
    assert agents.extraction_calls == 1
    assert extraction.attempt_count == 1
    assert extraction.status == "retryable"
    assert extraction.last_error_code == "schema_validation_error"


@pytest.mark.asyncio
async def test_analysis_stop_and_resume_keeps_completed_extraction(
    retrospective_application: AgentApplication,
) -> None:
    target = retrospective_application.job_targets("w1").create_target(
        role_name="后端工程师",
        seniority="3-5 年",
        company_name=None,
        source_url=None,
        idempotency_key="target-analysis-resume",
    )
    application = retrospective_application.interview_retrospectives("w1")
    retrospective = await application.create_retrospective(
        job_target_id=target.id,
        title="停止后继续",
        round_label="一面",
        interview_date=None,
        outcome="unrecorded",
        note="",
        idempotency_key="retrospective-analysis-resume",
    )
    source = application.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="问：介绍项目。答：我负责缓存治理。",
        file_name=None,
        idempotency_key="source-analysis-resume",
    )
    cleanup = application.service.create_cleanup_version(
        retrospective.id,
        source_version_id=source.id,
        input_digest="a" * 64,
        idempotency_key="cleanup-analysis-resume",
    )
    cleanup = application.replace_segments(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        segments=(
            {
                "speaker_role": "interviewer",
                "raw_speaker_label": "问",
                "display_name": "面试官",
                "body": "介绍项目",
                "source_start": 0,
                "source_end": 6,
                "confidence": 1.0,
                "uncertainty_reason": None,
                "ignored": False,
            },
            {
                "speaker_role": "candidate",
                "raw_speaker_label": "答",
                "display_name": "候选人",
                "body": "我负责缓存治理",
                "source_start": 7,
                "source_end": 15,
                "confidence": 1.0,
                "uncertainty_reason": None,
                "ignored": False,
            },
        ),
    )
    application.confirm_cleanup(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        idempotency_key="confirm-analysis-resume",
    )
    agents = GatedRetrospectiveAgents()
    application.agents = agents  # type: ignore[assignment]

    started = await application.start_analysis(
        retrospective.id,
        cleanup_version_id=cleanup.id,
        idempotency_key="analysis-resume-start",
    )
    await asyncio.wait_for(agents.analysis_started.wait(), timeout=2)
    run_id = started["analysisRunId"]
    questions_before_stop = application.list_questions(retrospective.id)
    stopped = await application.stop_analysis(
        retrospective.id,
        run_id,
        idempotency_key="analysis-stop",
    )
    stopped_replay = await application.stop_analysis(
        retrospective.id,
        run_id,
        idempotency_key="analysis-stop",
    )
    before_resume = application.repository.list_analysis_work_items(run_id)

    assert stopped.status == "stopped"
    assert stopped_replay.id == stopped.id
    assert [item.question_text for item in questions_before_stop] == ["介绍项目"]
    assert before_resume[0].work_key == "question_extraction:1:2"
    assert before_resume[0].status == "completed"
    assert before_resume[0].attempt_count == 1

    agents.release_analysis.set()
    resumed = await application.resume_analysis(
        retrospective.id,
        run_id,
        idempotency_key="analysis-resume",
    )
    resumed_replay = await application.resume_analysis(
        retrospective.id,
        run_id,
        idempotency_key="analysis-resume",
    )
    assert resumed_replay == resumed
    await retrospective_application._context("w1").executions.wait(
        resumed["executionId"]
    )
    final = application.get_analysis_run(retrospective.id, run_id)
    after_resume = application.repository.list_analysis_work_items(run_id)

    assert final.status == "completed"
    assert after_resume[0].attempt_count == 1
    assert all(item.status == "completed" for item in after_resume)

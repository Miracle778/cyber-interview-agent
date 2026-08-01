from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.agents.interview_retrospective_contracts import CleanupOutput
from app.api.dependencies import get_agent_application
from app.application.workspace_runtime import AgentApplication
from app.main import app


class FakeRetrospectiveAgents:
    async def cleanup_window(
        self,
        *,
        source_kind,
        source_start,
        source_end,
        body,
        context,
        config,
    ):
        del source_kind, context, config
        overlap = 0 if source_start == 0 else min(1_000, len(body) - 1)
        effective_start = source_start + overlap
        return CleanupOutput.model_validate(
            {
                "segments": [
                    {
                        "ordinal": 1,
                        "speakerRole": "interviewer",
                        "rawSpeakerLabel": "面试官",
                        "displayName": "面试官",
                        "text": body[overlap:],
                        "sourceStart": effective_start,
                        "sourceEnd": source_end,
                        "confidence": 0.95,
                        "uncertaintyReason": None,
                    }
                ]
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


@pytest_asyncio.fixture
async def retrospective_application(tmp_path: Path):
    root = tmp_path / "w1"
    root.mkdir()
    application = AgentApplication(
        workspace_resolver=lambda _workspace_id: root,
        workspace_ids=lambda: ("w1",),
        model_bindings=lambda _workspace_id: {
            "retrospective_analysis": "model-1",
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

    assert context.repository.get_session(retrospective.chat_session_id).visibility == "user"
    assert context.repository.get_session(retrospective.analysis_session_id).visibility == "system"
    assert {item.kind for item in sessions} >= {
        "interview.retrospective.chat",
        "interview.retrospective.analysis",
    }


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
    initial = retrospectives.get_cleanup(
        retrospective.id, receipt["cleanupVersionId"]
    )
    await context.executions.wait(receipt["executionId"])
    completed = retrospectives.get_cleanup(
        retrospective.id, receipt["cleanupVersionId"]
    )

    assert initial.execution_id == receipt["executionId"]
    assert initial.status in {"running", "review_pending"}
    assert completed.status == "review_pending"
    assert len(retrospectives.list_segments(retrospective.id, completed.id)) == 1
    assert context.repository.get_execution(receipt["executionId"]).status == "completed"


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
async def test_retrospective_capture_cleanup_and_confirm_api(
    retrospective_application: AgentApplication,
) -> None:
    app.dependency_overrides[get_agent_application] = (
        lambda: retrospective_application
    )
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
                    "body": "面试官：介绍一下缓存治理。",
                },
                headers={"Idempotency-Key": "api-retrospective-source-1"},
            )
            assert source_response.status_code == 201, source_response.text
            source = source_response.json()
            assert "body" not in source

            source_detail = await client.get(
                f"/api/interview-retrospectives/{retrospective['id']}/sources/{source['id']}",
                params={"workspaceId": "w1"},
            )
            assert source_detail.json()["body"] == "面试官：介绍一下缓存治理。"

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
            assert len(cleanup["segments"]) == 1

            current_cleanup = await client.get(
                f"/api/interview-retrospectives/{retrospective['id']}/cleanup-runs/current",
                params={"workspaceId": "w1"},
            )
            assert current_cleanup.status_code == 200
            assert current_cleanup.json()["id"] == cleanup["id"]

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

            listed = await client.get(
                "/api/interview-retrospectives",
                params={"workspaceId": "w1"},
            )
            assert [item["id"] for item in listed.json()] == [
                retrospective["id"]
            ]
    finally:
        app.dependency_overrides.pop(get_agent_application, None)

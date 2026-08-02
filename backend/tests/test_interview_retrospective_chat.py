from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.agents.interview_retrospective_contracts import (
    QuestionAnalysisOutput,
    RetrospectiveChatOutput,
)
from app.application.workspace_runtime import AgentApplication
from app.api.dependencies import get_agent_application
from app.main import app


class FakeDiscussionAgents:
    async def analyze_question(self, **_values):
        return QuestionAnalysisOutput(
            verdict="improvable",
            strengths=[],
            improvements=[],
            omissions=[],
            gaps=[],
            evidence_level="model_judgment",
            confidence=0.7,
            improvement_outline=["补充失败恢复边界"],
            suggested_answer="使用消息表和幂等补偿。",
        )

    async def discuss(
        self, *, message, selected_question_id, conversation, context, config
    ):
        del conversation, context, config
        if message == "为什么这里判断为高风险？":
            return RetrospectiveChatOutput(
                result_type="explanation",
                explanation="因为回答没有说明失败恢复边界。",
            )
        return RetrospectiveChatOutput(
            result_type="question_text_correction",
            question_id=selected_question_id,
            after={"questionText": "如何保证缓存与数据库最终一致？"},
            rationale="用户指出转写后的题目不准确",
        )


class DiscussionGraphFactory:
    def __call__(self, _kind: str, **_dependencies):
        raise AssertionError("retrospective chat uses its bounded background handler")

    def create_interview_retrospective_agents(self, **_dependencies):
        return FakeDiscussionAgents()


@pytest_asyncio.fixture
async def discussion_application(tmp_path: Path):
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
        graph_factory=DiscussionGraphFactory(),
    )
    try:
        yield application
    finally:
        await application.close()


async def _create_retrospective(application: AgentApplication):
    target = application.job_targets("w1").create_target(
        role_name="后端工程师",
        seniority="3-5 年",
        company_name="示例公司",
        source_url=None,
        idempotency_key="chat-target",
    )
    return await application.interview_retrospectives("w1").create_retrospective(
        job_target_id=target.id,
        title="示例公司一面",
        round_label="一面",
        interview_date=None,
        outcome="unrecorded",
        note="",
        idempotency_key="chat-retrospective",
    )


@pytest.mark.asyncio
async def test_explanation_creates_messages_without_new_analysis_version(
    discussion_application: AgentApplication,
) -> None:
    retrospective = await _create_retrospective(discussion_application)
    service = discussion_application.interview_retrospectives("w1")

    execution = await service.send_chat_message(
        retrospective.id,
        message="为什么这里判断为高风险？",
        selected_question_id=None,
    )
    await discussion_application._context("w1").executions.wait(execution.id)
    result = service.conversation(retrospective.id)

    assert [item.role for item in result["messages"]] == ["user", "assistant"]
    assert result["messages"][-1].content == "因为回答没有说明失败恢复边界。"
    assert result["proposals"] == ()
    assert service.repository.current_analysis_run(retrospective.id) is None


@pytest.mark.asyncio
async def test_correction_is_pending_and_does_not_mutate_question(
    discussion_application: AgentApplication,
) -> None:
    retrospective = await _create_retrospective(discussion_application)
    service = discussion_application.interview_retrospectives("w1")
    source = service.service.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="面试官：缓存怎么做？\n候选人：使用消息表。",
        file_name=None,
        idempotency_key="chat-source",
    )
    cleanup = service.service.create_cleanup_version(
        retrospective.id,
        source_version_id=source.id,
        input_digest="a" * 64,
        idempotency_key="chat-cleanup",
    )
    cleanup = service.service.replace_segments(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        segments=(
            {
                "speaker_role": "interviewer",
                "raw_speaker_label": "面试官",
                "display_name": "面试官",
                "body": "缓存怎么做？",
                "source_start": 0,
                "source_end": 7,
                "confidence": 1.0,
                "uncertainty_reason": None,
                "ignored": False,
            },
            {
                "speaker_role": "candidate",
                "raw_speaker_label": "候选人",
                "display_name": "我",
                "body": "使用消息表。",
                "source_start": 8,
                "source_end": 14,
                "confidence": 1.0,
                "uncertainty_reason": None,
                "ignored": False,
            },
        ),
    )
    cleanup = service.service.confirm_cleanup(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        idempotency_key="chat-confirm-cleanup",
    )
    run = service.service.create_analysis_run(
        retrospective.id,
        cleanup.id,
        input_digest="b" * 64,
        context_snapshot={},
        idempotency_key="chat-analysis",
    )
    segments = service.repository.list_segments(cleanup.id)
    question = service.repository.replace_question_units(
        run.id,
        questions=(
            {
                "ordinal": 1,
                "question_kind": "technical_knowledge",
                "origin": "original",
                "question_text": "缓存怎么做？",
                "question_segment_ids": (segments[0].id,),
                "answer_segment_ids": (segments[1].id,),
                "inference_basis": "",
                "confidence": 1.0,
            },
        ),
    )[0]
    service.repository.mark_analysis_completed(run.id, summary={})

    execution = await service.send_chat_message(
        retrospective.id,
        message="题目其实问的是最终一致性",
        selected_question_id=question.id,
    )
    await discussion_application._context("w1").executions.wait(execution.id)
    proposals = service.repository.list_correction_proposals(retrospective.id)

    assert len(proposals) == 1
    assert proposals[0].status == "pending"
    assert proposals[0].expected_version == question.version
    assert service.repository.get_question(question.id).question_text == "缓存怎么做？"

    confirmed = await service.decide_correction(
        retrospective.id, proposals[0].id, decision="confirmed"
    )
    assert confirmed.status == "confirmed"
    assert (
        service.repository.get_question(question.id).question_text
        == "如何保证缓存与数据库最终一致？"
    )
    assert [
        item.work_key
        for item in service.repository.list_analysis_work_items(
            confirmed.resulting_analysis_run_id
        )
    ] == [
        f"question_analysis:{question.id}",
        "gap_verification",
        "candidate_generation",
        "final_projection",
    ]


@pytest.mark.asyncio
async def test_conversation_api_returns_execution_and_messages(
    discussion_application: AgentApplication,
) -> None:
    retrospective = await _create_retrospective(discussion_application)
    app.dependency_overrides[get_agent_application] = lambda: discussion_application
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/api/interview-retrospectives/{retrospective.id}/conversation/messages",
                json={
                    "workspaceId": "w1",
                    "message": "为什么这里判断为高风险？",
                    "selectedQuestionId": None,
                },
            )
            assert response.status_code == 202
            execution_id = response.json()["executionId"]
            await discussion_application._context("w1").executions.wait(execution_id)

            result = await client.get(
                f"/api/interview-retrospectives/{retrospective.id}/conversation",
                params={"workspaceId": "w1"},
            )
            assert result.status_code == 200
            assert [item["role"] for item in result.json()["messages"]] == [
                "user",
                "assistant",
            ]
            assert result.json()["latestExecution"]["status"] == "completed"
    finally:
        app.dependency_overrides.pop(get_agent_application, None)

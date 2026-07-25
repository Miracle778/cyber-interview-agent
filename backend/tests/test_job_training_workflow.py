from pathlib import Path

import pytest
from langgraph.graph import END, START, StateGraph

from app.application.workspace_runtime import AgentApplication
from app.graphs.project_deep_dive import ProjectDeepDiveState
from app.tools.job_target_tools import ScopedJobTargetReader, ToolScopeViolation
from app.agents.review_round_contracts import RoundAnswerEvaluation


def _graph_factory(_kind: str, **dependencies):
    graph = StateGraph(dict)
    graph.add_node("complete", lambda state: state)
    graph.add_edge(START, "complete")
    graph.add_edge("complete", END)
    return graph.compile(checkpointer=dependencies.get("checkpointer"))


@pytest.mark.asyncio
async def test_analysis_deep_dive_and_project_question_library(tmp_path: Path):
    root = tmp_path / "w1"
    root.mkdir()
    application = AgentApplication(
        workspace_resolver=lambda _workspace_id: root,
        workspace_ids=lambda: ("w1",),
        model_bindings=lambda _workspace_id: {},
        graph_factory=_graph_factory,
    )
    try:
        profile = application.profile("w1")
        project = profile.create_profile_card(
            claim_type="project",
            value={
                "name": "订单系统",
                "background": "高并发交易系统",
                "tech_stack": ["Python", "Redis"],
            },
            command_id="project-workflow-1",
        )
        targets = application.job_targets("w1")
        target = targets.create_target(
            role_name="高级后端工程师",
            seniority="5-8 年",
            company_name="示例公司",
            source_url=None,
            idempotency_key="target-workflow-1",
        )
        document = targets.create_document_version(
            target.id,
            source_kind="jd_text",
            body="负责高并发服务设计\n熟悉 Python 与 Redis\n具备大型项目经验",
            idempotency_key="document-workflow-1",
        )
        target = targets.confirm_document_version(
            target.id,
            document.id,
            expected_version=target.version,
            idempotency_key="confirm-workflow-1",
        )
        training = application.job_training("w1")
        analysis = await training.start_analysis(target.id)
        assert analysis["status"] == "review_pending"
        assert analysis["progress"]["completed"] == analysis["progress"]["total"]
        assert analysis["savedOutputs"]["requirements"] == 3

        target = targets.get_target(target.id)
        targets.set_project_priorities(
            target.id,
            core_project_id=project.claim_id,
            supplementary_project_ids=(),
            expected_version=target.version,
            idempotency_key="priorities-workflow-1",
        )
        dive = await training.create_deep_dive(target.id, project.claim_id)
        original = training.product_repository.append_user_message(
            dive["sessionId"],
            content="项目背景是交易链路扩容，我负责核心服务设计、压测与上线复盘，并记录指标变化。",
        )
        training.product_repository.resolve_message(
            original.id, expected=("active",), target="unresolved"
        )
        previous = await training.executions.prepare_for_message(
            training.product_repository.get_session(dive["sessionId"]),
            input_message_id=original.id,
            input={"message": original.content, "deepDiveId": dive["id"]},
            configuration={"providerModelId": None, "reasoningEffort": "none"},
        )
        await training.executions.cancel(previous.id)
        training.repository.transition_deep_dive(dive["id"], "paused")
        dive = await training.control_deep_dive(dive["id"], "resume")
        assert [item["content"] for item in dive["messages"] if item["role"] == "user"] == [original.content]
        resumed_execution = dive["executions"][-1]
        assert resumed_execution["retryOfExecutionId"] == previous.id
        first_artifact = dive["artifacts"][0]
        narrative = training.confirm_narrative_sections(
            first_artifact["id"],
            section_ids=("background",),
            edited_values={},
            expected_project_version=1,
            idempotency_key="confirm-narrative-workflow-1",
        )
        assert narrative["confirmedSectionIds"] == ["background"]
        assert profile.repository.get_claim(project.claim_id).version == 2
        for index in range(6):
            dive = await training.answer_deep_dive(
                dive["id"],
                f"第 {index + 1} 个维度：我负责核心链路设计、压测和上线复盘，并记录了指标变化。",
            )
        assert dive["status"] == "completed"
        assert len(dive["questionCandidates"]) == 6

        first = dive["questionCandidates"][0]
        training.decide_question_candidate(first["id"], "confirmed")
        questions = application.review("w1").list_questions()
        project_question = next(item for item in questions if item.question_type == "project_experience")
        assert project_question.project_claim_id == project.claim_id
        assert "项目经历" in project_question.snapshot.topics
    finally:
        await application.close()


def test_deep_dive_state_is_bounded_and_tools_enforce_manifest():
    assert set(ProjectDeepDiveState.__annotations__) == {
        "job_target_id",
        "project_claim_id",
        "session_id",
        "execution_id",
        "current_stage",
        "current_question_id",
        "completed_stage_ids",
        "follow_up_ids",
        "waiting_for_input",
        "pause_requested",
        "end_requested",
    }
    reader = ScopedJobTargetReader(
        target_id="target-1",
        allowed_project_ids=frozenset({"project-1"}),
        get_target=lambda value: value,
        get_project=lambda value: value,
    )
    assert reader.read_project("project-1") == "project-1"
    with pytest.raises(ToolScopeViolation):
        reader.read_project("project-other")

    evaluation = RoundAnswerEvaluation(
        score="good",
        missing_key_points=[],
        evidence="回答具体但与已确认职责冲突",
        follow_up_required=False,
        follow_up_prompt=None,
        mastery_suggestion="stable",
        project_dimensions={
            "factual_consistency": "conflict",
            "specificity": "stable",
            "structural_completeness": "basic",
            "follow_up_resilience": "pending",
        },
        fact_conflict="用户声称独立负责，但画像记录为协作完成",
        project_mastery="stable",
    )
    assert evaluation.project_mastery == "pending"

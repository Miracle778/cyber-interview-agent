from collections.abc import AsyncIterator

import pytest

from app.hitl.models import ResolveActionCommand
from app.providers.chat_gateway import (
    ChatModelGateway,
    ProviderInvocationError,
    ResolvedModelBinding,
)
from app.providers.base import ProviderErrorCode
from app.runtime.default_graphs import create_default_graph_registry
from app.runtime.service import AgentRuntime


QUESTION = {
    "id": "q1",
    "title": "事务特性",
    "questionText": "什么是事务的 ACID？",
    "referenceAnswer": "原子性、一致性、隔离性、持久性",
    "topics": ["database"],
    "difficulty": "medium",
    "keyPoints": ["原子性", "一致性", "隔离性", "持久性"],
    "followUps": [],
    "mastery": "weak",
}


class FakeAdapter:
    async def invoke_structured(self, **_kwargs):
        return {
            "score": "partial",
            "missing_key_points": ["隔离性", "持久性"],
            "evidence": "回答包含原子性",
        }

    async def stream_text(self, **_kwargs) -> AsyncIterator[str]:
        yield "# 单题复习报告\n\n- 评分：partial\n"


def _runtime(
    tmp_path, bindings: dict[str, str], adapter: object | None = None
) -> AgentRuntime:
    def resolve(role: str, provider_model_id: str):
        return ResolvedModelBinding(
            role=role,
            provider_id="provider-1",
            provider_model_id=provider_model_id,
            api_format="fake",
            base_url="https://example.test",
            model_id=f"model-for-{role}",
            api_key="secret",
        )

    return AgentRuntime(
        graph_registry=create_default_graph_registry(),
        workspace_resolver=lambda _workspace_id: tmp_path,
        model_binding_resolver=lambda _workspace_id: dict(bindings),
        workspace_ids=lambda: ("w1",),
        chat_gateway=ChatModelGateway({"fake": adapter or FakeAdapter()}),
        resolve_model_binding=resolve,
    )


@pytest.mark.asyncio
async def test_review_runtime_persists_draft_waits_and_rejects(tmp_path) -> None:
    bindings = {
        "answer_evaluation": "evaluation-model-pk",
        "report_summarization": "report-model-pk",
    }
    runtime = _runtime(tmp_path, bindings)
    session = await runtime.create_session(
        workspace_id="w1",
        graph_id="review.single",
        graph_version=1,
        title="单题复习",
    )
    run = await runtime.start_run(
        session.id,
        input={"question": QUESTION, "user_answer": "事务保证原子性"},
    )
    waiting = await runtime.wait_run(run.id)

    assert waiting.status == "waiting_for_approval"
    assert waiting.model_bindings == bindings
    drafts = await runtime.list_drafts("w1")
    assert len(drafts) == 1
    assert drafts[0]["status"] == "review_pending"
    assert drafts[0]["session_id"] == session.id
    assert drafts[0]["run_id"] == run.id
    action = (await runtime.list_actions("w1", status="pending"))[0]
    assert action.action_type == "knowledge.publish"

    await runtime.reject_action(
        action.id,
        ResolveActionCommand(
            version=action.version,
            idempotency_key="reject-review-1",
            reason="先补充内容",
        ),
    )
    completed = await runtime.wait_run(run.id)

    assert completed.status == "completed"
    assert (await runtime.get_draft(drafts[0]["id"]))["status"] == "rejected"
    detail = await runtime.session_detail(session.id)
    assert detail["messages"][-1]["content"] == "单题复习报告未发布：先补充内容"
    await runtime.close()


@pytest.mark.asyncio
async def test_review_waiting_action_survives_runtime_restart(tmp_path) -> None:
    bindings = {
        "answer_evaluation": "evaluation-model-pk",
        "report_summarization": "report-model-pk",
    }
    first = _runtime(tmp_path, bindings)
    session = await first.create_session(
        workspace_id="w1", graph_id="review.single", graph_version=1,
        title="单题复习",
    )
    run = await first.start_run(
        session.id,
        input={"question": QUESTION, "user_answer": "事务保证原子性"},
    )
    assert (await first.wait_run(run.id)).status == "waiting_for_approval"
    await first.close()

    restored = _runtime(tmp_path, bindings)
    await restored.recover_interrupted_runs()
    action = (await restored.list_actions("w1", status="pending"))[0]
    await restored.reject_action(
        action.id,
        ResolveActionCommand(
            version=action.version,
            idempotency_key="reject-after-restart",
            reason="重启后拒绝",
        ),
    )

    assert (await restored.wait_run(run.id)).status == "completed"
    await restored.close()


@pytest.mark.asyncio
async def test_provider_failure_is_sanitized_in_run_and_event(tmp_path) -> None:
    class FailingAdapter(FakeAdapter):
        async def invoke_structured(self, **_kwargs):
            raise ProviderInvocationError(
                ProviderErrorCode.AUTH_FAILED, "raw-secret-provider-body"
            )

    bindings = {
        "answer_evaluation": "evaluation-model-pk",
        "report_summarization": "report-model-pk",
    }
    runtime = _runtime(tmp_path, bindings, FailingAdapter())
    session = await runtime.create_session(
        workspace_id="w1", graph_id="review.single", graph_version=1,
        title="单题复习",
    )
    run = await runtime.start_run(
        session.id,
        input={"question": QUESTION, "user_answer": "回答"},
    )
    failed = await runtime.wait_run(run.id)

    assert failed.status == "failed"
    assert failed.error_code == "auth_failed"
    assert failed.error_message == "API Key 无效或已过期"
    assert "raw-secret-provider-body" not in repr(failed)
    await runtime.close()


@pytest.mark.asyncio
async def test_review_start_rejects_missing_required_binding(tmp_path) -> None:
    runtime = _runtime(tmp_path, {"answer_evaluation": "model-pk"})
    session = await runtime.create_session(
        workspace_id="w1",
        graph_id="review.single",
        graph_version=1,
        title="单题复习",
    )

    with pytest.raises(RuntimeError, match="report_summarization"):
        await runtime.start_run(
            session.id,
            input={"question": QUESTION, "user_answer": "回答"},
        )

    assert (await runtime.session_detail(session.id))["latestRun"] is None
    await runtime.close()

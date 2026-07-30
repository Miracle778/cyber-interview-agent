from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.question_curation_contracts import QuestionSeedChunk
from app.application.workspace_runtime import AgentApplication
from app.graphs.publication import create_publication_graph
from app.graphs.question_curation import create_question_curation_graph
from app.knowledge.source_registry import KnowledgeSourceService
from app.review.errors import ReviewConflictError
from tests.test_review_api_v2 import _graph_factory


class TemporaryProviderFailure(RuntimeError):
    status_code = 503


class MessyNotesProvider:
    def __init__(self) -> None:
        self.enrichment_calls: list[tuple[str, ...]] = []
        self._transport_failed = False
        self._malformed_failed = False

    async def discover(self, sections, *, context, config, unit_index):
        return QuestionSeedChunk(seeds=[])

    async def enrich(
        self, seeds, *, sections, known_questions, context, config, unit_index
    ):
        questions = tuple(seed.question_text for seed in seeds)
        self.enrichment_calls.append(questions)
        if any("网络抖动" in question for question in questions) and not self._transport_failed:
            self._transport_failed = True
            raise TemporaryProviderFailure("temporary provider outage")
        if any("格式损坏" in question for question in questions) and not self._malformed_failed:
            self._malformed_failed = True
            return {"candidates": "not-a-list"}

        candidates = []
        for seed in seeds:
            if "答案缺失" in seed.question_text:
                continue
            refs = list(seed.source_refs)
            if "跨引用" in seed.question_text:
                refs = ["forged-source#section-9999"]
            mixed = "需要补全" in seed.question_text
            candidates.append({
                "seed_key": seed.seed_key,
                "title": None if "格式损坏" in seed.question_text else seed.question_text,
                "question_text": seed.question_text,
                "source_answer": "材料只记录了核心结论。",
                "supplemental_answer": "AI 补充了边界条件。" if mixed else None,
                "topics": "工程实践" if mixed else ["工程实践", None],
                "difficulty": "medium",
                "key_points": "核心结论" if mixed else ["核心结论", None],
                "follow_ups": None,
                "source_refs": [*reversed(refs), None],
                "correction_note": "请核对随手记上下文",
            })
        return {"candidates": candidates}

    async def revise(self, **_kwargs):
        raise AssertionError("acceptance scenario must not invoke revision")


@pytest.mark.asyncio
async def test_messy_notes_preserve_partial_results_and_block_unsafe_publication(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    provider = MessyNotesProvider()

    def graph_factory(kind, **dependencies):
        if kind in {"question.curate", "question.revise"}:
            return create_question_curation_graph(
                provider,
                repository=dependencies["review_repository"],
                checkpointer=dependencies["checkpointer"],
            )
        if kind == "knowledge.publish":
            return create_publication_graph(
                request_action=dependencies["create_action"],
                checkpointer=dependencies["checkpointer"],
            )
        return _graph_factory(kind, **dependencies)

    app = AgentApplication(
        workspace_resolver=lambda _workspace_id: workspace,
        workspace_ids=lambda: ("w1",),
        model_bindings=lambda _workspace_id: {},
        graph_factory=graph_factory,
    )
    sources = KnowledgeSourceService(workspace, workspace_id="w1")
    messy = await sources.create(
        original_filename="随手记.md",
        content_type="text/markdown",
        content=(
            "# 零散复习记录\n\n"
            "TODO: Redis 持久化再确认；下面夹着日志和代码。\n"
            "```python\nretry = min(retry + 1, 2)\n```\n"
            "2026-07-22 ERROR connection reset by peer\n\n"
            "1、稳定问题的处理边界是什么？\n答案：先保存进度。\n"
            "2、需要补全的问题如何处理？\n只记了：保留来源。\n"
            "3、答案缺失的问题怎么办？\n"
            "4、跨引用问题如何防止污染？\n答案：校验引用。\n"
            "5、格式损坏响应如何恢复？\n答案：单题回退。\n"
            "6、网络抖动时如何避免重放？\n答案：提交后落盘。\n"
            "7、重复主题问题如何归并？\n答案：稳定去重。\n"
            "8、暂停后如何继续？\n答案：读取持久状态。\n"
            "9、终止后保留什么？\n答案：保留已完成产物。\n"
            "10、日志时间如何展示？\n答案：统一北京时间。\n"
        ).encode("utf-8"),
    )
    unusable = await sources.create(
        original_filename="乱码.txt",
        content_type="text/plain",
        content=b"\xff\xfe\x00\x81",
    )

    try:
        review = app.review("w1")
        created = await review.create_curation_session(
            source_refs=(messy.id, unusable.id)
        )
        execution = await app.wait_execution(str(created["execution_id"]))
        assert execution.status == "completed"

        resource = await review.curation_resource(str(created["id"]))
        batch = review.repository.get_batch(str(created["active_batch_id"]))
        seeds = review.repository.list_curation_seed_tasks(batch.id)
        candidates = review.repository.list_candidates("w1")
        call_count = len(provider.enrichment_calls)

        assert batch.status == "review_pending"
        assert len(candidates) >= 6
        assert resource["seed_progress"]["skipped"] >= 2
        assert resource["quality_summary"]["mixed"] >= 1
        assert any(item["sourceId"] == unusable.id for item in resource["source_warnings"])
        assert all(seed.status in {"completed", "degraded", "skipped"} for seed in seeds)
        assert any(len(call) == 1 for call in provider.enrichment_calls)

        await app.recover()
        await review.curation_resource(str(created["id"]))
        assert len(provider.enrichment_calls) == call_count

        skipped = next(seed for seed in seeds if seed.status == "skipped")
        accepted = await review.retry_curation_seed_task(
            str(created["id"]),
            seed_task_id=skipped.id,
            expected_version=skipped.version,
            idempotency_key="messy-notes-seed-retry-0001",
        )
        await app.wait_execution(str(accepted["execution_id"]))

        seed_events = [
            event for event in app.replay_events(str(created["id"]), after_id=None)
            if event.type == "curation.seed.changed"
        ]
        assert seed_events
        assert all(
            not ({"questionText", "referenceAnswer", "sourceRefs", "path"} & set(event.payload))
            for event in seed_events
        )

        ai_candidate = next(item for item in candidates if item.answer_basis == "mixed")
        with pytest.raises(ReviewConflictError, match="requires explicit confirmation"):
            await review.publish_candidate(
                ai_candidate.id,
                idempotency_key="messy-publish-without-confirmation-0001",
            )
    finally:
        await app.close()

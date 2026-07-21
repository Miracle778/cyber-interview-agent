import logging

import pytest

from app.agents.review_contracts import AnswerEvaluation
from app.agents.question_curation_contracts import (
    QuestionCandidate,
    QuestionCandidateBatch,
)
from app.agents.review_round_contracts import (
    ReviewSessionReportOutput,
    RoundAnswerEvaluation,
)
from app.agents.profile_contracts import (
    ProfileAssessmentOutput,
    ProfileClaimCandidate,
    ProfileExtractionOutput,
)
from app.infrastructure.checkpoints import AgentCheckpointer


@pytest.mark.asyncio
async def test_checkpoint_serializer_explicitly_allows_review_contract(
    tmp_path, caplog
) -> None:
    (tmp_path / ".cyber-interview-agent").mkdir()
    evaluation = AnswerEvaluation(
        score="good",
        missing_key_points=[],
        evidence="覆盖关键点",
    )

    caplog.set_level(logging.WARNING, logger="langgraph.checkpoint.serde.jsonplus")
    async with AgentCheckpointer(tmp_path).open() as saver:
        payload = saver.serde.dumps_typed(evaluation)
        restored = saver.serde.loads_typed(payload)

    assert restored == evaluation
    assert "unregistered type" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    [
        RoundAnswerEvaluation(
            score="partial",
            missing_key_points=["边界"],
            evidence="覆盖定义",
            follow_up_required=True,
            follow_up_prompt="请补充边界",
            mastery_suggestion="partial",
        ),
        QuestionCandidateBatch(
            candidates=[
                QuestionCandidate(
                    title="MVCC",
                    question_text="什么是 MVCC？",
                    reference_answer="多版本并发控制",
                    topics=["database"],
                    difficulty="medium",
                    key_points=["版本链"],
                    follow_ups=[],
                    source_refs=["source-1"],
                    correction_note="结构化原题",
                )
            ]
        ),
        ReviewSessionReportOutput(
            title="复习报告",
            markdown="# 复习报告",
            mastery_explanation="继续练习",
        ),
    ],
)
async def test_checkpoint_serializer_allows_review_domain_contracts(
    tmp_path, caplog, value
) -> None:
    (tmp_path / ".cyber-interview-agent").mkdir()
    caplog.set_level(logging.WARNING, logger="langgraph.checkpoint.serde.jsonplus")
    async with AgentCheckpointer(tmp_path).open() as saver:
        restored = saver.serde.loads_typed(saver.serde.dumps_typed(value))

    assert restored == value
    assert "not in allowed_msgpack_modules" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    [
        ProfileExtractionOutput(
            candidates=[
                ProfileClaimCandidate(
                    category="skill",
                    value={"text": "Python"},
                    evidence_ids=["ev-1"],
                    confidence=0.9,
                    rationale="Evidence grounded",
                )
            ]
        ),
        ProfileAssessmentOutput(summary="Profile assessment"),
    ],
)
async def test_checkpoint_serializer_allows_profile_structured_contracts(
    tmp_path, caplog, value
) -> None:
    (tmp_path / ".cyber-interview-agent").mkdir()
    caplog.set_level(logging.WARNING, logger="langgraph.checkpoint.serde.jsonplus")
    async with AgentCheckpointer(tmp_path).open() as saver:
        restored = saver.serde.loads_typed(saver.serde.dumps_typed(value))

    assert restored == value
    assert "not in allowed_msgpack_modules" not in caplog.text

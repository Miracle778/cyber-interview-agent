import logging

import pytest

from app.agents.review_contracts import AnswerEvaluation
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

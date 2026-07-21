from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


_CHECKPOINT_TYPE_ALLOWLIST = (
    ("app.agents.profile_contracts", "ProfileAssessmentOutput"),
    ("app.agents.profile_contracts", "ProfileExtractionOutput"),
    ("app.agents.profile_contracts", "ProfileClaimCandidate"),
    ("app.agents.profile_contracts", "ProfileAssessmentRecommendation"),
    ("app.agents.profile_contracts", "ProfileAssessmentProposal"),
    ("app.agents.profile_contracts", "ProfileActionPlanProposal"),
    ("app.agents.profile_contracts", "ProfileActionPlanItemProposal"),
    ("app.agents.review_contracts", "AnswerEvaluation"),
    ("app.agents.question_curation_contracts", "QuestionCandidateBatch"),
    ("app.agents.review_round_contracts", "RoundAnswerEvaluation"),
    ("app.agents.review_round_contracts", "ReviewSessionReportOutput"),
)


class AgentCheckpointer:
    def __init__(self, workspace_root: Path) -> None:
        self._database_path = (
            Path(workspace_root)
            / ".cyber-interview-agent"
            / "checkpoints.sqlite"
        )

    @asynccontextmanager
    async def open(self) -> AsyncIterator[AsyncSqliteSaver]:
        connection = await aiosqlite.connect(self._database_path)
        try:
            await connection.execute("PRAGMA busy_timeout = 5000")
            saver = AsyncSqliteSaver(
                connection,
                serde=JsonPlusSerializer(
                    allowed_msgpack_modules=_CHECKPOINT_TYPE_ALLOWLIST
                ),
            )
            await saver.setup()
            yield saver
        finally:
            await connection.close()

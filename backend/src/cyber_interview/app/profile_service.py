from cyber_interview.app.run_service import AgentRunService


class ProfileService:
    """Entry point for creating Profile runs with artifact reuse."""

    def __init__(self, run_service: AgentRunService):
        self._run = run_service

    async def create_run(self, *, input_text: str) -> str:
        artifact_id = await self._run._ensure_artifact()
        return await self._run.create_run(artifact_id=artifact_id, input_text=input_text)

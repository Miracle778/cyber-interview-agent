from __future__ import annotations

from app.agents.job_target_contracts import DeepDiveTurnResult, JobRequirementExtraction


class JobTargetAgents:
    """Structured model boundary. Callers own persistence and validate every result."""

    def __init__(self, *, analyze, deep_dive) -> None:
        self._analyze = analyze
        self._deep_dive = deep_dive

    async def extract_requirements(self, prompt: str) -> JobRequirementExtraction:
        return JobRequirementExtraction.model_validate(await self._analyze(prompt))

    async def evaluate_turn(self, prompt: str) -> DeepDiveTurnResult:
        return DeepDiveTurnResult.model_validate(await self._deep_dive(prompt))

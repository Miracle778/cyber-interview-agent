import uuid
from collections.abc import Callable

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from cyber_interview.domain.artifact import ArtifactStatus
from cyber_interview.domain.constants import DEFAULT_WORKSPACE_ID
from cyber_interview.domain.errors import ErrorCategory, OutputError
from cyber_interview.domain.run import RunStatus, transition_run
from cyber_interview.harness.gates import GateError, OutputGate, RunGate
from cyber_interview.harness.model_gateway import Message
from cyber_interview.harness.output_parser import FinalOutputResult
from cyber_interview.harness.runtime import AgentRuntime, RunContext, RuntimeOutput
from cyber_interview.harness.task_registry import TaskRegistry
from cyber_interview.infra.models import AgentRunRow, RunAttemptRow
from cyber_interview.infra.repositories import (
    ArtifactRepository,
    ArtifactVersionRepository,
    RunEventRepository,
    _now,
)

SessionFactory = Callable[[], AsyncSession]

# spec §6.1: prompt 明确指示模型只输出 ProfileVersion JSON，不要 markdown 围栏。
# DU03+ 有 AgentDefinition 时，prompt 会移到 agent 定义里；DU01 硬编码这一个。
SYSTEM_PROMPT = (
    "你是一个 Profile 抽取助手。从用户提供的文本中抽取 1-3 条关键事实。\n"
    "只输出符合以下 JSON schema 的 JSON，不要 markdown 围栏，不要任何解释：\n"
    '{"schema_name": "profile", "schema_version": 1, '
    '"facts": [{"claim": "...", "evidence_ref": null}]}\n'
    "facts 长度 1-3，每条 claim 非空。"
)


class AgentRunService:
    def __init__(
        self,
        session_factory: SessionFactory,
        runtime: AgentRuntime,
        registry: TaskRegistry,
        *,
        provider: str = "openai",
        model: str = "gpt-4o-mini",
    ):
        self._sf = session_factory
        self._runtime = runtime
        self._registry = registry
        self._provider = provider
        self._model = model
        self._gate = RunGate()
        self._output_gate = OutputGate()

    async def _ensure_artifact(self) -> str:
        async with self._sf() as s:
            art = await ArtifactRepository(s).get_or_create_profile(DEFAULT_WORKSPACE_ID)
            await s.commit()
            return art.id

    async def create_run(self, *, artifact_id: str, input_text: str) -> str:
        run_id = str(uuid.uuid4())
        now = _now()
        try:
            self._gate.check(input_text=input_text, artifact_kind="profile")
        except GateError as exc:
            await self._fail_run_pre_dispatch(run_id, artifact_id, input_text, now, exc)
            return run_id

        async with self._sf() as s:
            run = AgentRunRow(
                id=run_id,
                artifact_id=artifact_id,
                workspace_id=DEFAULT_WORKSPACE_ID,
                status=RunStatus.QUEUED.value,
                input_text=input_text,
                created_at=now,
            )
            attempt = RunAttemptRow(
                id=str(uuid.uuid4()),
                run_id=run_id,
                attempt_no=1,
                status=RunStatus.QUEUED.value,
            )
            s.add(run)
            s.add(attempt)
            await s.commit()
        self._registry.create(run_id, self._execute(run_id, artifact_id, input_text))
        return run_id

    async def _execute(self, run_id: str, artifact_id: str, input_text: str) -> None:
        try:
            attempt_id = await self._transition_to_running(run_id)
            ctx = RunContext(
                run_id=run_id,
                attempt_id=attempt_id,
                provider=self._provider,
                model=self._model,
                messages=[
                    Message(role="system", content=SYSTEM_PROMPT),
                    Message(role="user", content=input_text),
                ],
            )
            final: FinalOutputResult | None = None
            seen_final = False
            async with self._sf() as s:
                ev_repo = RunEventRepository(s)
                async for out in self._runtime.run(ctx):
                    if isinstance(out, RuntimeOutput.Delta):
                        if seen_final:
                            raise RuntimeError("runtime emitted delta after final")
                        await ev_repo.append(run_id, "delta", {"text": out.text})
                        await s.commit()
                    elif isinstance(out, RuntimeOutput.Final):
                        if seen_final:
                            raise RuntimeError("runtime emitted multiple final outputs")
                        seen_final = True
                        final = out.result
            if final is None:
                final = FinalOutputResult(
                    error=OutputError(
                        category=ErrorCategory.MODEL,
                        safe_message="runtime 未产出 FinalOutputResult",
                    )
                )
            await self._finalize(run_id, artifact_id, final)
        except Exception as exc:
            await self._finalize(
                run_id,
                artifact_id,
                FinalOutputResult(
                    error=OutputError(category=ErrorCategory.INTERNAL, safe_message=str(exc))
                ),
            )

    async def _transition_to_running(self, run_id: str) -> str:
        async with self._sf() as s:
            run = await s.get(AgentRunRow, run_id)
            if run is None:
                raise ValueError("run not found")
            run.status = transition_run(RunStatus(run.status), RunStatus.RUNNING).value
            attempt = (
                await s.execute(select(RunAttemptRow).where(RunAttemptRow.run_id == run_id))
            ).scalar_one()
            attempt.status = RunStatus.RUNNING.value
            attempt.started_at = _now()
            await s.commit()
            return attempt.id

    async def _finalize(self, run_id: str, artifact_id: str, result: FinalOutputResult) -> None:
        try:
            self._output_gate.validate(result)
        except GateError:
            await self._fail(
                run_id,
                result.error
                or OutputError(category=ErrorCategory.POLICY, safe_message="output gate rejected"),
            )
            return
        await self._succeed(run_id, artifact_id, result)

    async def _succeed(self, run_id: str, artifact_id: str, result: FinalOutputResult) -> None:
        if result.profile is None:
            await self._fail(
                run_id,
                OutputError(category=ErrorCategory.POLICY, safe_message="无 profile 输出"),
            )
            return
        content = result.profile.model_dump_json()
        async with self._sf() as s:
            await s.execute(text("BEGIN IMMEDIATE"))
            vrepo = ArtifactVersionRepository(s)
            version_no = await vrepo.next_version_no(artifact_id)
            version = await vrepo.create_draft(artifact_id, version_no, content)
            await vrepo.set_status(version.id, ArtifactStatus.PENDING_APPROVAL.value)
            run = await s.get(AgentRunRow, run_id)
            if run is None:
                raise ValueError("run not found")
            run.status = transition_run(RunStatus(run.status), RunStatus.COMPLETED).value
            run.completed_at = _now()
            attempt = (
                await s.execute(select(RunAttemptRow).where(RunAttemptRow.run_id == run_id))
            ).scalar_one()
            attempt.status = RunStatus.COMPLETED.value
            attempt.ended_at = _now()
            await RunEventRepository(s).append(
                run_id, "completed", {"artifact_version_id": version.id}
            )
            await s.commit()

    async def _fail(self, run_id: str, error: OutputError) -> None:
        async with self._sf() as s:
            run = await s.get(AgentRunRow, run_id)
            if run is None:
                return
            run.status = transition_run(RunStatus(run.status), RunStatus.FAILED).value
            run.completed_at = _now()
            attempt = (
                await s.execute(select(RunAttemptRow).where(RunAttemptRow.run_id == run_id))
            ).scalar_one()
            attempt.status = RunStatus.FAILED.value
            attempt.ended_at = _now()
            await RunEventRepository(s).append(
                run_id,
                "failed",
                {
                    "category": error.category.value,
                    "safe_message": error.safe_message,
                    "diagnostic_id": str(uuid.uuid4()),
                },
            )
            await s.commit()

    async def _fail_run_pre_dispatch(
        self, run_id: str, artifact_id: str, input_text: str, now: int, gate_err: GateError
    ) -> None:
        async with self._sf() as s:
            run = AgentRunRow(
                id=run_id,
                artifact_id=artifact_id,
                workspace_id=DEFAULT_WORKSPACE_ID,
                status=RunStatus.FAILED.value,
                input_text=input_text,
                created_at=now,
                completed_at=now,
            )
            attempt = RunAttemptRow(
                id=str(uuid.uuid4()),
                run_id=run_id,
                attempt_no=1,
                status=RunStatus.FAILED.value,
                ended_at=now,
            )
            s.add(run)
            s.add(attempt)
            await RunEventRepository(s).append(
                run_id,
                "failed",
                {"category": gate_err.category.value, "safe_message": str(gate_err)},
            )
            await s.commit()

    async def _await_completion(self, run_id: str) -> None:
        task = self._registry._tasks.get(run_id)
        if task is not None:
            await task

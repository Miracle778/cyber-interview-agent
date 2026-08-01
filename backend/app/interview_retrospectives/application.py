from __future__ import annotations

import hashlib
import json

from app.agents.context import AgentContext
from app.agents.interview_retrospective_agents import InterviewRetrospectiveAgents
from app.application.execution_service import (
    AgentExecutionService,
    ExecutionCancellation,
)
from app.application.session_service import (
    AgentSessionService,
    ExecutionRecord,
    ProductRepository,
)
from app.graphs.interview_retrospective_cleanup import (
    create_source_windows,
    reduce_cleanup_segments,
)
from app.interview_retrospectives.errors import (
    RetrospectiveIdempotencyConflict,
    RetrospectiveModelNotConfigured,
    RetrospectiveSourceCleared,
    RetrospectiveTargetRequired,
)
from app.interview_retrospectives.repository import (
    InterviewRetrospectiveRepository,
)
from app.interview_retrospectives.service import InterviewRetrospectiveService


class InterviewRetrospectiveApplication:
    def __init__(
        self,
        *,
        workspace_id: str,
        service: InterviewRetrospectiveService,
        repository: InterviewRetrospectiveRepository,
        sessions: AgentSessionService,
        executions: AgentExecutionService,
        products: ProductRepository,
        agents: InterviewRetrospectiveAgents | None,
    ) -> None:
        self.workspace_id = workspace_id
        self.service = service
        self.repository = repository
        self.sessions = sessions
        self.executions = executions
        self.products = products
        self.agents = agents

    async def create_retrospective(
        self,
        *,
        job_target_id: str,
        title: str,
        round_label: str,
        interview_date: str | None,
        outcome: str,
        note: str,
        idempotency_key: str,
    ):
        replay = self.repository.retrospective_by_create_key(
            workspace_id=self.workspace_id,
            idempotency_key=idempotency_key,
        )
        if replay is not None:
            return replay
        # Validate ownership before creating either Session so a bad target cannot
        # leave orphan runtime records.
        target = self.service.job_targets.get_target(job_target_id)
        if target.workspace_id != self.workspace_id:
            raise RetrospectiveTargetRequired("求职目标不属于当前工作区")
        chat = await self.sessions.create(
            workspace_id=self.workspace_id,
            kind="interview.retrospective.chat",
            title=f"复盘讨论：{title.strip()}",
            visibility="user",
        )
        analysis = await self.sessions.create(
            workspace_id=self.workspace_id,
            kind="interview.retrospective.analysis",
            title=f"复盘分析：{title.strip()}",
            visibility="system",
        )
        return self.service.create(
            job_target_id=job_target_id,
            title=title,
            round_label=round_label,
            interview_date=interview_date,
            outcome=outcome,
            note=note,
            analysis_session_id=analysis.id,
            chat_session_id=chat.id,
            idempotency_key=idempotency_key,
        )

    def add_source_version(self, retrospective_id: str, **values):
        return self.service.add_source_version(retrospective_id, **values)

    def list_retrospectives(self, **values):
        return self.service.list(**values)

    def get_retrospective(self, retrospective_id: str):
        return self.service.get(retrospective_id)

    def update_retrospective(self, retrospective_id: str, **values):
        return self.service.update(retrospective_id, **values)

    def get_source_version(self, retrospective_id: str, version_id: str):
        self.service.get(retrospective_id)
        source = self.repository.get_source_version(version_id)
        if source.retrospective_id != retrospective_id:
            raise RetrospectiveTargetRequired("原始记录不属于当前复盘")
        return source

    def replace_segments(self, retrospective_id: str, cleanup_id: str, **values):
        return self.service.replace_segments(retrospective_id, cleanup_id, **values)

    def confirm_cleanup(self, retrospective_id: str, cleanup_id: str, **values):
        return self.service.confirm_cleanup(retrospective_id, cleanup_id, **values)

    def archive(self, retrospective_id: str, **values):
        return self.service.archive(retrospective_id, **values)

    def recycle(self, retrospective_id: str, **values):
        return self.service.recycle(retrospective_id, **values)

    def restore(self, retrospective_id: str, **values):
        return self.service.restore(retrospective_id, **values)

    def deletion_impact(self, retrospective_id: str):
        return self.service.deletion_impact(retrospective_id)

    def delete_permanently(self, retrospective_id: str, **values) -> None:
        self.service.delete_permanently(retrospective_id, **values)

    def get_cleanup(self, retrospective_id: str, cleanup_id: str):
        self.service.get(retrospective_id)
        cleanup = self.repository.get_cleanup_version(cleanup_id)
        if cleanup.retrospective_id != retrospective_id:
            raise RetrospectiveTargetRequired("整理版本不属于当前复盘")
        return cleanup

    def current_cleanup(self, retrospective_id: str):
        self.service.get(retrospective_id)
        return self.repository.latest_cleanup_version(retrospective_id)

    def list_segments(self, retrospective_id: str, cleanup_id: str):
        self.get_cleanup(retrospective_id, cleanup_id)
        return self.repository.list_segments(cleanup_id)

    async def start_cleanup(
        self,
        retrospective_id: str,
        *,
        source_version_id: str,
        idempotency_key: str,
    ) -> dict[str, str]:
        retrospective = self.service.get(retrospective_id)
        source = self.repository.get_source_version(source_version_id)
        if source.retrospective_id != retrospective_id:
            raise RetrospectiveTargetRequired("原始记录不属于当前复盘")
        if source.cleared_at is not None:
            raise RetrospectiveSourceCleared("原始记录已清除")
        if self.agents is None:
            raise RetrospectiveModelNotConfigured("请先配置面试复盘分析模型")
        request_hash = _digest(
            {
                "source_version_id": source_version_id,
                "content_sha256": source.content_sha256,
            }
        )
        replay = self.repository.receipt(
            retrospective_id, "start_cleanup", idempotency_key
        )
        if replay is not None:
            saved_hash, result = replay
            if saved_hash != request_hash:
                raise RetrospectiveIdempotencyConflict(
                    "同一幂等键不能启动不同整理任务"
                )
            return {
                "cleanupVersionId": str(result["cleanup_version_id"]),
                "executionId": str(result["execution_id"]),
            }
        windows = create_source_windows(source.body)
        cleanup = self.repository.insert_cleanup_run(
            retrospective_id,
            source_version_id=source.id,
            input_digest=source.content_sha256,
            windows=windows,
        )
        receipt = await self._schedule_cleanup(
            retrospective=retrospective,
            cleanup_id=cleanup.id,
            source=source,
        )
        self.repository.save_receipt(
            retrospective_id,
            scope="start_cleanup",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            result={
                "cleanup_version_id": receipt["cleanupVersionId"],
                "execution_id": receipt["executionId"],
            },
        )
        return receipt

    async def stop_cleanup(
        self,
        retrospective_id: str,
        cleanup_id: str,
        *,
        idempotency_key: str | None = None,
    ):
        request_hash = _digest({"cleanup_id": cleanup_id})
        if idempotency_key is not None:
            replay = self.repository.receipt(
                retrospective_id, "stop_cleanup", idempotency_key
            )
            if replay is not None:
                saved_hash, _result = replay
                if saved_hash != request_hash:
                    raise RetrospectiveIdempotencyConflict(
                        "同一幂等键不能停止不同整理任务"
                    )
                return self.get_cleanup(retrospective_id, cleanup_id)
        cleanup = self.get_cleanup(retrospective_id, cleanup_id)
        if cleanup.execution_id is None:
            current = self.repository.stop_cleanup(cleanup_id)
        else:
            await self.executions.cancel(cleanup.execution_id)
            current = self.repository.get_cleanup_version(cleanup_id)
            if current.status in {"queued", "running", "stopping"}:
                current = self.repository.stop_cleanup(cleanup_id)
        if idempotency_key is not None:
            self.repository.save_receipt(
                retrospective_id,
                scope="stop_cleanup",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                result={"cleanup_version_id": cleanup_id},
            )
        return current

    async def resume_cleanup(
        self,
        retrospective_id: str,
        cleanup_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, str]:
        request_hash = _digest({"cleanup_id": cleanup_id})
        if idempotency_key is not None:
            replay = self.repository.receipt(
                retrospective_id, "resume_cleanup", idempotency_key
            )
            if replay is not None:
                saved_hash, result = replay
                if saved_hash != request_hash:
                    raise RetrospectiveIdempotencyConflict(
                        "同一幂等键不能继续不同整理任务"
                    )
                return {
                    "cleanupVersionId": str(result["cleanup_version_id"]),
                    "executionId": str(result["execution_id"]),
                }
        if self.agents is None:
            raise RetrospectiveModelNotConfigured("请先配置面试复盘分析模型")
        retrospective = self.service.get(retrospective_id)
        cleanup = self.get_cleanup(retrospective_id, cleanup_id)
        source = self.get_source_version(
            retrospective_id, cleanup.source_version_id
        )
        if source.cleared_at is not None:
            raise RetrospectiveSourceCleared("原始记录已清除")
        self.repository.rearm_cleanup(cleanup_id)
        receipt = await self._schedule_cleanup(
            retrospective=retrospective,
            cleanup_id=cleanup_id,
            source=source,
        )
        if idempotency_key is not None:
            self.repository.save_receipt(
                retrospective_id,
                scope="resume_cleanup",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                result={
                    "cleanup_version_id": receipt["cleanupVersionId"],
                    "execution_id": receipt["executionId"],
                },
            )
        return receipt

    async def _schedule_cleanup(
        self,
        *,
        retrospective,
        cleanup_id: str,
        source,
    ) -> dict[str, str]:
        session = self.products.get_session(retrospective.analysis_session_id)
        execution = await self.executions.prepare(
            session,
            input={
                "retrospectiveId": retrospective.id,
                "cleanupVersionId": cleanup_id,
                "sourceVersionId": source.id,
            },
            project_input_message=False,
        )
        cleanup = self.repository.attach_cleanup_execution(
            cleanup_id, execution_id=execution.id
        )

        async def handler(
            current_execution: ExecutionRecord,
            cancellation: ExecutionCancellation,
        ) -> None:
            await self._run_cleanup(
                retrospective_id=retrospective.id,
                cleanup_id=cleanup.id,
                source_kind=source.source_kind,
                source_body=source.body,
                execution=current_execution,
                cancellation=cancellation,
            )

        self.executions.run_background(execution, handler)
        return {
            "cleanupVersionId": cleanup.id,
            "executionId": execution.id,
        }

    async def _run_cleanup(
        self,
        *,
        retrospective_id: str,
        cleanup_id: str,
        source_kind: str,
        source_body: str,
        execution: ExecutionRecord,
        cancellation: ExecutionCancellation,
    ) -> None:
        assert self.agents is not None
        context = self.executions.context(execution)
        try:
            for item in self.repository.list_resumable_cleanup_work_items(
                cleanup_id
            ):
                cancellation.raise_if_requested()
                current = self.repository.claim_cleanup_work_item(item.id)
                output = await self.agents.cleanup_window(
                    source_kind=source_kind,
                    source_start=current.source_start,
                    source_end=current.source_end,
                    body=source_body[current.source_start : current.source_end],
                    context=_cleanup_context(context, current.work_key),
                    config={
                        "configurable": {
                            "thread_id": f"{execution.session_id}:{cleanup_id}"
                        }
                    },
                )
                self.repository.complete_cleanup_work_item(
                    current.id,
                    output=output.model_dump(by_alias=True),
                )
            outputs = [
                item.output.get("segments", [])
                for item in self.repository.list_cleanup_work_items(cleanup_id)
                if item.status == "completed" and item.output is not None
            ]
            reduced = reduce_cleanup_segments(outputs)
            cleanup = self.repository.get_cleanup_version(cleanup_id)
            self.service.replace_segments(
                retrospective_id,
                cleanup_id,
                expected_version=cleanup.version,
                segments=tuple(_domain_segment(item) for item in reduced),
            )
            self.repository.mark_cleanup_review_pending(cleanup_id)
        except Exception as error:
            self.repository.fail_cleanup(
                cleanup_id,
                error_code=str(
                    getattr(error, "code", "retrospective_cleanup_failed")
                ),
            )
            raise


def _cleanup_context(context: AgentContext, work_key: str) -> AgentContext:
    return AgentContext(
        workspace_id=context.workspace_id,
        workspace_root=context.workspace_root,
        session_id=context.session_id,
        run_id=context.run_id,
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
        progress_scope=("interview_retrospective_cleanup", work_key),
    )


def _domain_segment(item: dict[str, object]) -> dict[str, object]:
    return {
        "speaker_role": item["speakerRole"],
        "raw_speaker_label": item.get("rawSpeakerLabel"),
        "display_name": item["displayName"],
        "body": item["text"],
        "source_start": item["sourceStart"],
        "source_end": item["sourceEnd"],
        "confidence": item["confidence"],
        "uncertainty_reason": item.get("uncertaintyReason"),
        "ignored": False,
    }


def _digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

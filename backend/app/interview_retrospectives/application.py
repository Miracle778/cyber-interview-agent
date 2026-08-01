from __future__ import annotations

import hashlib
import json

from app.agents.context import AgentContext
from app.agents.interview_retrospective_agents import InterviewRetrospectiveAgents
from app.application.execution_service import (
    AgentExecutionService,
    ExecutionCancellation,
    ExecutionCancelled,
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
from app.graphs.interview_retrospective_analysis import finalize_report
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
from app.profile.service import ProfileService


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
        profile: ProfileService | None = None,
        analysis_model_id: str | None = None,
    ) -> None:
        self.workspace_id = workspace_id
        self.service = service
        self.repository = repository
        self.sessions = sessions
        self.executions = executions
        self.products = products
        self.agents = agents
        self.profile = profile
        self.analysis_model_id = analysis_model_id

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

    async def start_analysis(
        self,
        retrospective_id: str,
        *,
        cleanup_version_id: str,
        idempotency_key: str,
    ) -> dict[str, str]:
        if self.agents is None:
            raise RetrospectiveModelNotConfigured("请先配置面试复盘分析模型")
        retrospective = self.service.get(retrospective_id)
        cleanup = self.get_cleanup(retrospective_id, cleanup_version_id)
        context_snapshot = self._analysis_context_snapshot(retrospective)
        input_digest = _digest(
            {
                "cleanupInputDigest": cleanup.input_digest,
                "contextSnapshot": context_snapshot,
            }
        )
        run = self.service.create_analysis_run(
            retrospective_id,
            cleanup_version_id,
            input_digest=input_digest,
            context_snapshot=context_snapshot,
            idempotency_key=idempotency_key,
        )
        if run.execution_id is not None:
            return {"analysisRunId": run.id, "executionId": run.execution_id}
        return await self._schedule_analysis(retrospective, run.id)

    def get_analysis_run(self, retrospective_id: str, run_id: str):
        self.service.get(retrospective_id)
        run = self.repository.get_analysis_run(run_id)
        if run.retrospective_id != retrospective_id:
            raise RetrospectiveTargetRequired("分析运行不属于当前复盘")
        return run

    def list_questions(self, retrospective_id: str):
        retrospective = self.service.get(retrospective_id)
        cleanup_id = retrospective.active_cleanup_version_id
        if cleanup_id is None:
            return ()
        return self.repository.list_questions(
            retrospective_id, cleanup_version_id=cleanup_id
        )

    async def decide_question(self, retrospective_id: str, question_id: str, **values):
        retrospective = self.service.get(retrospective_id)
        updated = self.service.decide_question(retrospective_id, question_id, **values)
        run = self.repository.current_analysis_run(retrospective_id)
        if run is not None and run.status == "queued":
            await self._schedule_analysis(retrospective, run.id)
        return updated

    async def stop_analysis(
        self,
        retrospective_id: str,
        run_id: str,
        *,
        idempotency_key: str,
    ):
        request_hash = _digest({"runId": run_id})
        replay = self.repository.receipt(
            retrospective_id, "stop_analysis", idempotency_key
        )
        if replay is not None:
            saved_hash, result = replay
            if saved_hash != request_hash:
                raise RetrospectiveIdempotencyConflict("同一幂等键不能停止不同分析")
            return self.get_analysis_run(
                retrospective_id, str(result["analysis_run_id"])
            )
        run = self.get_analysis_run(retrospective_id, run_id)
        if run.status in {"completed", "stopped", "failed"}:
            stopped = run
        else:
            self.repository.request_analysis_stop(run_id)
            if run.execution_id is not None:
                await self.executions.cancel(run.execution_id)
            stopped = self.repository.stop_analysis(run_id)
        self.repository.save_receipt(
            retrospective_id,
            scope="stop_analysis",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            result={"analysis_run_id": stopped.id},
        )
        return stopped

    async def resume_analysis(
        self,
        retrospective_id: str,
        run_id: str,
        *,
        idempotency_key: str,
    ) -> dict[str, str]:
        request_hash = _digest({"runId": run_id})
        replay = self.repository.receipt(
            retrospective_id, "resume_analysis", idempotency_key
        )
        if replay is not None:
            saved_hash, result = replay
            if saved_hash != request_hash:
                raise RetrospectiveIdempotencyConflict("同一幂等键不能继续不同分析")
            return {
                "analysisRunId": str(result["analysis_run_id"]),
                "executionId": str(result["execution_id"]),
            }
        if self.agents is None:
            raise RetrospectiveModelNotConfigured("请先配置面试复盘分析模型")
        retrospective = self.service.get(retrospective_id)
        self.get_analysis_run(retrospective_id, run_id)
        self.repository.rearm_analysis(run_id)
        receipt = await self._schedule_analysis(retrospective, run_id)
        self.repository.save_receipt(
            retrospective_id,
            scope="resume_analysis",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            result={
                "analysis_run_id": receipt["analysisRunId"],
                "execution_id": receipt["executionId"],
            },
        )
        return receipt

    async def retry_analysis(
        self,
        retrospective_id: str,
        run_id: str,
        *,
        idempotency_key: str,
    ) -> dict[str, str]:
        if self.agents is None:
            raise RetrospectiveModelNotConfigured("请先配置面试复盘分析模型")
        request_hash = _digest({"runId": run_id})
        replay = self.repository.receipt(
            retrospective_id, "retry_analysis", idempotency_key
        )
        if replay is not None:
            saved_hash, result = replay
            if saved_hash != request_hash:
                raise RetrospectiveIdempotencyConflict("同一幂等键不能重试不同分析")
            return {
                "analysisRunId": str(result["analysis_run_id"]),
                "executionId": str(result["execution_id"]),
            }
        retrospective = self.service.get(retrospective_id)
        previous = self.get_analysis_run(retrospective_id, run_id)
        snapshot = json.loads(previous.context_snapshot_json)
        retry = self.service.create_analysis_run(
            retrospective_id,
            previous.cleanup_version_id,
            input_digest=previous.input_digest,
            context_snapshot=snapshot,
            idempotency_key=idempotency_key,
            retry_of_analysis_run_id=previous.id,
        )
        receipt = await self._schedule_analysis(retrospective, retry.id)
        self.repository.save_receipt(
            retrospective_id,
            scope="retry_analysis",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            result={
                "analysis_run_id": receipt["analysisRunId"],
                "execution_id": receipt["executionId"],
            },
        )
        return receipt

    def report(self, retrospective_id: str):
        retrospective = self.service.get(retrospective_id)
        if retrospective.active_analysis_run_id is None:
            return None
        run = self.repository.get_analysis_run(retrospective.active_analysis_run_id)
        questions = self.repository.list_questions(
            retrospective_id, cleanup_version_id=run.cleanup_version_id
        )
        return (
            run,
            questions,
            self.repository.list_question_analyses(run.id),
            self.repository.list_gaps(run.id),
            self.repository.list_analysis_work_items(run.id),
        )

    def _analysis_context_snapshot(self, retrospective) -> dict[str, object]:
        target = self.service.job_targets.get_target(retrospective.job_target_id)
        document = None
        if target.current_document_version_id is not None:
            current = self.service.job_targets.get_document_version(
                target.current_document_version_id
            )
            document = {
                "id": current.id,
                "ordinal": current.ordinal,
                "bodyExcerpt": current.body[:12_000],
                "contentHash": current.content_hash,
            }
        profile = {"version": None, "items": []}
        if self.profile is not None:
            confirmed = self.profile.confirmed_profile_context(
                purpose="interview_retrospective", limit=20
            )
            profile = {
                "version": confirmed.profile_version,
                "items": [
                    {
                        "claimId": item.claim_id,
                        "claimVersionId": item.claim_version_id,
                        "claimType": item.claim_type,
                        "value": item.value,
                        "supportStatus": item.support_status,
                    }
                    for item in confirmed.items
                ],
            }
        return {
            "target": {
                "id": target.id,
                "roleName": target.role_name,
                "seniority": target.seniority,
                "companyName": target.company_name,
                "document": document,
            },
            "profile": profile,
            "relevantQuestionIds": [],
            "knowledgeRefs": [],
            "prompts": {
                "questionExtraction": "interview_retrospective.question_extraction@2026-08-02",
                "questionAnalysis": "interview_retrospective.question_analysis@2026-08-02",
            },
            "model": {
                "role": "retrospective_analysis",
                "providerModelId": self.analysis_model_id,
            },
        }

    async def _schedule_analysis(self, retrospective, run_id: str) -> dict[str, str]:
        session = self.products.get_session(retrospective.analysis_session_id)
        execution = await self.executions.prepare(
            session,
            input={
                "retrospectiveId": retrospective.id,
                "analysisRunId": run_id,
            },
            project_input_message=False,
        )
        run = self.repository.attach_analysis_execution(
            run_id, execution_id=execution.id
        )

        async def handler(current_execution, cancellation):
            await self._run_analysis(run.id, current_execution, cancellation)

        self.executions.run_background(execution, handler)
        return {"analysisRunId": run.id, "executionId": execution.id}

    async def _run_analysis(
        self,
        run_id: str,
        execution: ExecutionRecord,
        cancellation: ExecutionCancellation,
    ) -> None:
        assert self.agents is not None
        run = self.repository.get_analysis_run(run_id)
        context_snapshot = json.loads(run.context_snapshot_json)
        context = self.executions.context(execution)
        try:
            while True:
                pending = self.repository.list_resumable_analysis_work_items(run_id)
                if not pending:
                    break
                for item in pending:
                    cancellation.raise_if_requested()
                    current = self.repository.claim_analysis_work_item(item.id)
                    if current.work_key == "question_extraction":
                        segments = self.repository.list_segments(run.cleanup_version_id)
                        payload = _bounded_segments(segments)
                        output = await self.agents.extract_questions(
                            segments=payload,
                            context_snapshot=context_snapshot,
                            context=_analysis_context(context, current.work_key),
                            config={
                                "configurable": {
                                    "thread_id": f"{execution.session_id}:{run_id}"
                                }
                            },
                        )
                        with cancellation.critical_section():
                            questions = self.repository.replace_question_units(
                                run_id,
                                questions=tuple(
                                    _domain_question(
                                        question.model_dump(by_alias=False)
                                    )
                                    for question in output.questions
                                ),
                            )
                            self.repository.complete_analysis_work_item(
                                current.id,
                                output=output.model_dump(by_alias=True),
                            )
                            self.repository.schedule_analysis_work_items(
                                run_id,
                                question_ids=tuple(
                                    question.id for question in questions
                                ),
                            )
                    elif current.work_key.startswith("question_analysis:"):
                        question = self.repository.get_question(
                            str(current.question_unit_id)
                        )
                        segments = {
                            segment.id: segment
                            for segment in self.repository.list_segments(
                                run.cleanup_version_id
                            )
                        }
                        selected = [
                            segments[segment_id]
                            for segment_id in (
                                *question.question_segment_ids,
                                *question.answer_segment_ids,
                            )
                            if segment_id in segments
                        ]
                        output = await self.agents.analyze_question(
                            question=_question_payload(question),
                            segments=_bounded_segments(selected),
                            context_snapshot=context_snapshot,
                            context=_analysis_context(context, current.work_key),
                            config={
                                "configurable": {
                                    "thread_id": f"{execution.session_id}:{run_id}"
                                }
                            },
                        )
                        _validate_analysis_evidence(
                            output,
                            allowed_segment_ids={segment.id for segment in selected},
                        )
                        serialized = output.model_dump(by_alias=True)
                        with cancellation.critical_section():
                            self.repository.save_question_analysis(
                                run_id,
                                question.id,
                                output=serialized,
                                source_excerpt="\n".join(
                                    segment.body for segment in selected
                                )[:12_000],
                                result_status=(
                                    "draft"
                                    if question.origin == "inferred"
                                    and question.decision_status != "confirmed"
                                    else "formal"
                                ),
                            )
                            self.repository.complete_analysis_work_item(
                                current.id, output=serialized
                            )
                    elif current.work_key == "final_projection":
                        questions = self.repository.list_questions(
                            run.retrospective_id,
                            cleanup_version_id=run.cleanup_version_id,
                        )
                        analyses = self.repository.list_question_analyses(run_id)
                        summary = finalize_report(
                            questions=tuple(
                                _question_payload(item) for item in questions
                            ),
                            analyses=tuple(
                                {
                                    "questionUnitId": item.question_unit_id,
                                    "verdict": item.verdict,
                                }
                                for item in analyses
                            ),
                        )
                        with cancellation.critical_section():
                            self.repository.complete_analysis_work_item(
                                current.id, output=summary
                            )
                            self.repository.mark_analysis_completed(
                                run_id, summary=summary
                            )
                    else:
                        self.repository.complete_analysis_work_item(
                            current.id, output={"status": "not_applicable"}
                        )
            latest = self.repository.get_analysis_run(run_id)
            if latest.status == "running":
                questions = self.repository.list_questions(
                    run.retrospective_id,
                    cleanup_version_id=run.cleanup_version_id,
                )
                analyses = self.repository.list_question_analyses(run_id)
                self.repository.mark_analysis_completed(
                    run_id,
                    summary=finalize_report(
                        questions=tuple(_question_payload(item) for item in questions),
                        analyses=tuple(
                            {
                                "questionUnitId": item.question_unit_id,
                                "verdict": item.verdict,
                            }
                            for item in analyses
                        ),
                    ),
                )
        except ExecutionCancelled:
            self.repository.stop_analysis(run_id)
            raise
        except Exception as error:
            self.repository.fail_analysis(
                run_id,
                error_code=str(getattr(error, "code", "retrospective_analysis_failed")),
            )
            raise

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
                raise RetrospectiveIdempotencyConflict("同一幂等键不能启动不同整理任务")
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
        source = self.get_source_version(retrospective_id, cleanup.source_version_id)
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
            for item in self.repository.list_resumable_cleanup_work_items(cleanup_id):
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
                error_code=str(getattr(error, "code", "retrospective_cleanup_failed")),
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


def _analysis_context(context: AgentContext, work_key: str) -> AgentContext:
    return AgentContext(
        workspace_id=context.workspace_id,
        workspace_root=context.workspace_root,
        session_id=context.session_id,
        run_id=context.run_id,
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
        progress_scope=("interview_retrospective_analysis", work_key),
    )


def _bounded_segments(segments) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    remaining = 60_000
    for segment in segments:
        if segment.ignored or remaining <= 0:
            continue
        body = segment.body[: min(4_000, remaining)]
        remaining -= len(body)
        result.append(
            {
                "id": segment.id,
                "ordinal": segment.ordinal,
                "speakerRole": segment.speaker_role,
                "displayName": segment.display_name,
                "body": body,
                "confidence": segment.confidence,
            }
        )
    return result


def _domain_question(item: dict[str, object]) -> dict[str, object]:
    return {
        "ordinal": item["ordinal"],
        "question_kind": item["question_kind"],
        "origin": item["origin"],
        "question_text": item["question_text"],
        "question_segment_ids": tuple(item["question_segment_ids"]),
        "answer_segment_ids": tuple(item["answer_segment_ids"]),
        "inference_basis": item["inference_basis"],
        "confidence": item["confidence"],
    }


def _question_payload(question) -> dict[str, object]:
    return {
        "id": question.id,
        "ordinal": question.ordinal,
        "questionKind": question.question_kind,
        "origin": question.origin,
        "questionText": question.question_text,
        "questionSegmentIds": list(question.question_segment_ids),
        "answerSegmentIds": list(question.answer_segment_ids),
        "inferenceBasis": question.inference_basis,
        "confidence": question.confidence,
        "decisionStatus": question.decision_status,
        "version": question.version,
    }


def _validate_analysis_evidence(output, *, allowed_segment_ids: set[str]) -> None:
    points = (
        *output.strengths,
        *output.improvements,
        *output.omissions,
        *output.gaps,
    )
    referenced = {
        segment_id for point in points for segment_id in point.evidence_segment_ids
    }
    if referenced - allowed_segment_ids:
        raise ValueError("逐题分析引用了当前问题之外的证据片段")


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

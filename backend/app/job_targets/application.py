from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime

from app.agents.agent_factory import ModelOverride
from app.agents.job_target_agents import JobTargetAgents
from app.application.execution_service import (
    AgentExecutionService,
    ExecutionCancellation,
)
from app.application.session_service import (
    AgentSessionService,
    ExecutionRecord,
    ProductRepository,
)
from app.graphs.project_deep_dive import advance_stage
from app.job_targets.errors import JobTargetBusy, JobTargetConflict
from app.job_targets.requirement_classification import is_job_background_or_heading
from app.job_targets.repository import JobTargetRepository
from app.job_targets.service import JobTargetService
from app.profile.service import ProfileService


class JobTargetApplication:
    """Cross-domain coordinator. Model-facing code never writes confirmed state."""

    def __init__(
        self,
        *,
        workspace_id: str,
        service: JobTargetService,
        repository: JobTargetRepository,
        profile: ProfileService,
        sessions: AgentSessionService,
        executions: AgentExecutionService,
        product_repository: ProductRepository,
        agents: JobTargetAgents | None = None,
        agents_factory: Callable[[ModelOverride], JobTargetAgents] | None = None,
    ) -> None:
        self.workspace_id = workspace_id
        self.service = service
        self.repository = repository
        self.profile = profile
        self.sessions = sessions
        self.executions = executions
        self.product_repository = product_repository
        self.agents = agents
        self.agents_factory = agents_factory

    async def start_analysis(self, target_id: str) -> dict:
        target = self.service.get_target(target_id)
        if target.current_document_version_id is None:
            raise JobTargetConflict("请先确认岗位描述版本")
        current = self.repository.current_analysis_run(target_id)
        if current is not None and current["status"] in {"queued", "running", "pausing"}:
            raise JobTargetBusy("岗位分析正在进行")
        context = self.profile.confirmed_profile_context(
            purpose="job_target_analysis", limit=50
        )
        digest = hashlib.sha256(
            f"{target.current_document_version_id}:{context.profile_version}".encode()
        ).hexdigest()
        run_id = self.repository.create_analysis_run(
            target_id,
            target.current_document_version_id,
            profile_version=_version_number(context.profile_version),
            input_digest=digest,
        )
        projects = tuple(item for item in context.items if item.claim_type == "project")
        work = [
            ("requirement_extraction", target.current_document_version_id),
            ("profile_mapping", str(context.profile_version)),
            *[
                (f"project_mapping:{item.claim_id}", item.claim_version_id)
                for item in projects
            ],
            ("final_projection", digest),
        ]
        self.repository.create_analysis_work_items(run_id, tuple(work))
        session = await self.sessions.create(
            workspace_id=self.workspace_id,
            kind="job.analysis",
            title=f"岗位分析：{target.role_name or '待识别岗位'}",
            visibility="system",
        )
        execution = await self.executions.prepare(
            session,
            input={"jobTargetId": target_id, "analysisRunId": run_id},
            project_input_message=False,
        )
        self.repository.bind_analysis_execution(run_id, execution.id)
        self._schedule_analysis(run_id, execution)
        if self.agents is None:
            await self.executions.wait(execution.id)
        return self.analysis_resource(run_id)

    def _schedule_analysis(
        self, run_id: str, execution: ExecutionRecord
    ) -> None:
        async def handler(
            active: ExecutionRecord, cancellation: ExecutionCancellation
        ) -> None:
            await self._run_analysis(run_id, active, cancellation)

        self.executions.run_background(execution, handler)

    async def _run_analysis(
        self,
        run_id: str,
        execution: ExecutionRecord,
        cancellation: ExecutionCancellation,
    ) -> None:
        run = self.repository.get_analysis_run(run_id)
        target = self.service.get_target(run["job_target_id"])
        document = self.service.get_document_version(run["document_version_id"])
        for item in self.repository.list_analysis_work_items(run_id):
            cancellation.raise_if_requested()
            if item["status"] == "completed":
                continue
            fresh = self.repository.get_analysis_run(run_id)
            if fresh["control_intent"] == "terminate":
                self.repository.transition_analysis(run_id, status="terminated", stage="terminated")
                return
            if fresh["control_intent"] == "pause":
                self.repository.transition_analysis(run_id, status="paused", control_intent=None)
                return
            key = item["work_key"]
            try:
                if key == "requirement_extraction":
                    if self.agents is None:
                        suggestions = _extract_requirements(document.body)
                        metadata = None
                    else:
                        result = await self.agents.extract_requirements(
                            role=target.role_name,
                            seniority=target.seniority,
                            company=target.company_name,
                            document=document.body,
                            context=self.executions.context(execution),
                            config={},
                        )
                        metadata = result.metadata
                        suggestions = tuple(
                            normalized
                            for item in result.requirements
                            if not is_job_background_or_heading(item.text)
                            for normalized in (
                                _normalized_requirement(item.model_dump(), document.body),
                            )
                        )
                    with cancellation.critical_section():
                        requirements = self.service.replace_requirement_suggestions(
                            target.id, document.id, suggestions=suggestions
                        )
                        if metadata is not None and any(
                            (metadata.company_name, metadata.role_name, metadata.seniority)
                        ):
                            fresh_target = self.service.get_target(target.id)
                            target = self.service.update_target(
                                target.id,
                                expected_version=fresh_target.version,
                                company_name=(
                                    metadata.company_name
                                    if metadata.company_name is not None
                                    else fresh_target.company_name
                                ),
                                role_name=metadata.role_name or fresh_target.role_name,
                                seniority=metadata.seniority or fresh_target.seniority,
                                source_url=fresh_target.source_url,
                                idempotency_key=f"analysis-metadata:{run_id}",
                            )
                        output = {"requirements": len(requirements)}
                        stage = "mapping_profile"
                elif key == "profile_mapping":
                    output = {"profileVersion": run["profile_version"]}
                    stage = "mapping_projects"
                elif key.startswith("project_mapping:"):
                    output = {"projectId": key.split(":", 1)[1], "mapped": True}
                    stage = "mapping_projects"
                else:
                    output = {"readyForReview": True}
                    stage = "finalizing"
                with cancellation.critical_section():
                    self.repository.complete_analysis_work_item(item["id"], output)
                    self.repository.transition_analysis(
                        run_id, status="running", stage=stage
                    )
            except (asyncio.CancelledError,):
                raise
            except Exception as error:
                self.repository.fail_analysis_work_item(
                    item["id"], getattr(error, "code", type(error).__name__)
                )
                self.repository.transition_analysis(
                    run_id, status="failed", stage="failed"
                )
                raise
        self.repository.transition_analysis(
            run_id, status="review_pending", stage="waiting_for_review"
        )
        await self.executions.complete_background_execution(execution.id)

    def analysis_resource(self, run_id: str) -> dict:
        run = self.repository.get_analysis_run(run_id)
        items = self.repository.list_analysis_work_items(run_id)
        execution = (
            None
            if run["execution_id"] is None
            else self.product_repository.get_execution(run["execution_id"])
        )
        completed = sum(item["status"] == "completed" for item in items)
        outputs = [
            json.loads(item["output_json"])
            for item in items
            if item["output_json"]
        ]
        requirement_count = sum(int(item.get("requirements", 0)) for item in outputs)
        project_count = sum(1 for item in outputs if item.get("mapped"))
        return {
            "id": run["id"],
            "jobTargetId": run["job_target_id"],
            "status": run["status"],
            "stage": run["stage"],
            "version": run["version"],
            "executionId": None if execution is None else execution.id,
            "progress": {
                "completed": completed,
                "total": len(items),
                "activeWorkers": int(run["status"] == "running"),
            },
            "timing": {
                "currentElapsedMs": _execution_elapsed_ms(execution),
                "cumulativeElapsedMs": run["cumulative_elapsed_ms"],
            },
            "latestProgressAt": run["latest_progress_at"],
            "savedOutputs": {
                "requirements": requirement_count,
                "projectMappings": project_count,
            },
            "workItems": [
                {
                    "id": item["id"],
                    "key": item["work_key"],
                    "status": item["status"],
                    "attemptCount": item["attempt_count"],
                }
                for item in items
            ],
            "controls": {
                "canPause": run["status"] == "running",
                "canResume": run["status"] in {"paused", "interrupted", "failed"},
                "canTerminate": run["status"] in {
                    "queued",
                    "running",
                    "pausing",
                    "paused",
                    "interrupted",
                    "failed",
                },
            },
        }

    def current_analysis(self, target_id: str) -> dict | None:
        self.service.get_target(target_id)
        row = self.repository.current_analysis_run(target_id)
        return None if row is None else self.analysis_resource(row["id"])

    async def control_analysis(self, run_id: str, action: str) -> dict:
        row = self.repository.get_analysis_run(run_id)
        if action == "pause":
            if row["execution_id"]:
                await self.executions.cancel(row["execution_id"])
            self.repository.transition_analysis(run_id, status="paused", control_intent=None)
        elif action == "resume":
            previous = (
                None
                if row["execution_id"] is None
                else self.product_repository.get_execution(row["execution_id"])
            )
            session = (
                await self.sessions.create(
                    workspace_id=self.workspace_id,
                    kind="job.analysis",
                    title="岗位分析",
                    visibility="system",
                )
                if previous is None
                else self.sessions.get(previous.session_id)
            )
            execution = await self.executions.prepare(
                session,
                input={"jobTargetId": row["job_target_id"], "analysisRunId": run_id},
                project_input_message=False,
            )
            self.repository.bind_analysis_execution(run_id, execution.id)
            self._schedule_analysis(run_id, execution)
            if self.agents is None:
                await self.executions.wait(execution.id)
        elif action == "terminate":
            if row["execution_id"]:
                await self.executions.cancel(row["execution_id"])
            self.repository.transition_analysis(run_id, status="terminated", stage="terminated")
        else:
            raise ValueError("不支持的岗位分析操作")
        return self.analysis_resource(run_id)

    async def retry_work_item(self, run_id: str, item_id: str) -> dict:
        row = self.repository.get_analysis_run(run_id)
        self.repository.retry_analysis_work_item(item_id)
        return await self.control_analysis(run_id, "resume")

    async def create_deep_dive(self, target_id: str, project_claim_id: str) -> dict:
        self.service.get_target(target_id)
        self.service._assert_confirmed_project(
            project_claim_id, "项目深挖只能使用已确认的画像项目"
        )
        current = self.repository.current_deep_dive(target_id, project_claim_id)
        if current is not None:
            return self.deep_dive_resource(current["id"])
        project_context = self.profile.confirmed_profile_context(
            purpose="job_target_analysis",
            claim_ids=(project_claim_id,),
            limit=1,
        )
        project_title = _project_title(
            project_context.items[0].value if project_context.items else {}
        )
        session = await self.sessions.create(
            workspace_id=self.workspace_id,
            kind="project.deep_dive",
            title=f"项目深挖：{project_title}",
        )
        dive_id = self.repository.create_deep_dive(
            target_id, project_claim_id, session.id
        )
        self.product_repository.append_message(
            session.id,
            execution_id=None,
            role="assistant",
            content="先介绍这个项目的背景、目标，以及你在其中承担的职责。",
        )
        return self.deep_dive_resource(dive_id)

    def current_deep_dive(self, target_id: str, project_claim_id: str) -> dict | None:
        row = self.repository.current_deep_dive(target_id, project_claim_id)
        return None if row is None else self.deep_dive_resource(row["id"])

    async def restart_deep_dive(self, dive_id: str) -> dict:
        """Start a new attempt without overwriting the completed/ended conversation."""
        dive = self.repository.get_deep_dive(dive_id)
        if dive["status"] not in {"completed", "terminated"}:
            raise JobTargetConflict("只有已完成或已结束的项目深挖可以重新开始")
        self.repository.archive_deep_dive(dive_id)
        return await self.create_deep_dive(
            dive["job_target_id"], dive["project_claim_id"]
        )

    async def answer_deep_dive(
        self,
        dive_id: str,
        content: str,
        *,
        message_id: str | None = None,
        provider_model_id: str | None = None,
        reasoning_effort: str = "none",
    ) -> dict:
        dive = self.repository.get_deep_dive(dive_id)
        if dive["status"] != "active":
            raise JobTargetConflict("当前项目深挖未处于可回答状态")
        unresolved = [
            item
            for item in self.product_repository.list_messages(dive["session_id"])
            if item.role == "user" and item.resolution_status == "unresolved"
        ]
        if unresolved:
            raise JobTargetConflict("请先重试、修改或放弃上一次未完成的回答")
        message = (
            self.product_repository.append_user_message(
                dive["session_id"], content=content
            )
            if message_id is None
            else next(
                item
                for item in self.product_repository.list_messages(dive["session_id"])
                if item.id == message_id
            )
        )
        session = self.product_repository.get_session(dive["session_id"])
        execution = await self.executions.prepare_for_message(
            session,
            input_message_id=message.id,
            input={"message": message.content, "deepDiveId": dive_id},
            configuration={
                "providerModelId": provider_model_id,
                "reasoningEffort": reasoning_effort,
            },
        )
        self.repository.advance_deep_dive(
            dive_id,
            current_stage=dive["current_stage"],
            completed_stage_ids=tuple(
                json.loads(dive["completed_stage_ids_json"])
            ),
            waiting_for_input=False,
            status="active",
        )
        self._schedule_deep_dive(dive_id, message.id, execution)
        if self.agents is None:
            await self.executions.wait(execution.id)
        return self.deep_dive_resource(dive_id)

    def _schedule_deep_dive(
        self, dive_id: str, message_id: str, execution: ExecutionRecord
    ) -> None:
        async def handler(
            active: ExecutionRecord, cancellation: ExecutionCancellation
        ) -> None:
            try:
                await self._process_deep_dive_turn(
                    dive_id, message_id, active, cancellation
                )
            except asyncio.CancelledError:
                self._mark_message_unresolved(message_id)
                raise
            except Exception:
                self._mark_message_unresolved(message_id)
                raise

        self.executions.run_background(execution, handler)

    async def _process_deep_dive_turn(
        self,
        dive_id: str,
        message_id: str,
        execution: ExecutionRecord,
        cancellation: ExecutionCancellation,
    ) -> None:
        dive = self.repository.get_deep_dive(dive_id)
        message = next(
            item
            for item in self.product_repository.list_messages(dive["session_id"])
            if item.id == message_id
        )
        target = self.service.get_target(dive["job_target_id"])
        project_context = self.profile.confirmed_profile_context(
            purpose="job_target_analysis",
            claim_ids=(dive["project_claim_id"],),
            limit=1,
        )
        project = (
            project_context.items[0].value if project_context.items else {}
        )
        requirements = [
            {
                "id": item.id,
                "type": item.requirement_type,
                "priority": item.priority,
                "text": item.text,
            }
            for item in self.service.list_preparation_requirements(target.id)
            if item.confirmation_status == "confirmed"
        ]
        recent_messages = [
            {"role": item.role, "content": item.content}
            for item in self.product_repository.list_messages(dive["session_id"])
            if item.resolution_status == "active"
        ][-12:]
        cancellation.raise_if_requested()
        agents = self._agents_for_execution(execution)
        if agents is None:
            result = self._evaluate_turn(dive, message.content)
        else:
            model_result = await agents.evaluate_turn(
                stage=dive["current_stage"],
                target={
                    "company": target.company_name,
                    "role": target.role_name,
                    "seniority": target.seniority,
                },
                project=project,
                requirements=requirements,
                recent_messages=recent_messages,
                answer=message.content,
                context=self.executions.context(execution),
                config={},
            )
            result = _deep_dive_result(
                dive,
                model_result,
                has_previous_follow_up=any(
                    json.loads(item["payload_json"]).get("stage")
                    == dive["current_stage"]
                    for item in self.repository.list_artifacts(dive_id)
                ),
            )
        cancellation.raise_if_requested()
        with cancellation.critical_section():
            artifact_id = self.repository.create_artifact(
                dive_id,
                artifact_kind="turn_result",
                payload=result,
                execution_id=execution.id,
                message_id=message.id,
            )
            for gap in result["gaps"]:
                self.repository.create_gap(
                    dive_id,
                    kind=gap["kind"],
                    summary=gap["summary"],
                    source_artifact_id=artifact_id,
                )
            next_stage = result["nextStage"]
            completed = tuple(
                result.get(
                    "completedStageIds",
                    json.loads(dive["completed_stage_ids_json"]),
                )
            )
            finished = next_stage == "finished"
            self.repository.advance_deep_dive(
                dive_id,
                current_stage=next_stage,
                completed_stage_ids=tuple(dict.fromkeys(completed)),
                waiting_for_input=not finished,
                status="completed" if finished else "active",
            )
            if finished:
                self._generate_project_questions(dive_id)
            self.product_repository.append_message(
                dive["session_id"],
                execution_id=execution.id,
                role="assistant",
                content=result["reply"],
            )
            await self.executions.complete_background_execution(execution.id)

    def _agents_for_execution(
        self, execution: ExecutionRecord
    ) -> JobTargetAgents | None:
        model_id = execution.configuration.provider_model_id
        if model_id and self.agents_factory is not None:
            return self.agents_factory(
                ModelOverride(
                    provider_model_id=model_id,
                    reasoning_effort=execution.configuration.reasoning_effort,
                )
            )
        return self.agents

    def _mark_message_unresolved(self, message_id: str) -> None:
        message = next(
            (
                item
                for item in self.product_repository.connection.execute(
                    "SELECT resolution_status FROM agent_messages WHERE id = ?",
                    (message_id,),
                )
            ),
            None,
        )
        if message is not None and message["resolution_status"] == "active":
            self.product_repository.resolve_message(
                message_id, expected=("active",), target="unresolved"
            )

    async def retry_deep_dive(self, dive_id: str, execution_id: str) -> dict:
        dive = self.repository.get_deep_dive(dive_id)
        previous = self.product_repository.get_execution(execution_id)
        if previous.input_message_id is None:
            raise JobTargetConflict("本次执行没有可重试的用户回答")
        message = next(
            item
            for item in self.product_repository.list_messages(dive["session_id"])
            if item.id == previous.input_message_id
        )
        self.product_repository.resolve_message(
            message.id, expected=("unresolved", "active"), target="active"
        )
        session = self.product_repository.get_session(dive["session_id"])
        attempt = await self.executions.prepare_for_message(
            session,
            input_message_id=message.id,
            input={"message": message.content, "deepDiveId": dive_id},
            retry_of_execution_id=execution_id,
            configuration={
                "providerModelId": previous.configuration.provider_model_id,
                "reasoningEffort": previous.configuration.reasoning_effort,
            },
        )
        self._schedule_deep_dive(dive_id, message.id, attempt)
        if self.agents is None:
            await self.executions.wait(attempt.id)
        return self.deep_dive_resource(dive_id)

    def resolve_message(
        self, dive_id: str, message_id: str, *, resolution: str, replacement: str | None
    ) -> dict:
        dive = self.repository.get_deep_dive(dive_id)
        if resolution == "abandoned":
            self.product_repository.resolve_message(
                message_id, expected=("unresolved", "active"), target="abandoned"
            )
        elif resolution == "replaced" and replacement:
            self.product_repository.append_user_message(
                dive["session_id"],
                content=replacement,
                replaces_message_id=message_id,
            )
        else:
            raise ValueError("消息处理方式无效")
        return self.deep_dive_resource(dive_id)

    async def cancel_deep_dive_execution(
        self, dive_id: str, execution_id: str
    ) -> dict:
        dive = self.repository.get_deep_dive(dive_id)
        execution = self.product_repository.get_execution(execution_id)
        if execution.session_id != dive["session_id"]:
            raise JobTargetConflict("运行记录不属于当前项目深挖")
        cancelled = await self.executions.cancel(execution_id)
        if cancelled.input_message_id:
            self._mark_message_unresolved(cancelled.input_message_id)
        self.repository.advance_deep_dive(
            dive_id,
            current_stage=dive["current_stage"],
            completed_stage_ids=tuple(
                json.loads(dive["completed_stage_ids_json"])
            ),
            waiting_for_input=True,
            status=dive["status"],
        )
        return self.deep_dive_resource(dive_id)

    async def control_deep_dive(self, dive_id: str, action: str) -> dict:
        statuses = {"pause": "paused", "resume": "active", "terminate": "terminated"}
        if action not in statuses:
            raise ValueError("不支持的项目深挖操作")
        dive = self.repository.get_deep_dive(dive_id)
        running = next(
            (
                item
                for item in reversed(
                    self.product_repository.list_executions(dive["session_id"])
                )
                if item.status == "running"
            ),
            None,
        )
        if running is not None and action in {"pause", "terminate"}:
            await self.executions.cancel(running.id)
            if running.input_message_id:
                self._mark_message_unresolved(running.input_message_id)
        self.repository.transition_deep_dive(dive_id, statuses[action])
        if action == "resume":
            unfinished = next(
                (
                    item
                    for item in reversed(
                        self.product_repository.list_messages(dive["session_id"])
                    )
                    if item.role == "user" and item.resolution_status == "unresolved"
                ),
                None,
            )
            if unfinished is not None:
                previous = next(
                    (
                        item
                        for item in reversed(
                            self.product_repository.list_executions(dive["session_id"])
                        )
                        if item.input_message_id == unfinished.id
                    ),
                    None,
                )
                if previous is not None:
                    return await self.retry_deep_dive(dive_id, previous.id)
        return self.deep_dive_resource(dive_id)

    def deep_dive_resource(self, dive_id: str) -> dict:
        dive = self.repository.get_deep_dive(dive_id)
        messages = self.product_repository.list_messages(dive["session_id"])
        executions = self.product_repository.list_executions(dive["session_id"])
        artifacts = self.repository.list_artifacts(dive_id)
        gaps = self.repository.list_gaps(dive_id)
        candidates = self.repository.list_project_question_candidates(dive_id)
        return {
            "id": dive["id"],
            "jobTargetId": dive["job_target_id"],
            "projectClaimId": dive["project_claim_id"],
            "sessionId": dive["session_id"],
            "status": dive["status"],
            "currentStage": dive["current_stage"],
            "completedStageIds": json.loads(dive["completed_stage_ids_json"]),
            "waitingForInput": bool(dive["waiting_for_input"]),
            "version": dive["version"],
            "projectTitle": _project_title_for_dive(self.profile, dive),
            "messages": [_message_resource(item) for item in messages],
            "executions": [_execution_resource(item) for item in executions],
            "artifacts": [
                {
                    "id": row["id"],
                    "kind": row["artifact_kind"],
                    "payload": json.loads(row["payload_json"]),
                    "status": row["status"],
                    "version": row["version"],
                }
                for row in artifacts
            ],
            "gaps": [dict(row) for row in gaps],
            "questionCandidates": [
                {**dict(row), "question": json.loads(row["question_json"])}
                for row in candidates
            ],
            "runtime": {
                "modelRole": "project_deep_dive",
                "providerModelId": (
                    executions[-1].configuration.provider_model_id
                    if executions
                    else None
                ),
                "reasoningEffort": (
                    executions[-1].configuration.reasoning_effort
                    if executions
                    else "none"
                ),
                "calls": self.product_repository.usage(dive["session_id"])[
                    "callCount"
                ],
                "inputTokens": self.product_repository.usage(dive["session_id"])[
                    "inputTokens"
                ],
                "outputTokens": self.product_repository.usage(dive["session_id"])[
                    "outputTokens"
                ],
                "contextTokens": self.product_repository.context_usage(
                    dive["session_id"]
                )["currentTokens"],
                "contextThreshold": self.product_repository.context_usage(
                    dive["session_id"]
                )["thresholdTokens"],
                "estimated": bool(
                    self.product_repository.usage(dive["session_id"])[
                        "estimatedCount"
                    ]
                ),
                "compacted": self.product_repository.context_compacted(
                    dive["session_id"]
                ),
            },
        }

    def decide_question_candidate(self, candidate_id: str, decision: str) -> None:
        if decision not in {"confirmed", "ignored", "duplicate"}:
            raise ValueError("不支持的题目决定")
        self.repository.decide_project_question_candidate(candidate_id, decision)

    def confirm_narrative_sections(
        self,
        artifact_id: str,
        *,
        section_ids: tuple[str, ...],
        edited_values: dict[str, str],
        expected_project_version: int,
        idempotency_key: str,
    ) -> dict:
        artifact = self.repository.get_artifact(artifact_id)
        dive = self.repository.get_deep_dive(artifact["deep_dive_id"])
        payload = json.loads(artifact["payload_json"])
        suggestions = {
            item["section"]: item["content"]
            for item in payload.get("narrativeDelta", [])
        }
        selected = {
            section: edited_values.get(section, suggestions.get(section, "")).strip()
            for section in section_ids
            if edited_values.get(section, suggestions.get(section, "")).strip()
        }
        claim = self.profile.repository.get_claim(dive["project_claim_id"])
        if claim.version != expected_project_version:
            raise JobTargetConflict("项目画像已发生变化，请刷新后重新确认")
        current = self.profile.repository.get_claim_version(
            claim.current_confirmed_version_id
        )
        value = dict(current.value)
        if "background" in selected:
            value["background"] = selected["background"]
        if "role" in selected:
            value["role"] = selected["role"]
        actions = [
            selected[key]
            for key in ("solution", "difficulty", "tradeoff", "retrospective")
            if key in selected
        ]
        if actions:
            value["key_actions"] = list(
                dict.fromkeys([*value.get("key_actions", []), *actions])
            )[:30]
        if "outcome" in selected:
            value["results"] = list(
                dict.fromkeys([*value.get("results", []), selected["outcome"]])
            )[:30]
        version = self.profile.update_profile_card(
            claim.id,
            value=value,
            expected_version=expected_project_version,
            command_id=idempotency_key,
            session_id=dive["session_id"],
        )
        self.repository.confirm_narrative_sections(
            workspace_id=self.workspace_id,
            project_claim_id=claim.id,
            artifact_id=artifact_id,
            sections=selected,
            source_session_id=dive["session_id"],
            source_message_id=artifact["source_message_id"],
        )
        return {
            "artifactId": artifact_id,
            "confirmedSectionIds": list(selected),
            "projectClaimId": claim.id,
            "projectVersion": version.version,
        }

    def dispatch_gap(self, gap_id: str, *, idempotency_key: str) -> dict:
        gap = self.repository.get_gap(gap_id)
        kind = gap["gap_kind"]
        if kind == "experience":
            status, ref = "accepted_risk", f"risk:{gap_id}"
        elif kind == "knowledge":
            candidate_id = self.repository.create_project_question_candidate(
                gap["deep_dive_id"],
                gap["project_claim_id"],
                dimension="target_specific",
                question={
                    "title": gap["summary"],
                    "question": f"围绕这个薄弱点继续追问：{gap['summary']}",
                },
            )
            status, ref = "resolved", f"question:{candidate_id}"
        elif kind == "expression":
            artifact_id = self.repository.create_artifact(
                gap["deep_dive_id"],
                artifact_kind="narrative_proposal",
                payload={"summary": gap["summary"], "sourceGapId": gap_id},
            )
            status, ref = "resolved", f"narrative:{artifact_id}"
        else:
            status, ref = "resolved", f"profile-proposal:{gap_id}"
        self.repository.resolve_gap(gap_id, status=status, resolution_ref=ref)
        return {"gapId": gap_id, "status": status, "resolutionRef": ref}

    def readiness(self, target_id: str) -> dict:
        requirements = self.service.list_preparation_requirements(target_id)
        if any(item.confirmation_status == "pending" for item in requirements):
            status = "requirements_pending"
        elif not self.repository.list_project_priorities(target_id):
            status = "project_selection_pending"
        else:
            active = self.repository.connection.execute(
                "SELECT COUNT(*) FROM project_deep_dives WHERE job_target_id = ? "
                "AND status IN ('active', 'paused', 'interrupted')",
                (target_id,),
            ).fetchone()[0]
            open_risks = self.repository.connection.execute(
                "SELECT COUNT(*) FROM project_gaps gap JOIN project_deep_dives dive "
                "ON dive.id = gap.deep_dive_id WHERE dive.job_target_id = ? "
                "AND gap.gap_kind = 'experience' AND gap.status = 'open'",
                (target_id,),
            ).fetchone()[0]
            untrained = self.repository.connection.execute(
                "SELECT COUNT(*) FROM project_question_candidates candidate "
                "JOIN project_deep_dives dive ON dive.id = candidate.deep_dive_id "
                "WHERE dive.job_target_id = ? AND candidate.status != 'confirmed'",
                (target_id,),
            ).fetchone()[0]
            status = (
                "deep_dive_in_progress"
                if active
                else "high_risk_open"
                if open_risks or untrained
                else "core_preparation_complete"
            )
        return {
            "jobTargetId": target_id,
            "status": status,
            "requirements": len(requirements),
        }

    def _evaluate_turn(self, dive, answer: str) -> dict:
        stage = dive["current_stage"]
        next_stage = advance_stage(stage)
        needs_detail = len(answer.strip()) < 30
        gaps = (
            [{"kind": "expression", "summary": "当前回答较短，建议补充具体行动和结果"}]
            if needs_detail
            else []
        )
        question = _stage_question(next_stage)
        return {
            "stage": stage,
            "stageComplete": True,
            "evaluation": {
                "summary": "已保存本轮回答",
                "completeness": "basic" if needs_detail else "complete",
            },
            "narrativeDelta": [{"section": stage, "content": answer}],
            "targetFindings": [],
            "gaps": gaps,
            "nextStage": next_stage,
            "completedStageIds": list(
                dict.fromkeys(
                    (
                        *json.loads(dive["completed_stage_ids_json"]),
                        stage,
                    )
                )
            ),
            "reply": (
                "项目核心维度已经梳理完成，可以检查讲解草稿和候选题。"
                if next_stage == "finished"
                else question
            ),
        }

    def _generate_project_questions(self, dive_id: str) -> None:
        dive = self.repository.get_deep_dive(dive_id)
        for dimension, text in (
            ("background_role", "请介绍这个项目的背景、目标和你的职责。"),
            ("architecture_solution", "你为什么选择这个技术方案，还有哪些备选方案？"),
            ("difficulty_problem_solving", "项目中最难的问题是什么，你如何定位并解决？"),
            ("outcome", "项目最终取得了什么可量化结果？"),
            ("tradeoff_failure_retrospective", "如果重做一次，你会调整哪些设计？"),
            ("target_specific", "这段项目经验如何证明你胜任当前目标岗位？"),
        ):
            self.repository.create_project_question_candidate(
                dive_id,
                dive["project_claim_id"],
                dimension=dimension,
                question={"title": text, "question": text},
            )


def _extract_requirements(body: str) -> tuple[dict[str, object], ...]:
    lines = [
        line.strip(" -\t")
        for line in body.replace("；", "\n").replace("。", "\n").splitlines()
        if line.strip(" -\t")
    ]
    if not lines:
        lines = [body.strip()]
    result = []
    for index, line in enumerate(lines[:100]):
        if is_job_background_or_heading(line):
            continue
        lowered = line.lower()
        kind = (
            "skill"
            if any(token in lowered for token in ("python", "java", "sql", "redis", "技术", "熟悉", "掌握"))
            else "experience"
            if any(token in line for token in ("经验", "年"))
            else "project"
            if "项目" in line
            else "responsibility"
        )
        result.append(
            {
                "stable_key": hashlib.sha256(line.encode()).hexdigest()[:16],
                "requirement_type": kind,
                "priority": "must_have" if index < 5 else "nice_to_have",
                "text": line,
                "source_quote": line,
                "source_start": body.find(line),
                "source_end": body.find(line) + len(line),
                "inferred": False,
            }
        )
    return tuple(result)


def _version_number(value: str | int | None) -> int:
    if isinstance(value, int):
        return value
    if not value:
        return 0
    return int(hashlib.sha256(value.encode()).hexdigest()[:8], 16)


def _stage_question(stage: str) -> str:
    return {
        "role": "你在项目中具体负责哪些部分？请区分个人贡献与团队成果。",
        "solution": "核心方案是怎样设计的？为什么选择它？",
        "difficulty": "最棘手的问题是什么？你如何定位并解决？",
        "outcome": "最终结果如何？尽量给出可验证或可量化的变化。",
        "tradeoff": "方案做过哪些取舍？有哪些失败或遗憾？",
        "target_follow_up": "这段经历如何证明你能胜任当前目标岗位？",
        "finished": "",
    }.get(stage, "请继续补充这个项目。")


def _normalized_requirement(
    value: dict[str, object], document: str
) -> dict[str, object]:
    text = str(value.get("text") or "").strip()
    quote = str(value.get("source_quote") or "").strip()
    if quote and quote not in document:
        quote = ""
    start = document.find(quote) if quote else -1
    return {
        **value,
        "stable_key": str(value.get("stable_key") or "").strip()
        or hashlib.sha256(text.encode()).hexdigest()[:16],
        "text": text,
        "source_quote": quote,
        "source_start": start if start >= 0 else None,
        "source_end": start + len(quote) if start >= 0 else None,
        "inferred": bool(value.get("inferred")) or not bool(quote),
    }


def _deep_dive_result(
    dive, model_result, *, has_previous_follow_up: bool
) -> dict[str, object]:
    stage_complete = bool(model_result.stage_complete) or has_previous_follow_up
    current_stage = dive["current_stage"]
    next_stage = advance_stage(current_stage) if stage_complete else current_stage
    completed = tuple(json.loads(dive["completed_stage_ids_json"]))
    if stage_complete:
        completed = tuple(dict.fromkeys((*completed, current_stage)))
    question = (
        None
        if model_result.next_question is None
        else model_result.next_question.content.strip()
    )
    coach_reply = model_result.coach_reply.strip()
    follow_up = (
        "项目核心维度已经梳理完成，可以检查讲解草稿和候选题。"
        if next_stage == "finished"
        else question or _stage_question(next_stage)
    )
    reply = f"{coach_reply}\n\n{follow_up}" if coach_reply else follow_up
    return {
        "stage": current_stage,
        "stageComplete": stage_complete,
        "evaluation": model_result.answer_evaluation.model_dump(),
        "narrativeDelta": [
            item.model_dump() for item in model_result.narrative_delta
        ],
        "targetFindings": [
            item.model_dump() for item in model_result.target_findings
        ],
        "gaps": [item.model_dump() for item in model_result.gaps],
        "nextStage": next_stage,
        "completedStageIds": list(completed),
        "reply": reply,
    }


def _message_resource(item) -> dict[str, object]:
    return {
        "id": item.id,
        "executionId": item.execution_id,
        "role": item.role,
        "content": item.content,
        "messageKind": item.message_kind,
        "payload": item.payload,
        "createdAt": item.created_at,
        "replacesMessageId": item.replaces_message_id,
        "resolutionStatus": item.resolution_status,
    }


def _execution_resource(item: ExecutionRecord) -> dict[str, object]:
    return {
        "id": item.id,
        "sessionId": item.session_id,
        "inputMessageId": item.input_message_id,
        "retryOfExecutionId": item.retry_of_execution_id,
        "status": item.status,
        "configuration": {
            "providerModelId": item.configuration.provider_model_id,
            "reasoningEffort": item.configuration.reasoning_effort,
        },
        "cancelRequestedAt": item.cancel_requested_at,
        "errorCode": item.error_code,
        "errorMessage": item.error_message,
        "createdAt": item.created_at,
        "startedAt": item.started_at,
        "finishedAt": item.finished_at,
    }


def _execution_elapsed_ms(execution: ExecutionRecord | None) -> int:
    if execution is None or execution.started_at is None:
        return 0
    started = _utc_datetime(execution.started_at)
    finished = (
        _utc_datetime(execution.finished_at)
        if execution.finished_at is not None
        else datetime.now(UTC)
    )
    return max(0, int((finished - started).total_seconds() * 1000))


def _utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace(" ", "T"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _project_title(value: dict[str, object]) -> str:
    return str(value.get("name") or value.get("title") or "当前项目").strip()


def _project_title_for_dive(profile: ProfileService, dive) -> str:
    context = profile.confirmed_profile_context(
        purpose="job_target_analysis",
        claim_ids=(dive["project_claim_id"],),
        limit=1,
    )
    return _project_title(context.items[0].value if context.items else {})

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from urllib.parse import urlencode

from app.agents.context import AgentContext
from app.agents.interview_retrospective_agents import InterviewRetrospectiveAgents
from app.tools.interview_retrospective_tools import (
    RETROSPECTIVE_TOOL_NAMES,
    RETROSPECTIVE_TOOL_SCOPE,
)
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
    RetrospectiveVersionConflict,
)
from app.interview_retrospectives.repository import (
    InterviewRetrospectiveRepository,
)
from app.interview_retrospectives.service import InterviewRetrospectiveService
from app.knowledge.drafts import CreateDraftCommand, KnowledgeDraftService
from app.profile.models import CreateClaimProposalSpec
from app.profile.service import ProfileService
from app.review.question_similarity import question_similarity


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
        review=None,
        drafts: KnowledgeDraftService | None = None,
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
        self.review = review
        self.drafts = drafts
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

    def generate_candidates(self, retrospective_id: str, run_id: str):
        self.service.get(retrospective_id)
        run = self.get_analysis_run(retrospective_id, run_id)
        questions = self.repository.list_questions(
            retrospective_id, cleanup_version_id=run.cleanup_version_id
        )
        analyses = {
            item.question_unit_id: item
            for item in self.repository.list_question_analyses(run_id)
        }
        eligible = tuple(
            item for item in questions if item.decision_status == "confirmed"
        )
        if any(
            item.id not in analyses or analyses[item.id].result_status != "formal"
            for item in eligible
        ):
            raise ValueError("确认问题尚未全部完成分析")

        review_questions = () if self.review is None else self.review.list_questions()
        for question in eligible:
            analysis = analyses[question.id]
            matches = tuple(
                sorted(
                    (
                        {
                            "resourceId": item.snapshot.question_id,
                            "score": round(
                                question_similarity(
                                    question.question_text,
                                    item.snapshot.question_text,
                                ),
                                4,
                            ),
                            "title": item.snapshot.question_text,
                        }
                        for item in review_questions
                        if question_similarity(
                            question.question_text, item.snapshot.question_text
                        )
                        >= 0.45
                    ),
                    key=lambda item: (-float(item["score"]), str(item["resourceId"])),
                )
            )
            payload: dict[str, object] = {
                "questionText": question.question_text,
                "questionKind": question.question_kind,
                "sourceQuestionId": question.id,
                "verdict": analysis.verdict,
                "suggestedAnswer": analysis.suggested_answer,
                "keyPoints": list(analysis.improvement_outline),
            }
            self.repository.upsert_asset_candidate(
                retrospective_id,
                analysis_run_id=run_id,
                question_unit_id=question.id,
                candidate_kind="review_question",
                fingerprint=_digest(
                    {
                        "kind": "review_question",
                        "question": question.stable_key,
                        "payload": payload,
                    }
                ),
                payload=payload,
                matches=matches,
            )
            if question.question_kind == "project_experience":
                project_payload = {
                    "sourceQuestionId": question.id,
                    "questionText": question.question_text,
                    "suggestedNarrative": analysis.suggested_answer,
                    "improvementOutline": list(analysis.improvement_outline),
                }
                self.repository.upsert_asset_candidate(
                    retrospective_id,
                    analysis_run_id=run_id,
                    question_unit_id=question.id,
                    candidate_kind="project_narrative",
                    fingerprint=_digest(
                        {
                            "kind": "project_narrative",
                            "question": question.stable_key,
                            "payload": project_payload,
                        }
                    ),
                    payload=project_payload,
                    matches=self._project_matches(),
                )

        retrospective = self.service.get(retrospective_id)
        summary_payload = {
            "title": retrospective.title,
            "roundLabel": retrospective.round_label,
            "interviewDate": retrospective.interview_date,
            "questionIds": [item.id for item in eligible],
            "verdictCounts": _verdict_counts(eligible, analyses),
        }
        self.repository.upsert_asset_candidate(
            retrospective_id,
            analysis_run_id=run_id,
            question_unit_id=None,
            candidate_kind="summary",
            fingerprint=_digest({"kind": "summary", "payload": summary_payload}),
            payload=summary_payload,
        )
        eligible_ids = {item.id for item in eligible}
        for gap in self.repository.list_gaps(run_id):
            if gap.question_unit_id not in eligible_ids:
                continue
            self.repository.upsert_action_item(
                retrospective_id,
                analysis_run_id=run_id,
                question_unit_id=gap.question_unit_id,
                gap_id=gap.id,
                action_kind=gap.gap_kind,
                title=gap.summary,
                detail=f"来自复盘问题 {gap.question_unit_id}",
            )
        return self.repository.list_asset_candidates(retrospective_id)

    def _project_matches(self) -> tuple[dict[str, object], ...]:
        if self.profile is None:
            return ()
        return tuple(
            {
                "resourceId": item.id,
                "resourceVersion": item.version,
                "score": 1.0,
            }
            for item in self.profile.repository.list_claims(self.workspace_id)
            if item.claim_type == "project"
        )

    def list_candidates(self, retrospective_id: str, *, status: str | None = None):
        self.service.get(retrospective_id)
        return self.repository.list_asset_candidates(retrospective_id, status=status)

    async def decide_candidate(
        self,
        retrospective_id: str,
        candidate_id: str,
        *,
        action: str,
        target_resource_id: str | None,
        action_payload: dict[str, object],
        expected_version: int,
        idempotency_key: str,
    ):
        self.service.get(retrospective_id)
        candidate = self.repository.get_asset_candidate(candidate_id)
        if candidate.retrospective_id != retrospective_id:
            raise RetrospectiveTargetRequired("候选项不属于当前复盘")
        request = {
            "candidateId": candidate_id,
            "action": action,
            "targetResourceId": target_resource_id,
            "payload": action_payload,
            "expectedVersion": expected_version,
        }
        request_hash = _digest(request)
        scope = f"candidate_decision:{candidate_id}"
        replay = self.repository.receipt(retrospective_id, scope, idempotency_key)
        if replay is not None:
            saved_hash, result = replay
            if saved_hash != request_hash:
                raise RetrospectiveIdempotencyConflict("同一幂等键不能处理不同候选项")
            return self.repository.get_asset_candidate(str(result["candidateId"]))
        allowed = {
            "review_question": {
                "link_existing",
                "supplement_existing",
                "create_new",
                "reject",
            },
            "profile_claim": {
                "link_existing",
                "propose_update",
                "propose_new",
                "reject",
            },
            "project_narrative": {
                "link_existing",
                "propose_update",
                "propose_new",
                "reject",
            },
            "summary": {"include", "exclude"},
        }
        if action not in allowed[candidate.candidate_kind]:
            raise ValueError("候选动作与类型不匹配")
        target_type: str | None = None
        resolved_target: str | None = None
        try:
            if action in {"reject", "exclude"}:
                status = "rejected"
            elif candidate.candidate_kind == "summary":
                status, target_type, resolved_target = (
                    "confirmed",
                    "interview_retrospective_summary",
                    retrospective_id,
                )
            elif candidate.candidate_kind == "review_question":
                target_type, resolved_target = await self._write_review_candidate(
                    retrospective_id,
                    candidate,
                    action=action,
                    target_resource_id=target_resource_id,
                    action_payload=action_payload,
                )
                status = "confirmed"
            else:
                target_type, resolved_target = self._write_profile_candidate(
                    retrospective_id,
                    candidate,
                    action=action,
                    target_resource_id=target_resource_id,
                    action_payload=action_payload,
                    idempotency_key=idempotency_key,
                )
                status = "confirmed"
            decided = self.repository.transition_asset_candidate(
                candidate_id,
                status=status,
                target_resource_type=target_type,
                target_resource_id=resolved_target,
                last_error_code=None,
                expected_version=expected_version,
            )
        except Exception as error:
            if candidate.status in {"pending", "blocked", "failed"}:
                self.repository.transition_asset_candidate(
                    candidate_id,
                    status="failed",
                    target_resource_type=None,
                    target_resource_id=None,
                    last_error_code=type(error).__name__,
                    expected_version=candidate.version,
                )
            raise
        self.repository.save_receipt(
            retrospective_id,
            scope=scope,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            result={"candidateId": decided.id},
        )
        return decided

    async def _write_review_candidate(
        self,
        retrospective_id: str,
        candidate,
        *,
        action: str,
        target_resource_id: str | None,
        action_payload: dict[str, object],
    ) -> tuple[str, str]:
        if self.review is None:
            raise ValueError("题库适配器不可用")
        if action == "link_existing":
            if target_resource_id is None:
                raise ValueError("请选择已有题目")
            target = self.review.get_confirmed_question(target_resource_id)
            if target.workspace_id != self.workspace_id:
                raise ValueError("题目不属于当前工作区")
            return "review_question", target.snapshot.question_id
        if action == "supplement_existing" and target_resource_id is None:
            raise ValueError("补充已有题目必须选择目标")
        created = await self.review.create_retrospective_candidate(
            retrospective_id=retrospective_id,
            payload=json.loads(candidate.payload_json),
            target_question_id=target_resource_id,
            edited_payload=action_payload,
        )
        return "review_question_candidate", created.id

    def _write_profile_candidate(
        self,
        retrospective_id: str,
        candidate,
        *,
        action: str,
        target_resource_id: str | None,
        action_payload: dict[str, object],
        idempotency_key: str,
    ) -> tuple[str, str]:
        if self.profile is None:
            raise ValueError("画像适配器不可用")
        if action == "link_existing":
            if target_resource_id is None:
                raise ValueError("请选择已有画像项")
            claim = self.profile.repository.get_claim(target_resource_id)
            if claim.workspace_id != self.workspace_id:
                raise ValueError("画像项不属于当前工作区")
            return "profile_claim", claim.id
        proposal_type = "update" if action == "propose_update" else "create"
        target = None
        base = None
        if proposal_type == "update":
            if target_resource_id is None:
                raise ValueError("更新建议必须选择目标画像项")
            target = self.profile.repository.get_claim(target_resource_id)
            if target.workspace_id != self.workspace_id:
                raise ValueError("画像项不属于当前工作区")
            base = target.current_confirmed_version_id
        category = (
            "project"
            if candidate.candidate_kind == "project_narrative"
            else str(action_payload.get("category", "highlight"))
        )
        payload = json.loads(candidate.payload_json)
        supplied_value = action_payload.get("value", {})
        if not isinstance(supplied_value, dict):
            raise ValueError("画像建议内容格式不正确")
        proposed_value: dict[str, object] = {}
        if target is not None and base is not None:
            proposed_value.update(self.profile.repository.get_claim_version(base).value)
        proposed_value.update(supplied_value)
        if category == "project" and not proposed_value.get("name"):
            proposed_value["name"] = str(
                payload.get("questionText") or "面试复盘项目经历"
            )[:200]
            narrative = str(payload.get("suggestedNarrative") or "").strip()
            if narrative:
                proposed_value["key_actions"] = [narrative[:200]]
        elif category == "highlight" and not proposed_value.get("text"):
            proposed_value["text"] = str(
                payload.get("suggestedClaim")
                or payload.get("questionText")
                or "来自面试复盘的画像建议"
            )[:2000]
        proposed_value["category"] = category
        proposals = self.profile.create_retrospective_proposals(
            (
                CreateClaimProposalSpec(
                    proposal_type=proposal_type,
                    target_claim_id=None if target is None else target.id,
                    base_claim_version_id=base,
                    proposed_value=proposed_value,
                    reason=f"来自面试复盘 {retrospective_id}",
                ),
            ),
            retrospective_id=retrospective_id,
            candidate_id=candidate.id,
            idempotency_key=idempotency_key,
        )
        return "profile_claim_proposal", proposals[0].id

    def list_actions(self, retrospective_id: str):
        self.service.get(retrospective_id)
        return self.repository.list_action_items(retrospective_id)

    def conversation(self, retrospective_id: str) -> dict[str, object]:
        retrospective = self.service.get(retrospective_id)
        session = self.products.get_session(retrospective.chat_session_id)
        latest = self.products.latest_execution(session.id)
        return {
            "sessionId": session.id,
            "messages": self.products.list_messages(session.id),
            "proposals": self.repository.list_correction_proposals(retrospective_id),
            "latestExecution": latest,
        }

    async def send_chat_message(
        self,
        retrospective_id: str,
        *,
        message: str,
        selected_question_id: str | None,
    ):
        if self.agents is None:
            raise RetrospectiveModelNotConfigured("请先配置面试复盘分析模型")
        retrospective = self.service.get(retrospective_id)
        if selected_question_id is not None:
            question = self.repository.get_question(selected_question_id)
            if question.retrospective_id != retrospective_id:
                raise RetrospectiveTargetRequired("问题不属于当前复盘")
        session = self.products.get_session(retrospective.chat_session_id)
        user_message = self.products.append_user_message(session.id, content=message)
        execution = await self.executions.prepare_for_message(
            session,
            input_message_id=user_message.id,
            input={
                "message": message.strip(),
                "selectedQuestionId": selected_question_id,
                "retrospectiveId": retrospective_id,
            },
        )

        async def handle_chat(current, cancellation):
            cancellation.raise_if_requested()
            context = replace(
                self.executions.context(current),
                allowed_tools=frozenset(RETROSPECTIVE_TOOL_NAMES),
                allowed_scopes=frozenset({RETROSPECTIVE_TOOL_SCOPE}),
                retrospective_id=retrospective_id,
                tool_result_item_limit=20,
                tool_excerpt_char_limit=2_000,
                progress_scope=("interview_retrospective_chat",),
            )
            history = [
                {"role": item.role, "content": item.content}
                for item in self.products.list_messages(session.id)
                if item.id != user_message.id
            ]
            result = await self.agents.discuss(
                message=message.strip(),
                selected_question_id=selected_question_id,
                conversation=history,
                context=context,
                config={"configurable": {"thread_id": session.id}},
            )
            cancellation.raise_if_requested()
            if result.result_type == "explanation":
                self.products.append_message(
                    session.id,
                    execution_id=current.id,
                    role="assistant",
                    content=result.explanation,
                )
                return
            question = None
            if result.question_id is not None:
                question = self.repository.get_question(result.question_id)
                if question.retrospective_id != retrospective_id:
                    raise RetrospectiveTargetRequired("纠正问题不属于当前复盘")
            cleanup_id = (
                question.cleanup_version_id
                if question is not None
                else retrospective.active_cleanup_version_id
            )
            if cleanup_id is None:
                raise ValueError("复盘尚无可纠正的整理版本")
            if question is not None:
                before = {
                    "questionText": question.question_text,
                    "questionSegmentIds": list(question.question_segment_ids),
                    "answerSegmentIds": list(question.answer_segment_ids),
                }
                expected_version = question.version
            else:
                cleanup = self.repository.get_cleanup_version(cleanup_id)
                before = {"cleanupVersionId": cleanup.id}
                expected_version = cleanup.version
            assistant = self.products.append_message(
                session.id,
                execution_id=current.id,
                role="assistant",
                content="我整理了一条纠正建议。确认前不会修改当前复盘。",
                message_kind="proposal_card",
                payload={"proposalType": result.result_type},
            )
            self.repository.create_correction_proposal(
                retrospective_id,
                chat_message_id=assistant.id,
                proposal_type=result.result_type,
                target_question_id=None if question is None else question.id,
                source_cleanup_version_id=cleanup_id,
                source_analysis_run_id=retrospective.active_analysis_run_id,
                before=before,
                after=result.after,
                rationale=result.rationale,
                expected_version=expected_version,
            )

        self.executions.run_background(execution, handle_chat)
        return execution

    async def stop_chat(self, retrospective_id: str, execution_id: str):
        retrospective = self.service.get(retrospective_id)
        execution = self.products.get_execution(execution_id)
        if execution.session_id != retrospective.chat_session_id:
            raise RetrospectiveTargetRequired("讨论运行不属于当前复盘")
        return await self.executions.cancel(execution_id)

    async def decide_correction(
        self,
        retrospective_id: str,
        proposal_id: str,
        *,
        decision: str,
    ):
        retrospective = self.service.get(retrospective_id)
        proposal = self.repository.get_correction_proposal(proposal_id)
        if proposal.retrospective_id != retrospective_id:
            raise RetrospectiveTargetRequired("纠正建议不属于当前复盘")
        if proposal.status == decision:
            return proposal
        if proposal.status != "pending":
            raise ValueError("纠正建议已经处理")
        if decision == "rejected":
            return self.repository.decide_correction_proposal(
                proposal_id, status="rejected"
            )
        if decision != "confirmed":
            raise ValueError("不支持的纠正决定")
        if proposal.proposal_type == "speaker_correction":
            cleanup = self.repository.get_cleanup_version(
                proposal.source_cleanup_version_id
            )
            if (
                cleanup.version != proposal.expected_version
                or retrospective.active_cleanup_version_id != cleanup.id
            ):
                raise RetrospectiveVersionConflict("整理版本已经更新，请重新提出纠正")
            changes = proposal.after.get("segments", [])
            if not isinstance(changes, list):
                raise ValueError("说话人纠正内容格式不正确")
            by_id = {
                str(item.get("segmentId")): item
                for item in changes
                if isinstance(item, dict) and item.get("segmentId")
            }
            source_segments = self.repository.list_segments(cleanup.id)
            if set(by_id) - {item.id for item in source_segments}:
                raise RetrospectiveTargetRequired("说话人片段不属于当前整理版本")
            digest = _digest({"proposalId": proposal.id, "after": proposal.after})
            next_cleanup = self.service.create_cleanup_version(
                retrospective_id,
                source_version_id=cleanup.source_version_id,
                input_digest=digest,
                idempotency_key=f"correction-cleanup-{proposal.id}",
            )
            next_cleanup = self.service.replace_segments(
                retrospective_id,
                next_cleanup.id,
                expected_version=next_cleanup.version,
                segments=tuple(
                    {
                        "speaker_role": str(
                            by_id.get(item.id, {}).get("speakerRole", item.speaker_role)
                        ),
                        "raw_speaker_label": item.raw_speaker_label,
                        "display_name": str(
                            by_id.get(item.id, {}).get("displayName", item.display_name)
                        ),
                        "body": item.body,
                        "source_start": item.source_start,
                        "source_end": item.source_end,
                        "confidence": item.confidence,
                        "uncertainty_reason": item.uncertainty_reason,
                        "ignored": item.ignored,
                    }
                    for item in source_segments
                ),
            )
            next_cleanup = self.service.confirm_cleanup(
                retrospective_id,
                next_cleanup.id,
                expected_version=next_cleanup.version,
                idempotency_key=f"correction-confirm-{proposal.id}",
            )
            run = self.service.create_analysis_run(
                retrospective_id,
                next_cleanup.id,
                input_digest=_digest({"cleanup": next_cleanup.input_digest}),
                context_snapshot=self._analysis_context_snapshot(retrospective),
                idempotency_key=f"correction-analysis-{proposal.id}",
            )
            decided = self.repository.decide_correction_proposal(
                proposal_id,
                status="confirmed",
                resulting_cleanup_version_id=next_cleanup.id,
                resulting_analysis_run_id=run.id,
            )
            await self._schedule_analysis(retrospective, run.id)
            return decided
        if (
            proposal.target_question_id is None
            or proposal.source_analysis_run_id is None
        ):
            raise ValueError("纠正建议缺少目标问题或分析版本")
        after = proposal.after
        if proposal.proposal_type == "question_text_correction":
            self.repository.apply_question_correction(
                proposal.target_question_id,
                expected_version=proposal.expected_version,
                question_text=str(after.get("questionText", "")),
            )
        elif proposal.proposal_type == "question_segment_rebind":
            self.repository.apply_question_correction(
                proposal.target_question_id,
                expected_version=proposal.expected_version,
                question_segment_ids=tuple(
                    str(item) for item in after.get("questionSegmentIds", [])
                ),
                answer_segment_ids=tuple(
                    str(item) for item in after.get("answerSegmentIds", [])
                ),
            )
        elif proposal.proposal_type != "analysis_reconsideration":
            raise ValueError("不支持的纠正类型")
        else:
            question = self.repository.get_question(proposal.target_question_id)
            if question.version != proposal.expected_version:
                raise ValueError("问题已经更新，请重新提出分析建议")
        source_run = self.repository.get_analysis_run(proposal.source_analysis_run_id)
        if retrospective.active_analysis_run_id != source_run.id:
            raise RetrospectiveVersionConflict("分析版本已经更新，请重新提出纠正")
        if source_run.status in {"queued", "running", "stopping"}:
            raise ValueError("当前分析仍在运行，请完成或停止后再确认纠正")
        run = self.repository.insert_local_reanalysis_run(
            retrospective_id,
            source_run_id=source_run.id,
            question_id=proposal.target_question_id,
            input_digest=_digest({"proposalId": proposal.id, "after": proposal.after}),
            context_snapshot={
                **json.loads(source_run.context_snapshot_json),
                "correction": {
                    "type": proposal.proposal_type,
                    "rationale": proposal.rationale,
                },
            },
        )
        decided = self.repository.decide_correction_proposal(
            proposal_id,
            status="confirmed",
            resulting_analysis_run_id=run.id,
        )
        await self._schedule_analysis(retrospective, run.id)
        return decided

    def decide_action(
        self,
        retrospective_id: str,
        action_id: str,
        *,
        decision: str,
        expected_version: int,
        idempotency_key: str,
    ):
        if decision not in {"completed", "dismissed"}:
            raise ValueError("不支持的行动项状态")
        self.service.get(retrospective_id)
        request_hash = _digest(
            {
                "actionId": action_id,
                "decision": decision,
                "expectedVersion": expected_version,
            }
        )
        scope = f"action_decision:{action_id}"
        replay = self.repository.receipt(retrospective_id, scope, idempotency_key)
        if replay is not None:
            saved_hash, result = replay
            if saved_hash != request_hash:
                raise RetrospectiveIdempotencyConflict("同一幂等键不能处理不同行动项")
            return self.repository.get_action_item(str(result["actionId"]))
        action = self.repository.get_action_item(action_id)
        if action.retrospective_id != retrospective_id:
            raise RetrospectiveTargetRequired("行动项不属于当前复盘")
        decided = self.repository.decide_action_item(
            action_id, decision=decision, expected_version=expected_version
        )
        self.repository.save_receipt(
            retrospective_id,
            scope=scope,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            result={"actionId": decided.id},
        )
        return decided

    def immediate_practice_link(
        self, retrospective_id: str, review_question_id: str
    ) -> str:
        self.service.get(retrospective_id)
        if self.review is None:
            raise ValueError("题库适配器不可用")
        target = self.review.get_confirmed_question(review_question_id)
        if target.workspace_id != self.workspace_id:
            raise ValueError("题目不属于当前工作区")
        return "/review?" + urlencode(
            {
                "questionId": target.snapshot.question_id,
                "source": "retrospective",
                "id": retrospective_id,
            }
        )

    async def create_publication_draft(
        self,
        retrospective_id: str,
        *,
        selected_sections: tuple[str, ...],
        idempotency_key: str,
    ):
        retrospective = self.service.get(retrospective_id)
        allowed = {
            "basic_info",
            "confirmed_questions",
            "selected_conclusions",
            "confirmed_experiences",
            "action_items",
            "stable_links",
        }
        if not selected_sections or set(selected_sections) - allowed:
            raise ValueError("发布范围不合法")
        request_hash = _digest({"sections": list(selected_sections)})
        scope = "publication_draft"
        replay = self.repository.receipt(retrospective_id, scope, idempotency_key)
        if replay is not None:
            saved_hash, result = replay
            if saved_hash != request_hash:
                raise RetrospectiveIdempotencyConflict("同一幂等键不能生成不同发布稿")
            if self.drafts is None:
                raise ValueError("Knowledge 草稿服务不可用")
            return await self.drafts.get(str(result["draftId"]))
        if self.drafts is None:
            raise ValueError("Knowledge 草稿服务不可用")
        active_run = (
            None
            if retrospective.active_analysis_run_id is None
            else self.repository.get_analysis_run(retrospective.active_analysis_run_id)
        )
        draft = await self.drafts.create(
            CreateDraftCommand(
                domain="review",
                document_type="interview_retrospective",
                title=f"面试复盘：{retrospective.title}",
                markdown=self._publication_markdown(
                    retrospective_id, selected_sections
                ),
                source_refs=(f"retrospective:{retrospective_id}",),
                relation_refs=(f"job-target:{retrospective.job_target_id}",),
                session_id=retrospective.analysis_session_id,
                run_id=None if active_run is None else active_run.execution_id,
                agent_type="interview_retrospective",
            )
        )
        self.repository.save_receipt(
            retrospective_id,
            scope=scope,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            result={"draftId": draft.id},
        )
        return draft

    def _publication_markdown(
        self, retrospective_id: str, selected_sections: tuple[str, ...]
    ) -> str:
        retrospective = self.service.get(retrospective_id)
        run_id = retrospective.active_analysis_run_id
        if run_id is None:
            raise ValueError("复盘尚未生成分析")
        run = self.repository.get_analysis_run(run_id)
        questions = tuple(
            item
            for item in self.repository.list_questions(
                retrospective_id, cleanup_version_id=run.cleanup_version_id
            )
            if item.decision_status == "confirmed"
        )
        analyses = {
            item.question_unit_id: item
            for item in self.repository.list_question_analyses(run_id)
            if item.result_status == "formal"
        }
        lines = [f"# {retrospective.title}", ""]
        if "basic_info" in selected_sections:
            lines.extend(
                [
                    "## 基本信息",
                    f"- 面试轮次：{retrospective.round_label}",
                    f"- 面试日期：{retrospective.interview_date or '未记录'}",
                    f"- 面试结果：{retrospective.outcome}",
                    "",
                ]
            )
        if "confirmed_questions" in selected_sections:
            lines.extend(["## 已确认问题", ""])
            for index, question in enumerate(questions, start=1):
                lines.append(f"### {index}. {question.question_text}")
                analysis = analyses.get(question.id)
                if analysis is not None and analysis.suggested_answer:
                    lines.extend(["", analysis.suggested_answer])
                lines.append("")
        if "selected_conclusions" in selected_sections:
            lines.extend(["## 复盘结论", ""])
            for question in questions:
                analysis = analyses.get(question.id)
                if analysis is not None:
                    lines.append(f"- {question.question_text}：{analysis.verdict}")
            lines.append("")
        if "confirmed_experiences" in selected_sections:
            lines.extend(["## 已确认经历", ""])
            for candidate in self.repository.list_asset_candidates(retrospective_id):
                if (
                    candidate.candidate_kind == "project_narrative"
                    and candidate.status == "confirmed"
                ):
                    payload = json.loads(candidate.payload_json)
                    lines.append(f"- {payload.get('suggestedNarrative', '')}")
            lines.append("")
        if "action_items" in selected_sections:
            lines.extend(["## 后续行动", ""])
            for item in self.repository.list_action_items(retrospective_id):
                marker = "x" if item.status == "completed" else " "
                lines.append(f"- [{marker}] {item.title}")
            lines.append("")
        if "stable_links" in selected_sections:
            lines.extend(
                ["## 关联", "", f"- 复盘：retrospective:{retrospective_id}", ""]
            )
        return "\n".join(lines).rstrip() + "\n"

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
                    elif current.work_key == "candidate_generation":
                        with cancellation.critical_section():
                            candidates = self.generate_candidates(
                                run.retrospective_id, run_id
                            )
                            self.repository.complete_analysis_work_item(
                                current.id,
                                output={
                                    "candidateIds": [item.id for item in candidates],
                                    "actionItemIds": [
                                        item.id
                                        for item in self.list_actions(
                                            run.retrospective_id
                                        )
                                    ],
                                },
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


def _verdict_counts(questions, analyses) -> dict[str, int]:
    counts: dict[str, int] = {}
    for question in questions:
        verdict = analyses[question.id].verdict
        counts[verdict] = counts.get(verdict, 0) + 1
    return counts

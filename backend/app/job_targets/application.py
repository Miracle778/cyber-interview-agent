from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from app.application.execution_service import AgentExecutionService
from app.application.session_service import AgentSessionService, ProductRepository
from app.graphs.project_deep_dive import advance_stage
from app.job_targets.errors import JobTargetBusy, JobTargetConflict
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
    ) -> None:
        self.workspace_id = workspace_id
        self.service = service
        self.repository = repository
        self.profile = profile
        self.sessions = sessions
        self.executions = executions
        self.product_repository = product_repository

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
        self._run_analysis(run_id)
        return self.analysis_resource(run_id)

    def _run_analysis(self, run_id: str) -> None:
        run = self.repository.get_analysis_run(run_id)
        target = self.service.get_target(run["job_target_id"])
        document = self.service.get_document_version(run["document_version_id"])
        for item in self.repository.list_analysis_work_items(run_id):
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
            if key == "requirement_extraction":
                suggestions = _extract_requirements(document.body)
                requirements = self.service.replace_requirement_suggestions(
                    target.id, document.id, suggestions=suggestions
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
            self.repository.complete_analysis_work_item(item["id"], output)
            self.repository.transition_analysis(run_id, status="running", stage=stage)
        self.repository.transition_analysis(
            run_id, status="review_pending", stage="waiting_for_review"
        )

    def analysis_resource(self, run_id: str) -> dict:
        run = self.repository.get_analysis_run(run_id)
        items = self.repository.list_analysis_work_items(run_id)
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
            "progress": {
                "completed": completed,
                "total": len(items),
                "activeWorkers": int(run["status"] == "running"),
            },
            "timing": {
                "currentElapsedMs": 0,
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
                "canTerminate": run["status"] not in {"completed", "terminated"},
            },
        }

    def current_analysis(self, target_id: str) -> dict | None:
        self.service.get_target(target_id)
        row = self.repository.current_analysis_run(target_id)
        return None if row is None else self.analysis_resource(row["id"])

    def control_analysis(self, run_id: str, action: str) -> dict:
        row = self.repository.get_analysis_run(run_id)
        if action == "pause":
            self.repository.transition_analysis(run_id, status="paused", control_intent=None)
        elif action == "resume":
            self.repository.transition_analysis(run_id, status="running", control_intent=None)
            self._run_analysis(run_id)
        elif action == "terminate":
            self.repository.transition_analysis(run_id, status="terminated", stage="terminated")
        else:
            raise ValueError("不支持的岗位分析操作")
        return self.analysis_resource(run_id)

    def retry_work_item(self, run_id: str, item_id: str) -> dict:
        self.repository.get_analysis_run(run_id)
        self.repository.retry_analysis_work_item(item_id)
        self.repository.transition_analysis(run_id, status="running", control_intent=None)
        self._run_analysis(run_id)
        return self.analysis_resource(run_id)

    async def create_deep_dive(self, target_id: str, project_claim_id: str) -> dict:
        self.service.get_target(target_id)
        self.service._assert_confirmed_project(
            project_claim_id, "项目深挖只能使用已确认的画像项目"
        )
        current = self.repository.current_deep_dive(target_id, project_claim_id)
        if current is not None:
            return self.deep_dive_resource(current["id"])
        session = await self.sessions.create(
            workspace_id=self.workspace_id,
            kind="project.deep_dive",
            title="项目深挖",
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

    async def answer_deep_dive(
        self, dive_id: str, content: str, *, message_id: str | None = None
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
        )
        try:
            result = self._evaluate_turn(dive, message.content)
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
            completed = tuple(json.loads(dive["completed_stage_ids_json"])) + (
                dive["current_stage"],
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
            self.product_repository.transition_execution(
                execution.id, expected=("running",), target="completed"
            )
        except Exception:
            self.product_repository.resolve_message(
                message.id, expected=("active",), target="unresolved"
            )
            self.product_repository.transition_execution(
                execution.id,
                expected=("running",),
                target="failed",
                error_code="deep_dive_failed",
                error_message="本次回答处理未完成",
            )
            raise
        return self.deep_dive_resource(dive_id)

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
        )
        result = self._evaluate_turn(dive, message.content)
        self.product_repository.append_message(
            dive["session_id"], execution_id=attempt.id, role="assistant", content=result["reply"]
        )
        self.product_repository.transition_execution(
            attempt.id, expected=("running",), target="completed"
        )
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

    def control_deep_dive(self, dive_id: str, action: str) -> dict:
        statuses = {"pause": "paused", "resume": "active", "terminate": "terminated"}
        if action not in statuses:
            raise ValueError("不支持的项目深挖操作")
        self.repository.transition_deep_dive(dive_id, statuses[action])
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
            "messages": [asdict(item) for item in messages],
            "executions": [asdict(item) for item in executions],
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
                "calls": len(executions),
                "inputTokens": 0,
                "outputTokens": 0,
                "contextTokens": 0,
                "contextThreshold": 0,
                "estimated": True,
                "compacted": False,
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
        requirements = self.service.list_requirements(target_id)
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
            "evaluation": {
                "summary": "已保存本轮回答",
                "completeness": "basic" if needs_detail else "complete",
            },
            "narrativeDelta": [{"section": stage, "content": answer}],
            "targetFindings": [],
            "gaps": gaps,
            "nextStage": next_stage,
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

from __future__ import annotations

import json
import sqlite3
from hashlib import sha256
from typing import Any

from app.evaluation.outcomes import (
    BusinessOutcomePayload,
    BusinessOutcomeProjection,
    OutcomeCounters,
    OutcomeIdentity,
    OutcomeInput,
    OutcomeItem,
    OutcomeProvenance,
    OutcomeUnit,
    OutcomeUserDecision,
    freeze_business_outcome,
)


class SqliteOutcomeAdapter:
    task_type: str

    def __init__(
        self,
        connection: sqlite3.Connection,
        workspace_id: str,
        task_type: str,
    ) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.workspace_id = workspace_id
        self.task_type = task_type

    def build(self, execution_id: str) -> BusinessOutcomeProjection:
        execution = self._execution(execution_id)
        if self.task_type in {"review_round", "review_single"}:
            return self._review(execution)
        if self.task_type == "review_discussion":
            return self._discussion(execution)
        if self.task_type == "profile_ingest":
            return self._profile_ingest(execution)
        if self.task_type == "profile_assessment":
            return self._profile_assessment(execution)
        if self.task_type == "profile_assistant":
            return self._profile_assistant(execution, write_boundary=False)
        if self.task_type == "profile_write_boundary":
            return self._profile_assistant(execution, write_boundary=True)
        if self.task_type == "job_requirement_analysis":
            return self._job_analysis(execution)
        if self.task_type in {
            "project_deep_dive_coaching",
            "project_question_generation",
        }:
            return self._project(execution)
        raise LookupError(f"unsupported outcome task: {self.task_type}")

    def _execution(self, execution_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT run.*, session.workspace_id, session.graph_id, "
            "session.graph_version FROM agent_runs run JOIN agent_sessions session "
            "ON session.id = run.session_id WHERE run.id = ? "
            "AND session.workspace_id = ?",
            (execution_id, self.workspace_id),
        ).fetchone()
        if row is None:
            raise LookupError(execution_id)
        return row

    def _review(self, execution: sqlite3.Row) -> BusinessOutcomeProjection:
        round_row = self.connection.execute(
            "SELECT * FROM review_rounds WHERE workspace_id = ? "
            "AND (execution_id = ? OR session_id = ?) "
            "ORDER BY updated_at DESC LIMIT 1",
            (self.workspace_id, execution["id"], execution["session_id"]),
        ).fetchone()
        if round_row is None:
            return self._empty(
                execution,
                terminal_state=str(execution["status"]),
                gaps=("review_round_not_found",),
            )
        attempts = self.connection.execute(
            "SELECT * FROM review_attempts WHERE round_id = ? ORDER BY ordinal, id",
            (round_row["id"],),
        ).fetchall()
        items: list[OutcomeItem] = []
        units: list[OutcomeUnit] = []
        source_refs: set[str] = set()
        statuses: list[str] = []
        for row in attempts:
            question = _object(row["question_snapshot_json"])
            question_id = str(question.get("question_id") or question.get("questionId") or "")
            if question_id:
                source_refs.add(f"question:{question_id}")
            status = (
                "skipped"
                if bool(row["skipped"])
                else "completed"
                if row["evaluation_json"]
                else "pending"
            )
            statuses.append(status)
            provenance = [
                OutcomeProvenance(
                    field_path="content.question",
                    support_type="direct",
                    source_refs=(f"question:{question_id}",) if question_id else (),
                )
            ]
            if row["answer"]:
                provenance.append(
                    OutcomeProvenance(
                        field_path="content.answer",
                        support_type="user_asserted",
                        source_refs=(f"review-attempt:{row['id']}:answer",),
                    )
                )
            items.append(
                OutcomeItem(
                    item_id=str(row["id"]),
                    item_type="review_attempt",
                    status=status,
                    content={
                        "question": question,
                        "answer": row["answer"],
                        "follow_up_answer": row["follow_up_answer"],
                        "evaluation": _value(row["evaluation_json"]),
                        "coverage": _array(row["coverage_json"]),
                        "result_kind": row["result_kind"],
                        "hint_level": int(row["hint_level"]),
                        "answer_revisions": _array(row["answer_revisions_json"]),
                        "skipped": bool(row["skipped"]),
                    },
                    provenance=tuple(provenance),
                    user_decision=OutcomeUserDecision(
                        status="ignored" if bool(row["skipped"]) else "pending"
                    ),
                )
            )
            units.append(
                OutcomeUnit(
                    unit_id=str(row["id"]),
                    unit_type="review_attempt",
                    status=status,
                )
            )
        return self._freeze(
            execution,
            terminal_state=str(round_row["status"]),
            domain_refs={"roundId": str(round_row["id"])},
            source_refs=tuple(sorted(source_refs)),
            items=tuple(items),
            units=tuple(units),
            counters={"attempts": _counters(statuses)},
            gaps=() if attempts else ("review_attempts_not_recorded",),
            requested_scope={
                "currentIndex": int(round_row["current_index"]),
                "questionCount": len(_array(round_row["question_snapshots_json"])),
            },
        )

    def _discussion(self, execution: sqlite3.Row) -> BusinessOutcomeProjection:
        messages = self.connection.execute(
            "SELECT * FROM agent_messages WHERE run_id = ? "
            "ORDER BY created_at, id",
            (execution["id"],),
        ).fetchall()
        items = tuple(
            OutcomeItem(
                item_id=str(row["id"]),
                item_type="discussion_message",
                status=str(row["resolution_status"]),
                content={
                    "role": row["role"],
                    "message_kind": row["message_kind"],
                    "content": row["content"],
                    "resolution_status": row["resolution_status"],
                },
                provenance=(
                    OutcomeProvenance(
                        field_path="content.content",
                        support_type=(
                            "user_asserted" if row["role"] == "user" else "inferred"
                        ),
                        source_refs=(f"message:{row['id']}",),
                    ),
                ),
                user_decision=OutcomeUserDecision(status="pending"),
            )
            for row in messages
            if row["role"] in {"user", "assistant"}
        )
        return self._freeze(
            execution,
            terminal_state=str(execution["status"]),
            domain_refs={"sessionId": str(execution["session_id"])},
            source_refs=tuple(f"message:{item.item_id}" for item in items),
            items=items,
            units=(),
            counters={"messages": _counters(["completed"] * len(items))},
            gaps=("formal_review_progress_snapshot_not_projected",),
        )

    def _profile_ingest(self, execution: sqlite3.Row) -> BusinessOutcomeProjection:
        proposals = self.connection.execute(
            "SELECT * FROM profile_claim_proposals "
            "WHERE workspace_id = ? AND created_by_execution_id = ? "
            "ORDER BY created_at, id",
            (self.workspace_id, execution["id"]),
        ).fetchall()
        items = []
        for row in proposals:
            evidence_ids = tuple(str(item) for item in _array(row["evidence_ids_json"]))
            conflicts = self.connection.execute(
                "SELECT id FROM profile_claim_conflicts WHERE proposal_id = ? ORDER BY id",
                (row["id"],),
            ).fetchall()
            items.append(
                OutcomeItem(
                    item_id=str(row["id"]),
                    item_type="claim_proposal",
                    status=str(row["status"]),
                    content={
                        "proposal_type": row["proposal_type"],
                        "target_claim_id": row["target_claim_id"],
                        "proposed_value": _object(row["proposed_value_json"]),
                        "reason": row["reason"],
                        "status": row["status"],
                        "conflict_ids": [item["id"] for item in conflicts],
                    },
                    provenance=(
                        OutcomeProvenance(
                            field_path="content.proposedValue",
                            support_type="normalized",
                            evidence_refs=evidence_ids,
                        ),
                    ),
                    user_decision=_decision(str(row["status"]), row["decided_at"]),
                )
            )
        version = self.connection.execute(
            "SELECT * FROM profile_material_versions WHERE id = ?",
            (execution["session_id"],),
        ).fetchone()
        units = () if version is None else (
            OutcomeUnit(
                unit_id=str(version["id"]),
                unit_type="profile_material_version",
                status=str(version["processing_status"]),
            ),
        )
        statuses = [str(row["status"]) for row in proposals]
        return self._freeze(
            execution,
            terminal_state=(
                str(version["processing_status"])
                if version is not None else str(execution["status"])
            ),
            domain_refs={
                "materialVersionId": str(execution["session_id"]),
            },
            source_refs=tuple(
                sorted({ref for item in items for p in item.provenance for ref in p.evidence_refs})
            ),
            items=tuple(items),
            units=units,
            counters={"proposals": _decision_counters(statuses)},
            gaps=() if version is not None else ("material_version_not_found",),
        )

    def _profile_assessment(self, execution: sqlite3.Row) -> BusinessOutcomeProjection:
        rows = self.connection.execute(
            "SELECT * FROM profile_assessments WHERE workspace_id = ? "
            "AND created_by_execution_id = ? ORDER BY created_at, id",
            (self.workspace_id, execution["id"]),
        ).fetchall()
        items = tuple(
            OutcomeItem(
                item_id=str(row["id"]),
                item_type="profile_assessment",
                status="completed",
                content={
                    "base_profile_version": row["base_profile_version"],
                    "result": _object(row["result_json"]),
                },
                provenance=(
                    OutcomeProvenance(
                        field_path="content.result",
                        support_type="inferred",
                        source_refs=(f"profile:{row['base_profile_version']}",),
                    ),
                ),
                user_decision=OutcomeUserDecision(status="pending"),
            )
            for row in rows
        )
        return self._freeze(
            execution,
            terminal_state=str(execution["status"]),
            domain_refs={"sessionId": str(execution["session_id"])},
            source_refs=tuple(
                f"profile:{row['base_profile_version']}" for row in rows
            ),
            items=items,
            units=(),
            counters={"assessments": _counters(["completed"] * len(items))},
            gaps=() if rows else ("assessment_result_not_found",),
        )

    def _profile_assistant(
        self,
        execution: sqlite3.Row,
        *,
        write_boundary: bool,
    ) -> BusinessOutcomeProjection:
        if not write_boundary:
            messages = self.connection.execute(
                "SELECT * FROM agent_messages WHERE run_id = ? ORDER BY created_at, id",
                (execution["id"],),
            ).fetchall()
            audits = self.connection.execute(
                "SELECT * FROM tool_audits WHERE run_id = ? ORDER BY created_at, id",
                (execution["id"],),
            ).fetchall()
            items = tuple(
                OutcomeItem(
                    item_id=str(row["id"]),
                    item_type="profile_message",
                    status=str(row["resolution_status"]),
                    content={
                        "role": row["role"],
                        "message_kind": row["message_kind"],
                        "content": row["content"],
                    },
                    provenance=(
                        OutcomeProvenance(
                            field_path="content.content",
                            support_type=(
                                "user_asserted" if row["role"] == "user" else "inferred"
                            ),
                            source_refs=(f"message:{row['id']}",),
                        ),
                    ),
                    user_decision=OutcomeUserDecision(status="pending"),
                )
                for row in messages
                if row["role"] in {"user", "assistant"}
            )
            units = tuple(
                OutcomeUnit(
                    unit_id=str(row["id"]),
                    unit_type=f"tool:{row['tool_name']}",
                    status=str(row["status"]),
                    error_code=row["error_code"],
                )
                for row in audits
            )
            gaps = () if items else ("assistant_messages_not_found",)
        else:
            plans = self.connection.execute(
                "SELECT * FROM profile_action_plans WHERE workspace_id = ? "
                "AND execution_id = ? ORDER BY created_at, id",
                (self.workspace_id, execution["id"]),
            ).fetchall()
            plan_ids = [str(row["id"]) for row in plans]
            rows = []
            for plan_id in plan_ids:
                rows.extend(
                    self.connection.execute(
                        "SELECT * FROM profile_action_plan_items WHERE plan_id = ? "
                        "ORDER BY ordinal, id",
                        (plan_id,),
                    ).fetchall()
                )
            items = tuple(
                OutcomeItem(
                    item_id=str(row["id"]),
                    item_type="profile_action_plan_item",
                    status=str(row["status"]),
                    content={
                        "operation": row["operation"],
                        "target": _object(row["target_json"]),
                        "expected_version": row["expected_version"],
                        "status": row["status"],
                        "receipt_id": row["receipt_id"],
                        "error_code": row["error_code"],
                    },
                    provenance=(
                        OutcomeProvenance(
                            field_path="content.target",
                            support_type="normalized",
                            evidence_refs=tuple(
                                str(item) for item in _array(row["evidence_ids_json"])
                            ),
                        ),
                    ),
                    user_decision=OutcomeUserDecision(
                        status=(
                            "accepted" if row["status"] == "completed" else "pending"
                        )
                    ),
                )
                for row in rows
            )
            units = tuple(
                OutcomeUnit(
                    unit_id=str(row["id"]),
                    unit_type="profile_action_plan",
                    status=str(row["status"]),
                )
                for row in plans
            )
            gaps = () if plans else ("action_plan_not_found",)
        return self._freeze(
            execution,
            terminal_state=str(execution["status"]),
            domain_refs={"sessionId": str(execution["session_id"])},
            source_refs=tuple(
                sorted({ref for item in items for p in item.provenance for ref in (*p.source_refs, *p.evidence_refs)})
            ),
            items=items,
            units=units,
            counters={"items": _counters([item.status for item in items])},
            gaps=gaps,
        )

    def _job_analysis(self, execution: sqlite3.Row) -> BusinessOutcomeProjection:
        analysis = self.connection.execute(
            "SELECT * FROM job_analysis_runs WHERE execution_id = ? ORDER BY created_at DESC LIMIT 1",
            (execution["id"],),
        ).fetchone()
        if analysis is None:
            return self._empty(execution, str(execution["status"]), ("job_analysis_run_not_found",))
        document = self.connection.execute(
            "SELECT * FROM job_document_versions WHERE id = ?",
            (analysis["document_version_id"],),
        ).fetchone()
        requirements = self.connection.execute(
            "SELECT * FROM job_requirements WHERE document_version_id = ? "
            "ORDER BY created_at, id",
            (analysis["document_version_id"],),
        ).fetchall()
        items = []
        for row in requirements:
            locator_valid = _locator_valid(document["body"] if document else None, row)
            source_ref = (
                f"job-document:{row['document_version_id']}#"
                f"{row['source_start']}:{row['source_end']}"
            )
            items.append(
                OutcomeItem(
                    item_id=str(row["id"]),
                    item_type="job_requirement",
                    status=str(row["confirmation_status"]),
                    domain_version=int(row["version"]),
                    content={
                        "requirement_type": row["requirement_type"],
                        "priority": row["priority"],
                        "text": row["text"],
                        "source_quote": row["source_quote"],
                        "source_start": row["source_start"],
                        "source_end": row["source_end"],
                        "locator_valid": locator_valid,
                        "inferred": bool(row["inferred"]),
                        "confirmation_status": row["confirmation_status"],
                        "preparation_status": row["preparation_status"],
                    },
                    provenance=(
                        OutcomeProvenance(
                            field_path="content.text",
                            support_type=("inferred" if row["inferred"] else "normalized"),
                            source_refs=(source_ref,),
                        ),
                    ),
                    user_decision=_decision(str(row["confirmation_status"]), None),
                )
            )
        work = self.connection.execute(
            "SELECT * FROM job_analysis_work_items WHERE analysis_run_id = ? "
            "ORDER BY created_at, id",
            (analysis["id"],),
        ).fetchall()
        units = tuple(
            OutcomeUnit(
                unit_id=str(row["id"]),
                unit_type=f"job_analysis:{row['work_key']}",
                status=str(row["status"]),
                error_code=row["last_error_code"],
            )
            for row in work
        )
        gaps = []
        if document is None:
            gaps.append("job_document_version_not_found")
        if any(item.content.get("locator_valid") is False for item in items):
            gaps.append("job_source_locator_mismatch")
        return self._freeze(
            execution,
            terminal_state=str(analysis["status"]),
            domain_refs={
                "analysisRunId": str(analysis["id"]),
                "jobTargetId": str(analysis["job_target_id"]),
                "documentVersionId": str(analysis["document_version_id"]),
            },
            source_refs=(f"job-document:{analysis['document_version_id']}",),
            items=tuple(items),
            units=units,
            counters={
                "requirements": _decision_counters(
                    [str(row["confirmation_status"]) for row in requirements]
                ),
                "workItems": _counters([str(row["status"]) for row in work]),
            },
            gaps=tuple(gaps),
        )

    def _project(self, execution: sqlite3.Row) -> BusinessOutcomeProjection:
        dive = self.connection.execute(
            "SELECT * FROM project_deep_dives WHERE session_id = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (execution["session_id"],),
        ).fetchone()
        if dive is None:
            return self._empty(execution, str(execution["status"]), ("project_deep_dive_not_found",))
        questions = self.connection.execute(
            "SELECT * FROM project_question_candidates WHERE deep_dive_id = ? "
            "ORDER BY created_at, id",
            (dive["id"],),
        ).fetchall()
        if self.task_type == "project_question_generation":
            items = tuple(_project_question(row) for row in questions)
        else:
            artifacts = self.connection.execute(
                "SELECT * FROM project_deep_dive_artifacts WHERE deep_dive_id = ? "
                "AND (source_execution_id = ? OR source_execution_id IS NULL) "
                "ORDER BY created_at, id",
                (dive["id"], execution["id"]),
            ).fetchall()
            gaps = self.connection.execute(
                "SELECT * FROM project_gaps WHERE deep_dive_id = ? ORDER BY created_at, id",
                (dive["id"],),
            ).fetchall()
            narratives = self.connection.execute(
                "SELECT * FROM project_narrative_sections WHERE project_claim_id = ? "
                "AND status = 'confirmed' ORDER BY section_kind, version",
                (dive["project_claim_id"],),
            ).fetchall()
            items = tuple(
                [
                    OutcomeItem(
                        item_id=str(row["id"]),
                        item_type="deep_dive_artifact",
                        status=str(row["status"]),
                        domain_version=int(row["version"]),
                        content={
                            "artifact_kind": row["artifact_kind"],
                            "payload": _value(row["payload_json"]),
                            "status": row["status"],
                        },
                        provenance=(
                            OutcomeProvenance(
                                field_path="content.payload",
                                support_type="inferred",
                                source_refs=tuple(
                                    ref for ref in (
                                        f"message:{row['source_message_id']}" if row["source_message_id"] else None,
                                        f"execution:{row['source_execution_id']}" if row["source_execution_id"] else None,
                                    ) if ref
                                ),
                            ),
                        ),
                        user_decision=_decision(str(row["status"]), None),
                    )
                    for row in artifacts
                ]
                + [
                    OutcomeItem(
                        item_id=str(row["id"]),
                        item_type="project_gap",
                        status=str(row["status"]),
                        content={
                            "gap_kind": row["gap_kind"],
                            "summary": row["summary"],
                            "status": row["status"],
                            "resolution_ref": row["resolution_ref"],
                        },
                        provenance=(
                            OutcomeProvenance(
                                field_path="content.summary",
                                support_type="inferred",
                                source_refs=(
                                    f"artifact:{row['source_artifact_id']}",
                                ) if row["source_artifact_id"] else (),
                            ),
                        ),
                        user_decision=_decision(str(row["status"]), None),
                    )
                    for row in gaps
                ]
                + [
                    OutcomeItem(
                        item_id=str(row["id"]),
                        item_type="project_narrative",
                        status=str(row["status"]),
                        domain_version=int(row["version"]),
                        content={
                            "section_kind": row["section_kind"],
                            "content": row["content"],
                            "status": row["status"],
                        },
                        provenance=(
                            OutcomeProvenance(
                                field_path="content.content",
                                support_type="user_asserted",
                                source_refs=tuple(
                                    ref for ref in (
                                        f"message:{row['source_message_id']}" if row["source_message_id"] else None,
                                        f"session:{row['source_session_id']}" if row["source_session_id"] else None,
                                    ) if ref
                                ),
                            ),
                        ),
                        user_decision=OutcomeUserDecision(status="accepted"),
                    )
                    for row in narratives
                ]
            )
        return self._freeze(
            execution,
            terminal_state=str(dive["status"]),
            domain_refs={
                "deepDiveId": str(dive["id"]),
                "jobTargetId": str(dive["job_target_id"]),
                "projectClaimId": str(dive["project_claim_id"]),
            },
            source_refs=(f"project-claim:{dive['project_claim_id']}",),
            items=items,
            units=(),
            counters={"items": _decision_counters([item.status for item in items])},
            gaps=() if items else ("project_business_items_not_found",),
            requested_scope={
                "currentStage": dive["current_stage"],
                "waitingForInput": bool(dive["waiting_for_input"]),
            },
        )

    def _empty(
        self,
        execution: sqlite3.Row,
        terminal_state: str,
        gaps: tuple[str, ...],
    ) -> BusinessOutcomeProjection:
        return self._freeze(
            execution,
            terminal_state=terminal_state,
            domain_refs={"sessionId": str(execution["session_id"])},
            source_refs=(),
            items=(),
            units=(),
            counters={"items": _counters([])},
            gaps=gaps,
        )

    def _freeze(
        self,
        execution: sqlite3.Row,
        *,
        terminal_state: str,
        domain_refs: dict[str, str],
        source_refs: tuple[str, ...],
        items: tuple[OutcomeItem, ...],
        units: tuple[OutcomeUnit, ...],
        counters: dict[str, OutcomeCounters],
        gaps: tuple[str, ...],
        requested_scope: dict[str, object] | None = None,
    ) -> BusinessOutcomeProjection:
        raw_input = _object(execution["input_json"])
        input_hash = sha256(
            json.dumps(raw_input, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return freeze_business_outcome(
            BusinessOutcomePayload(
                task_type=self.task_type,
                identity=OutcomeIdentity(
                    workspace_id=self.workspace_id,
                    session_id=str(execution["session_id"]),
                    execution_id=str(execution["id"]),
                    graph_id=str(execution["graph_id"]),
                    domain_refs=domain_refs,
                ),
                input=OutcomeInput(
                    source_refs=source_refs,
                    input_hash=input_hash,
                    requested_scope=requested_scope or _safe_scope(raw_input),
                ),
                execution_status=str(execution["status"]),
                terminal_state=terminal_state,
                items=items,
                units=units,
                unit_counters=counters,
                evidence_gaps=tuple(dict.fromkeys(gaps)),
                runtime_versions={
                    "graph": f"{execution['graph_id']}@{execution['graph_version']}"
                },
            )
        )


def create_sqlite_outcome_adapter(
    task_type: str,
    connection: sqlite3.Connection,
    workspace_id: str,
) -> SqliteOutcomeAdapter:
    return SqliteOutcomeAdapter(connection, workspace_id, task_type)


def _project_question(row: sqlite3.Row) -> OutcomeItem:
    return OutcomeItem(
        item_id=str(row["id"]),
        item_type="project_question_candidate",
        status=str(row["status"]),
        content={
            "dimension": row["dimension"],
            "question": _object(row["question_json"]),
            "duplicate_of_question_id": row["duplicate_of_question_id"],
            "review_candidate_id": row["review_candidate_id"],
            "status": row["status"],
        },
        provenance=(
            OutcomeProvenance(
                field_path="content.question",
                support_type="inferred",
                source_refs=(f"project-claim:{row['project_claim_id']}",),
            ),
        ),
        user_decision=_decision(str(row["status"]), None),
    )


def _decision(status: str, occurred_at: object) -> OutcomeUserDecision:
    if status in {"accepted", "confirmed", "completed", "resolved"}:
        value = "accepted"
    elif status in {"rejected"}:
        value = "rejected"
    elif status in {"ignored", "dismissed", "skipped", "accepted_risk"}:
        value = "ignored"
    elif status in {"superseded", "partially_confirmed"}:
        value = "edited"
    else:
        value = "pending"
    return OutcomeUserDecision(
        status=value,
        occurred_at=str(occurred_at) if occurred_at else None,
    )


def _counters(statuses: list[str]) -> OutcomeCounters:
    completed_states = {"completed", "confirmed", "accepted", "resolved", "active"}
    failed_states = {"failed", "rejected", "retryable"}
    skipped_states = {"skipped", "ignored", "dismissed", "terminated", "cancelled"}
    completed = sum(item in completed_states for item in statuses)
    failed = sum(item in failed_states for item in statuses)
    skipped = sum(item in skipped_states for item in statuses)
    return OutcomeCounters(
        total=len(statuses),
        completed=completed,
        failed=failed,
        skipped=skipped,
        pending=len(statuses) - completed - failed - skipped,
    )


def _decision_counters(statuses: list[str]) -> OutcomeCounters:
    completed = sum(item in {"accepted", "confirmed", "completed", "resolved"} for item in statuses)
    skipped = sum(item in {"rejected", "ignored", "dismissed", "superseded", "duplicate"} for item in statuses)
    return OutcomeCounters(
        total=len(statuses),
        completed=completed,
        failed=0,
        skipped=skipped,
        pending=len(statuses) - completed - skipped,
    )


def _locator_valid(body: object, row: sqlite3.Row) -> bool | None:
    if not isinstance(body, str) or row["source_start"] is None or row["source_end"] is None:
        return None
    start, end = int(row["source_start"]), int(row["source_end"])
    if start < 0 or end < start or end > len(body):
        return False
    return body[start:end] == row["source_quote"]


def _safe_scope(value: dict[str, Any]) -> dict[str, object]:
    result = {}
    for key, item in value.items():
        normalized = key.casefold()
        if any(token in normalized for token in ("id", "ref", "hash", "mode", "count", "index", "scope")):
            if isinstance(item, (str, int, float, bool)) or item is None:
                result[key] = item
            elif isinstance(item, list):
                result[key] = [value for value in item[:20] if isinstance(value, (str, int, float, bool))]
    return result


def _object(value: object) -> dict[str, Any]:
    parsed = _value(value)
    return parsed if isinstance(parsed, dict) else {}


def _array(value: object) -> list[Any]:
    parsed = _value(value)
    return parsed if isinstance(parsed, list) else []


def _value(value: object) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from statistics import fmean


@dataclass(frozen=True, slots=True)
class EvaluationTrendPoint:
    bucket: str
    graph_id: str
    eval_pack_id: str
    eval_pack_version: int
    evaluation_contract_version: int
    run_kind: str
    judge_provider_model_id: str | None
    prompt_version: str
    schema_version: str
    tool_version: str
    run_count: int
    success_rate: float
    deterministic_issue_rate: float
    average_judge_score: float | None
    needs_review_rate: float
    severe_rate: float
    judge_human_agreement_rate: float | None
    user_edit_reject_rate: float
    infrastructure_failure_rate: float
    human_review_rate: float
    average_latency_ms: float | None
    average_tokens: float
    average_context_tokens: float


class EvaluationTrendService:
    def __init__(self, connection, workspace_id: str) -> None:
        self.connection = connection
        self.workspace_id = workspace_id

    def query(
        self,
        *,
        graph_id: str | None = None,
        eval_pack_id: str | None = None,
        eval_pack_version: int | None = None,
        judge_provider_model_id: str | None = None,
        started_from: str | None = None,
        started_to: str | None = None,
    ) -> tuple[EvaluationTrendPoint, ...]:
        rows = self.connection.execute(
            "SELECT eval.*, session.graph_id, run.started_at, run.finished_at, "
            "COALESCE((SELECT SUM(total_tokens) FROM model_invocation_usage usage "
            "WHERE usage.run_id = eval.execution_id), 0) AS tokens, "
            "COALESCE((SELECT MAX(current_tokens) FROM agent_context_usage context "
            "WHERE context.run_id = eval.execution_id), 0) AS context_tokens "
            "FROM agent_eval_runs eval "
            "JOIN agent_runs run ON run.id = eval.execution_id "
            "JOIN agent_sessions session ON session.id = run.session_id "
            "WHERE eval.workspace_id = ? ORDER BY eval.created_at",
            (self.workspace_id,),
        )
        groups: dict[tuple, list[dict[str, object]]] = defaultdict(list)
        for raw in rows:
            row = dict(raw)
            if graph_id and row["graph_id"] != graph_id:
                continue
            if eval_pack_id and row["eval_pack_id"] != eval_pack_id:
                continue
            if (
                eval_pack_version is not None
                and row["eval_pack_version"] != eval_pack_version
            ):
                continue
            if (
                judge_provider_model_id
                and row["judge_provider_model_id"] != judge_provider_model_id
            ):
                continue
            timestamp = str(row["created_at"])
            if started_from and timestamp < started_from:
                continue
            if started_to and timestamp > started_to:
                continue
            snapshot = _object(row["snapshot_json"])
            versions = snapshot.get("versions", {})
            tool_versions = snapshot.get("tool_versions", {})
            prompt = str(versions.get("prompt", "unknown")) if isinstance(versions, dict) else "unknown"
            schema = str(versions.get("schema", "unknown")) if isinstance(versions, dict) else "unknown"
            tool = (
                json.dumps(tool_versions, sort_keys=True, separators=(",", ":"))
                if isinstance(tool_versions, dict) and tool_versions
                else "unknown"
            )
            key = (
                timestamp[:10],
                row["graph_id"],
                row["eval_pack_id"],
                row["eval_pack_version"],
                row["evaluation_contract_version"],
                row["run_kind"],
                row["judge_provider_model_id"],
                prompt,
                schema,
                tool,
            )
            groups[key].append(row)
        points = []
        for key, items in sorted(groups.items()):
            eval_ids = [str(item["id"]) for item in items]
            placeholders = ",".join("?" for _ in eval_ids)
            dimensions = (
                []
                if not eval_ids
                else list(
                    self.connection.execute(
                        "SELECT * FROM agent_eval_dimension_results "
                        f"WHERE eval_run_id IN ({placeholders})",
                        tuple(eval_ids),
                    )
                )
            )
            scores = [
                float(row["score"])
                for row in dimensions
                if row["source"] == "judge" and row["score"] is not None
            ]
            deterministic_by_run = {
                row["eval_run_id"]
                for row in dimensions
                if row["source"] == "deterministic"
                and row["status"] == "failed"
            }
            v2_judge = [
                row for row in dimensions
                if row["source"] == "judge" and row["applicability"] == "applicable"
            ]
            needs_review = sum(row["rating"] == "needs_review" for row in v2_judge)
            severe = sum(row["rating"] == "severe" for row in v2_judge)
            feedback_rows = list(self.connection.execute(
                "SELECT verdict FROM agent_eval_human_feedback "
                f"WHERE eval_run_id IN ({placeholders}) AND dimension_id IS NULL "
                "ORDER BY feedback_version",
                tuple(eval_ids),
            )) if eval_ids else []
            comparable_feedback = [
                row for row in feedback_rows
                if row["verdict"] in {"accurate", "incorrect"}
            ]
            agreement = (
                None
                if not comparable_feedback
                else sum(row["verdict"] == "accurate" for row in comparable_feedback)
                / len(comparable_feedback)
            )
            decisions = []
            for item in items:
                snapshot = _object(item["snapshot_json"])
                outcome = snapshot.get("businessOutcome", {})
                if not isinstance(outcome, dict):
                    continue
                for result_item in outcome.get("items", []):
                    if isinstance(result_item, dict):
                        decision = result_item.get("userDecision", {})
                        if isinstance(decision, dict):
                            decisions.append(decision.get("status"))
            edited_or_rejected = sum(
                value in {"edited", "rejected", "ignored"} for value in decisions
            )
            infrastructure_failure_rate = self._infrastructure_failure_rate(
                bucket=key[0],
                eval_pack_id=key[2],
                eval_pack_version=key[3],
            )
            human_review = sum(
                bool(_object(item["judge_result_json"]).get("humanReviewRequired"))
                for item in items
            )
            latencies = [
                _latency(item["started_at"], item["finished_at"])
                for item in items
            ]
            valid_latencies = [item for item in latencies if item is not None]
            count = len(items)
            points.append(
                EvaluationTrendPoint(
                    bucket=key[0],
                    graph_id=key[1],
                    eval_pack_id=key[2],
                    eval_pack_version=key[3],
                    evaluation_contract_version=key[4],
                    run_kind=key[5],
                    judge_provider_model_id=key[6],
                    prompt_version=key[7],
                    schema_version=key[8],
                    tool_version=key[9],
                    run_count=count,
                    success_rate=sum(item["status"] == "completed" for item in items) / count,
                    deterministic_issue_rate=len(deterministic_by_run) / count,
                    average_judge_score=fmean(scores) if scores else None,
                    needs_review_rate=needs_review / max(1, len(v2_judge)),
                    severe_rate=severe / max(1, len(v2_judge)),
                    judge_human_agreement_rate=agreement,
                    user_edit_reject_rate=(
                        edited_or_rejected / len(decisions) if decisions else 0.0
                    ),
                    infrastructure_failure_rate=infrastructure_failure_rate,
                    human_review_rate=human_review / count,
                    average_latency_ms=fmean(valid_latencies) if valid_latencies else None,
                    average_tokens=fmean(float(item["tokens"]) for item in items),
                    average_context_tokens=fmean(
                        float(item["context_tokens"]) for item in items
                    ),
                )
            )
        return tuple(points)

    def _infrastructure_failure_rate(
        self,
        *,
        bucket: str,
        eval_pack_id: str,
        eval_pack_version: int,
    ) -> float:
        row = self.connection.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN run.error_code IS NOT NULL THEN 1 ELSE 0 END) AS failed "
            "FROM agent_eval_regression_runs run "
            "JOIN agent_eval_regression_cases case_row ON case_row.id = run.case_id "
            "WHERE run.workspace_id = ? AND case_row.eval_pack_id = ? "
            "AND case_row.eval_pack_version = ? AND substr(run.created_at, 1, 10) = ?",
            (self.workspace_id, eval_pack_id, eval_pack_version, bucket),
        ).fetchone()
        total = int(row["total"] or 0)
        return 0.0 if total == 0 else int(row["failed"] or 0) / total


def _object(value: object) -> dict:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _latency(start: object, finish: object) -> float | None:
    if not start or not finish:
        return None
    from datetime import datetime

    try:
        return max(
            0.0,
            (
                datetime.fromisoformat(str(finish).replace("Z", "+00:00"))
                - datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            ).total_seconds()
            * 1000,
        )
    except ValueError:
        return None

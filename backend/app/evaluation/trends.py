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
    judge_provider_model_id: str | None
    prompt_version: str
    schema_version: str
    tool_version: str
    run_count: int
    success_rate: float
    deterministic_issue_rate: float
    average_judge_score: float | None
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
                and row["status"] in {"failed", "inconclusive"}
            }
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
                    judge_provider_model_id=key[4],
                    prompt_version=key[5],
                    schema_version=key[6],
                    tool_version=key[7],
                    run_count=count,
                    success_rate=sum(item["status"] == "completed" for item in items) / count,
                    deterministic_issue_rate=len(deterministic_by_run) / count,
                    average_judge_score=fmean(scores) if scores else None,
                    human_review_rate=human_review / count,
                    average_latency_ms=fmean(valid_latencies) if valid_latencies else None,
                    average_tokens=fmean(float(item["tokens"]) for item in items),
                    average_context_tokens=fmean(
                        float(item["context_tokens"]) for item in items
                    ),
                )
            )
        return tuple(points)


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

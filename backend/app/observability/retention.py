from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4


BodyPolicy = Literal["permanent", "days", "metadata_only"]


@dataclass(frozen=True, slots=True)
class TraceRetentionPolicy:
    workspace_id: str
    body_policy: BodyPolicy
    body_days: int | None
    metadata_policy: Literal["retain"]
    updated_at: str


@dataclass(frozen=True, slots=True)
class TraceCleanupItem:
    relative_path: str
    run_id: str
    event_count: int
    byte_count: int
    sha256: str
    status: str
    error_code: str | None


@dataclass(frozen=True, slots=True)
class TraceCleanupPlan:
    id: str
    workspace_id: str
    status: str
    file_count: int
    event_count: int
    total_bytes: int
    protected_active_runs: int
    error_code: str | None
    created_at: str
    completed_at: str | None
    items: tuple[TraceCleanupItem, ...]


class TraceRetentionService:
    def __init__(
        self,
        *,
        connection,
        workspace_id: str,
        workspace_root: Path,
        now=None,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.workspace_root = workspace_root
        self._now = now or (lambda: datetime.now(timezone.utc))

    def get_policy(self) -> TraceRetentionPolicy:
        row = self.connection.execute(
            "SELECT * FROM agent_trace_retention_policy WHERE workspace_id = ?",
            (self.workspace_id,),
        ).fetchone()
        if row is None:
            self.connection.execute(
                "INSERT INTO agent_trace_retention_policy "
                "(workspace_id, body_policy, body_days, metadata_policy) "
                "VALUES (?, 'days', 90, 'retain')",
                (self.workspace_id,),
            )
            self.connection.commit()
            row = self.connection.execute(
                "SELECT * FROM agent_trace_retention_policy WHERE workspace_id = ?",
                (self.workspace_id,),
            ).fetchone()
        return self._policy(row)

    def replace_policy(
        self, *, body_policy: BodyPolicy, body_days: int | None = None
    ) -> TraceRetentionPolicy:
        if body_policy == "days":
            if body_days is None or not 1 <= body_days <= 3650:
                raise ValueError("body_days must be between 1 and 3650")
        elif body_days is not None:
            raise ValueError("body_days is only valid for days policy")
        self.connection.execute(
            "INSERT INTO agent_trace_retention_policy "
            "(workspace_id, body_policy, body_days, metadata_policy) "
            "VALUES (?, ?, ?, 'retain') "
            "ON CONFLICT(workspace_id) DO UPDATE SET "
            "body_policy = excluded.body_policy, body_days = excluded.body_days, "
            "updated_at = CURRENT_TIMESTAMP",
            (self.workspace_id, body_policy, body_days),
        )
        self.connection.commit()
        return self.get_policy()

    def create_plan(self) -> TraceCleanupPlan:
        policy = self.get_policy()
        eligible, protected = self._eligible_files(policy)
        identity = {
            "workspaceId": self.workspace_id,
            "policy": policy.body_policy,
            "days": policy.body_days,
            "files": [(item["relative_path"], item["file_mtime_ns"]) for item in eligible],
        }
        request_hash = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        existing = self.connection.execute(
            "SELECT id FROM agent_trace_cleanup_runs "
            "WHERE workspace_id = ? AND request_hash = ?",
            (self.workspace_id, request_hash),
        ).fetchone()
        if existing is not None:
            return self.get_plan(existing["id"])
        cleanup_id = str(uuid4())
        items = []
        for row in eligible:
            path = self.workspace_root / ".cyber-interview-agent" / "agent-traces" / row["relative_path"]
            data = path.read_bytes()
            event_count = self.connection.execute(
                "SELECT COUNT(*) FROM agent_trace_events "
                "WHERE relative_path = ? AND body_state = 'available'",
                (row["relative_path"],),
            ).fetchone()[0]
            items.append(
                (
                    row["relative_path"],
                    row["run_id"],
                    event_count,
                    len(data),
                    hashlib.sha256(data).hexdigest(),
                )
            )
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                "INSERT INTO agent_trace_cleanup_runs "
                "(id, workspace_id, request_hash, file_count, event_count, "
                "total_bytes, protected_active_runs) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    cleanup_id,
                    self.workspace_id,
                    request_hash,
                    len(items),
                    sum(item[2] for item in items),
                    sum(item[3] for item in items),
                    protected,
                ),
            )
            self.connection.executemany(
                "INSERT INTO agent_trace_cleanup_items "
                "(cleanup_id, relative_path, run_id, event_count, byte_count, sha256) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ((cleanup_id, *item) for item in items),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_plan(cleanup_id)

    def get_plan(self, cleanup_id: str) -> TraceCleanupPlan:
        row = self.connection.execute(
            "SELECT * FROM agent_trace_cleanup_runs WHERE id = ? "
            "AND workspace_id = ?",
            (cleanup_id, self.workspace_id),
        ).fetchone()
        if row is None:
            raise LookupError("cleanup plan not found")
        items = tuple(
            TraceCleanupItem(
                relative_path=item["relative_path"],
                run_id=item["run_id"],
                event_count=item["event_count"],
                byte_count=item["byte_count"],
                sha256=item["sha256"],
                status=item["status"],
                error_code=item["error_code"],
            )
            for item in self.connection.execute(
                "SELECT * FROM agent_trace_cleanup_items "
                "WHERE cleanup_id = ? ORDER BY relative_path",
                (cleanup_id,),
            )
        )
        return TraceCleanupPlan(
            id=row["id"],
            workspace_id=row["workspace_id"],
            status=row["status"],
            file_count=row["file_count"],
            event_count=row["event_count"],
            total_bytes=row["total_bytes"],
            protected_active_runs=row["protected_active_runs"],
            error_code=row["error_code"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            items=items,
        )

    def _eligible_files(self, policy: TraceRetentionPolicy):
        if policy.body_policy == "permanent":
            return [], self._active_count()
        cutoff = (
            self._now() + timedelta(seconds=1)
            if policy.body_policy == "metadata_only"
            else self._now() - timedelta(days=policy.body_days or 90)
        )
        rows = []
        protected = 0
        for trace_file in self.connection.execute(
            "SELECT file.*, execution.run_id, run.status "
            "FROM agent_trace_files file "
            "JOIN agent_trace_executions execution "
            "ON execution.run_id = substr(file.relative_path, "
            "instr(file.relative_path, '/') + 1, "
            "length(file.relative_path) - instr(file.relative_path, '/') - 6) "
            "LEFT JOIN agent_runs run ON run.id = execution.run_id "
            "ORDER BY file.relative_path"
        ):
            if trace_file["status"] in {
                "queued", "running", "waiting_for_input", "waiting_for_approval"
            }:
                protected += 1
                continue
            newest = self.connection.execute(
                "SELECT MAX(observed_at) FROM agent_trace_events "
                "WHERE relative_path = ? AND body_state = 'available'",
                (trace_file["relative_path"],),
            ).fetchone()[0]
            if newest is None:
                continue
            try:
                observed = datetime.fromisoformat(str(newest).replace("Z", "+00:00"))
            except ValueError:
                continue
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            if observed <= cutoff:
                rows.append(dict(trace_file))
        return rows, protected

    def _active_count(self) -> int:
        return int(
            self.connection.execute(
                "SELECT COUNT(*) FROM agent_runs WHERE status IN "
                "('queued','running','waiting_for_input','waiting_for_approval')"
            ).fetchone()[0]
        )

    @staticmethod
    def _policy(row) -> TraceRetentionPolicy:
        return TraceRetentionPolicy(
            workspace_id=row["workspace_id"],
            body_policy=row["body_policy"],
            body_days=row["body_days"],
            metadata_policy=row["metadata_policy"],
            updated_at=row["updated_at"],
        )

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from app.observability.repository import TraceIndexRepository
from app.observability.retention import TraceCleanupPlan, TraceRetentionService
from app.security.workspace_paths import PathPolicyError, WorkspacePathPolicy


class TraceCleanupError(RuntimeError):
    pass


class TraceCleanupService:
    def __init__(
        self,
        *,
        retention: TraceRetentionService,
        repository: TraceIndexRepository,
    ) -> None:
        self.retention = retention
        self.repository = repository
        self.connection = retention.connection
        self.workspace_root = retention.workspace_root

    def confirm(self, cleanup_id: str) -> TraceCleanupPlan:
        plan = self.retention.get_plan(cleanup_id)
        if plan.status == "completed":
            return plan
        self._set_run_status(cleanup_id, "quarantining", confirmed=True)
        failures = 0
        for item in self.retention.get_plan(cleanup_id).items:
            if item.status in {"quarantined", "finalized"}:
                continue
            try:
                self._quarantine(cleanup_id, item)
            except Exception:
                failures += 1
                self._set_item_status(
                    cleanup_id,
                    item.relative_path,
                    "failed",
                    "trace_quarantine_failed",
                )
        if failures:
            self._set_run_status(
                cleanup_id, "partial_failure", error_code="trace_cleanup_partial"
            )
            return self.retention.get_plan(cleanup_id)
        self._set_run_status(cleanup_id, "quarantined")
        self._set_run_status(cleanup_id, "finalizing")
        for item in self.retention.get_plan(cleanup_id).items:
            if item.status == "finalized":
                continue
            try:
                self._finalize(cleanup_id, item)
            except Exception:
                failures += 1
                self._set_item_status(
                    cleanup_id,
                    item.relative_path,
                    "failed",
                    "trace_finalize_failed",
                )
        self._set_run_status(
            cleanup_id,
            "completed" if failures == 0 else "partial_failure",
            error_code=None if failures == 0 else "trace_cleanup_partial",
            completed=failures == 0,
        )
        return self.retention.get_plan(cleanup_id)

    def resume_incomplete(self) -> tuple[TraceCleanupPlan, ...]:
        rows = self.connection.execute(
            "SELECT id FROM agent_trace_cleanup_runs "
            "WHERE workspace_id = ? AND status IN "
            "('quarantining','quarantined','finalizing') ORDER BY created_at",
            (self.retention.workspace_id,),
        )
        return tuple(self.confirm(row["id"]) for row in rows)

    def _quarantine(self, cleanup_id: str, item) -> None:
        trace_root = WorkspacePathPolicy(self.workspace_root).scope_root(
            "diagnostics.agent_traces"
        )
        source = trace_root / item.relative_path
        quarantine_root = (
            self.workspace_root
            / ".cyber-interview-agent"
            / "trace-quarantine"
            / cleanup_id
        )
        quarantine_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(quarantine_root, 0o700)
        target = quarantine_root / item.relative_path
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if target.is_symlink() or source.is_symlink():
            raise PathPolicyError("diagnostics.agent_traces", item.relative_path)
        if not source.exists():
            raise TraceCleanupError("planned trace source is missing")
        mode = source.lstat().st_mode
        if not stat.S_ISREG(mode) or self._sha256(source) != item.sha256:
            raise TraceCleanupError("planned trace source hash changed")
        os.replace(source, target)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                "UPDATE agent_trace_cleanup_items SET status = 'quarantined', "
                "quarantine_relative_path = ?, error_code = NULL, "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE cleanup_id = ? AND relative_path = ?",
                (
                    target.relative_to(
                        self.workspace_root / ".cyber-interview-agent"
                    ).as_posix(),
                    cleanup_id,
                    item.relative_path,
                ),
            )
            self.connection.execute(
                "UPDATE agent_trace_events SET body_state = 'quarantined' "
                "WHERE relative_path = ? AND body_state = 'available'",
                (item.relative_path,),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            if target.exists() and not source.exists():
                source.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                os.replace(target, source)
            raise

    def _finalize(self, cleanup_id: str, item) -> None:
        row = self.connection.execute(
            "SELECT quarantine_relative_path FROM agent_trace_cleanup_items "
            "WHERE cleanup_id = ? AND relative_path = ?",
            (cleanup_id, item.relative_path),
        ).fetchone()
        if row is None or not row["quarantine_relative_path"]:
            raise TraceCleanupError("quarantine receipt is missing")
        target = (
            self.workspace_root
            / ".cyber-interview-agent"
            / row["quarantine_relative_path"]
        )
        if target.is_symlink() or not target.is_file():
            raise TraceCleanupError("quarantined body is missing")
        if self._sha256(target) != item.sha256:
            raise TraceCleanupError("quarantined body hash changed")
        target.unlink()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                "UPDATE agent_trace_events SET body_state = 'deleted' "
                "WHERE relative_path = ? AND body_state = 'quarantined'",
                (item.relative_path,),
            )
            self.connection.execute(
                "UPDATE agent_trace_cleanup_items SET status = 'finalized', "
                "error_code = NULL, updated_at = CURRENT_TIMESTAMP "
                "WHERE cleanup_id = ? AND relative_path = ?",
                (cleanup_id, item.relative_path),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _set_run_status(
        self,
        cleanup_id: str,
        status: str,
        *,
        error_code: str | None = None,
        confirmed: bool = False,
        completed: bool = False,
    ) -> None:
        self.connection.execute(
            "UPDATE agent_trace_cleanup_runs SET status = ?, error_code = ?, "
            "confirmed_at = CASE WHEN ? THEN COALESCE(confirmed_at, CURRENT_TIMESTAMP) "
            "ELSE confirmed_at END, "
            "completed_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE completed_at END "
            "WHERE id = ? AND workspace_id = ?",
            (
                status,
                error_code,
                int(confirmed),
                int(completed),
                cleanup_id,
                self.retention.workspace_id,
            ),
        )
        self.connection.commit()

    def _set_item_status(
        self,
        cleanup_id: str,
        relative_path: str,
        status: str,
        error_code: str,
    ) -> None:
        self.connection.execute(
            "UPDATE agent_trace_cleanup_items SET status = ?, error_code = ?, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE cleanup_id = ? AND relative_path = ?",
            (status, error_code, cleanup_id, relative_path),
        )
        self.connection.commit()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

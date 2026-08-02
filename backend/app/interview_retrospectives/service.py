from __future__ import annotations

import hashlib
import json
from pathlib import PurePath

from app.interview_retrospectives.errors import (
    RetrospectiveBusy,
    RetrospectiveCleanupNotConfirmed,
    RetrospectiveDeleteBlocked,
    RetrospectiveIdempotencyConflict,
    RetrospectiveSourceCleared,
    RetrospectiveSourceTooLarge,
    RetrospectiveSourceUnsupported,
    RetrospectiveTargetRequired,
)
from app.interview_retrospectives.repository import (
    InterviewRetrospectiveRepository,
)
from app.job_targets.errors import JobTargetNotFound
from app.job_targets.repository import JobTargetRepository


MAX_SOURCE_CHARACTERS = 500_000
SUPPORTED_SOURCE_SUFFIXES = {".txt", ".md"}


class InterviewRetrospectiveService:
    def __init__(
        self,
        *,
        workspace_id: str,
        repository: InterviewRetrospectiveRepository,
        job_targets: JobTargetRepository,
    ) -> None:
        self.workspace_id = workspace_id
        self.repository = repository
        self.job_targets = job_targets

    def create(
        self,
        *,
        job_target_id: str,
        title: str,
        round_label: str,
        interview_date: str | None,
        outcome: str,
        note: str,
        analysis_session_id: str,
        chat_session_id: str,
        idempotency_key: str,
    ):
        try:
            target = self.job_targets.get_target(job_target_id)
        except JobTargetNotFound as error:
            raise RetrospectiveTargetRequired("请选择有效求职目标") from error
        if target.workspace_id != self.workspace_id:
            raise RetrospectiveTargetRequired("求职目标不属于当前工作区")
        clean_title = title.strip()
        clean_round = round_label.strip()
        if not clean_title or not clean_round:
            raise ValueError("标题和面试轮次不能为空")
        if outcome not in {"pending", "passed", "failed", "cancelled", "unrecorded"}:
            raise ValueError("不支持的面试结果")
        return self.repository.create_retrospective(
            workspace_id=self.workspace_id,
            job_target_id=target.id,
            title=clean_title,
            round_label=clean_round,
            interview_date=interview_date,
            outcome=outcome,
            note=note.strip(),
            analysis_session_id=analysis_session_id,
            chat_session_id=chat_session_id,
            create_idempotency_key=idempotency_key,
        )

    def get(self, retrospective_id: str):
        retrospective = self.repository.get_retrospective(retrospective_id)
        if retrospective.workspace_id != self.workspace_id:
            raise RetrospectiveTargetRequired("复盘不属于当前工作区")
        return retrospective

    def list(
        self,
        *,
        lifecycle_status: str = "active",
        job_target_id: str | None = None,
    ):
        if lifecycle_status not in {"active", "archived", "recycled"}:
            raise ValueError("不支持的复盘生命周期")
        records = self.repository.list_retrospectives(
            workspace_id=self.workspace_id,
            lifecycle_status=lifecycle_status,
        )
        if job_target_id is None:
            return records
        return tuple(item for item in records if item.job_target_id == job_target_id)

    def target_summary(self, job_target_id: str) -> dict[str, object]:
        try:
            target = self.job_targets.get_target(job_target_id)
        except JobTargetNotFound as error:
            raise RetrospectiveTargetRequired("请选择有效求职目标") from error
        if target.workspace_id != self.workspace_id:
            raise RetrospectiveTargetRequired("求职目标不属于当前工作区")
        return self.repository.target_summary(job_target_id)

    def update(
        self,
        retrospective_id: str,
        *,
        title: str | None,
        round_label: str | None,
        interview_date: str | None,
        outcome: str | None,
        note: str | None,
        expected_version: int,
        idempotency_key: str,
    ):
        del idempotency_key
        current = self.get(retrospective_id)
        next_title = current.title if title is None else title.strip()
        next_round = current.round_label if round_label is None else round_label.strip()
        next_outcome = current.outcome if outcome is None else outcome
        if not next_title or not next_round:
            raise ValueError("标题和面试轮次不能为空")
        if next_outcome not in {
            "pending",
            "passed",
            "failed",
            "cancelled",
            "unrecorded",
        }:
            raise ValueError("不支持的面试结果")
        return self.repository.update_retrospective(
            retrospective_id,
            title=next_title,
            round_label=next_round,
            interview_date=(
                current.interview_date if interview_date is None else interview_date
            ),
            outcome=next_outcome,
            note=current.note if note is None else note.strip(),
            expected_version=expected_version,
        )

    def add_source_version(
        self,
        retrospective_id: str,
        *,
        source_kind: str,
        body: str,
        file_name: str | None,
        idempotency_key: str,
    ):
        self.get(retrospective_id)
        if source_kind not in {"transcript", "recollection"}:
            raise RetrospectiveSourceUnsupported("不支持的记录类型")
        if not body.strip():
            raise RetrospectiveSourceUnsupported("记录内容不能为空")
        if len(body) > MAX_SOURCE_CHARACTERS:
            raise RetrospectiveSourceTooLarge("记录内容不能超过 500000 个字符")
        clean_file_name = None if file_name is None else PurePath(file_name).name
        if clean_file_name is not None:
            if (
                PurePath(clean_file_name).suffix.lower()
                not in SUPPORTED_SOURCE_SUFFIXES
            ):
                raise RetrospectiveSourceUnsupported("只支持 .txt 和 .md 文件")
        request = {
            "source_kind": source_kind,
            "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "file_name": clean_file_name,
        }
        request_hash = _digest(request)
        replay = self.repository.receipt(
            retrospective_id, "add_source", idempotency_key
        )
        if replay is not None:
            saved_hash, result = replay
            if saved_hash != request_hash:
                raise RetrospectiveIdempotencyConflict("同一幂等键不能提交不同记录")
            return self.repository.get_source_version(str(result["source_version_id"]))
        source = self.repository.insert_source_version(
            retrospective_id,
            source_kind=source_kind,
            file_name=clean_file_name,
            body=body,
            content_sha256=request["body_sha256"],
        )
        self.repository.save_receipt(
            retrospective_id,
            scope="add_source",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            result={"source_version_id": source.id},
        )
        return source

    def create_cleanup_version(
        self,
        retrospective_id: str,
        *,
        source_version_id: str,
        input_digest: str,
        idempotency_key: str,
    ):
        self.get(retrospective_id)
        source = self.repository.get_source_version(source_version_id)
        if source.retrospective_id != retrospective_id:
            raise RetrospectiveTargetRequired("原始记录不属于当前复盘")
        if source.cleared_at is not None:
            raise RetrospectiveSourceCleared("原始记录已清除")
        request_hash = _digest(
            {"source_version_id": source_version_id, "input_digest": input_digest}
        )
        replay = self.repository.receipt(
            retrospective_id, "create_cleanup", idempotency_key
        )
        if replay is not None:
            saved_hash, result = replay
            if saved_hash != request_hash:
                raise RetrospectiveIdempotencyConflict("同一幂等键不能创建不同整理版本")
            return self.repository.get_cleanup_version(str(result["cleanup_id"]))
        cleanup = self.repository.insert_cleanup_version(
            retrospective_id,
            source_version_id=source_version_id,
            input_digest=input_digest,
        )
        self.repository.save_receipt(
            retrospective_id,
            scope="create_cleanup",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            result={"cleanup_id": cleanup.id},
        )
        return cleanup

    def replace_segments(
        self,
        retrospective_id: str,
        cleanup_id: str,
        *,
        expected_version: int,
        segments: tuple[dict[str, object], ...],
    ):
        self.get(retrospective_id)
        cleanup = self.repository.get_cleanup_version(cleanup_id)
        if cleanup.retrospective_id != retrospective_id:
            raise RetrospectiveTargetRequired("整理版本不属于当前复盘")
        normalized: list[dict[str, object]] = []
        previous_end = -1
        for segment in segments:
            role = str(segment["speaker_role"])
            start = int(segment["source_start"])
            end = int(segment["source_end"])
            confidence = float(segment["confidence"])
            if role not in {"candidate", "interviewer", "unknown"}:
                raise ValueError("不支持的说话人角色")
            if start < 0 or end <= start or start < previous_end:
                raise ValueError("片段位置必须有序且不重叠")
            if not 0 <= confidence <= 1:
                raise ValueError("置信度必须位于 0 到 1")
            previous_end = end
            normalized.append(
                {
                    **segment,
                    "speaker_role": role,
                    "source_start": start,
                    "source_end": end,
                    "confidence": confidence,
                    "display_name": str(segment["display_name"]).strip(),
                    "body": str(segment["body"]),
                    "ignored": bool(segment["ignored"]),
                }
            )
        return self.repository.replace_segments(
            cleanup_id,
            expected_version=expected_version,
            segments=tuple(normalized),
        )

    def confirm_cleanup(
        self,
        retrospective_id: str,
        cleanup_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
    ):
        self.get(retrospective_id)
        cleanup = self.repository.get_cleanup_version(cleanup_id)
        if cleanup.retrospective_id != retrospective_id:
            raise RetrospectiveTargetRequired("整理版本不属于当前复盘")
        segments = self.repository.list_segments(cleanup_id)
        if not segments or any(
            not segment.ignored and segment.speaker_role == "unknown"
            for segment in segments
        ):
            raise RetrospectiveCleanupNotConfirmed("请先确认所有保留片段的说话人")
        return self.repository.confirm_cleanup(
            retrospective_id,
            cleanup_id,
            expected_version=expected_version,
        )

    def clear_source(
        self,
        retrospective_id: str,
        source_version_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
    ):
        self.get(retrospective_id)
        if self.repository.active_execution_count(retrospective_id):
            raise RetrospectiveBusy("复盘仍有运行中的任务")
        source = self.repository.get_source_version(source_version_id)
        if source.retrospective_id != retrospective_id:
            raise RetrospectiveTargetRequired("原始记录不属于当前复盘")
        request_hash = _digest(
            {
                "source_version_id": source_version_id,
                "expected_version": expected_version,
            }
        )
        replay = self.repository.receipt(
            retrospective_id, "clear_source", idempotency_key
        )
        if replay is not None:
            saved_hash, _ = replay
            if saved_hash != request_hash:
                raise RetrospectiveIdempotencyConflict("同一幂等键不能清除不同记录")
            return self.repository.get_source_version(source_version_id)
        cleared = self.repository.clear_source(
            retrospective_id,
            source_version_id,
            expected_version=expected_version,
        )
        self.repository.save_receipt(
            retrospective_id,
            scope="clear_source",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            result={"source_version_id": source_version_id},
        )
        return cleared

    def create_analysis_run(
        self,
        retrospective_id: str,
        cleanup_id: str,
        *,
        input_digest: str,
        context_snapshot: dict[str, object],
        idempotency_key: str,
        retry_of_analysis_run_id: str | None = None,
    ):
        self.get(retrospective_id)
        cleanup = self.repository.get_cleanup_version(cleanup_id)
        if cleanup.retrospective_id != retrospective_id:
            raise RetrospectiveTargetRequired("整理版本不属于当前复盘")
        if cleanup.status != "confirmed":
            raise RetrospectiveCleanupNotConfirmed("请先确认说话人整理结果")
        source = self.repository.get_source_version(cleanup.source_version_id)
        if source.cleared_at is not None:
            raise RetrospectiveSourceCleared("原始记录已清除，不能重新分析")
        request_hash = _digest(
            {
                "cleanup_id": cleanup_id,
                "input_digest": input_digest,
                "context_snapshot": context_snapshot,
                "retry_of_analysis_run_id": retry_of_analysis_run_id,
            }
        )
        replay = self.repository.receipt(
            retrospective_id, "start_analysis", idempotency_key
        )
        if replay is not None:
            saved_hash, result = replay
            if saved_hash != request_hash:
                raise RetrospectiveIdempotencyConflict("同一幂等键不能启动不同分析")
            return self.repository.get_analysis_run(str(result["analysis_run_id"]))
        existing = None
        if retry_of_analysis_run_id is None:
            existing = self.repository.analysis_run_by_digest(
                retrospective_id,
                cleanup_version_id=cleanup_id,
                input_digest=input_digest,
            )
        if existing is not None:
            self.repository.save_receipt(
                retrospective_id,
                scope="start_analysis",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                result={"analysis_run_id": existing.id},
            )
            return existing
        active = self.repository.current_analysis_run(retrospective_id)
        if active is not None and active.status in {
            "queued",
            "running",
            "stopping",
        }:
            raise RetrospectiveBusy("面试复盘分析正在进行")
        run = self.repository.insert_analysis_run(
            retrospective_id,
            cleanup_version_id=cleanup_id,
            input_digest=input_digest,
            context_snapshot=context_snapshot,
            retry_of_analysis_run_id=retry_of_analysis_run_id,
        )
        self.repository.save_receipt(
            retrospective_id,
            scope="start_analysis",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            result={"analysis_run_id": run.id},
        )
        return run

    def decide_question(
        self,
        retrospective_id: str,
        question_id: str,
        *,
        decision: str,
        edited_text: str | None,
        expected_version: int,
        idempotency_key: str,
    ):
        self.get(retrospective_id)
        question = self.repository.get_question(question_id)
        if question.retrospective_id != retrospective_id:
            raise RetrospectiveTargetRequired("问题不属于当前复盘")
        if decision not in {"confirmed", "rejected", "superseded"}:
            raise ValueError("不支持的问题决策")
        clean_text = None if edited_text is None else edited_text.strip()
        if edited_text is not None and not clean_text:
            raise ValueError("问题正文不能为空")
        scope = f"decide_question:{question_id}"
        request_hash = _digest(
            {
                "decision": decision,
                "edited_text": clean_text,
                "expected_version": expected_version,
            }
        )
        replay = self.repository.receipt(retrospective_id, scope, idempotency_key)
        if replay is not None:
            saved_hash, result = replay
            if saved_hash != request_hash:
                raise RetrospectiveIdempotencyConflict("同一幂等键不能提交不同问题决策")
            return self.repository.get_question(str(result["question_id"]))
        updated = self.repository.decide_question(
            question_id,
            decision=decision,
            edited_text=clean_text,
            expected_version=expected_version,
        )
        run = self.repository.current_analysis_run(retrospective_id)
        if run is not None:
            self.repository.schedule_analysis_work_items(
                run.id,
                question_ids=(question_id,) if decision == "confirmed" else (),
                include_finalizers=True,
            )
        self.repository.save_receipt(
            retrospective_id,
            scope=scope,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            result={"question_id": updated.id},
        )
        return updated

    def archive(
        self,
        retrospective_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
    ):
        self.get(retrospective_id)
        return self.repository.transition_lifecycle(
            retrospective_id,
            expected_version=expected_version,
            expected_states=("active",),
            target_state="archived",
        )

    def recycle(
        self,
        retrospective_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
    ):
        self.get(retrospective_id)
        if self.repository.active_execution_count(retrospective_id):
            raise RetrospectiveBusy("复盘仍有运行中的任务")
        return self.repository.transition_lifecycle(
            retrospective_id,
            expected_version=expected_version,
            expected_states=("active", "archived"),
            target_state="recycled",
        )

    def restore(
        self,
        retrospective_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
    ):
        self.get(retrospective_id)
        return self.repository.transition_lifecycle(
            retrospective_id,
            expected_version=expected_version,
            expected_states=("archived", "recycled"),
            target_state="active",
        )

    def delete_permanently(
        self,
        retrospective_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> None:
        retrospective = self.get(retrospective_id)
        if self.repository.active_execution_count(retrospective_id):
            raise RetrospectiveBusy("复盘仍有运行中的任务")
        if retrospective.version != expected_version:
            raise RetrospectiveDeleteBlocked("复盘版本已更新")
        if retrospective.lifecycle_status != "recycled":
            raise RetrospectiveDeleteBlocked("请先将复盘移入回收站")
        self.repository.delete_permanently(retrospective_id)

    def deletion_impact(self, retrospective_id: str) -> dict[str, object]:
        self.get(retrospective_id)
        return {
            **self.repository.deletion_impact(retrospective_id),
            "preservesReviewQuestions": True,
            "preservesProfileAndProjects": True,
            "preservesKnowledge": True,
        }


def _digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

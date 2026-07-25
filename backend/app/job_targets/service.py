from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from app.application.session_service import ProductRepository
from app.job_targets.errors import JobTargetBusy, JobTargetNotFound
from app.job_targets.models import (
    JobDocumentVersionRecord,
    JobRequirementRecord,
    JobTargetRecord,
    ProjectPriorityReceipt,
    RequirementDecisionReceipt,
    TargetDeletionImpact,
)
from app.job_targets.repository import JobTargetRepository
from app.job_targets.requirement_classification import is_job_background_or_heading
from app.profile.errors import ProfileClaimNotFound
from app.profile.repository import ProfileRepository


class JobTargetService:
    def __init__(
        self,
        *,
        workspace_id: str,
        repository: JobTargetRepository,
        profile_repository: ProfileRepository,
        product_repository: ProductRepository,
    ) -> None:
        self.workspace_id = workspace_id
        self.repository = repository
        self.profile_repository = profile_repository
        self.product_repository = product_repository

    def create_target(
        self,
        *,
        role_name: str,
        seniority: str,
        company_name: str | None,
        source_url: str | None,
        idempotency_key: str,
    ) -> JobTargetRecord:
        clean_role = role_name.strip()
        clean_seniority = seniority.strip()
        if bool(clean_role) != bool(clean_seniority):
            raise ValueError("岗位名称和职级需要同时填写，或交给岗位分析识别")
        operation = "create_target"
        replay = self.repository.receipt(
            self.workspace_id, operation, idempotency_key
        )
        if replay is not None:
            return self.get_target(str(replay["target_id"]))
        payload = {
            "role_name": clean_role,
            "seniority": clean_seniority,
            "company_name": _optional(company_name),
            "source_url": _optional(source_url),
        }
        target = self.repository.create_target(
            workspace_id=self.workspace_id, **payload
        )
        self._save_receipt(
            operation,
            idempotency_key,
            payload,
            {"target_id": target.id},
        )
        return target

    def get_target(self, target_id: str) -> JobTargetRecord:
        target = self.repository.get_target(target_id)
        self._assert_workspace(target)
        return target

    def list_targets(
        self,
        *,
        include_archived: bool = False,
        recycled_only: bool = False,
    ) -> tuple[JobTargetRecord, ...]:
        return self.repository.list_targets(
            self.workspace_id,
            include_archived=include_archived,
            recycled_only=recycled_only,
        )

    def update_target(
        self,
        target_id: str,
        *,
        expected_version: int,
        company_name: str | None,
        role_name: str,
        seniority: str,
        source_url: str | None,
        idempotency_key: str,
    ) -> JobTargetRecord:
        self.get_target(target_id)
        return self.repository.update_target(
            target_id,
            expected_version=expected_version,
            values={
                "company_name": _optional(company_name),
                "role_name": role_name.strip(),
                "seniority": seniority.strip(),
                "source_url": _optional(source_url),
            },
        )

    def archive_target(
        self,
        target_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> JobTargetRecord:
        return self._transition(
            target_id,
            expected_version=expected_version,
            expected_states=("active",),
            target_state="archived",
        )

    def recycle_target(
        self,
        target_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> JobTargetRecord:
        if self.repository.active_execution_count(target_id):
            raise JobTargetBusy("求职目标仍有运行中的任务")
        return self._transition(
            target_id,
            expected_version=expected_version,
            expected_states=("active", "archived"),
            target_state="recycled",
        )

    def restore_target(
        self,
        target_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> JobTargetRecord:
        return self._transition(
            target_id,
            expected_version=expected_version,
            expected_states=("archived", "recycled"),
            target_state="active",
        )

    def create_document_version(
        self,
        target_id: str,
        *,
        source_kind: str,
        body: str,
        idempotency_key: str,
    ) -> JobDocumentVersionRecord:
        target = self.get_target(target_id)
        clean = body.strip()
        if source_kind not in {"jd_text", "direction_reference"}:
            raise ValueError("不支持的岗位内容来源")
        if not clean:
            raise ValueError("岗位内容不能为空")
        operation = f"create_document:{target_id}"
        replay = self.repository.receipt(
            self.workspace_id, operation, idempotency_key
        )
        if replay is not None:
            return self.get_document_version(str(replay["document_version_id"]))
        document = self.repository.create_document_version(
            target.id,
            source_kind=source_kind,
            body=clean,
            content_hash=hashlib.sha256(clean.encode("utf-8")).hexdigest(),
        )
        self._save_receipt(
            operation,
            idempotency_key,
            {"source_kind": source_kind, "body": clean},
            {"document_version_id": document.id},
        )
        return document

    def get_document_version(self, version_id: str) -> JobDocumentVersionRecord:
        version = self.repository.get_document_version(version_id)
        self.get_target(version.job_target_id)
        return version

    def list_document_versions(
        self, target_id: str
    ) -> tuple[JobDocumentVersionRecord, ...]:
        self.get_target(target_id)
        return self.repository.list_document_versions(target_id)

    def confirm_document_version(
        self,
        target_id: str,
        version_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> JobTargetRecord:
        self.get_target(target_id)
        operation = f"confirm_document:{target_id}"
        replay = self.repository.receipt(
            self.workspace_id, operation, idempotency_key
        )
        if replay is not None:
            return self.get_target(target_id)
        target = self.repository.confirm_document_version(
            target_id,
            version_id,
            expected_version=expected_version,
        )
        self._save_receipt(
            operation,
            idempotency_key,
            {"version_id": version_id, "expected_version": expected_version},
            {"target_id": target.id, "version": target.version},
        )
        return target

    def replace_requirement_suggestions(
        self,
        target_id: str,
        document_version_id: str,
        *,
        suggestions: tuple[dict[str, object], ...],
    ) -> tuple[JobRequirementRecord, ...]:
        self.get_target(target_id)
        return self.repository.replace_requirement_suggestions(
            target_id, document_version_id, suggestions
        )

    def list_requirements(
        self, target_id: str
    ) -> tuple[JobRequirementRecord, ...]:
        self.get_target(target_id)
        return self.repository.list_requirements(target_id)

    def list_preparation_requirements(
        self, target_id: str
    ) -> tuple[JobRequirementRecord, ...]:
        return tuple(
            item
            for item in self.list_requirements(target_id)
            if not is_job_background_or_heading(item.text)
        )

    def confirm_safe_requirements(
        self,
        target_id: str,
        *,
        document_version_id: str,
        idempotency_key: str,
    ) -> RequirementDecisionReceipt:
        self.get_target(target_id)
        requirements = tuple(
            item
            for item in self.repository.list_requirements(
                target_id, document_version_id=document_version_id
            )
            if not is_job_background_or_heading(item.text)
        )
        confirmed: list[str] = []
        excluded: list[str] = []
        for item in requirements:
            safe = (
                item.confirmation_status == "pending"
                and not item.inferred
                and bool(item.source_quote.strip())
            )
            if safe:
                self.repository.set_requirement_confirmation(
                    item.id,
                    expected_version=item.version,
                    status="confirmed",
                )
                confirmed.append(item.id)
            elif item.confirmation_status == "pending":
                excluded.append(item.id)
        return RequirementDecisionReceipt(
            confirmed_ids=tuple(confirmed),
            rejected_ids=(),
            pending_ids=(),
            excluded_ids=tuple(excluded),
        )

    def decide_requirements(
        self,
        target_id: str,
        *,
        decisions: tuple[dict[str, object], ...],
        idempotency_key: str,
    ) -> RequirementDecisionReceipt:
        self.get_target(target_id)
        confirmed: list[str] = []
        rejected: list[str] = []
        pending: list[str] = []
        for decision in decisions:
            item = self.repository.get_requirement(
                str(decision["requirement_id"])
            )
            if item.job_target_id != target_id:
                raise JobTargetNotFound(target_id)
            target_status = str(decision["decision"])
            if target_status not in {"pending", "confirmed", "rejected"}:
                raise ValueError("不支持的岗位要求决定")
            updated = self.repository.set_requirement_confirmation(
                item.id,
                expected_version=int(decision["expected_version"]),
                status=target_status,
            )
            if updated.confirmation_status == "confirmed":
                confirmed.append(updated.id)
            elif updated.confirmation_status == "rejected":
                rejected.append(updated.id)
            else:
                pending.append(updated.id)
        return RequirementDecisionReceipt(
            confirmed_ids=tuple(confirmed),
            rejected_ids=tuple(rejected),
            pending_ids=tuple(pending),
            excluded_ids=(),
        )

    def set_project_priorities(
        self,
        target_id: str,
        *,
        core_project_id: str,
        supplementary_project_ids: tuple[str, ...],
        expected_version: int,
        idempotency_key: str,
    ) -> ProjectPriorityReceipt:
        self.get_target(target_id)
        if len(supplementary_project_ids) > 2:
            raise ValueError("补充项目最多选择两个")
        if core_project_id in supplementary_project_ids:
            raise ValueError("核心项目不能同时作为补充项目")
        self._assert_confirmed_project(
            core_project_id, "核心项目必须来自已确认的个人画像"
        )
        for project_id in supplementary_project_ids:
            self._assert_confirmed_project(
                project_id, "补充项目必须来自已确认的个人画像"
            )
        self.repository.replace_project_priorities(
            target_id,
            core_project_id=core_project_id,
            supplementary_project_ids=supplementary_project_ids,
        )
        target = self.repository.increment_target_version(
            target_id, expected_version=expected_version
        )
        return ProjectPriorityReceipt(
            job_target_id=target_id,
            core_project_id=core_project_id,
            supplementary_project_ids=supplementary_project_ids,
            version=target.version,
        )

    def deletion_impact(self, target_id: str) -> TargetDeletionImpact:
        self.get_target(target_id)
        counts = self.repository.deletion_impact(target_id)
        return TargetDeletionImpact(target_id=target_id, **counts)

    def delete_target(self, target_id: str, *, idempotency_key: str) -> None:
        self.get_target(target_id)
        self.repository.delete_target(target_id)

    def _transition(
        self,
        target_id: str,
        *,
        expected_version: int,
        expected_states: tuple[str, ...],
        target_state: str,
    ) -> JobTargetRecord:
        self.get_target(target_id)
        return self.repository.transition_lifecycle(
            target_id,
            expected_version=expected_version,
            expected_states=expected_states,
            target_state=target_state,
        )

    def _assert_confirmed_project(self, claim_id: str, message: str) -> None:
        try:
            claim = self.profile_repository.get_claim(claim_id)
        except ProfileClaimNotFound as error:
            raise ValueError(message) from error
        if (
            claim.workspace_id != self.workspace_id
            or claim.claim_type != "project"
            or claim.current_confirmed_version_id is None
        ):
            raise ValueError(message)

    def _assert_workspace(self, target: JobTargetRecord) -> None:
        if target.workspace_id != self.workspace_id:
            raise JobTargetNotFound(target.id)

    def _save_receipt(
        self,
        operation: str,
        idempotency_key: str,
        payload: dict[str, object],
        result: dict[str, object],
    ) -> None:
        digest = hashlib.sha256(
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        self.repository.save_receipt(
            workspace_id=self.workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_digest=digest,
            result=result,
        )


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value.strip()
    return clean or None

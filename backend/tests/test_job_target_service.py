from app.application.session_service import ProductRepository
from app.infrastructure.runtime_database import connect_runtime_database
from app.job_targets.repository import JobTargetRepository
from app.job_targets.service import JobTargetService
from app.profile.repository import ProfileRepository


def _service(tmp_path):
    connection = connect_runtime_database(tmp_path)
    return JobTargetService(
        workspace_id="w1",
        repository=JobTargetRepository(connection),
        profile_repository=ProfileRepository(connection),
        product_repository=ProductRepository(connection),
    )


def test_document_version_is_immutable_until_explicitly_confirmed(tmp_path):
    service = _service(tmp_path)
    target = service.create_target(
        role_name="高级后端工程师",
        seniority="5-8 年",
        company_name="示例公司",
        source_url=None,
        idempotency_key="create-target-1",
    )
    first = service.create_document_version(
        target.id,
        source_kind="jd_text",
        body="负责高并发服务设计",
        idempotency_key="create-jd-1",
    )
    service.confirm_document_version(
        target.id,
        first.id,
        expected_version=service.get_target(target.id).version,
        idempotency_key="confirm-jd-1",
    )
    second = service.create_document_version(
        target.id,
        source_kind="jd_text",
        body="负责高并发服务设计与稳定性治理",
        idempotency_key="create-jd-2",
    )

    current = service.get_target(target.id)
    assert current.current_document_version_id == first.id
    assert second.is_current is False
    assert service.get_document_version(first.id).body == "负责高并发服务设计"


def test_safe_bulk_confirmation_excludes_inferred_requirements(tmp_path):
    service = _service(tmp_path)
    target = service.create_target(
        role_name="后端工程师",
        seniority="3-5 年",
        company_name=None,
        source_url=None,
        idempotency_key="create-target-2",
    )
    document = service.create_document_version(
        target.id,
        source_kind="jd_text",
        body="负责 API 与系统设计",
        idempotency_key="create-jd-3",
    )
    service.replace_requirement_suggestions(
        target.id,
        document.id,
        suggestions=(
            {
                "stable_key": "source-api",
                "requirement_type": "responsibility",
                "priority": "must_have",
                "text": "负责 API 设计",
                "source_quote": "负责 API 与系统设计",
                "inferred": False,
            },
            {
                "stable_key": "inferred-team",
                "requirement_type": "experience",
                "priority": "nice_to_have",
                "text": "可能需要带团队",
                "source_quote": "",
                "inferred": True,
            },
        ),
    )

    receipt = service.confirm_safe_requirements(
        target.id,
        document_version_id=document.id,
        idempotency_key="confirm-safe-1",
    )

    assert len(receipt.confirmed_ids) == 1
    assert len(receipt.excluded_ids) == 1
    requirements = service.list_requirements(target.id)
    assert requirements[0].confirmation_status == "confirmed"
    assert requirements[1].confirmation_status == "pending"


def test_project_priorities_require_confirmed_profile_projects(tmp_path):
    service = _service(tmp_path)
    target = service.create_target(
        role_name="后端工程师",
        seniority="3-5 年",
        company_name=None,
        source_url=None,
        idempotency_key="create-target-3",
    )

    try:
        service.set_project_priorities(
            target.id,
            core_project_id="missing-project",
            supplementary_project_ids=(),
            expected_version=target.version,
            idempotency_key="priority-1",
        )
    except ValueError as error:
        assert str(error) == "核心项目必须来自已确认的个人画像"
    else:
        raise AssertionError("missing Profile project should be rejected")

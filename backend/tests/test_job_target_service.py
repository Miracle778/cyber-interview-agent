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
            {
                "stable_key": "culture-slogan",
                "requirement_type": "experience",
                "priority": "must_have",
                "text": "开放、务实、追求卓越",
                "source_quote": "开放、务实、追求卓越",
                "inferred": False,
            },
        ),
    )

    receipt = service.confirm_safe_requirements(
        target.id,
        document_version_id=document.id,
        idempotency_key="confirm-safe-1",
    )

    assert len(receipt.confirmed_ids) == 1
    assert len(receipt.excluded_ids) == 2
    requirements = service.list_requirements(target.id)
    assert requirements[0].confirmation_status == "confirmed"
    assert requirements[1].confirmation_status == "pending"
    assert requirements[2].confirmation_status == "pending"


def test_team_background_and_section_headings_stay_out_of_preparation(tmp_path):
    service = _service(tmp_path)
    target = service.create_target(
        role_name="后端工程师",
        seniority="3-5 年",
        company_name=None,
        source_url=None,
        idempotency_key="create-target-background",
    )
    document = service.create_document_version(
        target.id,
        source_kind="jd_text",
        body="团队服务于全站业务，产品包括服务注册中心。\n熟悉 Redis。",
        idempotency_key="create-jd-background",
    )
    service.replace_requirement_suggestions(
        target.id,
        document.id,
        suggestions=(
            {
                "stable_key": "team-intro",
                "requirement_type": "responsibility",
                "priority": "must_have",
                "text": "团队服务于全站业务，产品包括服务注册中心",
                "source_quote": "团队服务于全站业务，产品包括服务注册中心",
                "inferred": False,
            },
            {
                "stable_key": "heading",
                "requirement_type": "responsibility",
                "priority": "nice_to_have",
                "text": "优先考虑条件：",
                "source_quote": "优先考虑条件：",
                "inferred": False,
            },
            {
                "stable_key": "redis",
                "requirement_type": "skill",
                "priority": "must_have",
                "text": "熟悉 Redis",
                "source_quote": "熟悉 Redis",
                "inferred": False,
            },
        ),
    )

    receipt = service.confirm_safe_requirements(
        target.id,
        document_version_id=document.id,
        idempotency_key="confirm-safe-background",
    )

    assert len(receipt.confirmed_ids) == 1
    assert [item.text for item in service.list_preparation_requirements(target.id)] == [
        "熟悉 Redis"
    ]


def test_confirmed_requirement_can_be_returned_to_pending_for_reconfirmation(tmp_path):
    service = _service(tmp_path)
    target = service.create_target(
        role_name="后端工程师",
        seniority="3-5 年",
        company_name=None,
        source_url=None,
        idempotency_key="create-target-reconfirm",
    )
    document = service.create_document_version(
        target.id,
        source_kind="jd_text",
        body="熟悉 Redis",
        idempotency_key="create-jd-reconfirm",
    )
    requirement = service.replace_requirement_suggestions(
        target.id,
        document.id,
        suggestions=(
            {
                "stable_key": "redis",
                "requirement_type": "skill",
                "priority": "must_have",
                "text": "熟悉 Redis",
                "source_quote": "熟悉 Redis",
                "inferred": False,
            },
        ),
    )[0]
    service.decide_requirements(
        target.id,
        decisions=(
            {
                "requirement_id": requirement.id,
                "expected_version": requirement.version,
                "decision": "confirmed",
            },
        ),
        idempotency_key="confirm-redis",
    )
    confirmed = service.list_requirements(target.id)[0]

    receipt = service.decide_requirements(
        target.id,
        decisions=(
            {
                "requirement_id": confirmed.id,
                "expected_version": confirmed.version,
                "decision": "pending",
            },
        ),
        idempotency_key="reopen-redis",
    )

    assert receipt.pending_ids == (requirement.id,)
    assert service.list_requirements(target.id)[0].confirmation_status == "pending"


def test_reanalysis_reconciles_same_requirement_and_discards_stale_pending(tmp_path):
    service = _service(tmp_path)
    target = service.create_target(
        role_name="后端工程师",
        seniority="3-5 年",
        company_name=None,
        source_url=None,
        idempotency_key="create-target-reanalysis",
    )
    document = service.create_document_version(
        target.id,
        source_kind="jd_text",
        body="熟悉 Redis，具备性能优化经验",
        idempotency_key="create-jd-reanalysis",
    )
    service.replace_requirement_suggestions(
        target.id,
        document.id,
        suggestions=(
            {
                "stable_key": "model-key-a",
                "requirement_type": "skill",
                "priority": "must_have",
                "text": "熟悉 Redis",
                "source_quote": "熟悉 Redis",
                "inferred": False,
            },
            {
                "stable_key": "stale-pending",
                "requirement_type": "skill",
                "priority": "nice_to_have",
                "text": "有消息队列经验",
                "source_quote": "",
                "inferred": True,
            },
        ),
    )
    service.confirm_safe_requirements(
        target.id,
        document_version_id=document.id,
        idempotency_key="confirm-reanalysis",
    )

    requirements = service.replace_requirement_suggestions(
        target.id,
        document.id,
        suggestions=(
            {
                "stable_key": "different-model-key",
                "requirement_type": "skill",
                "priority": "must_have",
                "text": "熟悉Redis",
                "source_quote": "熟悉 Redis",
                "inferred": False,
            },
            {
                "stable_key": "new-pending",
                "requirement_type": "experience",
                "priority": "nice_to_have",
                "text": "具备性能优化经验",
                "source_quote": "具备性能优化经验",
                "inferred": False,
            },
        ),
    )

    assert [(item.text, item.confirmation_status) for item in requirements] == [
        ("熟悉 Redis", "confirmed"),
        ("具备性能优化经验", "pending"),
    ]


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

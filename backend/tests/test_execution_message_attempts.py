from app.application.session_service import ProductRepository
from app.infrastructure.runtime_database import connect_runtime_database


def test_retry_execution_reuses_one_user_message(tmp_path):
    repository = ProductRepository(connect_runtime_database(tmp_path))
    session = repository.create_session(
        workspace_id="w1",
        kind="project.deep_dive",
        title="项目深挖",
    )
    message = repository.append_user_message(
        session.id,
        content="我负责核心链路",
    )
    first = repository.create_execution(
        session.id,
        input={"message": message.content},
        model_bindings={},
        input_message_id=message.id,
    )
    repository.transition_execution(
        first.id,
        expected=("running",),
        target="failed",
        error_code="provider_error",
    )
    repository.resolve_message(
        message.id,
        expected=("active",),
        target="unresolved",
    )
    retry = repository.create_execution(
        session.id,
        input={"message": message.content},
        model_bindings={},
        input_message_id=message.id,
        retry_of_execution_id=first.id,
    )

    assert retry.input_message_id == message.id
    assert retry.retry_of_execution_id == first.id
    assert [item.content for item in repository.list_messages(session.id)] == [
        "我负责核心链路"
    ]


def test_replace_message_marks_original_out_of_active_context(tmp_path):
    repository = ProductRepository(connect_runtime_database(tmp_path))
    session = repository.create_session(
        workspace_id="w1",
        kind="project.deep_dive",
        title="项目深挖",
    )
    original = repository.append_user_message(
        session.id,
        content="我独立完成全部架构",
    )
    repository.resolve_message(
        original.id,
        expected=("active",),
        target="unresolved",
    )
    replacement = repository.append_user_message(
        session.id,
        content="我与团队共同完成核心架构",
        replaces_message_id=original.id,
    )

    messages = repository.list_messages(session.id)
    assert messages[0].resolution_status == "replaced"
    assert messages[1].replaces_message_id == original.id
    assert replacement.resolution_status == "active"

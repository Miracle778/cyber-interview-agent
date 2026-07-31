import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.infrastructure.runtime_database import connect_runtime_database
from app.hitl.handlers import (
    ActionHandlerRegistry,
    ActionPayloadValidationError,
    DefaultActionHandler,
    DuplicateActionHandlerError,
    UnknownActionTypeError,
)
from app.hitl.models import CreatePendingAction, ResolveActionCommand
from app.hitl.repository import PendingActionRepository
from app.hitl.service import HitlService
from app.application.session_service import ProductRepository


class RecordingHandler(DefaultActionHandler):
    def __init__(self) -> None:
        self.receipts: list[str] = []

    async def after_resolution(self, action, receipt) -> None:
        assert action.status != "pending"
        self.receipts.append(receipt.id)


class RecordingEvents:
    def __init__(self) -> None:
        self.items: list[tuple[str, str | None, str, dict[str, Any]]] = []

    async def publish(
        self,
        session_id: str,
        run_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        self.items.append((session_id, run_id, event_type, payload))


class RecordingResume:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any], str]] = []
        self.fail_once = fail_once

    async def __call__(self, run_id: str, decision: dict[str, Any], receipt_id: str):
        self.calls.append((run_id, decision, receipt_id))
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("internal detail must not be persisted")


class BlockingResume(RecordingResume):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, run_id: str, decision: dict[str, Any], receipt_id: str):
        self.calls.append((run_id, decision, receipt_id))
        self.started.set()
        await self.release.wait()


class BlockingPrepare:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, _run_id: str) -> None:
        self.started.set()
        await self.release.wait()


def _database(workspace: Path):
    connection = connect_runtime_database(workspace)
    runtime = ProductRepository(connection)
    runtime.create_session(
        workspace_id="w1",
        kind="test.approval",
        title="Approval",
        session_id="s1",
    )
    runtime.create_execution(
        "s1",
        input={"summary": "original"},
        model_bindings={},
        execution_id="r1",
    )
    return connection


def _request() -> CreatePendingAction:
    return CreatePendingAction(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        action_type="test.approval",
        payload={"summary": "original", "protected": "fixed"},
        preview={"summary": "original"},
        editable_fields=("summary",),
        idempotency_key="r1:test.approval",
    )


def _service(
    workspace: Path,
    *,
    resume: RecordingResume | None = None,
    prepare_resolution: BlockingPrepare | None = None,
) -> tuple[
    HitlService,
    PendingActionRepository,
    RecordingHandler,
    RecordingEvents,
    RecordingResume,
]:
    repository = PendingActionRepository(workspace)
    handler = RecordingHandler()
    registry = ActionHandlerRegistry()
    registry.register("test.approval", handler)
    events = RecordingEvents()
    resume_callback = resume or RecordingResume()
    return (
        HitlService(
            repository=repository,
            handlers=registry,
            event_stream=events,
            resume_action=resume_callback,
            prepare_resolution=prepare_resolution,
        ),
        repository,
        handler,
        events,
        resume_callback,
    )


@pytest.mark.asyncio
async def test_resolution_waits_for_execution_interrupt_before_writing(
    tmp_path: Path,
) -> None:
    connection = _database(tmp_path)
    prepare = BlockingPrepare()
    service, repository, _handler, _events, _resume = _service(
        tmp_path,
        prepare_resolution=prepare,
    )
    action = await service.create_action(_request())
    command = ResolveActionCommand(
        version=action.version,
        idempotency_key="approve-1",
    )

    approving = asyncio.create_task(service.approve(action.id, command))
    await prepare.started.wait()

    assert (await repository.get(action.id)).status == "pending"

    prepare.release.set()
    approved = await approving

    assert approved.status == "approved"
    connection.close()


def test_handler_registry_rejects_duplicate_and_unknown_types() -> None:
    registry = ActionHandlerRegistry()
    registry.register("test.approval", DefaultActionHandler())

    with pytest.raises(DuplicateActionHandlerError):
        registry.register("test.approval", DefaultActionHandler())
    with pytest.raises(UnknownActionTypeError):
        registry.get("knowledge.publish")


@pytest.mark.asyncio
async def test_edited_approval_persists_and_resumes_once(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    service, repository, handler, events, resume = _service(tmp_path)
    action = await service.create_action(_request())
    command = ResolveActionCommand(
        version=action.version,
        idempotency_key="approve-1",
        edited_payload={"summary": "edited"},
    )

    first = await service.approve(action.id, command)
    second = await service.approve(action.id, command)

    assert first == second
    assert first.status == "edited_and_approved"
    assert first.payload == {"summary": "edited", "protected": "fixed"}
    receipt = (await repository.list_resolutions(action.id))[0]
    assert receipt.delivery_status == "delivered"
    assert receipt.delivery_attempts == 1
    assert resume.calls == [
        (
            "r1",
            {
                "actionId": action.id,
                "decision": "approved",
                "payload": {"summary": "edited", "protected": "fixed"},
            },
            receipt.id,
        )
    ]
    assert handler.receipts == [receipt.id]
    assert [item[2] for item in events.items] == ["approval.resolved"]
    connection.close()


@pytest.mark.asyncio
async def test_reject_resumes_with_reason(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    service, repository, _handler, _events, resume = _service(tmp_path)
    action = await service.create_action(_request())

    rejected = await service.reject(
        action.id,
        ResolveActionCommand(
            version=action.version,
            idempotency_key="reject-1",
            reason="不发布",
        ),
    )

    receipt = (await repository.list_resolutions(action.id))[0]
    assert rejected.status == "rejected"
    assert resume.calls == [
        (
            "r1",
            {
                "actionId": action.id,
                "decision": "rejected",
                "reason": "不发布",
            },
            receipt.id,
        )
    ]
    connection.close()


@pytest.mark.asyncio
async def test_editing_non_editable_field_keeps_action_pending(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    service, repository, _handler, _events, resume = _service(tmp_path)
    action = await service.create_action(_request())

    with pytest.raises(ActionPayloadValidationError):
        await service.approve(
            action.id,
            ResolveActionCommand(
                version=action.version,
                idempotency_key="approve-1",
                edited_payload={"protected": "changed"},
            ),
        )

    assert (await repository.get(action.id)).status == "pending"
    assert resume.calls == []
    connection.close()


@pytest.mark.asyncio
async def test_failed_delivery_is_retried_with_same_receipt(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    resume = RecordingResume(fail_once=True)
    service, repository, handler, events, _resume = _service(tmp_path, resume=resume)
    action = await service.create_action(_request())
    command = ResolveActionCommand(
        version=action.version,
        idempotency_key="approve-1",
    )

    with pytest.raises(RuntimeError):
        await service.approve(action.id, command)
    failed = (await repository.list_resolutions(action.id))[0]
    assert failed.delivery_status == "failed"
    assert failed.delivery_error_code == "hitl_resume_failed"

    resolved = await service.approve(action.id, command)
    delivered = (await repository.list_resolutions(action.id))[0]

    assert resolved.status == "approved"
    assert delivered.id == failed.id
    assert delivered.delivery_status == "delivered"
    assert delivered.delivery_attempts == 2
    assert len(resume.calls) == 2
    assert handler.receipts == [failed.id, failed.id]
    assert [item[2] for item in events.items] == [
        "approval.resolved",
        "approval.resolved",
    ]
    connection.close()


@pytest.mark.asyncio
async def test_concurrent_duplicate_resolution_claims_delivery_once(
    tmp_path: Path,
) -> None:
    connection = _database(tmp_path)
    resume = BlockingResume()
    service, repository, handler, events, _resume = _service(tmp_path, resume=resume)
    action = await service.create_action(_request())
    command = ResolveActionCommand(
        version=action.version,
        idempotency_key="approve-1",
    )

    first = asyncio.create_task(service.approve(action.id, command))
    await resume.started.wait()
    second = asyncio.create_task(service.approve(action.id, command))
    await asyncio.sleep(0.05)

    assert len(resume.calls) == 1
    resume.release.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert first_result == second_result
    receipt = (await repository.list_resolutions(action.id))[0]
    assert receipt.delivery_status == "delivered"
    assert receipt.delivery_attempts == 1
    assert handler.receipts == [receipt.id]
    assert [item[2] for item in events.items] == ["approval.resolved"]
    connection.close()


@pytest.mark.asyncio
async def test_reconcile_settles_terminal_run_without_replaying_side_effects(
    tmp_path: Path,
) -> None:
    connection = _database(tmp_path)
    service, repository, handler, events, resume = _service(tmp_path)
    action = await repository.create(_request())
    receipt = await repository.resolve(
        action.id,
        expected_version=action.version,
        status="approved",
        resolution_key="approve-1",
        decision={"decision": "approved"},
    )
    runtime = ProductRepository(connection)
    runtime.transition_execution("r1", expected=("running",), target="completed")

    await service.reconcile()

    stored = (await repository.list_resolutions(action.id))[0]
    assert stored.id == receipt.id
    assert stored.delivery_status == "delivered"
    assert handler.receipts == []
    assert events.items == []
    assert resume.calls == []
    connection.close()

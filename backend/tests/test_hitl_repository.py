from pathlib import Path

import pytest

from app.db.runtime_database import connect_runtime_database
from app.hitl.models import CreatePendingAction
from app.hitl.repository import (
    ActionAlreadyResolvedError,
    ActionIdempotencyConflictError,
    ActionVersionConflictError,
    PendingActionRepository,
)
from app.runtime.repository import RuntimeRepository


def _database(workspace: Path):
    connection = connect_runtime_database(workspace)
    runtime = RuntimeRepository(connection)
    runtime.create_session(
        workspace_id="w1",
        graph_id="test.approval",
        graph_version=1,
        title="Approval",
        session_id="s1",
    )
    runtime.create_run(
        "s1",
        input={"summary": "original"},
        model_bindings={},
        run_id="r1",
        initial_status="running",
    )
    return connection


def _request(*, key: str = "r1:test.approval") -> CreatePendingAction:
    return CreatePendingAction(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        action_type="test.approval",
        payload={"summary": "original", "secret": "internal-only"},
        preview={"summary": "original"},
        editable_fields=("summary",),
        idempotency_key=key,
    )


def test_runtime_migration_creates_hitl_tables(tmp_path: Path) -> None:
    connection = connect_runtime_database(tmp_path)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    versions = connection.execute(
        "SELECT version FROM runtime_schema_migrations ORDER BY version"
    ).fetchall()

    assert {"pending_actions", "pending_action_resolutions"} <= tables
    assert [row[0] for row in versions] == [1, 2, 3, 4, 5]
    connection.close()


@pytest.mark.asyncio
async def test_create_is_idempotent(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    repository = PendingActionRepository(tmp_path)

    first = await repository.create(_request())
    second = await repository.create(_request())

    assert second == first
    assert first.status == "pending"
    assert first.version == 1
    assert first.editable_fields == ("summary",)
    connection.close()


@pytest.mark.asyncio
async def test_list_pending_filters_by_workspace_and_session(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    repository = PendingActionRepository(tmp_path)
    action = await repository.create(_request())

    assert await repository.list_pending("w1") == (action,)
    assert await repository.list_pending("w1", session_id="s1") == (action,)
    assert await repository.list_pending("w1", session_id="other") == ()
    assert await repository.list_pending("other") == ()
    connection.close()


@pytest.mark.asyncio
async def test_resolution_requires_current_version(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    repository = PendingActionRepository(tmp_path)
    action = await repository.create(_request())

    with pytest.raises(ActionVersionConflictError):
        await repository.resolve(
            action.id,
            expected_version=action.version + 1,
            status="approved",
            resolution_key="resolve-1",
            decision={"decision": "approved"},
        )

    assert (await repository.get(action.id)).status == "pending"
    connection.close()


@pytest.mark.asyncio
async def test_duplicate_resolution_returns_original_receipt(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    repository = PendingActionRepository(tmp_path)
    action = await repository.create(_request())

    first = await repository.resolve(
        action.id,
        expected_version=action.version,
        status="edited_and_approved",
        resolution_key="resolve-1",
        decision={"decision": "approved", "payload": {"summary": "edited"}},
        resolved_payload={"summary": "edited", "secret": "internal-only"},
    )
    second = await repository.resolve(
        action.id,
        expected_version=action.version,
        status="edited_and_approved",
        resolution_key="resolve-1",
        decision={"decision": "approved", "payload": {"summary": "edited"}},
        resolved_payload={"summary": "edited", "secret": "internal-only"},
    )

    assert second == first
    assert first.delivery_status == "pending"
    resolved = await repository.get(action.id)
    assert resolved.status == "edited_and_approved"
    assert resolved.version == 2
    assert resolved.payload["summary"] == "edited"
    connection.close()


@pytest.mark.asyncio
async def test_duplicate_resolution_key_rejects_changed_request(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    repository = PendingActionRepository(tmp_path)
    action = await repository.create(_request())
    await repository.resolve(
        action.id,
        expected_version=action.version,
        status="approved",
        resolution_key="resolve-1",
        decision={"decision": "approved"},
    )

    with pytest.raises(ActionIdempotencyConflictError):
        await repository.resolve(
            action.id,
            expected_version=action.version,
            status="rejected",
            resolution_key="resolve-1",
            decision={"decision": "rejected", "reason": "changed"},
            reason="changed",
        )

    with pytest.raises(ActionIdempotencyConflictError):
        await repository.resolve(
            action.id,
            expected_version=action.version + 1,
            status="approved",
            resolution_key="resolve-1",
            decision={"decision": "approved"},
        )
    connection.close()


@pytest.mark.asyncio
async def test_second_resolution_key_is_rejected(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    repository = PendingActionRepository(tmp_path)
    action = await repository.create(_request())
    await repository.resolve(
        action.id,
        expected_version=action.version,
        status="approved",
        resolution_key="approve-1",
        decision={"decision": "approved"},
    )

    with pytest.raises(ActionAlreadyResolvedError):
        await repository.resolve(
            action.id,
            expected_version=action.version,
            status="rejected",
            resolution_key="reject-1",
            decision={"decision": "rejected"},
            reason="changed mind",
        )
    connection.close()


@pytest.mark.asyncio
async def test_delivery_lifecycle_is_persisted(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    repository = PendingActionRepository(tmp_path)
    action = await repository.create(_request())
    receipt = await repository.resolve(
        action.id,
        expected_version=action.version,
        status="approved",
        resolution_key="approve-1",
        decision={"decision": "approved"},
    )

    delivering = await repository.mark_delivering(receipt.id)
    delivered = await repository.mark_delivered(receipt.id)

    assert delivering.delivery_status == "delivering"
    assert delivering.delivery_attempts == 1
    assert delivered.delivery_status == "delivered"
    assert delivered.delivered_at is not None
    assert await repository.list_undelivered() == ()
    connection.close()


@pytest.mark.asyncio
async def test_cancel_pending_for_run_is_idempotent(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    repository = PendingActionRepository(tmp_path)
    action = await repository.create(_request())

    first = await repository.cancel_pending_for_run("r1")
    second = await repository.cancel_pending_for_run("r1")

    assert first is not None
    assert first.id == action.id
    assert first.status == "cancelled"
    assert second is None
    connection.close()

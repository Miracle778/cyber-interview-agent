from pathlib import Path
from types import SimpleNamespace
import asyncio

import pytest

from app.application.workspace_runtime import AgentApplication
from app.knowledge.source_registry import KnowledgeSourceService
from app.review.curation_command_contracts import CurationCommandPlan
from app.review.models import MasteryProjection, QuestionSnapshot, ReviewRoundSettings
from tests.test_review_api_v2 import _graph_factory


class _BlockingClassifier:
    def __init__(self, entered: asyncio.Event) -> None:
        self.entered = entered

    async def classify(self, assembled, *, context):
        self.entered.set()
        await asyncio.Event().wait()


class _ResolvedClassifier:
    async def classify(self, assembled, *, context):
        return CurationCommandPlan(clarification="恢复后完成")


class _Responder:
    async def astream(self, rendered_context, *, context):
        yield "恢复后完成"


def _command_agents(classifier):
    return SimpleNamespace(
        classifier=classifier,
        summarizer=SimpleNamespace(),
        responder=_Responder(),
        context_limit_tokens=16_000,
        token_counter=len,
    )


@pytest.mark.asyncio
async def test_waiting_input_round_resumes_after_application_restart(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def build() -> AgentApplication:
        return AgentApplication(
            workspace_resolver=lambda _workspace_id: workspace,
            workspace_ids=lambda: ("w1",),
            model_bindings=lambda _workspace_id: {},
            graph_factory=_graph_factory,
        )

    first = build()
    review = first.review("w1")
    session = await review.sessions.create(
        workspace_id="w1", kind="review.round", title="Restart round"
    )
    round_id = "round-restart"
    execution = await review.executions.prepare(
        session, input={"roundId": round_id}
    )
    review.repository.create_round(
        workspace_id="w1",
        session_id=session.id,
        execution_id=execution.id,
        settings=ReviewRoundSettings(
            topics=(),
            difficulties=("medium",),
            mode="random-mixed",
            question_count=1,
            allow_follow_up=False,
            seed=1,
            answer_model_id="model-1",
            reasoning_effort="none",
        ),
        question_snapshots=(
            QuestionSnapshot(
                question_id="q1",
                document_id="doc-q1",
                content_hash="a" * 64,
                title="MVCC",
                question_text="Explain MVCC",
                reference_answer="Multi-version concurrency control",
                topics=("database",),
                difficulty="medium",
                key_points=("versions",),
                follow_ups=(),
            ),
        ),
        mastery_before=MasteryProjection("w1", 0, (), ()),
        round_id=round_id,
    )
    review.executions.run_prepared(
        execution, graph_input={"round_id": round_id}
    )
    await review.executions.wait(execution.id)
    before = await review.round_resource(round_id)
    assert before["execution_status"] == "waiting_for_input"
    request = before["current_input"]
    await first.close()

    second = build()
    try:
        assert await second.recover() == ()
        restored = await second.locate_review_round(round_id).round_resource(
            round_id
        )
        assert restored["current_input"]["id"] == request["id"]
        await second.locate_review_round(round_id).submit_answer(
            round_id,
            request_id=request["id"],
            version=request["version"],
            idempotency_key="restart-answer-01",
            value="multiple versions",
        )
        await second.wait_execution(restored["execution_id"])
        resumed = await second.locate_review_round(round_id).round_resource(
            round_id
        )
        assert resumed["attempts"][0]["answer"] == "multiple versions"
        assert resumed["execution_status"] == "waiting_for_approval"
    finally:
        await second.close()


@pytest.mark.parametrize(
    ("operation", "pre_paused", "expected_status", "expected_error_code"),
    (
        (None, False, "interrupted", "curation_interrupted"),
        ("pause", False, "paused", "curation_paused"),
        ("terminate", False, "terminated", "curation_terminated"),
        ("terminate", True, "terminated", "curation_terminated"),
    ),
)
@pytest.mark.asyncio
async def test_restart_reconciles_curation_control_intent_and_orphans(
    tmp_path: Path,
    operation: str | None,
    pre_paused: bool,
    expected_status: str,
    expected_error_code: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def build() -> AgentApplication:
        return AgentApplication(
            workspace_resolver=lambda _workspace_id: workspace,
            workspace_ids=lambda: ("w1",),
            model_bindings=lambda _workspace_id: {},
            graph_factory=_graph_factory,
        )

    first = build()
    review = first.review("w1")
    session = await review.sessions.create(
        workspace_id="w1", kind="question.curate", title="Interrupted batch"
    )
    review.repository.create_curation_session(
        workspace_id="w1",
        session_id=session.id,
        source_refs=("source-1",),
    )
    batch = review.repository.create_batch(
        workspace_id="w1",
        session_id=session.id,
        run_id=None,
        source_refs=("source-1",),
    )
    execution_input = {
        "batchId": batch.id,
        "batch_id": batch.id,
        "sourceRefs": ["source-1"],
        "source_refs": ["source-1"],
        "source_excerpts": ["source-1:restart.md\nQuestion?"],
        "similar_questions": [],
        "rewrite_feedback": None,
    }
    execution = await review.executions.prepare(
        session,
        input=execution_input,
        project_input_message=False,
    )
    batch = review.repository.attach_batch_run(batch.id, execution.id)
    review.repository.record_curation_attempt(
        batch.id, execution.id, reason="initial"
    )
    review.repository.update_curation_progress(
        session.id,
        stage="generating",
        completed_units=0,
        total_units=1,
        active_batch_id=batch.id,
    )
    item = review.repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="discovery",
        unit_index=0,
        input_digest="a" * 64,
        source_refs=("source-1#section-0001",),
    )
    review.repository.start_curation_work_item(item.id)
    if pre_paused:
        pause_receipt = review.repository.request_batch_control(
            batch.id,
            operation="pause",
            idempotency_key="pause-before-terminate-restart-0001",
            expected_version=batch.version,
        )
        batch = review.repository.finalize_batch_control(pause_receipt.id)
    if operation is not None:
        review.repository.request_batch_control(
            batch.id,
            operation=operation,
            idempotency_key=f"{operation}-before-restart-0001",
            expected_version=batch.version,
        )
    await first.close()

    second = build()
    try:
        await second.recover()
        restored_review = second.review("w1")
        restored = restored_review.repository.get_batch(batch.id)
        restored_item = restored_review.repository.get_curation_work_item(item.id)
        restored_session = restored_review.repository.get_curation_session(
            session.id
        )
        latest = restored_review.sessions.repository.latest_execution(session.id)

        assert restored.status == expected_status
        assert restored.control_intent is None
        assert restored_item.status == "interrupted"
        assert restored_item.last_error_code == expected_error_code
        assert restored_session.stage == expected_status
        assert latest is not None
        assert latest.status == "interrupted"
        assert restored.run_id == execution.id
        assert restored_review.sessions.repository.connection.execute(
            "SELECT COUNT(*) FROM agent_runs WHERE session_id = ? "
            "AND status IN ('queued', 'running')",
            (session.id,),
        ).fetchone()[0] == 0
        if operation is not None:
            receipt = restored_review.sessions.repository.connection.execute(
                "SELECT result_status FROM review_curation_control_receipts "
                "WHERE batch_id = ? AND operation = ?",
                (batch.id, operation),
            ).fetchone()
            assert receipt[0] == expected_status
    finally:
        await second.close()


@pytest.mark.parametrize(
    ("batch_status", "session_stage"),
    (
        ("paused", "paused"),
        ("failed", "failed"),
        ("interrupted", "interrupted"),
        ("terminated", "terminated"),
        ("review_pending", "waiting_for_command"),
        ("completed", "completed"),
    ),
)
@pytest.mark.asyncio
async def test_restart_interrupts_orphan_work_for_non_generating_batches(
    tmp_path: Path,
    batch_status: str,
    session_stage: str,
) -> None:
    workspace = tmp_path / "workspace-orphan-work"
    workspace.mkdir()
    source = await KnowledgeSourceService(
        workspace, workspace_id="w1"
    ).create(
        original_filename="orphan.md",
        content_type="text/markdown",
        content=b"# Orphan\n\nQuestion?",
    )

    def build() -> AgentApplication:
        return AgentApplication(
            workspace_resolver=lambda _workspace_id: workspace,
            workspace_ids=lambda: ("w1",),
            model_bindings=lambda _workspace_id: {},
            graph_factory=_graph_factory,
        )

    first = build()
    review = first.review("w1")
    session = await review.sessions.create(
        workspace_id="w1", kind="question.curate", title="Orphan work item"
    )
    review.repository.create_curation_session(
        workspace_id="w1", session_id=session.id, source_refs=(source.id,)
    )
    batch = review.repository.create_batch(
        workspace_id="w1",
        session_id=session.id,
        run_id=None,
        source_refs=(source.id,),
    )
    execution_input = {
        "batchId": batch.id,
        "batch_id": batch.id,
        "sourceRefs": [source.id],
        "source_refs": [source.id],
        "source_excerpts": [f"{source.id}:restart.md\nQuestion?"],
        "similar_questions": [],
        "rewrite_feedback": None,
    }
    execution = await review.executions.prepare(
        session, input=execution_input, project_input_message=False
    )
    batch = review.repository.attach_batch_run(batch.id, execution.id)
    review.repository.record_curation_attempt(
        batch.id, execution.id, reason="initial"
    )
    review.repository.update_curation_progress(
        session.id,
        stage="generating",
        completed_units=1,
        total_units=2,
        active_batch_id=batch.id,
    )
    completed_item = review.repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="discovery",
        unit_index=0,
        input_digest="b" * 64,
        source_refs=(f"{source.id}#section-0001",),
        processor_kind="deterministic",
    )
    completed_item = review.repository.complete_deterministic_curation_work_item(
        completed_item.id,
        output={
            "seeds": [
                {
                    "question_text": "What remains complete?",
                    "source_ref": f"{source.id}#section-0001",
                    "source_refs": [f"{source.id}#section-0001"],
                }
            ]
        },
    )
    running_item = review.repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="discovery",
        unit_index=1,
        input_digest="c" * 64,
        source_refs=(f"{source.id}#section-0002",),
    )
    review.repository.start_curation_work_item(running_item.id)
    connection = review.sessions.repository.connection
    connection.execute(
        "UPDATE review_question_batches SET status = ? WHERE id = ?",
        (batch_status, batch.id),
    )
    connection.execute(
        "UPDATE review_curation_sessions SET stage = ? WHERE session_id = ?",
        (session_stage, session.id),
    )
    connection.commit()
    await first.close()

    second = build()
    try:
        await second.recover()
        restored_review = second.review("w1")
        restored_batch = restored_review.repository.get_batch(batch.id)
        restored_running = restored_review.repository.get_curation_work_item(
            running_item.id
        )
        restored_completed = restored_review.repository.get_curation_work_item(
            completed_item.id
        )
        resource = await restored_review.curation_resource(session.id)

        assert restored_batch.status == batch_status
        assert restored_running.status == "interrupted"
        assert restored_running.last_error_code == f"curation_{batch_status}"
        assert restored_completed == completed_item
        assert resource["progress"]["active_workers"] == 0
    finally:
        await second.close()


@pytest.mark.asyncio
async def test_crash_pause_closes_execution_and_excludes_pause_gap_from_timing(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace-pause-timing"
    workspace.mkdir()
    source = await KnowledgeSourceService(
        workspace, workspace_id="w1"
    ).create(
        original_filename="timing.md",
        content_type="text/markdown",
        content=b"# Timing\n\nQuestion?",
    )

    def build() -> AgentApplication:
        return AgentApplication(
            workspace_resolver=lambda _workspace_id: workspace,
            workspace_ids=lambda: ("w1",),
            model_bindings=lambda _workspace_id: {},
            graph_factory=_graph_factory,
        )

    first = build()
    review = first.review("w1")
    session = await review.sessions.create(
        workspace_id="w1", kind="question.curate", title="Pause timing"
    )
    review.repository.create_curation_session(
        workspace_id="w1", session_id=session.id, source_refs=(source.id,)
    )
    batch = review.repository.create_batch(
        workspace_id="w1",
        session_id=session.id,
        run_id=None,
        source_refs=(source.id,),
    )
    execution_input = {
        "batchId": batch.id,
        "batch_id": batch.id,
        "sourceRefs": [source.id],
        "source_refs": [source.id],
        "source_excerpts": [f"{source.id}:timing.md\nQuestion?"],
        "similar_questions": [],
        "rewrite_feedback": None,
    }
    execution = await review.executions.prepare(
        session, input=execution_input, project_input_message=False
    )
    batch = review.repository.attach_batch_run(batch.id, execution.id)
    review.repository.record_curation_attempt(
        batch.id, execution.id, reason="initial"
    )
    review.repository.update_curation_progress(
        session.id,
        stage="generating",
        completed_units=0,
        total_units=1,
        active_batch_id=batch.id,
    )
    connection = review.sessions.repository.connection
    connection.execute(
        "UPDATE agent_runs SET started_at = datetime('now', '-10 seconds') "
        "WHERE id = ?",
        (execution.id,),
    )
    connection.commit()
    review.repository.request_batch_control(
        batch.id,
        operation="pause",
        idempotency_key="pause-before-timing-restart-0001",
        expected_version=batch.version,
    )
    await first.close()

    second = build()
    try:
        await second.recover()
        restored_review = second.review("w1")
        interrupted = restored_review.sessions.repository.get_execution(execution.id)
        assert interrupted.status == "interrupted"
        assert interrupted.finished_at is not None
        frozen = restored_review.repository.curation_batch_timing(batch.id)
        await asyncio.sleep(0.02)
        assert restored_review.repository.curation_batch_timing(batch.id) == frozen

        monkeypatch.setattr(
            restored_review.executions,
            "run_prepared",
            lambda prepared, *, graph_input: None,
        )
        paused_batch = restored_review.repository.get_batch(batch.id)
        resumed = await restored_review.resume_curation_session(
            session.id,
            expected_batch_version=paused_batch.version,
            idempotency_key="resume-after-timing-restart-0001",
        )
        resumed_execution_id = resumed["execution_id"]
        assert resumed_execution_id != execution.id
        connection = restored_review.sessions.repository.connection
        connection.execute(
            "UPDATE agent_runs SET status = 'completed', "
            "started_at = datetime(?, '+1 hour'), "
            "finished_at = datetime(?, '+1 hour', '+2 seconds') WHERE id = ?",
            (
                interrupted.finished_at,
                interrupted.finished_at,
                resumed_execution_id,
            ),
        )
        connection.commit()

        resumed_timing = restored_review.repository.curation_batch_timing(batch.id)
        assert resumed_timing.current_elapsed_ms == 2_000
        assert resumed_timing.cumulative_elapsed_ms == (
            frozen.cumulative_elapsed_ms + 2_000
        )
    finally:
        await second.close()


@pytest.mark.parametrize("crash_window", ("reservation_to_prepare", "prepare_to_bind"))
@pytest.mark.asyncio
async def test_resume_fault_window_replays_one_reserved_execution(
    tmp_path: Path, monkeypatch, crash_window: str
) -> None:
    workspace = tmp_path / f"workspace-resume-{crash_window}"
    workspace.mkdir()
    source = await KnowledgeSourceService(
        workspace, workspace_id="w1"
    ).create(
        original_filename="resume.md",
        content_type="text/markdown",
        content=b"# Resume\n\nQuestion?",
    )

    def build() -> AgentApplication:
        return AgentApplication(
            workspace_resolver=lambda _workspace_id: workspace,
            workspace_ids=lambda: ("w1",),
            model_bindings=lambda _workspace_id: {},
            graph_factory=_graph_factory,
        )

    first = build()
    review = first.review("w1")
    session = await review.sessions.create(
        workspace_id="w1", kind="question.curate", title="Reserved resume"
    )
    review.repository.create_curation_session(
        workspace_id="w1", session_id=session.id, source_refs=(source.id,)
    )
    batch = review.repository.create_batch(
        workspace_id="w1",
        session_id=session.id,
        run_id=None,
        source_refs=(source.id,),
    )
    execution_input = {
        "batchId": batch.id,
        "batch_id": batch.id,
        "sourceRefs": [source.id],
        "source_refs": [source.id],
        "source_excerpts": [f"{source.id}:resume.md\nQuestion?"],
        "similar_questions": [],
        "rewrite_feedback": None,
    }
    initial_execution = await review.executions.prepare(
        session, input=execution_input, project_input_message=False
    )
    batch = review.repository.attach_batch_run(batch.id, initial_execution.id)
    review.repository.record_curation_attempt(
        batch.id, initial_execution.id, reason="initial"
    )
    review.repository.update_curation_progress(
        session.id,
        stage="generating",
        completed_units=0,
        total_units=1,
        active_batch_id=batch.id,
    )
    paused = await review.pause_curation_session(
        session.id,
        expected_batch_version=batch.version,
        idempotency_key=f"pause-before-{crash_window}-0001",
    )
    resume_key = f"resume-after-{crash_window}-0001"

    class InjectedCrash(BaseException):
        pass

    if crash_window == "reservation_to_prepare":
        async def crash_before_prepare(*_args, **_kwargs):
            raise InjectedCrash()

        monkeypatch.setattr(review.executions, "prepare", crash_before_prepare)
    else:
        def crash_before_bind(*_args, **_kwargs):
            raise InjectedCrash()

        monkeypatch.setattr(
            review.repository, "resume_curation_batch", crash_before_bind
        )

    with pytest.raises(InjectedCrash):
        await review.resume_curation_session(
            session.id,
            expected_batch_version=paused["batch_version"],
            idempotency_key=resume_key,
        )
    preparing = review.repository.find_curation_control_receipt(
        batch.id, resume_key
    )
    assert preparing is not None
    assert preparing.result_status == "preparing"
    assert preparing.execution_id is None
    assert preparing.reserved_execution_id is not None
    reserved_execution_id = preparing.reserved_execution_id
    pre_crash_rows = review.sessions.repository.connection.execute(
        "SELECT id FROM agent_runs WHERE id = ?", (reserved_execution_id,)
    ).fetchall()
    assert len(pre_crash_rows) == (
        0 if crash_window == "reservation_to_prepare" else 1
    )
    await first.close()

    second = build()
    try:
        await second.recover()
        restored_review = second.review("w1")
        scheduled: list[str] = []
        monkeypatch.setattr(
            restored_review.executions,
            "run_prepared",
            lambda prepared, *, graph_input: scheduled.append(prepared.id),
        )
        resumed = await restored_review.resume_curation_session(
            session.id,
            expected_batch_version=paused["batch_version"],
            idempotency_key=resume_key,
        )
        replayed = await restored_review.resume_curation_session(
            session.id,
            expected_batch_version=paused["batch_version"],
            idempotency_key=resume_key,
        )

        assert resumed["execution_id"] == reserved_execution_id
        assert replayed["execution_id"] == reserved_execution_id
        assert scheduled == [reserved_execution_id]
        executions = restored_review.sessions.repository.list_executions(session.id)
        assert [run.id for run in executions] == [
            initial_execution.id,
            reserved_execution_id,
        ]
        reserved_execution = restored_review.sessions.repository.get_execution(
            reserved_execution_id
        )
        assert reserved_execution.status == "running"
        assert reserved_execution.finished_at is None
        attempts = restored_review.sessions.repository.connection.execute(
            "SELECT execution_id FROM review_curation_batch_attempts "
            "WHERE batch_id = ? ORDER BY ordinal",
            (batch.id,),
        ).fetchall()
        assert [row[0] for row in attempts] == [
            initial_execution.id,
            reserved_execution_id,
        ]
        receipt = restored_review.repository.find_curation_control_receipt(
            batch.id, resume_key
        )
        assert receipt is not None
        assert receipt.reserved_execution_id == reserved_execution_id
        assert receipt.execution_id == reserved_execution_id
        assert receipt.result_status == "generating"
    finally:
        await second.close()


@pytest.mark.asyncio
async def test_interrupted_curation_command_requires_explicit_retry(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace-command-retry"
    workspace.mkdir()

    def build() -> AgentApplication:
        return AgentApplication(
            workspace_resolver=lambda _workspace_id: workspace,
            workspace_ids=lambda: ("w1",),
            model_bindings=lambda _workspace_id: {},
            graph_factory=_graph_factory,
        )

    source = await KnowledgeSourceService(
        workspace, workspace_id="w1"
    ).create(
        original_filename="retry.md",
        content_type="text/markdown",
        content=b"# Retry\n\nExplain durable retries.",
    )
    first = build()
    created = await first.review("w1").create_curation_session(
        source_refs=(source.id,)
    )
    await first.wait_execution(created["execution_id"])
    session_id = created["id"]
    detail = await first.locate_review_session(session_id).curation_resource(
        session_id
    )
    entered = asyncio.Event()
    review = first.locate_review_session(session_id)
    review.curation_command_agents = _command_agents(
        _BlockingClassifier(entered)
    )
    accepted = await review.submit_curation_command(
        session_id,
        text="把这一批按之前方式处理一下",
        summary_version=detail["summary_version"],
        idempotency_key="restart-command-1",
        provider_model_id=None,
        reasoning_effort="none",
    )
    await asyncio.wait_for(entered.wait(), timeout=0.2)
    await first.close()

    second = build()
    try:
        restored_review = second.locate_curation_command(
            accepted["command_id"]
        )
        interrupted = restored_review.repository.get_curation_command_receipt(
            accepted["command_id"]
        )
        assert interrupted.lifecycle_status == "interrupted"
        assert interrupted.retry_count == 0
        assert second.replay_events(session_id, after_id=None)[-1].type != (
            "execution.completed"
        )

        restored_review.curation_command_agents = _command_agents(
            _ResolvedClassifier()
        )
        retried = await restored_review.retry_curation_command(
            accepted["command_id"]
        )
        assert retried["execution_id"] != accepted["execution_id"]
        await second.wait_execution(retried["execution_id"])
        completed = restored_review.repository.get_curation_command_receipt(
            accepted["command_id"]
        )
        messages = (await second.session_detail(session_id))["messages"]

        assert completed.lifecycle_status == "completed"
        assert completed.retry_count == 1
        assert sum(
            message["content"] == "把这一批按之前方式处理一下"
            for message in messages
        ) == 1
    finally:
        await second.close()


@pytest.mark.asyncio
async def test_restart_resumes_answer_accepted_before_graph_spawn(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace-accepted"
    workspace.mkdir()

    def build() -> AgentApplication:
        return AgentApplication(
            workspace_resolver=lambda _workspace_id: workspace,
            workspace_ids=lambda: ("w1",),
            model_bindings=lambda _workspace_id: {},
            graph_factory=_graph_factory,
        )

    first = build()
    review = first.review("w1")
    session = await review.sessions.create(
        workspace_id="w1", kind="review.round", title="Accepted answer"
    )
    execution = await review.executions.prepare(
        session, input={"roundId": "round-accepted"}
    )
    review.repository.create_round(
        workspace_id="w1",
        session_id=session.id,
        execution_id=execution.id,
        settings=ReviewRoundSettings(
            topics=(), difficulties=("medium",), mode="random-mixed",
            question_count=1, allow_follow_up=False, seed=1,
            answer_model_id="model-1", reasoning_effort="none",
        ),
        question_snapshots=(QuestionSnapshot(
            question_id="q-accepted", document_id="doc-accepted",
            content_hash="c" * 64, title="Accepted",
            question_text="Explain durable acceptance",
            reference_answer="Commit before model work",
            topics=("runtime",), difficulty="medium",
            key_points=("transaction",), follow_ups=(),
        ),),
        mastery_before=MasteryProjection("w1", 0, (), ()),
        round_id="round-accepted",
    )
    review.executions.run_prepared(
        execution, graph_input={"round_id": "round-accepted"}
    )
    await review.executions.wait(execution.id)
    request = (await review.round_resource("round-accepted"))["current_input"]
    receipt = review.repository.accept_review_answer(
        request_id=request["id"], expected_version=request["version"],
        idempotency_key="accepted-before-spawn", value="transaction first",
    )
    assert receipt.status == "evaluating"
    await first.close()

    second = build()
    try:
        await second.recover()
        await second.wait_execution(execution.id)
        restored = await second.locate_review_round(
            "round-accepted"
        ).round_resource("round-accepted")
        assert restored["attempts"][0]["status"] == "completed"
        assert restored["attempts"][0]["answer"] == "transaction first"
        assert sum(
            message["content"] == "transaction first"
            for message in restored["messages"]
        ) == 1
    finally:
        await second.close()

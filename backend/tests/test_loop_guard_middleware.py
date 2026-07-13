import pytest

from app.db.runtime_database import connect_runtime_database
from app.runtime.middleware.loop_guard import LoopGuardMiddleware
from app.runtime.middleware.repository import RuntimeMiddlewareRepository
from app.runtime.middleware.session_title import SessionTitleMiddleware, normalize_title
from app.runtime.middleware.types import MiddlewareConfig, MiddlewareContext, ModelInvocation, RuntimeGuardError
from app.runtime.repository import RuntimeRepository


def setup(tmp_path):
    connection = connect_runtime_database(tmp_path)
    runtime = RuntimeRepository(connection)
    session = runtime.create_session(workspace_id="w1", graph_id="test", graph_version=1, title="新会话")
    run = runtime.create_run(session.id, input={}, model_bindings={})
    return connection, runtime, MiddlewareContext("w1", session.id, run.id, "test", 1)


@pytest.mark.asyncio
async def test_repeat_guard_warns_then_fails_after_reopen(tmp_path):
    connection, _, context = setup(tmp_path)
    config = MiddlewareConfig(repeat_soft_limit=2, repeat_hard_limit=3)
    warnings: list[str] = []
    guard = LoopGuardMiddleware(RuntimeMiddlewareRepository(connection), config, publish_warning=warnings.append)
    invocation = ModelInvocation("op1", "answer", "p1", "m1", ())

    async def call_next(value):
        return "ok"

    await guard.wrap_model(context, invocation, call_next)
    await guard.wrap_model(context, invocation, call_next)
    assert warnings == ["loop_detected"]
    connection.close()

    reopened = connect_runtime_database(tmp_path)
    guard = LoopGuardMiddleware(RuntimeMiddlewareRepository(reopened), config)
    with pytest.raises(RuntimeGuardError) as caught:
        await guard.wrap_model(context, invocation, call_next)
    assert caught.value.code == "loop_detected"


@pytest.mark.asyncio
async def test_title_is_generated_once_and_never_overwrites_user_title(tmp_path):
    _, runtime, context = setup(tmp_path)
    runtime.append_message(context.session_id, run_id=context.run_id, role="user", content="缓存穿透是什么")
    assistant = runtime.append_message(context.session_id, run_id=context.run_id, role="assistant", content="缓存穿透是查询不存在的数据")
    calls = 0

    async def generate(messages):
        nonlocal calls
        calls += 1
        return "  '缓存穿透\n复习'  "

    middleware = SessionTitleMiddleware(runtime, generate)
    await middleware.after_message(context, assistant)
    await middleware.after_message(context, assistant)
    assert runtime.get_session(context.session_id).title == "缓存穿透 复习"
    assert calls == 1
    assert normalize_title("x" * 80) == "x" * 40

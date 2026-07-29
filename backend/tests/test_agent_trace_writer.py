import json
import os
import stat
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from threading import Thread

import pytest
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app.diagnostics.agent_trace import (
    AgentTraceWriter,
    TraceIdentity,
    initialize_agent_trace_directory,
    read_trace_rows,
    safe_trace_value,
)
from app.security.workspace_paths import PathPolicyError


def identity(root: Path, *, agent_name: str = "question_discovery") -> TraceIdentity:
    return TraceIdentity(
        workspace_id="w1",
        workspace_root=root,
        session_id="s1",
        run_id="r1",
        agent_role="question_generation",
        agent_name=agent_name,
        invocation_id="inv-1",
    )


def test_writer_appends_parseable_ordered_events_and_resumes_sequence(tmp_path: Path) -> None:
    initialize_agent_trace_directory(tmp_path)
    assert AgentTraceWriter().append(identity(tmp_path), "model.request", {"text": "完整原文"})
    assert AgentTraceWriter().append(identity(tmp_path), "model.response", {"text": "完整回答"}, terminal=True)
    rows = read_trace_rows(tmp_path, "s1", "r1")
    assert [row["sequence"] for row in rows] == [1, 2]
    assert rows[0]["payload"]["text"] == "完整原文"
    assert rows[1]["payload"]["text"] == "完整回答"
    assert all(row["schema_version"] == 3 for row in rows)
    assert all(row["operation_kind"] == "model" for row in rows)
    assert rows[0]["operation_id"] == rows[1]["operation_id"]
    assert rows[0]["parent_operation_id"] == rows[1]["parent_operation_id"]
    assert all("+00:00" in row["timestamp"] for row in rows)


def test_writer_records_utc_and_beijing_time_for_the_same_instant(tmp_path: Path) -> None:
    AgentTraceWriter().append(identity(tmp_path), "model.request", {})
    row = read_trace_rows(tmp_path, "s1", "r1")[0]
    assert row["schema_version"] == 3
    assert row["timezone"] == "Asia/Shanghai"
    utc = datetime.fromisoformat(row["timestamp"])
    local = datetime.fromisoformat(row["local_timestamp"])
    assert utc.utcoffset().total_seconds() == 0
    assert local.utcoffset().total_seconds() == 8 * 60 * 60
    assert utc.timestamp() == local.timestamp()


def test_writer_reads_handwritten_v1_before_appending_v3(tmp_path: Path) -> None:
    initialize_agent_trace_directory(tmp_path)
    trace_file = tmp_path / ".cyber-interview-agent/agent-traces/s1/r1.jsonl"
    trace_file.parent.mkdir()
    trace_file.write_text(
        json.dumps({"schema_version": 1, "sequence": 1, "event_type": "model.request"}) + "\n",
        encoding="utf-8",
    )

    assert AgentTraceWriter().append(identity(tmp_path), "model.response", {})

    rows = read_trace_rows(tmp_path, "s1", "r1")
    assert [row["schema_version"] for row in rows] == [1, 3]
    assert [row["sequence"] for row in rows] == [1, 2]


def test_writer_concurrent_appends_are_monotonic_and_file_modes_are_private(tmp_path: Path) -> None:
    initialize_agent_trace_directory(tmp_path)
    writer = AgentTraceWriter()
    threads = [
        Thread(target=lambda: writer.append(identity(tmp_path), "model.request", {"index": index}))
        for index in range(12)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    rows = read_trace_rows(tmp_path, "s1", "r1")
    assert [row["sequence"] for row in rows] == list(range(1, 13))
    trace_root = tmp_path / ".cyber-interview-agent" / "agent-traces"
    assert stat.S_IMODE(trace_root.stat().st_mode) == 0o700
    assert stat.S_IMODE((trace_root / "s1").stat().st_mode) == 0o700
    assert stat.S_IMODE((trace_root / "s1" / "r1.jsonl").stat().st_mode) == 0o600


def test_safe_serializer_never_uses_unknown_repr_or_credentials() -> None:
    class SecretObject:
        def __repr__(self) -> str:
            return "Bearer leaked-token"

    class ExampleModel(BaseModel):
        answer: str

    value = safe_trace_value({
        "content": "Bearer is legitimate interview text",
        "authorization": "Bearer leaked-token",
        "api_key": "sk-leaked",
        "opaque": SecretObject(),
        "model": ExampleModel(answer="safe"),
        "message": HumanMessage(content="完整消息"),
    })
    encoded = json.dumps(value, ensure_ascii=False)
    assert "legitimate interview text" in encoded
    assert "leaked-token" not in encoded
    assert "sk-leaked" not in encoded
    assert "client" not in value
    assert value["opaque"] == {"type": "SecretObject", "unserializable": True}
    assert value["model"] == {"answer": "safe"}
    assert value["message"]["content"] == "完整消息"


def test_safe_serializer_records_model_response_and_structured_output() -> None:
    class StructuredOutput(BaseModel):
        answer: str

    value = safe_trace_value(
        ModelResponse(
            result=[AIMessage(content="完整模型回答")],
            structured_response=StructuredOutput(answer="结构化结果"),
        )
    )

    assert value["result"][0]["content"] == "完整模型回答"
    assert value["structured_response"] == {"answer": "结构化结果"}


def test_trace_path_rejects_symlink_and_invalid_identifier(tmp_path: Path) -> None:
    initialize_agent_trace_directory(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    trace_root = tmp_path / ".cyber-interview-agent" / "agent-traces"
    (trace_root / "s1").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathPolicyError):
        AgentTraceWriter().append(identity(tmp_path), "model.request", {})
    with pytest.raises(PathPolicyError):
        AgentTraceWriter().append(replace(identity(tmp_path), session_id="../escape"), "model.request", {})


def test_writer_ignores_unterminated_crash_fragment_when_resuming(tmp_path: Path) -> None:
    initialize_agent_trace_directory(tmp_path)
    trace_file = tmp_path / ".cyber-interview-agent/agent-traces/s1/r1.jsonl"
    trace_file.parent.mkdir()
    trace_file.write_bytes(b'{"sequence": 41}\n{"sequence": 99}')
    assert AgentTraceWriter().append(identity(tmp_path), "model.request", {})
    assert read_trace_rows(tmp_path, "s1", "r1")[-1]["sequence"] == 42


def test_writer_is_fail_open_for_append_os_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    initialize_agent_trace_directory(tmp_path)
    monkeypatch.setattr(os, "open", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    assert not AgentTraceWriter().append(identity(tmp_path), "model.request", {})

import pytest

from cyber_interview.harness.fake_model import FakeModelGateway
from cyber_interview.harness.model_gateway import Message, ModelChunk
from cyber_interview.harness.runtime import AgentRuntime, LoopAgentRuntime, RuntimeOutput


@pytest.mark.asyncio
async def test_loop_yields_deltas_then_final_result():
    import json

    payload = json.dumps(
        {
            "schema_name": "profile",
            "schema_version": 1,
            "facts": [{"claim": "x", "evidence_ref": None}],
        }
    )
    gw = FakeModelGateway(
        chunks=[
            ModelChunk(type="delta", text=payload[:10]),
            ModelChunk(type="delta", text=payload[10:]),
            ModelChunk(type="done", finish_reason="stop"),
        ]
    )
    runtime: AgentRuntime = LoopAgentRuntime(model_gateway=gw)
    outputs = []
    async for out in runtime.run(_ctx()):
        outputs.append(out)
    deltas = [o for o in outputs if isinstance(o, RuntimeOutput.Delta)]
    finals = [o for o in outputs if isinstance(o, RuntimeOutput.Final)]
    assert len(deltas) == 2
    assert len(finals) == 1
    assert isinstance(outputs[-1], RuntimeOutput.Final)
    assert finals[0].result.profile is not None


@pytest.mark.asyncio
async def test_loop_always_emits_exactly_one_final():
    import json

    payload = json.dumps(
        {
            "schema_name": "profile",
            "schema_version": 1,
            "facts": [{"claim": "x", "evidence_ref": None}],
        }
    )
    gw = FakeModelGateway(
        chunks=[
            ModelChunk(type="delta", text=payload),
            ModelChunk(type="done", finish_reason="stop"),
        ]
    )
    runtime = LoopAgentRuntime(model_gateway=gw)
    outputs = [o async for o in runtime.run(_ctx())]
    finals = [o for o in outputs if isinstance(o, RuntimeOutput.Final)]
    assert len(finals) == 1
    assert isinstance(outputs[-1], RuntimeOutput.Final)


def _ctx():
    from dataclasses import dataclass

    @dataclass
    class Ctx:
        run_id: str = "r1"
        attempt_id: str = "a1"
        provider: str = "openai"
        model: str = "m"
        messages: list | None = None

    return Ctx(messages=[Message(role="user", content="hi")])

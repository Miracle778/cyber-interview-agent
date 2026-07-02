import pytest

from cyber_interview.harness.model_gateway import Message, ModelChunk, ModelGateway


def test_model_chunk_delta():
    c = ModelChunk(type="delta", text="hello")
    assert c.type == "delta" and c.text == "hello"


def test_model_chunk_done_with_usage():
    c = ModelChunk(type="done", finish_reason="stop", usage={"in": 10, "out": 5})
    assert c.finish_reason == "stop"


@pytest.mark.asyncio
async def test_protocol_satisfied_by_fake():
    from cyber_interview.harness.fake_model import FakeModelGateway

    gw: ModelGateway = FakeModelGateway(
        chunks=[ModelChunk(type="delta", text="x"), ModelChunk(type="done", finish_reason="stop")]
    )
    out = []
    async for chunk in gw.stream(
        provider="openai", model="m", messages=[Message(role="user", content="hi")]
    ):
        out.append(chunk)
    assert len(out) == 2 and out[-1].type == "done"

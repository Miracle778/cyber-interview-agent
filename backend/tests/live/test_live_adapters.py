import os

import pytest

from cyber_interview.config import ProviderConfig
from cyber_interview.harness.model_adapters import AnthropicAdapter, OpenAIAdapter
from cyber_interview.harness.model_gateway import Message

pytestmark = pytest.mark.live


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="no OPENAI_API_KEY")
async def test_openai_streams_then_done():
    config = ProviderConfig(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ.get("OPENAI_BASE_URL"),
    )
    adapter = OpenAIAdapter(config=config, model="gpt-4o-mini")
    chunks = []
    async for chunk in adapter.stream(
        "openai",
        "gpt-4o-mini",
        [Message(role="user", content='输出 {"facts":[]}')],
    ):
        chunks.append(chunk)
    assert chunks and chunks[-1].type == "done"


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="no ANTHROPIC_API_KEY")
async def test_anthropic_streams_then_done():
    config = ProviderConfig(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
    )
    adapter = AnthropicAdapter(config=config, model="claude-3-5-haiku-latest")
    chunks = []
    async for chunk in adapter.stream(
        "anthropic",
        "claude-3-5-haiku-latest",
        [Message(role="user", content='输出 {"facts":[]}')],
    ):
        chunks.append(chunk)
    assert chunks and chunks[-1].type == "done"

import pytest
from httpx import ASGITransport, AsyncClient

from cyber_interview.main import create_app


@pytest.fixture
async def client():
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client

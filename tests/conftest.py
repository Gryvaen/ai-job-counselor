import pytest
import httpx


@pytest.fixture
async def client():
    from api.server import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

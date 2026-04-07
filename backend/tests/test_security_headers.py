import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_response_includes_security_headers(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

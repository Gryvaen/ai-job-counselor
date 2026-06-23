import pytest


@pytest.mark.anyio
async def test_health_ok(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "llm" in data["checks"]


@pytest.mark.anyio
async def test_api_token_required(monkeypatch):
    monkeypatch.setattr("config.settings.settings.webui_api_token", "secret-token")
    from api.server import ApiTokenMiddleware, app
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    middleware = ApiTokenMiddleware(app)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def ok_response(_request):
        return JSONResponse({"ok": True})

    denied = await middleware.dispatch(
        Request({"type": "http", "method": "POST", "path": "/api/consult", "headers": []}, receive),
        ok_response,
    )
    assert denied.status_code == 401

    allowed = await middleware.dispatch(
        Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/consult",
                "headers": [(b"authorization", b"Bearer secret-token")],
            },
            receive,
        ),
        ok_response,
    )
    assert allowed.status_code == 200

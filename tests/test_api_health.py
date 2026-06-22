import pytest
import httpx

from storage.db import get_engine


@pytest.fixture
async def client(tmp_db_path):
    get_engine(tmp_db_path)
    from api.server import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.anyio
async def test_health_ok(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["checks"]["database"]["ok"] is True


@pytest.mark.anyio
async def test_health_auth_not_required(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_config_masks_secrets(tmp_db_path, monkeypatch):
    get_engine(tmp_db_path)
    from api.server import _settings_to_config

    monkeypatch.setattr("config.settings.settings.openai_api_key", "sk-testsecret1234")
    body = _settings_to_config().model_dump()
    assert "sk-***" in body["openai_api_key"]
    assert body["openai_api_key"].endswith("1234")


@pytest.mark.anyio
async def test_knowledge_status(tmp_db_path):
    get_engine(tmp_db_path)
    from api.server import knowledge_status

    assert "indexed_sources" in knowledge_status()


@pytest.mark.anyio
async def test_api_token_required(tmp_db_path, monkeypatch):
    monkeypatch.setattr("config.settings.settings.webui_api_token", "secret-token")
    get_engine(tmp_db_path)
    from api.server import ApiTokenMiddleware, app
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    middleware = ApiTokenMiddleware(app)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def ok_response(_request):
        return JSONResponse({"ok": True})

    denied = await middleware.dispatch(
        Request({"type": "http", "method": "GET", "path": "/api/dashboard", "headers": []}, receive),
        ok_response,
    )
    assert denied.status_code == 401

    allowed = await middleware.dispatch(
        Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/dashboard",
                "headers": [(b"authorization", b"Bearer secret-token")],
            },
            receive,
        ),
        ok_response,
    )
    assert allowed.status_code == 200


@pytest.mark.anyio
async def test_interview_next_returns_agent_rubric(monkeypatch):
    from api.server import InterviewRequest, _build_interview_turn

    monkeypatch.setattr("api.server.llm_chat", lambda *_args, **_kwargs: "")
    data = _build_interview_turn(
        InterviewRequest(
            target_role="AI Agent 工程师",
            skills="Python, FastAPI, LangGraph, RAG, Docker",
            projects="AI 面试机器人：使用 FastAPI 和 LangGraph 编排多轮面试，结合 RAG 检索项目证据。",
            answer="",
            history=[],
        )
    )
    assert data.stage == "项目真实性"
    assert data.rubric
    assert data.answer_shape
    assert any(item["name"] == "Agent 编排" and item["covered"] for item in data.coverage)
    assert any(item["name"] == "RAG" and item["covered"] for item in data.coverage)

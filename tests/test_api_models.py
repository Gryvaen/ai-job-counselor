import pytest


@pytest.mark.anyio
async def test_models_endpoint(client, monkeypatch):
    monkeypatch.setattr(
        "config.llm.list_ollama_models",
        lambda: [{"name": "qwen2.5-coder:1.5b", "size": 986_000_000}],
    )
    monkeypatch.setattr("config.settings.settings.ollama_model", "qwen2.5-coder:7b")

    resp = await client.get("/api/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["default"] == "qwen2.5-coder:7b"
    assert data["default_available"] is False
    assert data["models"][0]["name"] == "qwen2.5-coder:1.5b"


@pytest.mark.anyio
async def test_consult_accepts_model_override(client, monkeypatch):
    monkeypatch.setattr("config.llm.is_llm_available", lambda: False)
    captured: list[str | None] = []

    def fake_use_model(model):
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            captured.append(model)
            yield

        return _ctx()

    monkeypatch.setattr("api.routes.consult.use_model", fake_use_model)

    resp = await client.post(
        "/api/consult",
        json={
            "user_query": "我想找 AI Agent 实习",
            "resume_text": "Python",
            "model": "qwen2.5-coder:1.5b",
        },
    )
    assert resp.status_code == 200
    assert captured == ["qwen2.5-coder:1.5b"]

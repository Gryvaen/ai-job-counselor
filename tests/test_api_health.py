import pytest
from fastapi.testclient import TestClient

from storage.db import get_engine


@pytest.fixture
def client(tmp_db_path):
    get_engine(tmp_db_path)
    from api.server import app
    return TestClient(app)


def test_health_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["checks"]["database"]["ok"] is True


def test_health_auth_not_required(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200


def test_config_masks_secrets(client, monkeypatch):
    monkeypatch.setattr("config.settings.settings.openai_api_key", "sk-testsecret1234")
    monkeypatch.setattr("config.settings.settings.feishu_webhook", "https://hook.example/abcdef12")
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert "sk-***" in body["openai_api_key"]
    assert body["openai_api_key"].endswith("1234")
    assert body["feishu_webhook"].startswith("*")


def test_knowledge_status(client):
    resp = client.get("/api/knowledge/status")
    assert resp.status_code == 200
    assert "indexed_sources" in resp.json()


def test_api_token_required(tmp_db_path, monkeypatch):
    monkeypatch.setattr("config.settings.settings.webui_api_token", "secret-token")
    get_engine(tmp_db_path)
    from api.server import app
    client = TestClient(app)
    denied = client.get("/api/dashboard")
    assert denied.status_code == 401
    allowed = client.get("/api/dashboard", headers={"Authorization": "Bearer secret-token"})
    assert allowed.status_code == 200

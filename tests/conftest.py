import pytest

import storage.db as db_module


@pytest.fixture
def reset_db_engine():
    db_module._engine = None
    db_module._engine_path = None
    db_module._session_factory = None
    yield
    db_module._engine = None
    db_module._engine_path = None
    db_module._session_factory = None


@pytest.fixture
def tmp_db_path(tmp_path, reset_db_engine, monkeypatch):
    db_path = tmp_path / "jobmatch.db"
    chroma_dir = tmp_path / "chroma"
    knowledge_dir = tmp_path / "knowledge"
    resume_versions_dir = tmp_path / "resume_versions"
    knowledge_dir.mkdir()
    monkeypatch.setattr("config.settings.settings.db_path", db_path)
    monkeypatch.setattr("config.settings.settings.chroma_dir", chroma_dir)
    monkeypatch.setattr("config.settings.settings.knowledge_dir", knowledge_dir)
    monkeypatch.setattr("config.settings.settings.resume_versions_dir", resume_versions_dir)
    monkeypatch.setattr("config.settings.settings.webui_api_token", "")
    return db_path

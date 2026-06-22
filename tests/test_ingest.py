from unittest.mock import MagicMock, patch

import pytest

from storage.db import get_engine, latest_knowledge_ingest, record_knowledge_ingest


def test_ingest_directory_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.settings.knowledge_dir", tmp_path)
    from rag.ingest import ingest_directory

    assert ingest_directory(tmp_path) == 0


def test_ingest_file_counts_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.settings.knowledge_dir", tmp_path)
    sample = tmp_path / "notes"
    sample.mkdir()
    (sample / "demo.md").write_text("# Demo\nLinux driver project with I2C and GPIO.", encoding="utf-8")

    mock_retriever = MagicMock()
    with patch("rag.ingest.RAGRetriever", return_value=mock_retriever):
        from rag.ingest import ingest_file
        chunks = ingest_file(sample / "demo.md", retriever=mock_retriever)
    assert chunks > 0
    mock_retriever.ingest.assert_called_once()


def test_record_knowledge_ingest(tmp_db_path):
    get_engine(tmp_db_path)
    record_knowledge_ingest(12, str(tmp_db_path))
    latest = latest_knowledge_ingest()
    assert latest is not None
    assert latest["chunks"] == 12

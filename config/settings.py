"""
Unified configuration via Pydantic Settings.
Reads from environment variables first, falls back to defaults.
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

# Project root for relative path defaults
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # Provider
    model_provider: str = "openai"  # openai / ollama / deepseek-compatible

    # LLM
    openai_api_key: str = ""
    openai_base_url: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    # Ollama OpenAI-compatible API
    ollama_base_url: str = "http://127.0.0.1:11434/v1"
    ollama_model: str = "qwen2.5:7b"
    ollama_embedding_model: str = "nomic-embed-text"

    # File paths
    resume_path: Path = PROJECT_ROOT / "data" / "resume.json"
    knowledge_dir: Path = PROJECT_ROOT / "data" / "knowledge"
    resume_versions_dir: Path = PROJECT_ROOT / "data" / "resume_versions"
    db_path: Path = PROJECT_ROOT / "data" / "jobmatch.db"
    chroma_dir: Path = PROJECT_ROOT / "storage" / "vector_store"

    # RAG
    rag_chunk_size: int = 512       #切片大小
    rag_chunk_overlap: int = 64     #切片重叠量
    rag_top_k: int = 5              #检索数目

    # Matching
    match_threshold: int = 75       #匹配分数阈值

    # Web console security (optional; required when binding 0.0.0.0)
    webui_api_token: str = ""

    # Ops
    log_level: str = "INFO"
    sentry_dsn: str = ""

    model_config = {"env_file": ".env", "env_prefix": "", "extra": "ignore"}


settings = Settings()

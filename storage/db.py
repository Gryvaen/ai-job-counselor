"""
SQLite persistence for JobMatch Agent.
SQLAlchemy models + helper functions for jobs, matches, resume versions, notifications.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text, create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

Base = declarative_base()


class JobRecord(Base):
    __tablename__ = "jobs"

    id = Column(String(32), primary_key=True)
    title = Column(String(256), nullable=False)
    company = Column(String(256), nullable=False)
    salary = Column(String(64))
    city = Column(String(64))
    description = Column(Text)
    url = Column(String(512))
    scraped_at = Column(DateTime, default=datetime.now)

    def __repr__(self):
        return f"<JobRecord {self.company} - {self.title}>"


class MatchRecord(Base):
    __tablename__ = "match_results"
    __table_args__ = (Index("ix_match_results_job_id", "job_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(32), nullable=False)
    score = Column(Integer)
    advantages = Column(Text)  # JSON list
    missing = Column(Text)  # JSON list
    suggestion = Column(String(16))
    rag_evidence = Column(Text)  # JSON list
    reasoning = Column(Text)
    matched_at = Column(DateTime, default=datetime.now)


class ResumeVersionRecord(Base):
    __tablename__ = "resume_versions"
    __table_args__ = (Index("ix_resume_versions_job_id", "job_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(32), nullable=False)
    file_path = Column(String(512))
    content_md = Column(Text)
    status = Column(String(16), default="draft")  # draft / reviewed / applied
    created_at = Column(DateTime, default=datetime.now)


class NotificationRecord(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(32), nullable=False)
    channel = Column(String(32), default="feishu")
    payload = Column(Text)  # JSON
    sent_at = Column(DateTime, default=datetime.now)


class LearningPlanRecord(Base):
    __tablename__ = "learning_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(32), nullable=False)
    priority_skills = Column(Text)  # JSON list
    weekly_plan = Column(Text)  # JSON list
    estimated_hours = Column(Integer)
    created_at = Column(DateTime, default=datetime.now)


class SearchTaskRecord(Base):
    __tablename__ = "search_tasks"

    task_id = Column(String(32), primary_key=True)
    task_type = Column(String(32), default="job_search")
    status = Column(String(16), default="queued")
    stage = Column(String(32), default="queued")
    progress = Column(Integer, default=0)
    message = Column(Text, default="")
    request_json = Column(Text, default="{}")
    events_json = Column(Text, default="[]")
    screenshot_path = Column(String(512), default="")
    result_json = Column(Text, default="")
    error = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now)


class KnowledgeIngestRecord(Base):
    __tablename__ = "knowledge_ingests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chunks = Column(Integer, default=0)
    source_dir = Column(String(512), default="")
    ingested_at = Column(DateTime, default=datetime.now)


# ---------------------------------------------------------------------------
# Engine + session helpers
# ---------------------------------------------------------------------------

_engine = None
_engine_path = None
_session_factory = None


def _run_schema_migrations(engine) -> None:
    """Lightweight migrations for existing SQLite databases."""
    with engine.connect() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_match_results_job_id ON match_results (job_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_resume_versions_job_id ON resume_versions (job_id)"))
        conn.commit()


def get_engine(db_path: Path | str) -> Any:
    global _engine, _engine_path, _session_factory
    normalized_path = str(Path(db_path))
    if _engine is None or _engine_path != normalized_path:
        _engine = create_engine(f"sqlite:///{normalized_path}", echo=False)
        _engine_path = normalized_path
        _session_factory = sessionmaker(bind=_engine)
        Base.metadata.create_all(_engine)
        _run_schema_migrations(_engine)
        _run_alembic_migrations(normalized_path)
    return _engine


def _run_alembic_migrations(db_path: str) -> None:
    try:
        from alembic import command
        from alembic.config import Config
        from config.settings import PROJECT_ROOT

        cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
        command.upgrade(cfg, "head")
    except Exception:
        pass


def get_session() -> Session:
    if _session_factory is None:
        raise RuntimeError("Call get_engine() first.")
    return _session_factory()


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def save_job(session: Session, job) -> None:
    """Save a Job Pydantic model to SQLite. Silently skips if already exists."""
    if get_job(session, job.id):
        return
    record = JobRecord(
        id=job.id, title=job.title, company=job.company,
        salary=job.salary, city=job.city,
        description=job.description, url=job.url, scraped_at=job.scraped_at,
    )
    session.add(record)


def get_job(session: Session, job_id: str) -> JobRecord | None:
    return session.get(JobRecord, job_id)


def save_match(session: Session, match) -> None:
    """Upsert latest match result per job_id."""
    existing = (
        session.query(MatchRecord)
        .filter(MatchRecord.job_id == match.job_id)
        .order_by(MatchRecord.matched_at.desc())
        .first()
    )
    if existing:
        existing.score = match.score
        existing.advantages = json.dumps(match.advantages, ensure_ascii=False)
        existing.missing = json.dumps(match.missing, ensure_ascii=False)
        existing.suggestion = match.suggest
        existing.rag_evidence = json.dumps(match.rag_evidence, ensure_ascii=False)
        existing.reasoning = match.reasoning
        existing.matched_at = datetime.now()
        return
    record = MatchRecord(
        job_id=match.job_id, score=match.score,
        advantages=json.dumps(match.advantages, ensure_ascii=False),
        missing=json.dumps(match.missing, ensure_ascii=False),
        suggestion=match.suggest,
        rag_evidence=json.dumps(match.rag_evidence, ensure_ascii=False),
        reasoning=match.reasoning,
    )
    session.add(record)


def save_notification(session: Session, job_id: str, payload: dict, channel: str = "feishu") -> None:
    record = NotificationRecord(
        job_id=job_id, channel=channel,
        payload=json.dumps(payload, ensure_ascii=False),
    )
    session.add(record)


def save_resume_version(session: Session, resume, file_path: str = "", status: str = "draft") -> None:
    record = ResumeVersionRecord(
        job_id=resume.job_id,
        file_path=file_path,
        content_md=resume.full_markdown,
        status=status,
    )
    session.add(record)


def save_learning_plan(session: Session, plan) -> None:
    record = LearningPlanRecord(
        job_id=plan.job_id,
        priority_skills=json.dumps(plan.priority_skills, ensure_ascii=False),
        weekly_plan=json.dumps(plan.weekly_plan, ensure_ascii=False),
        estimated_hours=plan.estimated_hours,
    )
    session.add(record)


def get_cached_job_ids(session: Session) -> set[str]:
    """Return all job IDs already in DB for deduplication."""
    rows = session.query(JobRecord.id).all()
    return {r[0] for r in rows}


def recent_scrape_exists(session: Session, keyword: str, city: str, hours: int = 24) -> bool:
    """Return True if jobs were scraped recently for similar keyword/city."""
    cutoff = datetime.now() - timedelta(hours=hours)
    count = (
        session.query(JobRecord)
        .filter(JobRecord.scraped_at >= cutoff)
        .filter(JobRecord.city == city)
        .count()
    )
    if count == 0:
        return False
    if not keyword:
        return True
    rows = (
        session.query(JobRecord)
        .filter(JobRecord.scraped_at >= cutoff)
        .filter(JobRecord.city == city)
        .limit(50)
        .all()
    )
    needle = keyword.lower()
    return any(needle in f"{row.title} {row.description}".lower() for row in rows)


# ---------------------------------------------------------------------------
# Search task persistence
# ---------------------------------------------------------------------------

def _task_to_dict(record: SearchTaskRecord) -> dict:
    return {
        "id": record.task_id,
        "type": record.task_type,
        "status": record.status,
        "stage": record.stage,
        "progress": record.progress,
        "message": record.message or "",
        "request": json.loads(record.request_json or "{}"),
        "events": json.loads(record.events_json or "[]"),
        "login_screenshot": "",
        "login_screenshot_url": (
            f"/api/tasks/{record.task_id}/login-screenshot"
            if record.screenshot_path else ""
        ),
        "result": json.loads(record.result_json) if record.result_json else None,
        "error": record.error or "",
        "created_at": record.created_at.isoformat(timespec="seconds") if record.created_at else "",
        "updated_at": record.updated_at.isoformat(timespec="seconds") if record.updated_at else "",
    }


def create_search_task(task: dict) -> dict:
    with get_session() as sess:
        record = SearchTaskRecord(
            task_id=task["id"],
            task_type=task.get("type", "job_search"),
            status=task.get("status", "queued"),
            stage=task.get("stage", "queued"),
            progress=int(task.get("progress", 0)),
            message=task.get("message", ""),
            request_json=json.dumps(task.get("request", {}), ensure_ascii=False),
            events_json=json.dumps(task.get("events", []), ensure_ascii=False),
            screenshot_path=task.get("screenshot_path", ""),
            result_json=json.dumps(task["result"], ensure_ascii=False) if task.get("result") else "",
            error=task.get("error", ""),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        sess.add(record)
        sess.commit()
        return _task_to_dict(record)


def get_search_task(task_id: str) -> dict | None:
    with get_session() as sess:
        record = sess.get(SearchTaskRecord, task_id)
        if not record:
            return None
        return _task_to_dict(record)


def update_search_task(task_id: str, **fields) -> dict | None:
    with get_session() as sess:
        record = sess.get(SearchTaskRecord, task_id)
        if not record:
            return None
        for key, value in fields.items():
            if key == "request":
                record.request_json = json.dumps(value, ensure_ascii=False)
            elif key == "events":
                record.events_json = json.dumps(value, ensure_ascii=False)
            elif key == "result":
                record.result_json = json.dumps(value, ensure_ascii=False) if value is not None else ""
            elif key == "screenshot_path":
                record.screenshot_path = value or ""
            elif hasattr(record, key):
                setattr(record, key, value)
        record.updated_at = datetime.now()
        sess.commit()
        sess.refresh(record)
        return _task_to_dict(record)


def prune_search_tasks(ttl_seconds: int) -> int:
    cutoff = datetime.now() - timedelta(seconds=ttl_seconds)
    with get_session() as sess:
        rows = sess.query(SearchTaskRecord).filter(SearchTaskRecord.updated_at < cutoff).all()
        count = len(rows)
        for row in rows:
            sess.delete(row)
        sess.commit()
        return count


def record_knowledge_ingest(chunks: int, source_dir: str) -> None:
    with get_session() as sess:
        sess.add(KnowledgeIngestRecord(chunks=chunks, source_dir=source_dir))
        sess.commit()


def latest_knowledge_ingest() -> dict | None:
    with get_session() as sess:
        row = (
            sess.query(KnowledgeIngestRecord)
            .order_by(KnowledgeIngestRecord.ingested_at.desc())
            .first()
        )
        if not row:
            return None
        return {
            "chunks": row.chunks,
            "source_dir": row.source_dir,
            "ingested_at": row.ingested_at.isoformat(timespec="seconds") if row.ingested_at else "",
        }

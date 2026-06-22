"""
SQLite persistence for JobMatch Agent.
SQLAlchemy models + helper functions for jobs, matches, resume versions, and learning plans.
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


class LearningPlanRecord(Base):
    __tablename__ = "learning_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(32), nullable=False)
    priority_skills = Column(Text)  # JSON list
    weekly_plan = Column(Text)  # JSON list
    estimated_hours = Column(Integer)
    created_at = Column(DateTime, default=datetime.now)


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
    return _engine


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

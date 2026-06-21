"""
SQLite persistence for JobMatch Agent.
SQLAlchemy models + helper functions for jobs, matches, resume versions, notifications.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine
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


# ---------------------------------------------------------------------------
# Engine + session helpers
# ---------------------------------------------------------------------------

_engine = None
_engine_path = None
_session_factory = None


def get_engine(db_path: Path | str) -> Any:
    global _engine, _engine_path, _session_factory
    normalized_path = str(Path(db_path))
    if _engine is None or _engine_path != normalized_path:
        _engine = create_engine(f"sqlite:///{normalized_path}", echo=False)
        _engine_path = normalized_path
        _session_factory = sessionmaker(bind=_engine)
        Base.metadata.create_all(_engine)
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

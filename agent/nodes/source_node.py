"""
source_node.py — Load target jobs from the local job library.

The project intentionally avoids live job-board collection. Candidates can paste,
import, or seed job descriptions into SQLite, then run the Agent pipeline over
that controlled dataset.
"""

import logging

from config.settings import settings
from models.agent_state import AgentState
from models.job import Job

logger = logging.getLogger(__name__)


def source_node(state: AgentState) -> dict:
    keywords = [kw.lower() for kw in state.get("keywords", []) if kw]
    city = state.get("city", "全国")
    existing_jobs = state.get("jobs", [])

    if existing_jobs:
        return {"jobs": existing_jobs, "source_error": ""}

    try:
        from storage.db import JobRecord, get_engine, get_session

        get_engine(settings.db_path)
        with get_session() as sess:
            query = sess.query(JobRecord)
            if city and city != "全国":
                query = query.filter(JobRecord.city == city)
            rows = query.order_by(JobRecord.scraped_at.desc()).limit(100).all()
    except Exception as exc:
        logger.exception("[agent/source] Could not load local jobs")
        return {"jobs": [], "source_error": f"local_job_source_failed: {exc}"}

    jobs = [_record_to_job(row) for row in rows]
    if keywords:
        jobs = [
            job for job in jobs
            if any(kw in f"{job.title} {job.company} {job.description}".lower() for kw in keywords)
        ]

    logger.info("[agent/source] Loaded %d local jobs for %s · %s", len(jobs), city, keywords)
    return {"jobs": jobs, "source_error": "" if jobs else "no_jobs_found"}


def _record_to_job(record) -> Job:
    return Job(
        id=record.id,
        title=record.title,
        company=record.company,
        salary=record.salary or "",
        city=record.city or "",
        description=record.description or "",
        url=record.url or "",
        scraped_at=record.scraped_at,
    )

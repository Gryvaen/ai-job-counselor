import logging
from models.agent_state import AgentState
from models.job import Job
from models.match import MatchResult
from config.settings import settings
from storage.db import get_engine, get_session, save_job, save_match, Base

logger = logging.getLogger(__name__)


def record_node(state: AgentState) -> dict:
    """
    Persist jobs and match_results to SQLite.
    """
    try:
        get_engine(settings.db_path)
        with get_session() as session:
            jobs = state["jobs"]
            match_results = state["match_results"]
            job_map = {j.id: j for j in jobs}
            for result in match_results:
                job = job_map.get(result.job_id)
                if job:
                    save_job(session, job)
                save_match(session, result)
            session.commit()

        print(f"[record_node] Saved {len(match_results)} match results to {settings.db_path}")
    except Exception as e:
        logger.warning(f"Failed to persist match results: {e}")

    return {}

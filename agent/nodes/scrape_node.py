"""
scrape_node.py — LangGraph node that calls Boss Zhipin scraper.
"""

import asyncio
from scraper import BossSession, BossScraper, deduplicate_jobs
from config.settings import settings
from models.agent_state import AgentState


def scrape_node(state: AgentState) -> dict:
    keywords = state["keywords"]
    existing_jobs = state.get("jobs", [])

    async def _scrape_all():
        session = BossSession(settings.boss_state_path)
        await session.start(headless=True)
        try:
            scraper = BossScraper(session, fetch_detail=True)
            all_jobs = []
            for kw in keywords:
                jobs = await scraper.search_jobs(kw, max_pages=2, delay=3.0)
                all_jobs.extend(jobs)
            return all_jobs
        finally:
            await session.close()

    print(f"[agent/scrape] Searching for: {keywords}")
    try:
        fresh_jobs = asyncio.run(_scrape_all())
    except Exception as e:
        print(f"[agent/scrape] Scraping failed: {e}")
        if existing_jobs:
            print(f"[agent/scrape] Using {len(existing_jobs)} pre-existing jobs")
            return {"jobs": existing_jobs}
        return {"jobs": []}

    all_jobs = existing_jobs + fresh_jobs
    all_jobs = deduplicate_jobs(all_jobs)

    # Deduplicate against DB
    try:
        from storage.db import get_engine, get_cached_job_ids, get_session
        get_engine(settings.db_path)
        with get_session() as sess:
            cached_ids = get_cached_job_ids(sess)
        new_jobs = [j for j in all_jobs if j.id not in cached_ids]
        print(f"[agent/scrape] {len(all_jobs)} total, {len(cached_ids)} cached, {len(new_jobs)} new")
    except Exception:
        new_jobs = all_jobs

    return {"jobs": new_jobs}

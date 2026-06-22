#!/usr/bin/env python3
"""
boss-mcp — MCP Server for Boss Zhipin job scraping.

Tools: search_jobs, get_job_detail, get_cached_jobs
Usage: python mcp_servers/boss_server.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from fastmcp import FastMCP
from config.settings import settings
from scraper import BossSession, BossScraper, LoginRequiredError, deduplicate_jobs
from storage.db import get_engine, get_session, get_cached_job_ids

mcp = FastMCP("jobmatch-boss", port=8001)


@mcp.tool()
async def search_jobs(keywords: list[str], city: str = "全国", max_pages: int = 2) -> list[dict]:
    """Search Boss Zhipin for jobs matching the given keywords.

    Args:
        keywords: List of search keywords (e.g., ["Linux驱动", "BSP"])
        city: Target city name (default: "全国")
        max_pages: Maximum pages to scrape per keyword (default: 2)

    Returns:
        List of job dictionaries
    """
    async def _search(headless: bool, login_first: bool = False) -> list[dict]:
        session = BossSession(settings.boss_state_path)
        await session.start(headless=headless)
        try:
            if login_first:
                await session.wait_for_login()
            scraper = BossScraper(session, fetch_detail=True)
            all_jobs = []
            for kw in keywords:
                jobs = await scraper.search_jobs(kw, city=city, max_pages=max_pages, delay=3.0)
                all_jobs.extend(jobs)
            deduped = deduplicate_jobs(all_jobs)
            try:
                get_engine(settings.db_path)
                with get_session() as sess:
                    cached = get_cached_job_ids(sess)
                return [j.model_dump() for j in deduped if j.id not in cached]
            except Exception:
                return [j.model_dump() for j in deduped]
        finally:
            await session.close()

    saved_login = BossSession(settings.boss_state_path).has_saved_login()
    try:
        return await _search(headless=saved_login, login_first=not saved_login)
    except LoginRequiredError:
        return await _search(headless=False, login_first=True)


@mcp.tool()
async def get_cached_jobs() -> list[dict]:
    """Get list of previously cached job IDs from the database.

    Returns:
        List of cached job IDs
    """
    try:
        get_engine(settings.db_path)
        with get_session() as sess:
            cached = get_cached_job_ids(sess)
        return list(cached)
    except Exception as e:
        return []


@mcp.tool()
async def get_job_detail(job_id: str) -> dict | None:
    """Get details for a specific job by ID.

    Args:
        job_id: Job ID (MD5 hash of company + title)

    Returns:
        Job details dict or None
    """
    try:
        get_engine(settings.db_path)
        from storage.db import JobRecord
        with get_session() as sess:
            record = sess.query(JobRecord).filter(JobRecord.id == job_id).first()
            if record:
                return {
                    "id": record.id, "title": record.title, "company": record.company,
                    "salary": record.salary, "city": record.city,
                    "description": record.description, "url": record.url,
                }
    except Exception:
        pass
    return None


if __name__ == "__main__":
    mcp.run(transport="stdio")

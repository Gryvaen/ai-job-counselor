"""
scrape_node.py — LangGraph node that calls Boss Zhipin scraper.
"""

import asyncio
import logging
import os

from scraper import BossSession, BossScraper, LoginRequiredError, deduplicate_jobs
from scraper.boss_scraper import BlockedPageError, SecurityCheckPending
from config.settings import settings
from models.agent_state import AgentState

logger = logging.getLogger(__name__)


def scrape_node(state: AgentState) -> dict:
    keywords = state["keywords"]
    city = state.get("city", "全国")
    login_screenshot_callback = state.get("login_screenshot_callback")
    login_started_callback = state.get("login_started_callback")
    existing_jobs = state.get("jobs", [])
    can_open_browser = (
        settings.boss_auto_open_browser
        and bool(os.environ.get("DISPLAY"))
        and (not _running_in_container() or _truthy_env("BOSS_VISIBLE_BROWSER_IN_DOCKER"))
    )
    scrape_error = ""

    async def _scrape_all(headless: bool = True, login_first: bool = False):
        if login_first:
            raise LoginRequiredError("Boss login is required before searching jobs.")
        session = BossSession(
            settings.boss_state_path,
            restore_state=not login_first,
            fresh_login=login_first,
        )
        await session.start(headless=headless)
        try:
            scraper = BossScraper(session, fetch_detail=True)
            all_jobs = []
            for kw in keywords:
                jobs = await scraper.search_jobs(kw, city=city, max_pages=2, delay=3.0)
                all_jobs.extend(jobs)
            return all_jobs
        finally:
            await session.close()

    logger.info("[agent/scrape] Searching for: %s in %s", keywords, city)

    try:
        from storage.db import get_engine, get_cached_job_ids, get_session, recent_scrape_exists

        get_engine(settings.db_path)
        with get_session() as sess:
            if all(recent_scrape_exists(sess, kw, city, settings.scrape_cooldown_hours) for kw in keywords):
                logger.info(
                    "[agent/scrape] Skipping scrape — recent results exist within %dh",
                    settings.scrape_cooldown_hours,
                )
                return {"jobs": existing_jobs, "scrape_error": ""}
    except Exception as exc:
        logger.warning("[agent/scrape] Cooldown check failed: %s", exc)

    fresh_jobs = []
    try:
        saved_login = BossSession(settings.boss_state_path).has_saved_login()
        if not saved_login:
            if login_started_callback:
                login_started_callback()
            return {"jobs": existing_jobs, "scrape_error": "login_required"}
        headless = not can_open_browser
        if saved_login and can_open_browser:
            logger.info("[agent/scrape] Using visible Chrome for Boss search...")
        fresh_jobs = asyncio.run(_scrape_all(headless=headless, login_first=False))
    except LoginRequiredError:
        logger.warning("[agent/scrape] Boss login required; waiting for user-triggered manual login.")
        if login_started_callback:
            login_started_callback()
        return {"jobs": existing_jobs, "scrape_error": "login_required"}
    except SecurityCheckPending as e:
        scrape_error = f"boss_security_check: {e}"
        logger.error("[agent/scrape] Boss security check required: %s", e)
        return {"jobs": existing_jobs, "scrape_error": scrape_error}
    except BlockedPageError as e:
        scrape_error = (
            "boss_access_restricted: Boss 返回访问受限/IP 异常页面。"
            "请在弹出的 Boss 浏览器中手动查看页面提示，等待限制恢复或更换正常网络后再搜索。"
        )
        logger.error("[agent/scrape] Boss access restricted: %s", e)
        return {"jobs": existing_jobs, "scrape_error": scrape_error}
    except Exception as e:
        scrape_error = f"scraping_failed: {e}"
        logger.error("[agent/scrape] Scraping failed: %s", e)
        if existing_jobs:
            logger.info("[agent/scrape] Using %d pre-existing jobs", len(existing_jobs))
            return {"jobs": existing_jobs, "scrape_error": scrape_error}
        return {"jobs": [], "scrape_error": scrape_error}

    all_jobs = existing_jobs + fresh_jobs
    all_jobs = deduplicate_jobs(all_jobs)

    try:
        from storage.db import get_engine, get_cached_job_ids, get_session
        get_engine(settings.db_path)
        with get_session() as sess:
            cached_ids = get_cached_job_ids(sess)
        new_jobs = [j for j in all_jobs if j.id not in cached_ids]
        logger.info(
            "[agent/scrape] %d total, %d cached, %d new",
            len(all_jobs), len(cached_ids), len(new_jobs),
        )
    except Exception:
        new_jobs = all_jobs

    if not new_jobs and not existing_jobs and not scrape_error:
        scrape_error = "no_jobs_found"

    return {"jobs": new_jobs, "scrape_error": scrape_error}


def _running_in_container() -> bool:
    return os.path.exists("/.dockerenv") or _truthy_env("RUNNING_IN_CONTAINER")


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}

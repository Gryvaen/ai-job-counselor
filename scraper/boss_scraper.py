"""
Boss Zhipin scraper — uses Playwright via BossSession to search and extract jobs.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import Page

from config.settings import settings
from models.job import Job
from scraper.session import BossSession
from scraper.parser import parse_job_list

logger = logging.getLogger(__name__)
DEBUG_DIR = settings.knowledge_dir.parent / "debug"


class LoginRequiredError(RuntimeError):
    """Raised when Boss redirects to a login wall during scraping."""


class SecurityCheckPending(RuntimeError):
    def __init__(self, url: str):
        self.url = url
        super().__init__(url)


class BlockedPageError(RuntimeError):
    def __init__(self, url: str):
        self.url = url
        super().__init__(url)


class BossScraper:
    """Scrapes job listings from Boss Zhipin using an existing BossSession."""

    BASE_URL = "https://www.zhipin.com"
    MAX_RETRIES = 2

    def __init__(self, session: BossSession, fetch_detail: bool = False):
        self.session = session
        self.fetch_detail = fetch_detail

    async def search_jobs(
        self,
        keyword: str,
        city: str = "全国",
        max_pages: int = 2,
        delay: float = 2.0,
    ) -> list[Job]:
        """Search Boss Zhipin for a keyword and return list of Jobs."""
        all_jobs: list[Job] = []
        last_page: Page | None = None

        for pg in range(1, max_pages + 1):
            url = self._build_search_url(keyword, city, pg)
            logger.info("[scraper] Searching: %s", url)

            page_jobs: list[Job] = []
            for attempt in range(1, self.MAX_RETRIES + 1):
                try:
                    async def scrape_page(page: Page) -> list[Job]:
                        nonlocal last_page
                        last_page = page
                        if await self._is_login_required(page):
                            raise LoginRequiredError("Boss login is required before searching jobs.")
                        if await self._is_blocked(page):
                            page_url = page.url or ""
                            if "_security_check" in page_url or "/verify" in page_url:
                                raise SecurityCheckPending(page_url)
                            raise BlockedPageError(page_url or url)
                        await page.wait_for_selector(
                            ".job-list li, .search-job-result li",
                            timeout=8000,
                        )
                        return await parse_job_list(page)

                    page_jobs = await self.session.run_with_page(
                        url,
                        scrape_page,
                        timeout=20000,
                    )
                    break
                except SecurityCheckPending as exc:
                    logger.warning(
                        "[scraper] Boss security check at %s — waiting for manual verification",
                        exc.url,
                    )
                    await asyncio.sleep(8)
                    if attempt < self.MAX_RETRIES:
                        continue
                    if last_page:
                        await self._save_debug(last_page, keyword, city, pg, "security_check")
                    break
                except LoginRequiredError:
                    raise
                except BlockedPageError as exc:
                    logger.warning("[scraper] Blocked by anti-scraping at %s", exc.url)
                    if last_page:
                        await self._save_debug(last_page, keyword, city, pg, "blocked")
                    break
                except Exception as e:
                    logger.warning(
                        "[scraper] Search failed for page %d attempt %d: %s",
                        pg, attempt, e,
                    )
                    if attempt < self.MAX_RETRIES:
                        await asyncio.sleep(1.5)
                        continue
                    if last_page:
                        await self._save_debug(last_page, keyword, city, pg, "error")
                    break

            all_jobs.extend(page_jobs)
            if len(page_jobs) == 0:
                break
            await asyncio.sleep(delay)

        if not all_jobs and last_page:
            await self._save_debug(last_page, keyword, city, 0, "zero_jobs")

        logger.info("[scraper] Scraped %d jobs for keyword '%s'", len(all_jobs), keyword)
        return all_jobs

    async def _save_debug(self, page: Page, keyword: str, city: str, pg: int, reason: str) -> None:
        try:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_kw = quote(keyword, safe="")
            base = DEBUG_DIR / f"{stamp}_{city}_{safe_kw}_p{pg}_{reason}"
            await page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
            html = await page.content()
            base.with_suffix(".html").write_text(html, encoding="utf-8")
            logger.info("[scraper] Saved debug artifacts: %s", base.name)
        except Exception as exc:
            logger.warning("[scraper] Could not save debug artifacts: %s", exc)

    async def _is_login_required(self, page: Page) -> bool:
        """Check if Boss shows login page or login modal."""
        try:
            url = str(page.url)
            title = await page.title()
            if "/web/user/safe/login" in url or "login" in url.lower():
                return True
            if "登录" in title and "BOSS" in title.upper():
                return True
            login_selectors = [
                ".login-dialog",
                ".login-box",
                ".scan-login",
                "text=扫码登录",
                "text=登录后继续",
            ]
            for selector in login_selectors:
                if await page.query_selector(selector):
                    return True
        except Exception:
            pass
        return False

    async def _is_blocked(self, page: Page) -> bool:
        """Check if Boss shows anti-scraping page or login wall."""
        try:
            url = str(page.url or "")
            if not url or url == "about:blank":
                return True
            if "_security_check" in url or "/verify" in url:
                return True
            title = await page.title()
            if any(w in title for w in ("验证", "verify", "captcha", "安全检查")):
                return True
            if "verify" in url:
                return True
        except Exception:
            return True
        return False

    @staticmethod
    def _build_search_url(keyword: str, city: str, page: int) -> str:
        city_code = _get_city_code(city)
        return (
            f"{BossScraper.BASE_URL}/web/geek/job"
            f"?query={quote(keyword)}"
            f"&city={city_code}"
            f"&page={page}"
        )


def deduplicate_jobs(jobs: list[Job]) -> list[Job]:
    """Remove duplicate jobs by Job.id (MD5 of company + title)."""
    seen: set[str] = set()
    result: list[Job] = []
    for job in jobs:
        if job.id not in seen:
            seen.add(job.id)
            result.append(job)
    return result


# --- Boss city codes ---
CITY_CODES = {
    "全国": "100010000", "北京": "101010100", "上海": "101020100",
    "广州": "101280100", "深圳": "101280600", "杭州": "101210100",
    "成都": "101270100", "南京": "101190100", "武汉": "101200100",
    "苏州": "101190400", "西安": "101110100", "重庆": "101040100",
    "长沙": "101250100", "厦门": "101230200", "合肥": "101220100",
    "郑州": "101180100", "青岛": "101120200", "大连": "101070200",
    "天津": "101030100", "珠海": "101280700",
}


def _get_city_code(city: str) -> str:
    return CITY_CODES.get(city, "100010000")

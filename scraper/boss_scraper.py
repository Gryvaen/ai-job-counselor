"""
Boss Zhipin scraper — uses Playwright via BossSession to search and extract jobs.
"""

import asyncio
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import Page

from models.job import Job
from scraper.session import BossSession
from scraper.parser import parse_job_list


class BossScraper:
    """Scrapes job listings from Boss Zhipin using an existing BossSession."""

    BASE_URL = "https://www.zhipin.com"

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
        page = await self.session.get_page()
        all_jobs: list[Job] = []

        for pg in range(1, max_pages + 1):
            url = self._build_search_url(keyword, city, pg)
            print(f"[scraper] Searching: {url}")

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)

                if await self._is_blocked(page):
                    print(f"[scraper] Blocked by anti-scraping at {url}")
                    break

                try:
                    await page.wait_for_selector(".job-list li, .search-job-result li", timeout=8000)
                except Exception:
                    print(f"[scraper] No job results found on page {pg} for '{keyword}'")
                    break

                page_jobs = await parse_job_list(page)
                all_jobs.extend(page_jobs)

                if len(page_jobs) == 0:
                    break

            except Exception as e:
                print(f"[scraper] Search failed for page {pg}: {e}")
                break

            await asyncio.sleep(delay)

        print(f"[scraper] Scraped {len(all_jobs)} jobs for keyword '{keyword}'")
        return all_jobs

    async def _is_blocked(self, page: Page) -> bool:
        """Check if Boss shows anti-scraping page or login wall."""
        try:
            title = await page.title()
            if any(w in title for w in ("验证", "verify", "captcha", "安全检查")):
                return True
            if "verify" in str(page.url):
                return True
        except Exception:
            pass
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

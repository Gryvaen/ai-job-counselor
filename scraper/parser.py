"""
Parser for Boss Zhipin — extracts Job objects from a Playwright page.
"""

from playwright.async_api import Page, ElementHandle

from models.job import Job


async def parse_job_list(page: Page) -> list[Job]:
    """Parse a Boss Zhipin search results page and return a list of Job objects."""
    jobs = []
    items = await page.query_selector_all("li.job-card, .job-list li, .search-job-result li")
    if not items:
        return jobs

    for item in items:
        try:
            job = await _parse_job_item(item)
            if job:
                jobs.append(job)
        except Exception:
            pass
    return jobs


async def _parse_job_item(item: ElementHandle) -> Job | None:
    """Extract a single Job from a Playwright element."""
    title_el = await item.query_selector(".job-name a, .job-title a, a.job-card-left")
    if not title_el:
        return None

    title = (await title_el.inner_text()).strip()
    href = await title_el.get_attribute("href")
    url = f"https://www.zhipin.com{href}" if href and not href.startswith("http") else (href or "")

    company_el = await item.query_selector(".company-name a, .brand-name a, .company-text a")
    company = (await company_el.inner_text()).strip() if company_el else ""

    salary_el = await item.query_selector(".salary, .job-salary")
    salary = (await salary_el.inner_text()).strip() if salary_el else ""

    area_el = await item.query_selector(".job-area, .job-location, .info-primary .location")
    city = (await area_el.inner_text()).strip().split()[0] if area_el else ""

    desc_el = await item.query_selector(".job-info .job-desc, .job-card-left .job-info")
    description = (await desc_el.inner_text()).strip() if desc_el else ""

    if not title or not company:
        return None

    return Job(title=title, company=company, salary=salary, city=city, description=description, url=url)


def parse_job_detail_page_elements(
    title_el_text: str, company_el_text: str, salary_el_text: str,
    location_el_text: str, desc_el_text: str, url: str,
) -> Job:
    """Parse job detail from individual element texts (extracted via Playwright)."""
    return Job(
        title=title_el_text, company=company_el_text, salary=salary_el_text,
        city=location_el_text.split()[0] if location_el_text else "",
        description=desc_el_text, url=url,
    )

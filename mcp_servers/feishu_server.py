#!/usr/bin/env python3
"""
feishu-mcp — MCP Server for Feishu notifications.

Tools: send_job_alert, send_resume_advice, send_summary
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastmcp import FastMCP
from config.settings import settings
from notifier.feishu import FeishuNotifier

mcp = FastMCP("jobmatch-feishu", port=8005)


@mcp.tool()
def send_job_alert(job_title: str, company: str, salary: str, city: str,
                   score: int, suggest: str, advantages: list[str] | None = None,
                   missing: list[str] | None = None, url: str = "") -> bool:
    """Send a job alert notification to Feishu.

    Args:
        job_title: Job title
        company: Company name
        salary: Salary range
        city: Work city
        score: Match score (0-100)
        suggest: Recommendation (推荐投递/观望/不推荐)
        advantages: List of advantages
        missing: List of missing skills
        url: Job detail URL

    Returns:
        True if sent successfully
    """
    from models.job import Job
    from models.match import MatchResult

    job = Job(title=job_title, company=company, salary=salary, city=city, url=url, description="")
    match = MatchResult(
        job_id="", score=score, suggest=suggest,
        advantages=advantages or [], missing=missing or [],
        rag_evidence=[], reasoning="",
    )
    notifier = FeishuNotifier()
    return notifier.send_job_alert(job, match)


@mcp.tool()
def send_resume_advice(resume_text: str) -> bool:
    """Send resume optimization advice to Feishu.

    Args:
        resume_text: Resume content in markdown format

    Returns:
        True if sent successfully
    """
    notifier = FeishuNotifier()
    return notifier.send_resume_advice(resume_text)


@mcp.tool()
def send_summary(job_count: int, high_score_count: int,
                jobs: list[dict]) -> bool:
    """Send a summary notification to Feishu.

    Args:
        job_count: Total jobs scraped
        high_score_count: Number of high-score recommendations
        jobs: List of {title, company, salary, city, score} dicts

    Returns:
        True if sent successfully
    """
    from models.job import Job
    from models.match import MatchResult

    results = []
    for j in jobs:
        job = Job(
            title=j["title"], company=j["company"], salary=j.get("salary", ""),
            city=j.get("city", ""), url=j.get("url", ""), description="",
        )
        match = MatchResult(
            job_id="", score=j.get("score", 0), suggest="推荐投递",
            advantages=[], missing=[], rag_evidence=[], reasoning="",
        )
        results.append((job, match))

    notifier = FeishuNotifier()
    return notifier.send_summary(results, total_scraped=job_count)


if __name__ == "__main__":
    mcp.run(transport="stdio")

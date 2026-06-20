#!/usr/bin/env python3
"""
optimizer-mcp — MCP Server for resume optimization and learning planning.

Tools: optimize_for_job, list_versions, get_version
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastmcp import FastMCP
from config.settings import settings
from crews.resume_optimizer import (
    list_versions as list_resume_versions,
    optimize_for_job as build_optimized_resume,
    save_resume_version,
)

mcp = FastMCP("jobmatch-optimizer", port=8004)


@mcp.tool()
def optimize_for_job(job_id: str, company: str, title: str, description: str,
                    match_score: int = 0, match_missing: list[str] | None = None) -> dict:
    """Generate a tailored resume for a specific job.

    Args:
        job_id: Job ID
        company: Company name
        title: Job title
        description: Job description
        match_score: Matching score (0-100)
        match_missing: List of missing skills from matching

    Returns:
        Optimized resume dict
    """
    from models.job import Job
    from models.match import MatchResult

    job = Job(
        id=job_id, title=title, company=company, salary="", city="",
        description=description, url="",
    )
    match = MatchResult(
        job_id=job_id, score=match_score, suggest="推荐投递",
        advantages=[], missing=match_missing or [],
        rag_evidence=[], reasoning="",
    )

    resume = build_optimized_resume(job, match)
    path = save_resume_version(resume)
    result = resume.model_dump()
    result["saved_path"] = str(path)
    return result


@mcp.tool()
def list_versions() -> list[dict]:
    """List all saved resume versions.

    Returns:
        List of version info dicts
    """
    return list_resume_versions()


@mcp.tool()
def get_version(filename: str) -> str:
    """Get the content of a specific resume version.

    Args:
        filename: Resume version filename

    Returns:
        Resume content as markdown
    """
    fp = settings.resume_versions_dir / filename
    if not fp.exists():
        return f"File not found: {filename}"
    return fp.read_text(encoding="utf-8")


if __name__ == "__main__":
    mcp.run(transport="stdio")

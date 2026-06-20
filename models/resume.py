"""
OptimizedResume — tailored resume output for a specific job.
Includes honest tracking: no fabricated experiences, evidence-sourced bullets.
"""

from typing import Literal

from pydantic import BaseModel, Field


class ResumeBullet(BaseModel):
    """A single resume bullet point with evidence tracking."""

    original: str | None = Field(default=None, description="Original bullet from resume.json, if exists")
    optimized: str = Field(description="Rewritten bullet, aligned to the target JD")
    keywords_matched: list[str] = Field(default_factory=list)
    evidence_source: str = Field(description="Path or source that supports this bullet")
    confidence: Literal["高", "中", "待核实"] = Field(
        default="中",
        description="Confidence that the user can honestly discuss this in an interview",
    )


class OptimizedResume(BaseModel):
    job_id: str
    company: str
    title: str
    summary: str = Field(description="Tailored professional summary for this job")
    skills_highlight: list[str] = Field(default_factory=list, description="Skills to highlight, ordered by relevance")
    project_bullets: list[ResumeBullet] = Field(default_factory=list)
    experience_bullets: list[ResumeBullet] = Field(default_factory=list)
    missing_gaps: list[str] = Field(default_factory=list, description="Missing skills identified from JD comparison")
    honest_notes: list[str] = Field(
        default_factory=list,
        description="Warnings: skills to mark as 'learning' or exclude due to lack of evidence",
    )
    ats_keyword_coverage: float = Field(ge=0.0, le=1.0, description="ATS keyword coverage ratio, e.g. 0.78")
    full_markdown: str = Field(default="", description="Full resume in Markdown format")
    cover_letter_hook: str = Field(default="", description="Suggested opening line for cover letter")

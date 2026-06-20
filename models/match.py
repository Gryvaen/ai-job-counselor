"""
MatchResult — matching score and reasoning for a job.
"""

from typing import Literal

from pydantic import BaseModel, Field


class MatchResult(BaseModel):
    job_id: str
    score: int = Field(ge=0, le=100, description="Matching score 0-100")
    advantages: list[str] = Field(default_factory=list, description="Why this job is a good match")
    missing: list[str] = Field(default_factory=list, description="Missing skills or experience")
    suggest: Literal["推荐投递", "观望", "不推荐"]
    rag_evidence: list[str] = Field(default_factory=list, description="Referenced knowledge base snippets")
    reasoning: str

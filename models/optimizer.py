"""
LearningPlan — weekly study plan for skills missing from the target job.
"""

from pydantic import BaseModel, Field


class LearningPlan(BaseModel):
    job_id: str
    priority_skills: list[str] = Field(description="Skills to learn, ordered by priority")
    weekly_plan: list[str] = Field(default_factory=list, description="Day-by-day study tasks")
    resource_links: list[str] = Field(default_factory=list)
    estimated_hours: int = Field(ge=0, description="Total estimated hours for the plan")

"""Pydantic models for the AI Job Counselor pipeline."""

from __future__ import annotations

from typing import TypedDict

from pydantic import BaseModel, Field


class JobProfile(BaseModel):
    title: str = Field(description="Target job title")
    seniority: str = Field(default="实习", description="Junior / intern / mid / senior")
    key_skills: list[str] = Field(default_factory=list, description="Core skills for the role")
    responsibilities: list[str] = Field(default_factory=list, description="Typical responsibilities")
    summary: str = Field(default="", description="Brief role overview")


class SkillGap(BaseModel):
    matched_skills: list[str] = Field(default_factory=list)
    skills_missing: list[str] = Field(default_factory=list)
    gap_summary: str = Field(default="")


class LearningItem(BaseModel):
    skill: str
    duration: str = Field(description="e.g. 3天, 1周")
    tasks: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)


class ProjectRecommendation(BaseModel):
    title: str
    description: str
    skills: list[str] = Field(default_factory=list)
    difficulty: str = Field(default="中等", description="入门 / 中等 / 进阶")


class CounselorState(TypedDict, total=False):
    user_query: str
    resume_text: str
    jd_text: str
    job_profile: JobProfile | None
    skill_gap: SkillGap | None
    learning_plan: list[LearningItem]
    project_recommendations: list[ProjectRecommendation]
    steps_completed: list[str]


class ConsultRequest(BaseModel):
    user_query: str = Field(min_length=2, description="e.g. 我想找 AI Agent 实习")
    resume_text: str = ""
    jd_text: str = ""
    model: str | None = Field(default=None, description="Ollama model name override")


class CounselorResponse(BaseModel):
    steps_completed: list[str] = Field(default_factory=list)
    job_analysis: JobProfile | None = None
    skills_missing: list[str] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    gap_summary: str = ""
    learning_plan: list[LearningItem] = Field(default_factory=list)
    project_recommendations: list[ProjectRecommendation] = Field(default_factory=list)

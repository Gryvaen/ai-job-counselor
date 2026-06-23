"""Project Recommender node — suggest portfolio projects."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent.fallbacks import fallback_projects
from config.llm import llm_with_tools
from models.counselor import CounselorState, JobProfile, ProjectRecommendation, SkillGap

_SYSTEM = """你是求职顾问的项目推荐模块。根据技能缺口和目标岗位，推荐 2-4 个可写进简历的练手项目。
项目要具体、可落地，难度与候选人水平匹配，突出 Agent/后端/全栈等技术栈。"""


class ProjectListOutput(BaseModel):
    project_recommendations: list[ProjectRecommendation] = Field(
        description="Portfolio project recommendations"
    )


def project_recommender_node(state: CounselorState) -> dict:
    gap: SkillGap | None = state.get("skill_gap")
    profile: JobProfile | None = state.get("job_profile")
    missing = gap.skills_missing if gap else []
    title = profile.title if profile else state.get("user_query", "目标岗位")

    user_prompt = (
        f"目标岗位：{title}\n"
        f"技能缺口：{', '.join(missing) if missing else '无'}\n"
        f"已掌握：{', '.join(gap.matched_skills) if gap else '未知'}"
    )

    result = llm_with_tools(
        _SYSTEM,
        user_prompt,
        ProjectListOutput,
        "recommend_projects",
        "Recommend portfolio projects that demonstrate missing skills.",
    )
    projects = result.project_recommendations if result else fallback_projects(missing, title)

    steps = list(state.get("steps_completed", []))
    steps.append("project_recommender")

    return {"project_recommendations": projects, "steps_completed": steps}

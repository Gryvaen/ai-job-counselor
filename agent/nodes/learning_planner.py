"""Learning Planner node — generate study plan for missing skills."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent.fallbacks import fallback_learning_plan
from config.llm import llm_with_tools
from models.counselor import CounselorState, LearningItem, SkillGap

_SYSTEM = """你是求职顾问的学习规划模块。针对技能缺口生成可执行的短期学习计划。
每项计划包含具体任务和推荐资源，时长以天或周为单位，适合实习生/应届生。"""


class LearningPlanOutput(BaseModel):
    learning_plan: list[LearningItem] = Field(description="Ordered study plan items")


def learning_planner_node(state: CounselorState) -> dict:
    gap: SkillGap | None = state.get("skill_gap")
    missing = gap.skills_missing if gap else []

    profile = state.get("job_profile")
    role_title = profile.title if profile else state.get("user_query", "")
    user_prompt = (
        f"技能缺口：{', '.join(missing) if missing else '无显著缺口，建议深化工程化'}\n"
        f"目标岗位：{role_title}"
    )

    result = llm_with_tools(
        _SYSTEM,
        user_prompt,
        LearningPlanOutput,
        "build_learning_plan",
        "Build a practical learning plan for missing skills.",
    )
    plan = result.learning_plan if result else fallback_learning_plan(missing)

    steps = list(state.get("steps_completed", []))
    steps.append("learning_planner")

    return {"learning_plan": plan, "steps_completed": steps}

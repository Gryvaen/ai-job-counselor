"""Skill Gap Analyzer node — compare resume against job requirements."""

from __future__ import annotations

from agent.fallbacks import fallback_skill_gap
from config.llm import llm_with_tools
from models.counselor import CounselorState, JobProfile, SkillGap

_SYSTEM = """你是求职顾问的技能缺口分析模块。对比候选人简历与目标岗位要求。
只能基于简历中可验证的信息判断 matched_skills，不得编造经历。
skills_missing 是岗位要求但简历未体现的技能。"""


def skill_gap_analyzer_node(state: CounselorState) -> dict:
    job_profile: JobProfile | None = state.get("job_profile")
    if job_profile is None:
        job_profile = fallback_job_profile(state.get("user_query", ""), state.get("jd_text", ""))

    resume_text = state.get("resume_text", "")
    user_prompt = (
        f"目标岗位：{job_profile.title}\n"
        f"要求技能：{', '.join(job_profile.key_skills)}\n"
        f"职责：{'; '.join(job_profile.responsibilities[:5])}\n\n"
        f"候选人简历/技能：\n{resume_text[:3000] if resume_text.strip() else '(未提供)'}"
    )

    gap = llm_with_tools(
        _SYSTEM,
        user_prompt,
        SkillGap,
        "analyze_skill_gap",
        "Compare resume skills against job requirements and list gaps.",
    )
    if gap is None:
        gap = fallback_skill_gap(resume_text, job_profile)

    steps = list(state.get("steps_completed", []))
    steps.append("skill_gap_analyzer")

    return {"skill_gap": gap, "steps_completed": steps}

"""Job Analyzer node — extract target role profile via Tool Calling."""

from __future__ import annotations

from agent.fallbacks import fallback_job_profile
from config.llm import llm_with_tools
from models.counselor import CounselorState, JobProfile

_SYSTEM = """你是求职顾问的岗位分析模块。根据用户目标和可选 JD，提取目标岗位画像。
只输出结构化数据，技能列表要具体可验证（如 FastAPI、LangGraph，不要泛泛的"良好的沟通能力"）。"""


def job_analyzer_node(state: CounselorState) -> dict:
    user_query = state.get("user_query", "")
    jd_text = state.get("jd_text", "")

    user_prompt = f"用户目标：{user_query}"
    if jd_text.strip():
        user_prompt += f"\n\n岗位 JD：\n{jd_text[:3000]}"

    profile = llm_with_tools(
        _SYSTEM,
        user_prompt,
        JobProfile,
        "extract_job_profile",
        "Extract target job profile including title, seniority, key skills and responsibilities.",
    )
    if profile is None:
        profile = fallback_job_profile(user_query, jd_text)

    steps = list(state.get("steps_completed", []))
    steps.append("job_analyzer")

    return {"job_profile": profile, "steps_completed": steps}

"""Rule-based fallbacks when LLM is unavailable."""

from __future__ import annotations

import re

from models.counselor import JobProfile, LearningItem, ProjectRecommendation, SkillGap

KNOWN_SKILLS = [
    "Python", "FastAPI", "LangGraph", "LangChain", "OpenAI", "Pydantic",
    "RAG", "ChromaDB", "Docker", "Git", "SQL", "Redis", "PostgreSQL",
    "React", "TypeScript", "JavaScript", "Linux", "Kubernetes",
    "PyTorch", "机器学习", "NLP", "Agent", "Function Calling", "MCP",
    "Prompt Engineering", "向量数据库", "Embedding",
]

ROLE_SKILLS: dict[str, list[str]] = {
    "agent": ["Python", "LangGraph", "OpenAI", "FastAPI", "RAG", "Function Calling", "Pydantic", "Docker"],
    "backend": ["Python", "FastAPI", "PostgreSQL", "Redis", "Docker", "Git", "Linux"],
    "frontend": ["TypeScript", "React", "JavaScript", "Git"],
    "ml": ["Python", "PyTorch", "机器学习", "NLP", "Docker"],
}


def _skill_in_text(skill: str, text: str) -> bool:
    lower = text.lower()
    needle = skill.lower()
    if re.fullmatch(r"[a-z0-9+#./-]+", needle):
        return bool(re.search(rf"(?<![a-z0-9+#./-]){re.escape(needle)}(?![a-z0-9+#./-])", lower))
    return needle in lower


def _extract_skills(text: str) -> list[str]:
    return [s for s in KNOWN_SKILLS if _skill_in_text(s, text)]


def _infer_role_type(query: str, jd: str) -> str:
    combined = (query + " " + jd).lower()
    if any(k in combined for k in ["agent", "langgraph", "llm", "rag"]):
        return "agent"
    if any(k in combined for k in ["前端", "frontend", "react", "vue"]):
        return "frontend"
    if any(k in combined for k in ["机器学习", "ml", "nlp", "pytorch"]):
        return "ml"
    return "backend"


def fallback_job_profile(user_query: str, jd_text: str) -> JobProfile:
    role_type = _infer_role_type(user_query, jd_text)
    jd_skills = _extract_skills(jd_text)
    base_skills = jd_skills or ROLE_SKILLS.get(role_type, ROLE_SKILLS["backend"])

    title = user_query.strip()
    if "实习" in user_query:
        seniority = "实习"
    elif any(k in user_query for k in ["高级", "资深", "senior"]):
        seniority = "高级"
    else:
        seniority = "初级"

    responsibilities = [
        f"掌握 {base_skills[0]} 等核心技术栈",
        "参与需求分析与技术方案设计",
        "编写可维护、可测试的代码",
    ]
    if role_type == "agent":
        responsibilities.insert(0, "设计和实现基于 LLM 的 Agent 工作流")

    return JobProfile(
        title=title[:60] or "目标岗位",
        seniority=seniority,
        key_skills=base_skills[:10],
        responsibilities=responsibilities,
        summary=f"面向 {title} 的典型技能与职责要求（规则引擎推断）。",
    )


def fallback_skill_gap(resume_text: str, job_profile: JobProfile) -> SkillGap:
    resume_skills = _extract_skills(resume_text)
    if not resume_text.strip():
        resume_skills = []

    required = job_profile.key_skills
    matched = [s for s in required if s in resume_skills or _skill_in_text(s, resume_text)]
    missing = [s for s in required if s not in matched]

    if not resume_text.strip():
        gap_summary = "未提供简历，以下为目标岗位常见技能缺口。"
        missing = required[:6]
        matched = []
    elif missing:
        gap_summary = f"已匹配 {len(matched)} 项技能，还需补充 {len(missing)} 项核心能力。"
    else:
        gap_summary = "核心技能基本覆盖，建议深化项目经验与工程化能力。"

    return SkillGap(matched_skills=matched, skills_missing=missing, gap_summary=gap_summary)


def fallback_learning_plan(missing: list[str]) -> list[LearningItem]:
    if not missing:
        return [
            LearningItem(
                skill="工程化深化",
                duration="1周",
                tasks=["完善项目文档与测试", "补充部署与监控实践"],
                resources=["FastAPI 官方文档", "Docker 入门教程"],
            )
        ]

    items: list[LearningItem] = []
    for i, skill in enumerate(missing[:4]):
        days = 2 + (i % 2)
        items.append(
            LearningItem(
                skill=skill,
                duration=f"{days}天",
                tasks=[
                    f"阅读 {skill} 官方文档核心章节",
                    f"完成一个最小 {skill} demo",
                    f"将 {skill} 融入现有项目或 side project",
                ],
                resources=[f"{skill} 官方文档", f"{skill} GitHub 示例"],
            )
        )
    return items


def fallback_projects(missing: list[str], role_title: str) -> list[ProjectRecommendation]:
    skills = missing[:3] or ["Python", "FastAPI"]
    return [
        ProjectRecommendation(
            title="AI 求职顾问 Agent",
            description="基于 FastAPI + LangGraph 的多节点求职分析 Agent，支持岗位分析、技能缺口与学习路线生成。",
            skills=["FastAPI", "LangGraph", "OpenAI", "Pydantic"],
            difficulty="中等",
        ),
        ProjectRecommendation(
            title=f"{skills[0]} 练手 API",
            description=f"用 {skills[0]} 实现一个带 Tool Calling 的小型 REST 服务，覆盖 CRUD 与结构化输出。",
            skills=skills[:3],
            difficulty="入门",
        ),
        ProjectRecommendation(
            title="RAG 知识库问答",
            description="搭建文档入库、向量检索与引用溯源的 RAG 流水线，可写入简历作为 Agent 相关项目。",
            skills=["RAG", "Embedding", "ChromaDB", "Python"],
            difficulty="进阶",
        ),
    ]

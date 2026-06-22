"""Resume Optimizer Crew — generates honest tailored resumes for high-score jobs."""

import json
import logging
import re
from pathlib import Path

from config.llm import is_llm_available, llm_optimize_resume
from config.settings import settings
from models.resume import ResumeBullet, OptimizedResume

logger = logging.getLogger(__name__)

CORE_JOB_KEYWORDS = [
    "Linux", "驱动", "BSP", "嵌入式", "C", "STM32", "ARM", "RTOS",
    "Device Tree", "设备树", "Kernel", "I2C", "SPI", "GPIO", "Platform Driver",
]


def load_resume() -> dict:
    """Load user's base resume from data/resume.json."""
    rp = settings.resume_path
    if not rp.exists():
        return {"name": "", "skills": [], "projects": [], "experience": [], "education": []}
    with open(rp, encoding="utf-8") as f:
        return json.load(f)


def _contains(text: str, keyword: str) -> bool:
    kw = keyword.lower()
    if kw == "c":
        return bool(re.search(r"(?<![a-z0-9+#])c(?![a-z0-9+#])", text))
    if re.fullmatch(r"[a-z0-9+#. -]+", kw):
        return bool(re.search(rf"(?<![a-z0-9+#.-]){re.escape(kw)}(?![a-z0-9+#.-])", text))
    return kw in text


def optimize_for_job(job, match: "MatchResult", resume: dict | None = None) -> OptimizedResume:
    """Generate a tailored resume for a specific job.

    Args:
        job: Job Pydantic model
        match: MatchResult from matching
        resume: Base resume dict (loaded from file if None)

    Returns:
        OptimizedResume Pydantic model
    """
    if resume is None:
        resume = load_resume()

    if is_llm_available():
        llm_resume = llm_optimize_resume(job, match, resume)
        if llm_resume:
            logger.info("[resume_optimizer] LLM resume generated for %s", job.id)
            return llm_resume

    job_text = f"{job.title} {job.description}".lower()
    skills = resume.get("skills", [])
    job_keywords = [kw for kw in CORE_JOB_KEYWORDS if _contains(job_text, kw)]
    matched_skills = [s for s in skills if _contains(job_text, str(s))]
    highlighted = list(dict.fromkeys(matched_skills + job_keywords))[:8]

    project_bullets = []
    experience_bullets = []
    for proj in resume.get("projects", []):
        desc = proj.get("description", "")
        proj_skills = [s for s in proj.get("skills", []) if _contains(job_text, str(s))]
        bullet = ResumeBullet(
            original=desc,
            optimized=f"{proj.get('name', '项目')}: {desc}",
            keywords_matched=proj_skills,
            evidence_source=proj.get("evidence", "resume.json"),
            confidence="高" if proj_skills else "中",
        )
        project_bullets.append(bullet)

    for exp in resume.get("experience", []):
        for bullet in exp.get("bullets", []):
            exp_keywords = [s for s in resume.get("skills", []) if _contains(job_text, str(s))]
            experience_bullets.append(ResumeBullet(
                original=bullet,
                optimized=bullet,
                keywords_matched=exp_keywords,
                evidence_source=f"{exp.get('company', '?')}/{exp.get('role', '?')}",
                confidence="高" if exp_keywords else "中",
            ))

    missing = match.missing[:5] if hasattr(match, "missing") else []
    if not project_bullets and not experience_bullets:
        project_bullets.append(ResumeBullet(
            original=None,
            optimized=(
                f"围绕 {job.title} 要求准备可验证项目材料，优先覆盖 "
                f"{', '.join(highlighted[:4] or job_keywords[:4] or missing[:4])}"
            ),
            keywords_matched=highlighted[:4],
            evidence_source="resume.json (profile missing)",
            confidence="待核实",
        ))

    full_md = f"# {job.title} @ {job.company}\n\n"
    full_md += f"## Professional Summary\n面向 {job.company} 的 {job.title} 岗位，突出与 JD 直接相关的技能和项目证据。\n\n"
    full_md += f"## Technical Skills\n{', '.join(highlighted or skills[:4] or job_keywords[:6])}\n\n"
    full_md += "## Project Experience\n" + "\n".join(f"- {b.optimized}" for b in project_bullets) + "\n"
    if experience_bullets:
        full_md += "\n## Work Experience\n" + "\n".join(f"- {b.optimized}" for b in experience_bullets) + "\n"

    coverage_base = set(kw.lower() for kw in (job_keywords or missing or CORE_JOB_KEYWORDS[:6]))
    covered = {kw.lower() for kw in highlighted if kw.lower() in coverage_base}
    ats_coverage = len(covered) / max(len(coverage_base), 1)

    return OptimizedResume(
        job_id=job.id, company=job.company, title=job.title,
        summary=f"面向 {job.company} 的 {job.title} 岗位，突出与 JD 直接相关的技能和项目证据。",
        skills_highlight=highlighted or skills[:4] or job_keywords[:6],
        project_bullets=project_bullets,
        experience_bullets=experience_bullets,
        missing_gaps=missing,
        honest_notes=[f"[待核实] {sk}" for sk in missing[:3]],
        ats_keyword_coverage=round(min(max(ats_coverage, 0.0), 1.0), 2),
        full_markdown=full_md,
        cover_letter_hook=f"我关注到贵司 {job.title} 岗位强调 {', '.join(job_keywords[:3])}，这与我的项目准备方向高度相关。",
    )


def save_resume_version(resume: OptimizedResume, base_dir: Path | None = None) -> Path:
    """Save an optimized resume version to data/resume_versions/."""
    d = base_dir or settings.resume_versions_dir
    d.mkdir(parents=True, exist_ok=True)
    fname = f"{resume.company}_{resume.title.replace(' ', '_').replace('/', '_')}.md"
    path = d / fname
    with open(path, "w", encoding="utf-8") as f:
        f.write(resume.full_markdown)
    return path


def list_versions() -> list[dict]:
    """List all saved resume versions."""
    d = settings.resume_versions_dir
    if not d.exists():
        return []
    versions = []
    for fp in sorted(d.glob("*.md")):
        versions.append({"file": fp.name, "path": str(fp), "size": fp.stat().st_size})
    return versions

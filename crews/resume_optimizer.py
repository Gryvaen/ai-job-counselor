"""
Resume Optimizer Crew — generates tailored resumes for high-score jobs.

Phase 4 placeholder: This module uses simple template-based generation.
Replace with real CrewAI crew (JD Analyst → Evidence Mapper → Resume Writer → Reviewer) later.
"""

import json
from pathlib import Path
from config.settings import settings
from models.resume import ResumeBullet, OptimizedResume


def load_resume() -> dict:
    """Load user's base resume from data/resume.json."""
    rp = settings.resume_path
    if not rp.exists():
        return {"name": "", "skills": [], "projects": [], "experience": [], "education": []}
    with open(rp) as f:
        return json.load(f)


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

    job_text = f"{job.title} {job.description}".lower()
    skills = resume.get("skills", [])
    matched_skills = [s for s in skills if s.lower() in job_text]

    bullets = []
    for proj in resume.get("projects", []):
        desc = proj.get("description", "")
        proj_skills = [s for s in proj.get("skills", []) if s.lower() in job_text]
        bullets.append(ResumeBullet(
            original=desc,
            optimized=f"{proj.get('name', '项目')}: {desc}",
            keywords_matched=proj_skills,
            evidence_source=proj.get("evidence", "resume.json"),
            confidence="高" if proj_skills else "待核实",
        ))

    for exp in resume.get("experience", []):
        for bullet in exp.get("bullets", []):
            bullets.append(ResumeBullet(
                original=bullet,
                optimized=bullet,
                keywords_matched=[s for s in resume.get("skills", []) if s.lower() in job_text],
                evidence_source=f"{exp.get('company', '?')}/{exp.get('role', '?')}",
                confidence="高",
            ))

    missing = match.missing[:5] if hasattr(match, "missing") else []

    full_md = f"# {job.title} @ {job.company}\n\n"
    full_md += f"## Professional Summary\nSeeking {job.title} position at {job.company}.\n\n"
    full_md += f"## Technical Skills\n{', '.join(matched_skills or skills[:4])}\n\n"
    full_md += f"## Project Experience\n" + "\n".join(f"- {b.optimized}" for b in bullets) + "\n"

    return OptimizedResume(
        job_id=job.id, company=job.company, title=job.title,
        summary=f"Seeking {job.title} position at {job.company}.",
        skills_highlight=matched_skills or skills[:4],
        project_bullets=[b for b in bullets if b.confidence != "待核实"],
        experience_bullets=[b for b in bullets if b.confidence == "待核实"],
        missing_gaps=missing,
        honest_notes=[f"[待核实] {sk}" for sk in missing[:3]],
        ats_keyword_coverage=round(len(matched_skills) / max(len(skills), 1), 2),
        full_markdown=full_md,
    )


def save_resume_version(resume: OptimizedResume, base_dir: Path | None = None) -> Path:
    """Save an optimized resume version to data/resume_versions/."""
    d = base_dir or settings.resume_versions_dir
    d.mkdir(parents=True, exist_ok=True)
    fname = f"{resume.company}_{resume.title.replace(' ', '_').replace('/', '_')}.md"
    path = d / fname
    with open(path, "w") as f:
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

"""
optimize_node.py — LangGraph node that generates tailored resumes for high-score jobs.

Phase 4: Currently uses simple template-based generation. Will be replaced by CrewAI crew later.
"""

import json
from pathlib import Path

from config.settings import settings
from models.resume import ResumeBullet, OptimizedResume
from models.optimizer import LearningPlan
from models.agent_state import AgentState


def _load_resume() -> dict:
    """Load user's base resume from data/resume.json."""
    resume_path = settings.resume_path
    if not resume_path.exists():
        return {"skills": [], "projects": [], "experience": [], "education": [], "preferences": {}}
    with open(resume_path) as f:
        return json.load(f)


def _generate_optimized_resume(job, match: "MatchResult", resume: dict) -> OptimizedResume:
    """Generate a tailored resume for a job based on match results and base resume."""
    job_desc_words = f"{job.title} {job.description}".lower().split()
    skills = resume.get("skills", [])

    # Skills matched between user resume and job requirements
    matched_skills = [s for s in skills if any(s.lower() in w for w in job_desc_words)]
    highlight_skills = matched_skills[:6] if matched_skills else skills[:4]

    bullets = []
    for proj in resume.get("projects", []):
        desc = proj.get("description", "")
        bullets.append(ResumeBullet(
            original=desc,
            optimized=f"{proj.get('name', '项目')}: {desc}",
            keywords_matched=[s for s in proj.get("skills", []) if s.lower() in f"{job.title}{job.description}".lower()],
            evidence_source=proj.get("evidence", "resume.json"),
            confidence="高",
        ))

    missing = match.missing[:5] if hasattr(match, "missing") else []

    full_md = f"# {job.title} @ {job.company}\n\n"
    full_md += f"## Professional Summary\nTailored for {job.company} - {job.title}.\n\n"
    full_md += f"## Skills\n" + ", ".join(highlight_skills) + "\n\n"
    full_md += f"## Projects\n" + "\n".join(f"- {b.optimized}" for b in bullets) + "\n"

    return OptimizedResume(
        job_id=job.id, company=job.company, title=job.title,
        summary=f"Tailored for {job.company} - {job.title}.",
        skills_highlight=highlight_skills,
        project_bullets=bullets,
        missing_gaps=missing,
        honest_notes=[f"⚠️ Cannot confirm experience: {sk}" for sk in missing[:3]],
        ats_keyword_coverage=min(len(matched_skills) / max(len(highlight_skills), 1), 1.0),
        full_markdown=full_md,
    )


def _generate_learning_plan(job, resume: dict, missing_skills: list[str]) -> LearningPlan:
    """Generate a weekly study plan for missing skills."""
    if not missing_skills:
        return LearningPlan(job_id=job.id, priority_skills=[], weekly_plan=[], resource_links=[], estimated_hours=0)

    weekly = []
    for i, skill in enumerate(missing_skills[:4]):
        weekly.append(f"Mon-Wed: Study {skill} fundamentals — read documentation and tutorials")
        weekly.append(f"Thu-Fri: Build a small project or demo using {skill}")
        weekly.append(f"Sat: Review and document learnings")

    return LearningPlan(
        job_id=job.id, priority_skills=missing_skills,
        weekly_plan=weekly,
        resource_links=[f"https://search.example.com/{skill}"],
        estimated_hours=40,
    )


def optimize_node(state: AgentState) -> dict:
    """Generate tailored resumes and learning plans for high-score matches."""
    resumes = []
    plans = []

    resume = _load_resume()
    job_map = {j.id: j for j in state.get("jobs", [])}

    high_matches = [m for m in state.get("match_results", []) if m.score >= state.get("threshold", 75)]

    for match in high_matches:
        job = job_map.get(match.job_id)
        if not job:
            continue

        opt_resume = _generate_optimized_resume(job, match, resume)
        resumes.append(opt_resume)

        # Save resume version to file
        versions_dir = settings.resume_versions_dir
        versions_dir.mkdir(parents=True, exist_ok=True)
        version_file = f"{job.company}_{job.title.replace(' ', '_')}.md"
        version_path = versions_dir / version_file
        with open(version_path, "w") as f:
            f.write(opt_resume.full_markdown)
        print(f"[agent/optimize] Saved resume version: {version_path}")

        plan = _generate_learning_plan(job, resume, match.missing if hasattr(match, "missing") else [])
        plans.append(plan)

    print(f"[agent/optimize] Generated {len(resumes)} resumes + {len(plans)} learning plans")
    return {
        "optimized_resumes": resumes,
        "learning_plans": plans,
    }

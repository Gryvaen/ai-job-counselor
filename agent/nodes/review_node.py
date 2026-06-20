"""
review_node.py — Quality check for optimized resumes before notification.
"""

from models.agent_state import AgentState


def review_node(state: AgentState) -> dict:
    resumes = state.get("optimized_resumes", [])
    failed_ids = []

    for resume in resumes:
        issues = []

        # Check bullet confidence — no low-confidence bullets should pass
        low_conf = [b for b in resume.project_bullets + resume.experience_bullets
                     if b.confidence == "待核实"]
        if low_conf:
            issues.append(f"{len(low_conf)} bullets need verification")
            failed_ids.append(resume.job_id)

        # ATS coverage must be >= 0.4
        if resume.ats_keyword_coverage < 0.4:
            issues.append(f"ATS too low ({resume.ats_keyword_coverage:.0%})")
            failed_ids.append(resume.job_id)

        if issues:
            resume.honest_notes.extend(issues)

    passed = [r for r in resumes if r.job_id not in failed_ids]
    print(f"[review] {len(passed)}/{len(resumes)} resumes passed, {len(failed_ids)} flagged")
    return {"optimized_resumes": resumes}

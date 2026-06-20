"""optimize_node.py — generate tailored resumes and learning plans."""

from crews.learning_planner import generate_learning_plan
from crews.resume_optimizer import load_resume, optimize_for_job, save_resume_version
from models.agent_state import AgentState


def optimize_node(state: AgentState) -> dict:
    """Generate tailored resumes and learning plans for high-score matches."""
    resumes = []
    plans = []

    resume = load_resume()
    job_map = {j.id: j for j in state.get("jobs", [])}

    high_matches = [m for m in state.get("match_results", []) if m.score >= state.get("threshold", 75)]

    for match in high_matches:
        job = job_map.get(match.job_id)
        if not job:
            continue

        opt_resume = optimize_for_job(job, match, resume)
        resumes.append(opt_resume)

        version_path = save_resume_version(opt_resume)
        print(f"[agent/optimize] Saved resume version: {version_path}")

        city = resume.get("preferences", {}).get("city", job.city)
        plan = generate_learning_plan(job.id, match.missing if hasattr(match, "missing") else [], city)
        plans.append(plan)

    print(f"[agent/optimize] Generated {len(resumes)} resumes + {len(plans)} learning plans")
    return {
        "optimized_resumes": resumes,
        "learning_plans": plans,
    }

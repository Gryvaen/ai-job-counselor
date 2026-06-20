"""
Learning Planner — generates weekly study plans for missing skills.

Phase 4 placeholder: simple rule-based plan generation.
"""

from config.settings import settings
from models.optimizer import LearningPlan


def generate_learning_plan(
    job_id: str,
    missing_skills: list[str],
    city: str = "上海",
) -> LearningPlan:
    """Generate a weekly study plan for skills missing from the target job.

    Args:
        job_id: Target job ID
        missing_skills: Skills identified as missing
        city: User's target city (affects resource recommendations)

    Returns:
        LearningPlan Pydantic model
    """
    if not missing_skills:
        return LearningPlan(
            job_id=job_id, priority_skills=[], weekly_plan=[],
            resource_links=[], estimated_hours=0,
        )

    weekly_plan = []
    total_hours = 0

    for i, skill in enumerate(missing_skills[:4]):
        days = 2 + (i % 2)
        hours = days * 2
        total_hours += hours
        weekly_plan.append(
            f"Day {i*3+1}-{i*3+days}: Study {skill} fundamentals — "
            f"read documentation, build small projects"
        )
        weekly_plan.append(f"  • Focus: {skill} core concepts and practical exercises")

    weekly_plan.append(f"Total estimated investment: {total_hours} hours over {len(missing_skills[:4])} weeks")

    return LearningPlan(
        job_id=job_id,
        priority_skills=missing_skills[:4],
        weekly_plan=weekly_plan,
        resource_links=[f"https://search.example.com/{skill}" for skill in missing_skills[:4]],
        estimated_hours=total_hours,
    )

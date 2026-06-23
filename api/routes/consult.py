"""Consult endpoint — runs the LangGraph counselor pipeline."""

from fastapi import APIRouter

from agent.graph import build_counselor_graph
from api.schemas import ConsultRequest, CounselorResponse
from config.llm import list_available_models, use_model
from models.counselor import CounselorState

router = APIRouter()


@router.get("/models")
def models() -> dict:
    return list_available_models()


def _state_to_response(state: CounselorState) -> CounselorResponse:
    gap = state.get("skill_gap")
    profile = state.get("job_profile")
    return CounselorResponse(
        steps_completed=state.get("steps_completed", []),
        job_analysis=profile,
        skills_missing=gap.skills_missing if gap else [],
        matched_skills=gap.matched_skills if gap else [],
        gap_summary=gap.gap_summary if gap else "",
        learning_plan=state.get("learning_plan", []),
        project_recommendations=state.get("project_recommendations", []),
    )


@router.post("/consult", response_model=CounselorResponse)
def consult(payload: ConsultRequest) -> CounselorResponse:
    initial: CounselorState = {
        "user_query": payload.user_query.strip(),
        "resume_text": payload.resume_text.strip(),
        "jd_text": payload.jd_text.strip(),
        "job_profile": None,
        "skill_gap": None,
        "learning_plan": [],
        "project_recommendations": [],
        "steps_completed": [],
    }
    graph = build_counselor_graph()
    with use_model(payload.model):
        result = graph.invoke(initial)
    return _state_to_response(result)

"""LangGraph counselor pipeline integration test."""

import pytest

from agent.graph import build_counselor_graph


@pytest.fixture(autouse=True)
def disable_llm(monkeypatch):
    monkeypatch.setattr("config.llm.is_llm_available", lambda: False)


def test_counselor_graph_full_pipeline():
    graph = build_counselor_graph()
    state = {
        "user_query": "我想找 AI Agent 实习",
        "resume_text": "Python, Docker, 做过简单 RAG 项目",
        "jd_text": "",
        "job_profile": None,
        "skill_gap": None,
        "learning_plan": [],
        "project_recommendations": [],
        "steps_completed": [],
    }
    result = graph.invoke(state)

    assert result["steps_completed"] == [
        "job_analyzer",
        "skill_gap_analyzer",
        "learning_planner",
        "project_recommender",
    ]
    assert result["job_profile"] is not None
    assert result["job_profile"].title
    assert result["skill_gap"] is not None
    assert isinstance(result["skill_gap"].skills_missing, list)
    assert len(result["learning_plan"]) >= 1
    assert len(result["project_recommendations"]) >= 1


def test_counselor_graph_with_jd():
    graph = build_counselor_graph()
    jd = """
    AI Agent 工程师（实习）
    要求：熟悉 Python、FastAPI、LangGraph、OpenAI API
    负责设计和实现 Agent 工作流
    """
    result = graph.invoke({
        "user_query": "AI Agent 实习",
        "resume_text": "Python",
        "jd_text": jd,
        "job_profile": None,
        "skill_gap": None,
        "learning_plan": [],
        "project_recommendations": [],
        "steps_completed": [],
    })

    gap = result["skill_gap"]
    assert "FastAPI" in gap.skills_missing or "LangGraph" in gap.skills_missing

import pytest


@pytest.fixture(autouse=True)
def disable_llm(monkeypatch):
    monkeypatch.setattr("config.llm.is_llm_available", lambda: False)


@pytest.mark.anyio
async def test_consult_endpoint(client):
    resp = await client.post(
        "/api/consult",
        json={
            "user_query": "我想找 AI Agent 实习",
            "resume_text": "Python, Docker",
            "jd_text": "",
        },
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["steps_completed"] == [
        "job_analyzer",
        "skill_gap_analyzer",
        "learning_planner",
        "project_recommender",
    ]
    assert data["job_analysis"] is not None
    assert "title" in data["job_analysis"]
    assert isinstance(data["skills_missing"], list)
    assert isinstance(data["learning_plan"], list)
    assert len(data["learning_plan"]) >= 1
    assert isinstance(data["project_recommendations"], list)
    assert len(data["project_recommendations"]) >= 1


@pytest.mark.anyio
async def test_consult_requires_query(client):
    resp = await client.post("/api/consult", json={"user_query": ""})
    assert resp.status_code == 422

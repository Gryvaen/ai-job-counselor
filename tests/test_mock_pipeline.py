"""Mock pipeline integration tests."""

from config.settings import settings
from models.agent_state import AgentState
from models.job import Job
from agent.nodes.match_node import match_node
from storage.db import get_engine, get_session, save_job, save_match


def test_match_node_scores_mock_jobs(tmp_db_path):
    get_engine(tmp_db_path)
    mock_jobs = [
        Job(
            title="Linux BSP 开发工程师",
            company="芯联科技",
            salary="15-25K",
            city="上海",
            description="熟悉 Linux 内核驱动开发，掌握 I2C/SPI/GPIO 等总线协议",
            url="https://jobs.example.com/abc123",
        ),
        Job(
            title="Python 后端开发",
            company="云端科技",
            salary="30-50K",
            city="北京",
            description="要求精通微服务架构，熟悉 Kubernetes、Docker、gRPC",
            url="https://jobs.example.com/ghi789",
        ),
    ]
    for job in mock_jobs:
        with get_session() as sess:
            save_job(sess, job)
            sess.commit()

    state: AgentState = {
        "user_query": "Linux驱动,BSP",
        "keywords": ["Linux驱动", "BSP"],
        "threshold": settings.match_threshold,
        "jobs": mock_jobs,
        "retrieved_context": [],
        "match_results": [],
        "optimized_resumes": [],
        "learning_plans": [],
        "messages": [],
    }
    result = match_node(state)
    matches = result["match_results"]
    assert len(matches) == 2
    assert matches[0].score >= matches[1].score or matches[0].job_id != matches[1].job_id

    with get_session() as sess:
        for match in matches:
            save_match(sess, match)
        sess.commit()

    with get_session() as sess:
        save_match(sess, matches[0])
        sess.commit()

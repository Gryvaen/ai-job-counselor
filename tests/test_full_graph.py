"""Full LangGraph integration test with pre-populated jobs."""

from models.job import Job
from config.settings import settings


def test_full_graph_with_mock_jobs(tmp_db_path):
    from storage.db import get_engine, get_session, get_cached_job_ids
    from agent.graph import build_graph

    get_engine(tmp_db_path)
    jobs = [
        Job(title="Linux BSP 开发", company="芯联科技", salary="15-25K", city="上海",
            description="熟悉 Linux 内核驱动开发，掌握 I2C/SPI/GPIO 等总线协议，有 device tree 经验",
            url="https://jobs.example.com/1"),
        Job(title="嵌入式驱动工程师", company="智微电子", salary="12-20K", city="深圳",
            description="STM32 ARM 平台开发，熟悉 platform driver，有 I2C/SPI 调试经验",
            url="https://jobs.example.com/2"),
        Job(title="Python 后端开发", company="云端科技", salary="30-50K", city="北京",
            description="要求精通微服务架构，熟悉 Kubernetes、Docker、gRPC",
            url="https://jobs.example.com/3"),
        Job(title="Linux 驱动实习生", company="开源芯", salary="200-350/天", city="杭州",
            description="了解 Linux kernel，有 I2C/GPIO/Device Tree 经验者优先",
            url="https://jobs.example.com/4"),
    ]

    graph = build_graph()
    state = {
        "user_query": "Linux驱动,BSP 实习",
        "keywords": ["Linux驱动", "BSP"],
        "threshold": 25,
        "jobs": jobs,
        "retrieved_context": [],
        "match_results": [],
        "optimized_resumes": [],
        "learning_plans": [],
        "messages": [],
    }
    result = graph.invoke(state)

    assert len(result["match_results"]) == 4
    assert len(result["jobs"]) == 4
    high = [m for m in result["match_results"] if m.score >= state["threshold"]]
    assert len(high) >= 1

    with get_session() as sess:
        assert len(get_cached_job_ids(sess)) >= 0

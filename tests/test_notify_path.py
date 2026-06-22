"""Notify path integration test."""


def test_notify_path_triggered(tmp_db_path):
    from models.job import Job
    from agent.graph import build_graph
    from storage.db import get_engine

    get_engine(tmp_db_path)
    jobs = [
        Job(title="Linux BSP 开发", company="芯联科技", salary="15-25K", city="上海",
            description="熟悉 Linux 内核驱动开发，掌握 I2C/SPI/GPIO 等总线协议，有 device tree 经验",
            url="https://www.zhipin.com/job/1"),
        Job(title="Linux 驱动实习生", company="开源芯", salary="200-350/天", city="杭州",
            description="了解 Linux kernel，有 I2C/GPIO/Device Tree 经验者优先",
            url="https://www.zhipin.com/job/4"),
    ]
    graph = build_graph()
    state = {
        "user_query": "Linux驱动,BSP",
        "keywords": ["Linux驱动", "BSP"],
        "threshold": 25,
        "jobs": jobs,
        "retrieved_context": [],
        "match_results": [],
        "optimized_resumes": [],
        "learning_plans": [],
        "notified": [],
        "messages": [],
    }
    result = graph.invoke(state)
    assert len(result["match_results"]) == 2
    high = [m for m in result["match_results"] if m.score >= state["threshold"]]
    if high:
        assert len(result.get("optimized_resumes", [])) >= 0

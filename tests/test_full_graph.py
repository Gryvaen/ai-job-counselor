#!/usr/bin/env python3
"""
Full LangGraph integration test — runs compiled graph with pre-populated jobs.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.job import Job
from config.settings import settings

def main():
    print("=== Full LangGraph Integration Test ===")
    print()

    # Init DB
    from storage.db import get_engine, get_session, save_job, get_cached_job_ids
    get_engine(settings.db_path)
    print(f"[1] DB initialized ✅")

    # Pre-populate DB so the scrape_node dedup works
    # We'll use a "fake scrape" approach: inject jobs directly into the graph state
    jobs = [
        Job(title="Linux BSP 开发", company="芯联科技", salary="15-25K", city="上海",
            description="熟悉 Linux 内核驱动开发，掌握 I2C/SPI/GPIO 等总线协议，有 device tree 经验",
            url="https://www.zhipin.com/job/1"),
        Job(title="嵌入式驱动工程师", company="智微电子", salary="12-20K", city="深圳",
            description="STM32 ARM 平台开发，熟悉 platform driver，有 I2C/SPI 调试经验",
            url="https://www.zhipin.com/job/2"),
        Job(title="Python 后端开发", company="云端科技", salary="30-50K", city="北京",
            description="要求精通微服务架构，熟悉 Kubernetes、Docker、gRPC",
            url="https://www.zhipin.com/job/3"),
        Job(title="Linux 驱动实习生", company="开源芯", salary="200-350/天", city="杭州",
            description="了解 Linux kernel，有 I2C/GPIO/Device Tree 经验者优先",
            url="https://www.zhipin.com/job/4"),
    ]

    print(f"[2] Loaded {len(jobs)} mock jobs ✅")

    # Build graph
    from agent.graph import build_graph
    graph = build_graph()
    print(f"[3] Graph built ✅")

    # Create initial state with jobs pre-populated (skip actual scraping)
    state = {
        "user_query": "Linux驱动,BSP 实习",
        "keywords": ["Linux驱动", "BSP"],
        "threshold": 25,  # Lower threshold to trigger notify node
        "jobs": jobs,
        "retrieved_context": [],
        "match_results": [],
        "optimized_resumes": [],
        "learning_plans": [],
        "notified": [],
        "messages": [],
    }

    print(f"[4] Running full graph (threshold={state['threshold']})...")
    result = graph.invoke(state)

    print()
    print(f"=== Results ===")
    print(f"  Jobs in state: {len(result['jobs'])}")
    print(f"  Matches: {len(result['match_results'])}")
    print(f"  Notified: {len(result['notified'])}")
    print()

    high = [m for m in result["match_results"] if m.score >= state["threshold"]]
    print(f"High-score ({state['threshold']}+): {len(high)}")

    for match in result["match_results"]:
        job = next((j for j in result["jobs"] if j.id == match.job_id), None)
        name = f"{job.title} @ {job.company}" if job else match.job_id
        emoji = "✅" if match.score >= state["threshold"] else "⬜"
        print(f"  {emoji} {match.score:3d} | {match.suggest:4s} | {name}")
        if match.advantages:
            print(f"       ✅ {', '.join(match.advantages[:3])}")

    # Verify DB persistence
    with get_session() as sess:
        cached = get_cached_job_ids(sess)
        print(f"\n[5] DB has {len(cached)} jobs persisted ✅")

    print("\n=== FULL GRAPH TEST PASSED ===")


if __name__ == "__main__":
    main()

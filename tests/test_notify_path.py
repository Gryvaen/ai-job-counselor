#!/usr/bin/env python3
"""
Test the notify path of the graph (score >= threshold) with pre-injected jobs.
Bypasses actual scraping by starting from the match node.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.job import Job
from config.settings import settings
from storage.db import get_engine, get_session, get_cached_job_ids


def main():
    print("=== Notify Path Test (score >= threshold) ===\n")

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

    from agent.graph import build_graph
    graph = build_graph()

    # Start from match node (skip scrape)
    state = {
        "user_query": "Linux驱动,BSP",
        "keywords": ["Linux驱动", "BSP"],
        "threshold": 25,  # Low threshold to trigger notify
        "jobs": jobs,
        "retrieved_context": [],
        "match_results": [],
        "optimized_resumes": [],
        "learning_plans": [],
        "notified": [],
        "messages": [],
    }

    print(f"Jobs: {len(jobs)}, threshold: {state['threshold']}")
    print()

    result = graph.invoke(state)

    print(f"\n=== Results ===")
    print(f"  Jobs scraped: {len(result['jobs'])}")
    print(f"  Matches: {len(result['match_results'])}")
    print(f"  Notified: {len(result['notified'])}")

    for match in result["match_results"]:
        job = next((j for j in result["jobs"] if j.id == match.job_id), None)
        name = f"{job.title} @ {job.company}" if job else match.job_id
        emoji = "✅" if match.score >= state["threshold"] else "⬜"
        print(f"  {emoji} {match.score:3d} | {match.suggest:4s} | {name}")
        if match.advantages:
            print(f"       ✅ {', '.join(match.advantages[:3])}")
        if match.missing:
            print(f"       ❌ {', '.join(match.missing[:3])}")

    # Verify DB
    get_engine(settings.db_path)
    with get_session() as sess:
        cached = get_cached_job_ids(sess)
        print(f"\n[DB] {len(cached)} jobs persisted ✅")

    # Check notify path was taken
    if result["notified"]:
        print(f"\n[NOTIFY] {len(result['notified'])} jobs sent to Feishu (simulated, no webhook) ✅")
        print("\n=== NOTIFY PATH TEST PASSED ===")
    else:
        # Could be that all scores < threshold with this low a threshold... let me check
        scores = [m.score for m in result["match_results"]]
        above = len([s for s in scores if s >= state["threshold"]])
        print(f"\n[NOTIFY] {above} jobs above threshold - notify was {'triggered' if above > 0 else 'skipped'}")


if __name__ == "__main__":
    main()

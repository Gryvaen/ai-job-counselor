#!/usr/bin/env python3
"""
Integration test for the JobMatch pipeline using mock data.
Skips actual Boss scraping (needs login) and injects mock jobs directly.

Usage:
    python tests/test_mock_pipeline.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage.db import get_engine, get_session, save_job, save_match
from models.job import Job
from models.agent_state import AgentState
from agent.nodes.match_node import match_node
from config.settings import settings


def main():
    print("===" * 20)
    print("JobMatch Pipeline Mock Integration Test")
    print("===" * 20)
    print()

    # 1. Init DB
    print("[1/4] Initializing database...")
    get_engine(settings.db_path)
    print(f"  DB: {settings.db_path} ✅")

    # 2. Create mock jobs (simulating scraper output)
    print("\n[2/4] Creating mock jobs (simulating scraper)...")
    mock_jobs = [
        Job(
            title="Linux BSP 开发工程师",
            company="芯联科技",
            salary="15-25K",
            city="上海",
            description="熟悉 Linux 内核驱动开发，掌握 I2C/SPI/GPIO 等总线协议",
            url="https://www.zhipin.com/job/abc123",
        ),
        Job(
            title="嵌入式软件工程师",
            company="智微电子",
            salary="12-20K",
            city="深圳",
            description="STM32 ARM 平台开发经验优先，了解 RTOS",
            url="https://www.zhipin.com/job/def456",
        ),
        Job(
            title="高级 Python 开发工程师",
            company="云端科技",
            salary="30-50K",
            city="北京",
            description="要求精通微服务架构，熟悉 Kubernetes、Docker、gRPC",
            url="https://www.zhipin.com/job/ghi789",
        ),
        Job(
            title="Linux 驱动开发实习生",
            company="开源芯",
            salary="200-350/天",
            city="杭州",
            description="了解 Linux kernel，有 I2C/GPIO/Device Tree 经验者优先",
            url="https://www.zhipin.com/job/jkl012",
        ),
    ]
    for j in mock_jobs:
        with get_session() as sess:
            save_job(sess, j)
            sess.commit()
    print(f"  Created {len(mock_jobs)} mock jobs ✅")

    # 3. Run match node
    print("\n[3/4] Running match node (rule-based scoring)...")
    state: AgentState = {
        "user_query": "Linux驱动,BSP",
        "keywords": ["Linux驱动", "BSP"],
        "threshold": settings.match_threshold,
        "jobs": mock_jobs,
        "retrieved_context": [],
        "match_results": [],
        "optimized_resumes": [],
        "learning_plans": [],
        "notified": [],
        "messages": [],
    }
    result = match_node(state)
    matches = result["match_results"]
    print(f"  Scored {len(matches)} jobs ✅")

    for job, match in zip(mock_jobs, matches):
        print(f"\n  📌 {job.title} @ {job.company}")
        print(f"    💰 {job.salary} | 📍 {job.city}")
        print(f"    ⭐ Score: {match.score} | {match.suggest}")
        if match.advantages:
            print(f"    ✅ {' / '.join(match.advantages[:3])}")
        if match.missing:
            print(f"    ❌ {' / '.join(match.missing[:3])}")

    # 4. Save matches and verify Feishu notifier skips gracefully
    print("\n[4/4] Saving matches, testing notifier...")
    with get_session() as sess:
        for m in matches:
            save_match(sess, m)
        sess.commit()
    print(f"  Saved {len(matches)} matches to SQLite ✅")

    from notifier import FeishuNotifier
    notifier = FeishuNotifier()  # No webhook configured — should skip gracefully
    notifier.send_summary(list(zip(mock_jobs, matches)), len(mock_jobs))
    print("  Notifier gracefully skipped (no webhook) ✅")

    # Summary
    high = [m for m in matches if m.score >= settings.match_threshold]
    print()
    print("===" * 20)
    print(f"TEST COMPLETE: {len(mock_jobs)} jobs scraped, {len(matches)} scored, "
          f"{len(high)} >= {settings.match_threshold} threshold")
    print(f"DB persisted to: {settings.db_path}")
    print("===" * 20)


if __name__ == "__main__":
    main()

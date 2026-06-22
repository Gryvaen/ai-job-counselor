#!/usr/bin/env python3
"""JobMatch Agent CLI — Boss Zhipin job scraping + RAG matching + resume optimization + Feishu notification."""

import argparse
import json
import sys
from config.settings import settings
from agent.nodes.plan_node import parse_job_query


def _run(args: argparse.Namespace) -> int:
    user_query = getattr(args, "query", None) or args.keywords
    city = getattr(args, "city", "全国")
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    threshold = getattr(args, "threshold", settings.match_threshold)

    print(f"[JOBMATCH] Pipeline: keywords={keywords}, city={city}, threshold={threshold}")
    print(f"[JOBMATCH] DB: {settings.db_path}")
    print(f"[JOBMATCH] Boss state: {settings.boss_state_path}")

    try:
        from agent.graph import build_graph
        from models.agent_state import AgentState
        from storage.db import get_engine
        get_engine(settings.db_path)
        print("[JOBMATCH] Database initialized.")

        graph = build_graph()
        state: AgentState = {
            "user_query": user_query,
            "keywords": keywords,
            "city": city,
            "threshold": threshold,
            "jobs": [], "retrieved_context": [],
            "match_results": [], "optimized_resumes": [],
            "learning_plans": [], "notified": [], "messages": [],
        }

        print("[JOBMATCH] Executing pipeline...")
        result = graph.invoke(state)

        print("\n=== Pipeline Results ===")
        print(f"Jobs scraped:  {len(result.get('jobs', []))}")
        print(f"Matches scored: {len(result.get('match_results', []))}")
        print(f"Jobs notified:  {len(result.get('notified', []))}")

        job_map = {j.id: j for j in result.get("jobs", [])}
        for m in result.get("match_results", []):
            j = job_map.get(m.job_id)
            name = f"{j.title} @ {j.company}" if j else m.job_id
            salary = f"{j.salary}" if j else "?"
            city = f"{j.city}" if j else "?"
            print(f"\n  {name}")
            print(f"    Salary: {salary} | City: {city}")
            print(f"    Score: {m.score} | {m.suggest}")
            if m.advantages:
                print(f"    Advantages: {', '.join(m.advantages[:3])}")
            if m.missing:
                print(f"    Missing: {', '.join(m.missing[:3])}")

        # Resume versions
        resumes = result.get("optimized_resumes", [])
        plans = result.get("learning_plans", [])
        if resumes:
            print(f"\nGenerated {len(resumes)} resume versions:")
            for r in resumes:
                print(f"  📝 {r.title} @ {r.company} (ATS: {r.ats_keyword_coverage:.0%})")
        if plans:
            print(f"\nGenerated {len(plans)} learning plans:")
            for p in plans:
                print(f"  📚 {p.job_id}: {p.priority_skills} ({p.estimated_hours}h)")

        return 0
    except Exception as e:
        print(f"[JOBMATCH] Pipeline failed: {e}", file=sys.stderr)
        import traceback; traceback.print_exc()
        return 1


def _chat(_: argparse.Namespace) -> int:
    print("[chat] JobMatch interactive mode. Try: /search <城市> <关键词...> [80分以上]")
    while True:
        try:
            line = input("jobmatch> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not line:
            continue
        if line in {"quit", "exit", "q"}:
            return 0
        if line == "help":
            print("Commands:")
            print("  /search <城市> <关键词...> [80分以上]")
            print("  /status")
            print("  /help")
            print("  帮我找上海的 Linux驱动,BSP 岗位")
            print("  run Linux驱动,BSP [--city 上海] [--threshold 75]")
            print("  explain <job_id>")
            print("  quit")
            continue
        if line.startswith("/"):
            if line in {"/help", "/"}:
                print("Slash commands:")
                print("  /search <城市> <关键词...> [80分以上]  运行岗位搜索")
                print("  /status                         查看本地记录数量")
                print("  /help                           查看帮助")
                continue
            if line.startswith("/search"):
                query = line.removeprefix("/search").strip()
                keywords, city, parsed_threshold = parse_job_query(query)
                threshold = parsed_threshold or settings.match_threshold
                if not keywords:
                    print("[chat] 用法: /search <城市> <关键词...> [80分以上]")
                    print("[chat] 示例: /search 上海 Linux驱动 BSP 80分以上")
                    continue
                _run(argparse.Namespace(
                    keywords=",".join(keywords),
                    city=city,
                    threshold=threshold,
                    query=query,
                ))
                continue
            if line == "/status":
                _print_status()
                continue
            print("[chat] Unknown slash command. Type /help.")
            continue
        if line.startswith("run "):
            parts = line[4:].split()
            keywords = parts[0]
            city = "全国"
            threshold = settings.match_threshold
            if "--city" in parts:
                idx = parts.index("--city")
                if idx + 1 < len(parts):
                    city = parts[idx + 1]
            if "--threshold" in parts:
                idx = parts.index("--threshold")
                if idx + 1 < len(parts):
                    threshold = int(parts[idx + 1])
            _run(argparse.Namespace(keywords=keywords, city=city, threshold=threshold, query=line[4:]))
            continue
        if line.startswith("explain "):
            _explain(argparse.Namespace(job_id=line.split(maxsplit=1)[1]))
            continue

        keywords, city, parsed_threshold = parse_job_query(line)
        if keywords:
            threshold = parsed_threshold or settings.match_threshold
            _run(argparse.Namespace(
                keywords=",".join(keywords),
                city=city,
                threshold=threshold,
                query=line,
            ))
            continue

        print("[chat] I did not catch the target role. Type help for examples.")
    return 0


def _print_status() -> None:
    from storage.db import (
        JobRecord,
        LearningPlanRecord,
        MatchRecord,
        ResumeVersionRecord,
        get_engine,
        get_session,
    )

    get_engine(settings.db_path)
    with get_session() as sess:
        print(
            "[status] "
            f"jobs={sess.query(JobRecord).count()}, "
            f"matches={sess.query(MatchRecord).count()}, "
            f"resumes={sess.query(ResumeVersionRecord).count()}, "
            f"plans={sess.query(LearningPlanRecord).count()}"
        )


def _explain(args: argparse.Namespace) -> int:
    from storage.db import (
        JobRecord,
        LearningPlanRecord,
        MatchRecord,
        ResumeVersionRecord,
        get_engine,
        get_session,
    )

    get_engine(settings.db_path)
    with get_session() as sess:
        job = sess.get(JobRecord, args.job_id)
        match = (
            sess.query(MatchRecord)
            .filter(MatchRecord.job_id == args.job_id)
            .order_by(MatchRecord.matched_at.desc())
            .first()
        )
        resume = (
            sess.query(ResumeVersionRecord)
            .filter(ResumeVersionRecord.job_id == args.job_id)
            .order_by(ResumeVersionRecord.created_at.desc())
            .first()
        )
        plan = (
            sess.query(LearningPlanRecord)
            .filter(LearningPlanRecord.job_id == args.job_id)
            .order_by(LearningPlanRecord.created_at.desc())
            .first()
        )

        if not job:
            print(f"[explain] Job not found: {args.job_id}")
            return 1

        print(f"\n=== Job Explanation ===")
        print(f"{job.title} @ {job.company}")
        print(f"Salary: {job.salary} | City: {job.city}")
        if job.url:
            print(f"URL: {job.url}")

        if match:
            advantages = json.loads(match.advantages or "[]")
            missing = json.loads(match.missing or "[]")
            evidence = json.loads(match.rag_evidence or "[]")
            print(f"\nScore: {match.score} | {match.suggestion}")
            print(f"Reasoning: {match.reasoning}")
            if advantages:
                print(f"Advantages: {', '.join(advantages[:8])}")
            if missing:
                print(f"Missing: {', '.join(missing[:8])}")
            if evidence:
                print("\nRAG Evidence:")
                for item in evidence[:3]:
                    print(f"- {item[:240]}")
        else:
            print("\nNo match result recorded yet.")

        if resume:
            print(f"\nResume draft: {resume.file_path or '(stored in DB)'}")
            preview = (resume.content_md or "").strip().splitlines()[:8]
            for line in preview:
                print(line)

        if plan:
            skills = json.loads(plan.priority_skills or "[]")
            print(f"\nLearning plan: {plan.estimated_hours}h | {', '.join(skills)}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python main.py", description="JobMatch Agent CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run full pipeline")
    run_parser.add_argument("--keywords", type=str, required=True, help="Comma-separated search keywords")
    run_parser.add_argument("--city", type=str, default="全国", help="Boss city name (default: 全国)")
    run_parser.add_argument("--threshold", type=int, default=settings.match_threshold, help=f"Match threshold (default: {settings.match_threshold})")
    run_parser.set_defaults(func=_run)

    subparsers.add_parser("chat", help="Interactive command mode").set_defaults(func=_chat)

    explain_parser = subparsers.add_parser("explain", help="RAG explanation for a job (coming soon)")
    explain_parser.add_argument("job_id", type=str)
    explain_parser.set_defaults(func=_explain)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

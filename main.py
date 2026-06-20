#!/usr/bin/env python3
"""JobMatch Agent CLI — Boss Zhipin job scraping + RAG matching + resume optimization + Feishu notification."""

import argparse
import sys
from config.settings import settings


def _run(args: argparse.Namespace) -> int:
    keywords = [k.strip() for k in args.keywords.split(",")]
    threshold = getattr(args, "threshold", settings.match_threshold)

    print(f"[JOBMATCH] Pipeline: keywords={keywords}, threshold={threshold}")
    print(f"[JOBMATCH] DB: {settings.db_path}")
    print(f"[JOBMATCH] Boss state: {settings.boss_state_path}")

    try:
        from agent.graph import build_graph
        from models.agent_state import AgentState
        from storage.db import get_engine
        get_engine(settings.db_path)
        print("[JOBMARK] Database initialized.")

        graph = build_graph()
        state: AgentState = {
            "user_query": args.keywords,
            "keywords": keywords,
            "threshold": threshold,
            "jobs": [], "retrieved_context": [],
            "match_results": [], "optimized_resumes": [],
            "learning_plans": [], "notified": [], "messages": [],
        }

        print("[JOBMARK] Executing pipeline...")
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
        print(f"[JOBMARK] Pipeline failed: {e}", file=sys.stderr)
        import traceback; traceback.print_exc()
        return 1


def _chat(_: argparse.Namespace) -> int:
    print("[chat] Interactive chat mode — coming soon.")
    return 0


def _explain(args: argparse.Namespace) -> int:
    print(f"[explain] RAG explanation for job {args.job_id} — coming soon.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python main.py", description="JobMatch Agent CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run full pipeline")
    run_parser.add_argument("--keywords", type=str, required=True, help="Comma-separated search keywords")
    run_parser.add_argument("--threshold", type=int, default=settings.match_threshold, help=f"Match threshold (default: {settings.match_threshold})")
    run_parser.set_defaults(func=_run)

    subparsers.add_parser("chat", help="Interactive chat (coming soon)").set_defaults(func=_chat)

    explain_parser = subparsers.add_parser("explain", help="RAG explanation for a job (coming soon)")
    explain_parser.add_argument("job_id", type=str)
    explain_parser.set_defaults(func=_explain)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

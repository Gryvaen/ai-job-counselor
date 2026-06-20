# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**JobMatch Agent** — A LangGraph + CrewAI + MCP intelligent job search system. Scrapes positions from Boss Zhipin, matches against personal knowledge via RAG, optimizes resumes, and pushes notifications via Feishu webhooks.

Read `docs/ARCHITECTURE.md` first for the full pipeline diagram, data models, and MCP server design.

## Current State

### ✅ Implemented
- `config/settings.py` — Pydantic Settings (LLM, Feishu, paths, RAG config)
- `models/` — All Pydantic models: Job, MatchResult, ResumeBullet, OptimizedResume, LearningPlan, AgentState
- `scraper/` — Playwright Boss Zhipin scraper (session management, HTML parsing, search + dedup)
- `storage/db.py` — SQLAlchemy models + CRUD (JobRecord, MatchRecord, ResumeVersion, Notification)
- `agent/graph.py` — LangGraph StateGraph with conditional routing
- `agent/nodes/` — scrape, match (rule-based), notify, record nodes
- `notifier/feishu.py` — Feishu webhook notifications
- `main.py` — CLI with `run` (wired to LangGraph), `chat`, `explain` subcommands
- `scripts/` — login_boss.py, ingest_knowledge.py
- `tests/` — Mock pipeline, full graph, and notify path integration tests
- `data/` — Directory structure with resume.json.template
- Pipeline test: 4 mock jobs → 3 scored >= 25 → notify + record all pass

### ❌ Not yet implemented
- `rag/` — Chroma RAG + embeddings (Phase 2)
- `crews/` — CrewAI resume optimizer (Phase 4)
- `mcp_servers/` — 5 MCP servers (Phase 3)
- `api/` — FastAPI for n8n
- Resume optimization pipeline
- Interactive chat mode
- RAG-enhanced explain command

## Project Structure

```
ai_agent/
├── main.py                      # CLI entry (run wired to LangGraph)
├── config/                      # settings.py — Pydantic Settings
├── models/                      # Job, MatchResult, OptimizedResume, LearningPlan, AgentState
├── scraper/                     # BossSession, BossScraper, parser (Playwright)
├── storage/                     # db.py — SQLAlchemy SQLite models
├── agent/                       # graph.py + nodes: scrape, match, notify, record
├── notifier/                    # feishu.py — webhook notifications
├── scripts/                     # login_boss.py, ingest_knowledge.py
├── tests/                       # Integration tests
├── data/                        # resume.json.template, knowledge/, resume_versions/
├── docs/ARCHITECTURE.md         # Architecture reference
└── .venv/                       # Python 3.14
```

## Tech Stack

Python 3.14 | LangGraph | Playwright | Pydantic v2 | SQLAlchemy | Chroma | OpenAI API | SQLite | Feishu webhook | httpx

## Key Constraints
- MCP servers are **decoupled from any single client**
- Resume optimization defaults to **Human-in-the-loop** — never auto-overwrite `data/resume.json`
- All resume bullets must have `evidence_source` — no fabricated experiences
- Secrets via env vars only, never hardcoded

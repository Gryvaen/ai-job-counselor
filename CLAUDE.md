# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**JobMatch Agent** — A LangGraph intelligent job search system. Scrapes positions from Boss Zhipin, matches against personal knowledge via RAG, optimizes resumes (LLM with rule fallback), and pushes notifications via Feishu webhooks. Optional MCP servers for IDE clients.

Read `docs/ARCHITECTURE.md` first for the full pipeline diagram, data models, and MCP server design.

## Current State

### Implemented (personal production baseline)
- `config/` — Pydantic Settings, logging, LLM helpers
- `models/` — Job, MatchResult, OptimizedResume, LearningPlan, AgentState
- `scraper/` — Playwright Boss scraper (retry, debug artifacts, cooldown)
- `storage/` — SQLite + search task persistence + Alembic indexes
- `notifier/` — Feishu webhook notifications
- `rag/` — Chroma ingest/retrieve wired into pipeline
- `agent/` — LangGraph full pipeline (plan → scrape → retrieve → match → optimize → review → notify → record)
- `crews/` — Resume optimizer + learning planner (LLM with rule fallback)
- `api/` — FastAPI Web Console (auth token, health checks, knowledge ingest, `/api/run`)
- `mcp_servers/` — 5 MCP servers (optional `pip install -e ".[agents]"`)
- `scripts/` — login_boss, ingest_knowledge, backup_data
- `tests/` — pytest suite + GitHub Actions CI

### Optional / future
- CrewAI multi-agent crews (architecture doc; current code uses single LLM calls)
- LLM-powered chat in WebUI (slash commands + rule routing today)
- Multi-tenant SaaS features

## Project Structure

```
ai_agent/
├── main.py                      # CLI entry (run/chat/explain)
├── api/server.py                # FastAPI Web Console
├── config/                      # settings, logging, llm helpers
├── models/                      # Pydantic models
├── scraper/                     # Boss Playwright automation
├── storage/db.py                # SQLite ORM + task persistence
├── agent/graph.py               # LangGraph StateGraph
├── rag/                         # Chroma RAG
├── crews/                       # Resume optimization
├── mcp_servers/                 # Optional MCP tools
├── scripts/                     # Ops scripts
├── alembic/                     # DB migrations
├── tests/                       # pytest
└── docs/ARCHITECTURE.md
```

## Tech Stack

Python 3.11+ | LangGraph | Playwright | Pydantic v2 | SQLAlchemy | Chroma | OpenAI/Ollama | SQLite | Feishu | FastAPI

## Key Constraints
- MCP servers are **decoupled from any single client**
- Resume optimization defaults to **Human-in-the-loop** — never auto-overwrite `data/resume.json`
- All resume bullets must have `evidence_source` — no fabricated experiences
- Secrets via env vars only; WebUI masks secrets in GET `/api/config`
- Set `WEBUI_API_TOKEN` when exposing the API beyond localhost

## Common Commands

```bash
.venv/bin/python main.py run --keywords "Linux驱动,BSP" --city 上海
.venv/bin/python scripts/ingest_knowledge.py
.venv/bin/uvicorn api.server:app --host 127.0.0.1 --port 8000
.venv/bin/python -m pytest tests/ -q
./scripts/backup_data.sh
```

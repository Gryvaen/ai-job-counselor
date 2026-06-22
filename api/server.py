"""FastAPI web console for the JobMatch Agent workspace."""

from __future__ import annotations

import json
import logging
import os
import re
import asyncio
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import text
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from config.llm import llm_chat
from config.logging import setup_logging
from config.settings import settings
from config.settings import PROJECT_ROOT
from agent.nodes.plan_node import parse_job_query
from models.agent_state import AgentState
from models.job import Job
from scraper import BossSession
from scraper.session import BOSS_LOGIN_URL
from storage.db import (
    JobRecord,
    LearningPlanRecord,
    MatchRecord,
    ResumeVersionRecord,
    SearchTaskRecord,
    create_search_task as db_create_search_task,
    get_engine,
    get_search_task,
    get_session,
    latest_knowledge_ingest,
    prune_search_tasks,
    record_knowledge_ingest,
    update_search_task,
)

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
TASK_SCREENSHOT_DIR = settings.task_screenshots_dir


class ResumeGenerateRequest(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    skills: str = Field(default="", description="Comma or newline separated skills")
    target_role: str = Field(min_length=1)
    github_url: str = ""
    notes: str = ""


class ResumeImportRequest(BaseModel):
    content: str = Field(min_length=20, description="Raw pasted resume text, Markdown, or JSON")
    target_roles: str = ""
    cities: str = ""
    source_label: str = "pasted_resume"


class ResumeImportResponse(BaseModel):
    profile: dict
    saved_path: str
    extracted: dict
    message: str


class GithubProject(BaseModel):
    name: str
    url: str
    description: str = ""
    language: str = ""
    stars: int = 0
    topics: list[str] = Field(default_factory=list)
    updated_at: str = ""


class ResumeGenerateResponse(BaseModel):
    markdown: str
    skills: list[str]
    github_user: str | None = None
    projects: list[GithubProject] = Field(default_factory=list)
    saved_path: str | None = None
    gaps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class JobSearchRequest(BaseModel):
    keywords: str = Field(min_length=1)
    city: str = "全国"
    threshold: int = Field(default=settings.match_threshold, ge=0, le=100)


class JobSearchResponse(BaseModel):
    jobs_scraped: int
    matches_scored: int
    resumes_generated: int
    notified: int
    jobs: list[dict]
    message: str


class SearchTaskCreateResponse(BaseModel):
    task_id: str
    status: str
    message: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    reply: str
    action: str
    data: dict = Field(default_factory=dict)


class ResumeProfileSaveRequest(BaseModel):
    profile: dict


class JobStatusRequest(BaseModel):
    status: str = Field(pattern="^(draft|interested|ignored|applied)$")


class AppConfig(BaseModel):
    model_provider: str = Field(default="openai", pattern="^(openai|ollama)$")
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    ollama_base_url: str = "http://127.0.0.1:11434/v1"
    ollama_model: str = "qwen2.5:7b"
    ollama_embedding_model: str = "nomic-embed-text"
    feishu_webhook: str = ""
    resume_path: str = "data/resume.json"
    boss_state_path: str = "data/boss_state.json"
    knowledge_dir: str = "data/knowledge"
    resume_versions_dir: str = "data/resume_versions"
    db_path: str = "data/jobmatch.db"
    chroma_dir: str = "storage/vector_store"
    rag_chunk_size: int = Field(default=512, ge=64, le=8192)
    rag_chunk_overlap: int = Field(default=64, ge=0, le=4096)
    rag_top_k: int = Field(default=5, ge=1, le=50)
    match_threshold: int = Field(default=75, ge=0, le=100)
    boss_auto_open_browser: bool = True
    webui_api_token: str = ""


class KnowledgeIngestResponse(BaseModel):
    chunks: int
    source_dir: str
    message: str


class PipelineRunRequest(BaseModel):
    keywords: str = Field(min_length=1)
    city: str = "全国"
    threshold: int = Field(default=settings.match_threshold, ge=0, le=100)


app = FastAPI(title="JobMatch Agent Web Console")


class ApiTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = settings.webui_api_token.strip()
        if not token:
            return await call_next(request)
        path = request.url.path
        if path in {"/api/health", "/"} or path.startswith("/static"):
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if auth == f"Bearer {token}":
            return await call_next(request)
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})


app.add_middleware(ApiTokenMiddleware)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

TASK_LOCK = threading.Lock()
SEARCH_RUN_LOCK = threading.Lock()
BOSS_LOGIN_LOCK = threading.Lock()
BOSS_LOGIN_LOOP: asyncio.AbstractEventLoop | None = None
BOSS_LOGIN_SESSION: BossSession | None = None
BOSS_LOGIN_STOP: threading.Event | None = None
BOSS_LOGIN_THREAD: threading.Thread | None = None
TASK_TTL_SECONDS = 60 * 60 * 6
BOSS_LOGIN_WAIT_SECONDS = 60 * 10


SLASH_COMMANDS = [
    {
        "name": "/search",
        "label": "搜索岗位",
        "usage": "/search <city> <job> [score]",
        "params": "<city> <job> [score]",
        "example": "/search 上海 Linux驱动 BSP 80分以上",
        "description": "打开 Boss 并按城市、关键词、匹配分运行完整岗位搜索。",
    },
    {
        "name": "/status",
        "label": "查看状态",
        "usage": "/status",
        "params": "",
        "example": "/status",
        "description": "查看岗位、匹配、简历版本和学习计划数量。",
    },
    {
        "name": "/matches",
        "label": "匹配结果",
        "usage": "/matches",
        "params": "",
        "example": "/matches",
        "description": "跳转到匹配结果页面。",
    },
    {
        "name": "/versions",
        "label": "简历版本",
        "usage": "/versions",
        "params": "",
        "example": "/versions",
        "description": "跳转到定制简历版本页面。",
    },
    {
        "name": "/resume",
        "label": "简历建议",
        "usage": "/resume <target_role>",
        "params": "<target_role>",
        "example": "/resume 嵌入式 Linux 驱动",
        "description": "基于简历事实档案给出定制简历建议。",
    },
    {
        "name": "/profile",
        "label": "简历档案",
        "usage": "/profile",
        "params": "",
        "example": "/profile",
        "description": "跳转到简历事实档案。",
    },
    {
        "name": "/settings",
        "label": "设置",
        "usage": "/settings",
        "params": "",
        "example": "/settings",
        "description": "跳转到模型、Boss 登录态和数据路径设置。",
    },
    {
        "name": "/help",
        "label": "帮助",
        "usage": "/help",
        "params": "",
        "example": "/help",
        "description": "列出可用 slash 指令。",
    },
]


@app.on_event("startup")
def startup() -> None:
    setup_logging()
    get_engine(settings.db_path)
    settings.resume_versions_dir.mkdir(parents=True, exist_ok=True)
    settings.task_screenshots_dir.mkdir(parents=True, exist_ok=True)
    _fail_interrupted_search_tasks()
    prune_search_tasks(TASK_TTL_SECONDS)
    if settings.sentry_dsn:
        try:
            import sentry_sdk
            sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.1)
        except Exception as exc:
            logger.warning("Sentry init failed: %s", exc)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def _check_db() -> tuple[bool, str]:
    try:
        with get_session() as sess:
            sess.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def _fail_interrupted_search_tasks() -> None:
    try:
        with get_session() as sess:
            rows = (
                sess.query(SearchTaskRecord)
                .filter(SearchTaskRecord.status.in_(("queued", "running")))
                .all()
            )
            now = datetime.now()
            for row in rows:
                row.status = "failed"
                row.stage = "failed"
                row.progress = max(int(row.progress or 0), 1)
                row.message = "服务已重启，旧搜索任务已停止。请重新发起搜索。"
                row.error = row.message
                row.updated_at = now
            sess.commit()
            if rows:
                logger.info("Marked %d interrupted search tasks as failed.", len(rows))
    except Exception as exc:
        logger.warning("Failed to mark interrupted search tasks: %s", exc)


def _check_chroma() -> tuple[bool, str]:
    try:
        from rag.retriever import RAGRetriever
        retriever = RAGRetriever()
        retriever.list_sources()
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


async def _check_ollama() -> tuple[bool, str]:
    if settings.model_provider.lower().strip() != "ollama":
        return True, "skipped"
    url = settings.ollama_base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{url}/models")
            resp.raise_for_status()
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


@app.get("/api/health")
async def health() -> dict:
    db_ok, db_msg = _check_db()
    chroma_ok, chroma_msg = _check_chroma()
    ollama_ok, ollama_msg = await _check_ollama()
    checks = {
        "database": {"ok": db_ok, "detail": db_msg},
        "chroma": {"ok": chroma_ok, "detail": chroma_msg},
        "ollama": {"ok": ollama_ok, "detail": ollama_msg},
    }
    all_ok = all(item["ok"] for item in checks.values())
    any_fail = any(not item["ok"] for item in checks.values() if item["detail"] != "skipped")
    status = "ok" if all_ok else ("degraded" if any_fail else "ok")
    ingest = latest_knowledge_ingest()
    return {
        "ok": status == "ok",
        "status": status,
        "time": datetime.now().isoformat(timespec="seconds"),
        "db_path": str(settings.db_path),
        "resume_exists": settings.resume_path.exists(),
        "boss_login_exists": BossSession(settings.boss_state_path).has_saved_login(),
        "openai_configured": bool(settings.openai_api_key),
        "model_provider": settings.model_provider,
        "ollama_configured": bool(settings.ollama_base_url and settings.ollama_model),
        "feishu_configured": bool(settings.feishu_webhook),
        "auth_required": bool(settings.webui_api_token.strip()),
        "checks": checks,
        "knowledge_ingest": ingest,
    }


@app.get("/api/commands")
def list_commands() -> dict:
    return {"commands": SLASH_COMMANDS}


@app.post("/api/boss/login/start")
def start_boss_login() -> dict:
    global BOSS_LOGIN_THREAD
    if not os.environ.get("DISPLAY"):
        raise HTTPException(
            status_code=409,
            detail=(
                "当前 WebUI 运行环境没有可视化浏览器 DISPLAY，无法从容器里弹出 Boss 登录页。"
                "请在宿主机项目目录运行 .venv/bin/python scripts/login_boss.py 完成登录，"
                "登录态会写入 data/boss_state.json，当前搜索会检测到后继续。"
            ),
        )

    with BOSS_LOGIN_LOCK:
        if BOSS_LOGIN_THREAD and BOSS_LOGIN_THREAD.is_alive():
            return {
                "status": "opening",
                "message": "Boss 登录页已打开。登录完成后请点击“已完成登录”。",
            }

    ready = threading.Event()
    stop = threading.Event()
    error: dict[str, str] = {}

    def _login_worker() -> None:
        global BOSS_LOGIN_LOOP, BOSS_LOGIN_SESSION, BOSS_LOGIN_STOP, BOSS_LOGIN_THREAD
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        session: BossSession | None = None

        async def _wait_until_done() -> None:
            assert session is not None
            while not stop.is_set():
                if session._chrome_process and session._chrome_process.poll() is not None:
                    break
                await asyncio.sleep(1)

        async def _run() -> None:
            global BOSS_LOGIN_LOOP, BOSS_LOGIN_SESSION, BOSS_LOGIN_STOP
            nonlocal session
            session = BossSession(
                settings.boss_state_path,
                restore_state=False,
                fresh_login=False,
            )
            await session.start(headless=False, initial_url=BOSS_LOGIN_URL)
            with BOSS_LOGIN_LOCK:
                BOSS_LOGIN_LOOP = loop
                BOSS_LOGIN_SESSION = session
                BOSS_LOGIN_STOP = stop
            ready.set()
            await _wait_until_done()

        try:
            loop.run_until_complete(_run())
        except Exception as exc:
            error["message"] = str(exc)
            ready.set()
            logger.exception("Boss login helper failed")
        finally:
            async def _run() -> None:
                if session:
                    await session.close()
            try:
                loop.run_until_complete(_run())
            except Exception:
                logger.exception("Boss login cleanup failed")
            with BOSS_LOGIN_LOCK:
                if BOSS_LOGIN_LOOP is loop:
                    BOSS_LOGIN_LOOP = None
                    BOSS_LOGIN_SESSION = None
                    BOSS_LOGIN_STOP = None
                    BOSS_LOGIN_THREAD = None
            loop.close()

    thread = threading.Thread(target=_login_worker, name="jobmatch-boss-login", daemon=True)
    with BOSS_LOGIN_LOCK:
        BOSS_LOGIN_THREAD = thread
    thread.start()
    if not ready.wait(timeout=15):
        raise HTTPException(status_code=504, detail="打开 Boss 登录浏览器超时，请稍后重试。")
    if error:
        raise HTTPException(status_code=500, detail=error["message"])
    return {
        "status": "opening",
        "message": "已打开 Boss 登录页。请手动完成登录，然后点击“已完成登录”。",
    }


@app.post("/api/boss/login/save")
def save_boss_login() -> dict:
    with BOSS_LOGIN_LOCK:
        loop = BOSS_LOGIN_LOOP
        session = BOSS_LOGIN_SESSION
        stop = BOSS_LOGIN_STOP
    if not loop or not session:
        raise HTTPException(status_code=409, detail="Boss 登录浏览器未打开，请先点击“打开 Boss 登录页”。")

    try:
        future = asyncio.run_coroutine_threadsafe(session.save_current_login(), loop)
        saved = future.result(timeout=15)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"保存 Boss 登录态失败: {exc}") from exc

    if not saved:
        raise HTTPException(
            status_code=409,
            detail="没有读到 Boss 登录 cookie。请确认已在刚弹出的 Boss 浏览器窗口中完成登录。",
        )
    if stop:
        stop.set()
    return {"status": "saved", "message": "Boss 登录态已保存，搜索任务会自动继续。"}


@app.get("/api/config", response_model=AppConfig)
def get_config() -> AppConfig:
    return _settings_to_config()


@app.get("/api/models")
async def list_models(provider: str = "ollama", base_url: str = "") -> dict:
    provider = provider.lower().strip()
    if provider == "ollama":
        url = (base_url or settings.ollama_base_url).rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{url}/models")
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            return {
                "provider": provider,
                "chat_models": [],
                "embedding_models": [],
                "warning": f"无法读取 Ollama 模型列表: {exc}",
            }
        models = [item.get("id", "") for item in data.get("data", []) if item.get("id")]
        return {
            "provider": provider,
            "chat_models": models,
            "embedding_models": models,
            "warning": "" if models else "Ollama 当前没有返回模型，请先 pull 模型。",
        }

    return {
        "provider": "openai",
        "chat_models": [
            "gpt-4o-mini",
            "gpt-4o",
            "deepseek-chat",
            "deepseek-reasoner",
            "qwen-plus",
            "qwen-turbo",
        ],
        "embedding_models": [
            "text-embedding-3-small",
            "text-embedding-3-large",
        ],
        "warning": "",
    }


@app.post("/api/knowledge/ingest", response_model=KnowledgeIngestResponse)
def ingest_knowledge() -> KnowledgeIngestResponse:
    from rag.ingest import ingest_directory

    try:
        chunks = ingest_directory(settings.knowledge_dir)
        record_knowledge_ingest(chunks, str(settings.knowledge_dir))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"知识库入库失败: {exc}") from exc
    return KnowledgeIngestResponse(
        chunks=chunks,
        source_dir=str(settings.knowledge_dir),
        message=f"已索引 {chunks} 个文本块。",
    )


@app.get("/api/knowledge/status")
def knowledge_status() -> dict:
    from rag.retriever import RAGRetriever

    ingest = latest_knowledge_ingest()
    sources = RAGRetriever().list_sources()
    return {
        "knowledge_dir": str(settings.knowledge_dir),
        "latest_ingest": ingest,
        "indexed_sources": len(sources),
        "sources": sources[:20],
    }


@app.post("/api/run", response_model=JobSearchResponse)
def run_pipeline(payload: PipelineRunRequest) -> JobSearchResponse:
    keywords = _parse_keywords(payload.keywords)
    if not keywords:
        raise HTTPException(status_code=400, detail="请输入至少一个岗位关键词")
    return _run_job_search(
        keywords=keywords,
        city=payload.city or "全国",
        threshold=payload.threshold,
        user_query=payload.keywords,
    )


@app.put("/api/config")
def save_config(payload: AppConfig) -> dict:
    if payload.rag_chunk_overlap >= payload.rag_chunk_size:
        raise HTTPException(status_code=400, detail="RAG overlap 必须小于 chunk size")

    _write_env(payload)
    _apply_config(payload)
    get_engine(settings.db_path)
    settings.resume_path.parent.mkdir(parents=True, exist_ok=True)
    settings.resume_versions_dir.mkdir(parents=True, exist_ok=True)
    settings.knowledge_dir.mkdir(parents=True, exist_ok=True)
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    return {
        "ok": True,
        "message": "配置已保存到 .env，并已同步到当前 Web 进程。",
        "config": _settings_to_config(mask_secrets=True).model_dump(),
    }


@app.get("/api/dashboard")
def dashboard() -> dict:
    with get_session() as sess:
        jobs = sess.query(JobRecord).count()
        matches = sess.query(MatchRecord).count()
        resumes = sess.query(ResumeVersionRecord).count()
        plans = sess.query(LearningPlanRecord).count()
        latest_jobs = _jobs_with_matches(sess, limit=6)
    return {
        "metrics": {
            "jobs": jobs,
            "matches": matches,
            "resumes": resumes,
            "plans": plans,
        },
        "latest_jobs": latest_jobs,
    }


@app.get("/api/resume-profile")
def get_resume_profile() -> dict:
    if not settings.resume_path.exists():
        return _empty_resume_profile()
    try:
        return json.loads(settings.resume_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"resume.json 格式错误: {exc}") from exc


@app.put("/api/resume-profile")
def save_resume_profile(payload: ResumeProfileSaveRequest) -> dict:
    settings.resume_path.parent.mkdir(parents=True, exist_ok=True)
    settings.resume_path.write_text(
        json.dumps(payload.profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"ok": True, "path": str(settings.resume_path)}


@app.post("/api/import-resume", response_model=ResumeImportResponse)
def import_resume(payload: ResumeImportRequest) -> ResumeImportResponse:
    profile = _profile_from_resume_text(payload)
    settings.resume_path.parent.mkdir(parents=True, exist_ok=True)
    settings.resume_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    extracted = {
        "skills": len(profile.get("skills", [])),
        "projects": len(profile.get("projects", [])),
        "experience": len(profile.get("experience", [])),
        "target_roles": profile.get("preferences", {}).get("target_roles", []),
        "cities": profile.get("preferences", {}).get("cities", []),
    }
    return ResumeImportResponse(
        profile=profile,
        saved_path=str(settings.resume_path),
        extracted=extracted,
        message="已从传入简历生成新的简历事实档案，后续 /search 和定制简历都会使用这份档案。",
    )


@app.post("/api/generate-resume", response_model=ResumeGenerateResponse)
async def generate_resume(payload: ResumeGenerateRequest) -> ResumeGenerateResponse:
    skills = _parse_skills(payload.skills)
    github_user = _github_user_from_url(payload.github_url)
    projects: list[GithubProject] = []
    warnings: list[str] = []
    if github_user:
        projects, warning = await _fetch_github_projects(github_user)
        if warning:
            warnings.append(warning)
    markdown = _build_resume_markdown(payload, skills, projects)
    saved_path = _save_generated_resume(payload.target_role, markdown)
    gaps = _infer_gaps(payload.target_role, skills, projects)
    return ResumeGenerateResponse(
        markdown=markdown,
        skills=skills,
        github_user=github_user,
        projects=projects,
        saved_path=str(saved_path),
        gaps=gaps,
        warnings=warnings,
    )


@app.post("/api/jobs/search", response_model=JobSearchResponse)
def search_jobs(payload: JobSearchRequest) -> JobSearchResponse:
    keywords = _parse_keywords(payload.keywords)
    if not keywords:
        raise HTTPException(status_code=400, detail="请输入至少一个岗位关键词")

    return _run_job_search(
        keywords=keywords,
        city=payload.city or "全国",
        threshold=payload.threshold,
        user_query=payload.keywords,
    )


@app.post("/api/jobs/search/tasks", response_model=SearchTaskCreateResponse)
def create_search_task_endpoint(payload: JobSearchRequest) -> SearchTaskCreateResponse:
    keywords = _parse_keywords(payload.keywords)
    if not keywords:
        raise HTTPException(status_code=400, detail="请输入至少一个岗位关键词")

    task_id = uuid.uuid4().hex
    task = {
        "id": task_id,
        "type": "job_search",
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "message": "任务已排队，等待 Agent 开始搜索。",
        "request": {
            "keywords": keywords,
            "city": payload.city or "全国",
            "threshold": payload.threshold,
            "user_query": payload.keywords,
        },
        "events": [],
        "login_screenshot": "",
        "login_screenshot_url": "",
        "result": None,
        "error": "",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    with TASK_LOCK:
        prune_search_tasks(TASK_TTL_SECONDS)
        db_create_search_task(task)
    _append_task_event(task_id, "queued", 0, "任务已排队，等待 Agent 开始搜索。")
    try:
        _start_search_task(task_id)
    except Exception as exc:
        _fail_task(task_id, f"搜索任务启动失败: {exc}")
    return SearchTaskCreateResponse(
        task_id=task_id,
        status="queued",
        message="搜索任务已创建。",
    )


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    task = get_search_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return task


@app.get("/api/tasks/{task_id}/login-screenshot")
def get_task_login_screenshot(task_id: str) -> FileResponse:
    path = TASK_SCREENSHOT_DIR / f"{task_id}.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="登录截图不存在")
    return FileResponse(path, media_type="image/png")


def _run_job_search(
    keywords: list[str],
    city: str,
    threshold: int,
    user_query: str,
) -> JobSearchResponse:
    try:
        from agent.graph import build_graph

        graph = build_graph()
        state: AgentState = {
            "user_query": user_query,
            "keywords": keywords,
            "city": city,
            "threshold": threshold,
            "jobs": [],
            "retrieved_context": [],
            "match_results": [],
            "optimized_resumes": [],
            "learning_plans": [],
            "notified": [],
            "messages": [],
        }
        result = graph.invoke(state)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"岗位搜索流水线失败: {exc}") from exc

    with get_session() as sess:
        jobs = _jobs_with_matches(sess, limit=30)

    return JobSearchResponse(
        jobs_scraped=len(result.get("jobs", [])),
        matches_scored=len(result.get("match_results", [])),
        resumes_generated=len(result.get("optimized_resumes", [])),
        notified=len(result.get("notified", [])),
        jobs=jobs,
        message=f"已完成 {city} · {', '.join(keywords)} 搜索和匹配。",
    )


def _boss_state_stamp() -> tuple[int, int] | None:
    try:
        stat = settings.boss_state_path.stat()
        return (stat.st_mtime_ns, stat.st_size)
    except FileNotFoundError:
        return None


def _wait_for_boss_login(
    task_id: str,
    *,
    require_state_change: bool = False,
    previous_stamp: tuple[int, int] | None = None,
) -> None:
    if not require_state_change and BossSession(settings.boss_state_path).has_saved_login():
        return

    _append_task_event(
        task_id,
        "login",
        10,
        "需要先登录 Boss。请点击任务中的“打开 Boss 登录页”，并在浏览器里手动完成登录。",
    )
    deadline = time.monotonic() + BOSS_LOGIN_WAIT_SECONDS
    while time.monotonic() < deadline:
        state_changed = _boss_state_stamp() != previous_stamp
        if BossSession(settings.boss_state_path).has_saved_login() and (
            not require_state_change or state_changed
        ):
            _append_task_event(task_id, "login", 18, "已检测到 Boss 登录态，继续搜索。")
            return
        time.sleep(2)

    raise RuntimeError("等待 Boss 登录超时，请重新发起搜索并点击“打开 Boss 登录页”完成登录。")


def _run_search_task(task_id: str) -> None:
    acquired = SEARCH_RUN_LOCK.acquire(blocking=False)
    if not acquired:
        _append_task_event(task_id, "waiting", 2, "已有搜索任务正在运行，本任务等待上一轮结束。")
        SEARCH_RUN_LOCK.acquire()

    task = get_search_task(task_id)
    if not task:
        SEARCH_RUN_LOCK.release()
        return
    request = dict(task["request"])

    try:
        _append_task_event(task_id, "starting", 4, "Agent 线程已启动，正在准备搜索环境。")
        _wait_for_boss_login(task_id)
        result = _run_job_search_with_progress(
            keywords=request["keywords"],
            city=request["city"],
            threshold=request["threshold"],
            user_query=request["user_query"],
            progress=lambda stage, pct, msg: _append_task_event(task_id, stage, pct, msg),
            login_wait_callback=lambda previous_stamp=None: _wait_for_boss_login(
                task_id,
                require_state_change=previous_stamp is not None,
                previous_stamp=previous_stamp,
            ),
            login_screenshot_callback=lambda image: _update_task_login_screenshot(task_id, image),
            login_started_callback=lambda: _append_task_event(
                task_id,
                "login",
                20,
                "Boss 登录态失效。请点击任务中的“打开 Boss 登录页”，并在浏览器里手动完成登录。",
            ),
        )
        update_search_task(
            task_id,
            status="completed",
            stage="completed",
            progress=100,
            message=result.message,
            result=result.model_dump(),
        )
        _append_task_event(task_id, "completed", 100, result.message)
    except Exception as exc:
        logger.exception("Search task %s failed", task_id)
        _fail_task(task_id, f"搜索失败: {exc}")
    finally:
        SEARCH_RUN_LOCK.release()


def _start_search_task(task_id: str) -> None:
    thread = threading.Thread(
        target=_run_search_task,
        args=(task_id,),
        name=f"jobmatch-search-{task_id[:8]}",
        daemon=True,
    )
    thread.start()


def _fail_task(task_id: str, message: str) -> None:
    task = get_search_task(task_id)
    if not task:
        return
    progress = max(int(task.get("progress", 0)), 1)
    update_search_task(
        task_id,
        status="failed",
        stage="failed",
        progress=progress,
        message=message,
        error=message,
    )
    _append_task_event(task_id, "failed", 100, message)


def _run_job_search_with_progress(
    keywords: list[str],
    city: str,
    threshold: int,
    user_query: str,
    progress,
    login_wait_callback=None,
    login_screenshot_callback=None,
    login_started_callback=None,
) -> JobSearchResponse:
    from agent.nodes.match_node import match_node
    from agent.nodes.notify_node import notify_node
    from agent.nodes.optimize_node import optimize_node
    from agent.nodes.plan_node import plan_node
    from agent.nodes.record_node import record_node
    from agent.nodes.retrieve_node import retrieve_node
    from agent.nodes.review_node import review_node
    from agent.nodes.scrape_node import scrape_node

    state: AgentState = {
        "user_query": user_query,
        "keywords": keywords,
        "city": city,
        "threshold": threshold,
        "jobs": [],
        "retrieved_context": [],
        "match_results": [],
        "optimized_resumes": [],
        "learning_plans": [],
        "notified": [],
        "messages": [],
        "login_screenshot_callback": login_screenshot_callback,
        "login_started_callback": login_started_callback,
    }

    def apply_update(update: dict | None) -> None:
        if update:
            state.update(update)

    progress("planning", 8, f"解析搜索意图: {city} · {', '.join(keywords)}")
    apply_update(plan_node(state))

    progress("scraping", 18, "打开 Boss 并检索岗位。若登录态失效，任务会提示你手动登录。")
    previous_stamp = _boss_state_stamp()
    scrape_update = scrape_node(state)
    apply_update(scrape_update)
    scrape_error = scrape_update.get("scrape_error", "")
    if scrape_error == "login_required" and login_wait_callback:
        progress("login", 20, "Boss 登录态失效。请点击任务中的“打开 Boss 登录页”，并在浏览器里手动完成登录。")
        login_wait_callback(previous_stamp)
        progress("scraping", 24, "已检测到新的 Boss 登录态，正在重新检索岗位。")
        scrape_update = scrape_node(state)
        apply_update(scrape_update)
        scrape_error = scrape_update.get("scrape_error", "")
    if scrape_error == "no_jobs_found":
        progress("scraping", 22, "Boss 未返回岗位，可能登录失效或页面结构变化。请检查 data/debug/ 调试产物。")
    elif scrape_error:
        raise RuntimeError(f"Boss 采集失败: {scrape_error}")

    progress("retrieving", 45, f"抓取到 {len(state.get('jobs', []))} 个新岗位，正在检索个人知识库证据。")
    apply_update(retrieve_node(state))

    progress("matching", 62, "正在计算岗位与简历事实档案的匹配分。")
    apply_update(match_node(state))

    high = [r for r in state.get("match_results", []) if r.score >= threshold]
    if high:
        progress("optimizing", 76, f"发现 {len(high)} 个高匹配岗位，正在生成定制简历和学习计划。")
        apply_update(optimize_node(state))
        progress("reviewing", 86, "正在复核简历草稿、ATS 覆盖和待核实内容。")
        apply_update(review_node(state))
        progress("notifying", 93, "正在发送通知并准备写入记录。")
        apply_update(notify_node(state))
    else:
        progress("reviewing", 82, "暂无达到阈值的岗位，跳过简历生成并准备写入记录。")

    progress("recording", 96, "正在保存岗位、匹配结果、简历版本和学习计划。")
    apply_update(record_node(state))

    with get_session() as sess:
        jobs = _jobs_with_matches(sess, limit=30)

    return JobSearchResponse(
        jobs_scraped=len(state.get("jobs", [])),
        matches_scored=len(state.get("match_results", [])),
        resumes_generated=len(state.get("optimized_resumes", [])),
        notified=len(state.get("notified", [])),
        jobs=jobs,
        message=f"已完成 {city} · {', '.join(keywords)} 搜索和匹配。",
    )


@app.get("/api/jobs")
def list_jobs(limit: int = 50) -> dict:
    with get_session() as sess:
        return {"jobs": _jobs_with_matches(sess, limit=limit)}


@app.get("/api/jobs/{job_id}")
def get_job_detail(job_id: str) -> dict:
    with get_session() as sess:
        job = sess.get(JobRecord, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="岗位不存在")
        match = _latest_match(sess, job_id)
        resume = _latest_resume(sess, job_id)
        plan = _latest_plan(sess, job_id)
        return {
            "job": _job_record_to_dict(job),
            "match": _match_record_to_dict(match) if match else None,
            "resume": _resume_record_to_dict(resume) if resume else None,
            "learning_plan": _plan_record_to_dict(plan) if plan else None,
        }


@app.post("/api/jobs/{job_id}/generate-resume")
def generate_resume_for_job(job_id: str) -> dict:
    with get_session() as sess:
        job_record = sess.get(JobRecord, job_id)
        match = _latest_match(sess, job_id)
    if not job_record:
        raise HTTPException(status_code=404, detail="岗位不存在")
    if not match:
        raise HTTPException(status_code=400, detail="该岗位还没有匹配结果，无法生成定制简历")

    try:
        from crews.learning_planner import generate_learning_plan
        from crews.resume_optimizer import load_resume, optimize_for_job, save_resume_version
        from storage.db import save_learning_plan, save_resume_version as save_resume_record

        resume_source = load_resume()
        job = Job(**_job_record_to_dict(job_record))
        match_model = _match_record_to_model(match)
        optimized = optimize_for_job(job, match_model, resume_source)
        version_path = save_resume_version(optimized)
        plan = generate_learning_plan(job.id, match_model.missing, resume_source.get("preferences", {}).get("city", job.city))
        with get_session() as sess:
            save_resume_record(sess, optimized, file_path=str(version_path))
            save_learning_plan(sess, plan)
            sess.commit()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"生成定制简历失败: {exc}") from exc

    return {
        "resume": {
            "job_id": optimized.job_id,
            "title": optimized.title,
            "company": optimized.company,
            "content_md": optimized.full_markdown,
            "file_path": str(version_path),
            "ats_keyword_coverage": optimized.ats_keyword_coverage,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        },
        "learning_plan": {
            "job_id": plan.job_id,
            "priority_skills": plan.priority_skills,
            "weekly_plan": plan.weekly_plan,
            "estimated_hours": plan.estimated_hours,
        },
    }


@app.post("/api/jobs/{job_id}/status")
def update_job_status(job_id: str, payload: JobStatusRequest) -> dict:
    # The current schema tracks status on resume versions. This endpoint is a
    # small bridge for the UI until a dedicated applications table is added.
    with get_session() as sess:
        resume = _latest_resume(sess, job_id)
        if not resume:
            resume = ResumeVersionRecord(job_id=job_id, status=payload.status, content_md="")
            sess.add(resume)
        else:
            resume.status = payload.status
        sess.commit()
    return {"ok": True, "job_id": job_id, "status": payload.status}


@app.get("/api/resume-versions")
def list_resume_versions(limit: int = 50) -> dict:
    with get_session() as sess:
        rows = (
            sess.query(ResumeVersionRecord)
            .order_by(ResumeVersionRecord.created_at.desc())
            .limit(limit)
            .all()
        )
        return {"versions": [_resume_record_to_dict(row) for row in rows]}


@app.get("/api/resume-versions/{version_id}")
def get_resume_version(version_id: int) -> dict:
    with get_session() as sess:
        row = sess.get(ResumeVersionRecord, version_id)
        if not row:
            raise HTTPException(status_code=404, detail="简历版本不存在")
        return {"version": _resume_record_to_dict(row)}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    text = payload.message.strip()
    lower = text.lower()

    if text.startswith("/"):
        return _handle_slash_command(text)

    action = "general"
    data: dict = {}
    context_parts: list[str] = []

    if any(word in text for word in ["找工作", "搜岗位", "搜索岗位", "找岗位"]):
        keywords, city, threshold = _parse_search_intent(text)
        action = "suggest_search"
        data = {"keywords": ",".join(keywords), "city": city, "threshold": threshold}
        context_parts.append(
            f"用户想找岗位。建议关键词: {', '.join(keywords)}，城市: {city}，匹配阈值: {threshold}。"
            "可引导使用 /search 命令启动搜索。"
        )

    elif any(word in text for word in ["改简历", "优化简历", "修改简历", "简历模板"]):
        profile = get_resume_profile()
        roles = profile.get("preferences", {}).get("target_roles", [])
        action = "resume_advice"
        data = {"profile": profile}
        context_parts.append(
            f"用户想优化简历。目标岗位: {'、'.join(roles) if roles else '未设置'}。"
            "只能基于 resume.json 事实改写，不得编造经历。"
        )

    elif "状态" in text or "概览" in text or "dashboard" in lower:
        dash = dashboard()
        metrics = dash["metrics"]
        action = "dashboard"
        data = dash
        context_parts.append(
            f"系统概览: {metrics['jobs']} 个岗位、{metrics['matches']} 条匹配、"
            f"{metrics['resumes']} 版简历、{metrics['plans']} 个学习计划。"
        )

    reply = llm_chat(text, context="\n".join(context_parts))
    if reply:
        return ChatResponse(action=action, reply=reply, data=data)

    if action == "suggest_search":
        keywords = data.get("keywords", "").split(",")
        city = data.get("city", "全国")
        return ChatResponse(
            action=action,
            reply=f"我建议搜索 {city} 的这些关键词: {', '.join(keywords)}。输入 /search 启动搜索。（LLM 未配置或不可用）",
            data=data,
        )
    if action == "resume_advice":
        return ChatResponse(
            action=action,
            reply="可以。我会基于 resume.json 的事实来改，不编造经历。（LLM 未配置或不可用）",
            data=data,
        )
    if action == "dashboard":
        metrics = data["metrics"]
        return ChatResponse(
            action=action,
            reply=(
                f"当前已记录 {metrics['jobs']} 个岗位、{metrics['matches']} 条匹配、"
                f"{metrics['resumes']} 版简历、{metrics['plans']} 个学习计划。（LLM 未配置或不可用）"
            ),
            data=data,
        )

    return ChatResponse(
        action="general",
        reply="LLM 未配置或暂时不可用。请检查设置页的 MODEL_PROVIDER 和 Ollama 连接，或使用 /help 查看指令。",
        data={},
    )


def _handle_slash_command(text: str) -> ChatResponse:
    command, _, raw_args = text.partition(" ")
    command = command.lower().strip()
    args = raw_args.strip()
    command = _resolve_slash_command(command)

    if command in {"/help", "/"}:
        lines = ["可用指令:"]
        lines.extend(f"{item['usage']} - {item['description']}" for item in SLASH_COMMANDS)
        return ChatResponse(action="help", reply="\n".join(lines), data={"commands": SLASH_COMMANDS})

    if command == "/search":
        keywords, city, threshold = _parse_search_intent(args)
        if not keywords:
            raise HTTPException(status_code=400, detail="请在 /search 后输入岗位关键词，例如 /search 上海 Linux驱动 BSP")
        task = create_search_task_endpoint(JobSearchRequest(
            keywords=",".join(keywords),
            city=city,
            threshold=threshold,
        ))
        return ChatResponse(
            action="search_started",
            reply=(
                f"已启动搜索任务: {city} · {', '.join(keywords)}。\n"
                "我会在下方显示进度，完成后自动切到匹配结果。"
            ),
            data={
                "task_id": task.task_id,
                "keywords": ",".join(keywords),
                "city": city,
                "threshold": threshold,
            },
        )

    if command == "/status":
        data = dashboard()
        metrics = data["metrics"]
        return ChatResponse(
            action="dashboard",
            reply=f"当前已记录 {metrics['jobs']} 个岗位、{metrics['matches']} 条匹配、{metrics['resumes']} 版简历、{metrics['plans']} 个学习计划。",
            data=data,
        )

    if command == "/matches":
        return ChatResponse(action="navigate", reply="已切到匹配结果。", data={"view": "matches"})

    if command == "/versions":
        return ChatResponse(action="navigate", reply="已切到简历版本。", data={"view": "versions"})

    if command == "/profile":
        return ChatResponse(action="navigate", reply="已切到简历事实档案。", data={"view": "profile"})

    if command == "/settings":
        return ChatResponse(action="navigate", reply="已切到设置。", data={"view": "settings"})

    if command == "/resume":
        profile = get_resume_profile()
        target = args or "目标岗位"
        return ChatResponse(
            action="resume_advice",
            reply=f"进入简历模式。针对 {target}，我会只使用简历事实档案里的经历，优先强化项目证据、关键词覆盖和可量化结果。",
            data={"profile": profile, "target_role": target},
        )

    return ChatResponse(
        action="unknown_command",
        reply=f"不认识 {command}。输入 /help 查看可用指令。",
        data={"commands": SLASH_COMMANDS},
    )


def _resolve_slash_command(command: str) -> str:
    if command in {"/", ""}:
        return command
    names = [item["name"] for item in SLASH_COMMANDS]
    if command in names:
        return command
    matches = [name for name in names if name.startswith(command)]
    return matches[0] if len(matches) == 1 else command


def _append_task_event(task_id: str, stage: str, progress: int, message: str) -> None:
    event = {
        "stage": stage,
        "progress": max(0, min(100, int(progress))),
        "message": message,
        "time": _now_iso(),
    }
    with TASK_LOCK:
        task = get_search_task(task_id)
        if not task:
            return
        events = list(task.get("events", []))
        events.append(event)
        events = events[-30:]
        status = task.get("status", "queued")
        if status not in {"failed", "completed"}:
            status = "running" if stage != "queued" else "queued"
        update_search_task(
            task_id,
            status=status,
            stage=stage,
            progress=event["progress"],
            message=message,
            events=events,
        )


def _update_task_login_screenshot(task_id: str, image: bytes) -> None:
    TASK_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = TASK_SCREENSHOT_DIR / f"{task_id}.png"
    path.write_bytes(image)
    current = get_search_task(task_id) or {}
    update_search_task(
        task_id,
        status="running",
        stage="login",
        progress=max(int(current.get("progress", 0)), 20),
        message="等待 Boss 登录。请在浏览器中手动完成登录，登录成功后任务会继续。",
        screenshot_path=str(path),
    )


def _mask_secret(value: str, keep_end: int = 4) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= keep_end + 3:
        return "***"
    return f"{'*' * 8}{value[-keep_end:]}"


def _mask_api_key(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith("sk-"):
        return f"sk-***{value[-4:]}" if len(value) > 7 else "sk-***"
    return _mask_secret(value)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _jobs_with_matches(sess, limit: int = 50) -> list[dict]:
    jobs = sess.query(JobRecord).order_by(JobRecord.scraped_at.desc()).limit(limit).all()
    return [_job_with_latest_records(sess, job) for job in jobs]


CONFIG_ENV_KEYS = {
    "model_provider": "MODEL_PROVIDER",
    "openai_api_key": "OPENAI_API_KEY",
    "openai_base_url": "OPENAI_BASE_URL",
    "openai_model": "OPENAI_MODEL",
    "openai_embedding_model": "OPENAI_EMBEDDING_MODEL",
    "ollama_base_url": "OLLAMA_BASE_URL",
    "ollama_model": "OLLAMA_MODEL",
    "ollama_embedding_model": "OLLAMA_EMBEDDING_MODEL",
    "feishu_webhook": "FEISHU_WEBHOOK",
    "resume_path": "RESUME_PATH",
    "boss_state_path": "BOSS_STATE_PATH",
    "knowledge_dir": "KNOWLEDGE_DIR",
    "resume_versions_dir": "RESUME_VERSIONS_DIR",
    "db_path": "DB_PATH",
    "chroma_dir": "CHROMA_DIR",
    "rag_chunk_size": "RAG_CHUNK_SIZE",
    "rag_chunk_overlap": "RAG_CHUNK_OVERLAP",
    "rag_top_k": "RAG_TOP_K",
    "match_threshold": "MATCH_THRESHOLD",
    "boss_auto_open_browser": "BOSS_AUTO_OPEN_BROWSER",
    "webui_api_token": "WEBUI_API_TOKEN",
}


def _settings_to_config(mask_secrets: bool = True) -> AppConfig:
    api_key = settings.openai_api_key
    webhook = settings.feishu_webhook
    token = settings.webui_api_token
    if mask_secrets:
        api_key = _mask_api_key(api_key)
        webhook = _mask_secret(webhook)
        token = _mask_secret(token) if token else ""
    return AppConfig(
        model_provider=settings.model_provider,
        openai_api_key=api_key,
        openai_base_url=_clean_config_value(settings.openai_base_url or ""),
        openai_model=settings.openai_model,
        openai_embedding_model=settings.openai_embedding_model,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
        ollama_embedding_model=settings.ollama_embedding_model,
        feishu_webhook=webhook,
        resume_path=_display_path(settings.resume_path),
        boss_state_path=_display_path(settings.boss_state_path),
        knowledge_dir=_display_path(settings.knowledge_dir),
        resume_versions_dir=_display_path(settings.resume_versions_dir),
        db_path=_display_path(settings.db_path),
        chroma_dir=_display_path(settings.chroma_dir),
        rag_chunk_size=settings.rag_chunk_size,
        rag_chunk_overlap=settings.rag_chunk_overlap,
        rag_top_k=settings.rag_top_k,
        match_threshold=settings.match_threshold,
        boss_auto_open_browser=settings.boss_auto_open_browser,
        webui_api_token=token,
    )


def _apply_config(config: AppConfig) -> None:
    if config.openai_api_key.strip() and not config.openai_api_key.strip().startswith("*"):
        settings.openai_api_key = config.openai_api_key.strip()
    settings.model_provider = config.model_provider.strip()
    settings.openai_base_url = config.openai_base_url.strip() or None
    settings.openai_model = config.openai_model.strip()
    settings.openai_embedding_model = config.openai_embedding_model.strip()
    settings.ollama_base_url = config.ollama_base_url.strip()
    settings.ollama_model = config.ollama_model.strip()
    settings.ollama_embedding_model = config.ollama_embedding_model.strip()
    if config.feishu_webhook.strip() and not config.feishu_webhook.strip().startswith("*"):
        settings.feishu_webhook = config.feishu_webhook.strip()
    if config.webui_api_token.strip() and not config.webui_api_token.strip().startswith("*"):
        settings.webui_api_token = config.webui_api_token.strip()
    settings.resume_path = _resolve_config_path(config.resume_path)
    settings.boss_state_path = _resolve_config_path(config.boss_state_path)
    settings.knowledge_dir = _resolve_config_path(config.knowledge_dir)
    settings.resume_versions_dir = _resolve_config_path(config.resume_versions_dir)
    settings.db_path = _resolve_config_path(config.db_path)
    settings.chroma_dir = _resolve_config_path(config.chroma_dir)
    settings.rag_chunk_size = config.rag_chunk_size
    settings.rag_chunk_overlap = config.rag_chunk_overlap
    settings.rag_top_k = config.rag_top_k
    settings.match_threshold = config.match_threshold
    settings.boss_auto_open_browser = config.boss_auto_open_browser


def _write_env(config: AppConfig) -> None:
    env_path = PROJECT_ROOT / ".env"
    current = _read_env_file(env_path)
    values = config.model_dump()
    for field, env_key in CONFIG_ENV_KEYS.items():
        if field not in values:
            continue
        current[env_key] = str(values[field]).strip()
    lines = ["# JobMatch Agent WebUI managed config"]
    for field, env_key in CONFIG_ENV_KEYS.items():
        lines.append(f"{env_key}={_env_quote(current.get(env_key, ''))}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = _env_unquote(value.strip())
    return values


def _env_quote(value: str) -> str:
    if value == "":
        return ""
    if re.search(r"\s|#|\"|'", value):
        return json.dumps(value, ensure_ascii=False)
    return value


def _env_unquote(value: str) -> str:
    if not (value.startswith('"') or value.startswith("'")) and "#" in value:
        value = value.split("#", 1)[0].strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    return value


def _clean_config_value(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("#"):
        return ""
    return stripped


def _resolve_config_path(value: str) -> Path:
    path = Path(value.strip()).expanduser()
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _job_with_latest_records(sess, job: JobRecord) -> dict:
    data = _job_record_to_dict(job)
    match = _latest_match(sess, job.id)
    resume = _latest_resume(sess, job.id)
    plan = _latest_plan(sess, job.id)
    data["match"] = _match_record_to_dict(match) if match else None
    data["resume"] = _resume_record_to_dict(resume) if resume else None
    data["learning_plan"] = _plan_record_to_dict(plan) if plan else None
    return data


def _latest_match(sess, job_id: str) -> MatchRecord | None:
    return (
        sess.query(MatchRecord)
        .filter(MatchRecord.job_id == job_id)
        .order_by(MatchRecord.matched_at.desc())
        .first()
    )


def _latest_resume(sess, job_id: str) -> ResumeVersionRecord | None:
    return (
        sess.query(ResumeVersionRecord)
        .filter(ResumeVersionRecord.job_id == job_id)
        .order_by(ResumeVersionRecord.created_at.desc())
        .first()
    )


def _latest_plan(sess, job_id: str) -> LearningPlanRecord | None:
    return (
        sess.query(LearningPlanRecord)
        .filter(LearningPlanRecord.job_id == job_id)
        .order_by(LearningPlanRecord.created_at.desc())
        .first()
    )


def _job_record_to_dict(job: JobRecord) -> dict:
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "salary": job.salary or "",
        "city": job.city or "",
        "description": job.description or "",
        "url": job.url or "",
        "scraped_at": job.scraped_at.isoformat(timespec="seconds") if job.scraped_at else "",
    }


def _match_record_to_dict(match: MatchRecord) -> dict:
    return {
        "id": match.id,
        "job_id": match.job_id,
        "score": match.score or 0,
        "advantages": _json_list(match.advantages),
        "missing": _json_list(match.missing),
        "suggestion": match.suggestion or "",
        "rag_evidence": _json_list(match.rag_evidence),
        "reasoning": match.reasoning or "",
        "matched_at": match.matched_at.isoformat(timespec="seconds") if match.matched_at else "",
    }


def _match_record_to_model(match: MatchRecord):
    from models.match import MatchResult

    suggestion = match.suggestion if match.suggestion in {"推荐投递", "观望", "不推荐"} else "观望"
    return MatchResult(
        job_id=match.job_id,
        score=match.score or 0,
        advantages=_json_list(match.advantages),
        missing=_json_list(match.missing),
        suggest=suggestion,
        rag_evidence=_json_list(match.rag_evidence),
        reasoning=match.reasoning or "",
    )


def _resume_record_to_dict(resume: ResumeVersionRecord) -> dict:
    return {
        "id": resume.id,
        "job_id": resume.job_id,
        "file_path": resume.file_path or "",
        "content_md": resume.content_md or "",
        "status": resume.status or "draft",
        "created_at": resume.created_at.isoformat(timespec="seconds") if resume.created_at else "",
    }


def _plan_record_to_dict(plan: LearningPlanRecord) -> dict:
    return {
        "id": plan.id,
        "job_id": plan.job_id,
        "priority_skills": _json_list(plan.priority_skills),
        "weekly_plan": _json_list(plan.weekly_plan),
        "estimated_hours": plan.estimated_hours or 0,
        "created_at": plan.created_at.isoformat(timespec="seconds") if plan.created_at else "",
    }


def _json_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return [raw]
    return value if isinstance(value, list) else [value]


def _parse_keywords(raw: str) -> list[str]:
    return list(dict.fromkeys(p.strip() for p in re.split(r"[,，、\s\n]+", raw) if p.strip()))


def _parse_search_intent(text: str) -> tuple[list[str], str, int]:
    keywords, city, parsed_threshold = parse_job_query(text)
    return keywords, city, parsed_threshold or settings.match_threshold


def _empty_resume_profile() -> dict:
    return {
        "profile": {"name": "", "email": "", "phone": "", "location": ""},
        "skills": [],
        "projects": [],
        "experience": [],
        "education": [],
        "preferences": {"cities": [], "target_roles": [], "keywords": [], "salary_range": ""},
        "constraints": {"do_not_invent": True, "must_mark_uncertain": True},
    }


def _profile_from_resume_text(payload: ResumeImportRequest) -> dict:
    content = payload.content.strip()
    parsed_json = _try_parse_resume_json(content)
    if parsed_json:
        profile = _normalize_resume_profile(parsed_json)
    else:
        profile = _extract_resume_profile(content, payload.source_label)

    target_roles = _parse_skills(payload.target_roles)
    cities = _parse_skills(payload.cities)
    preferences = profile.setdefault("preferences", {})
    if target_roles:
        preferences["target_roles"] = target_roles
        preferences["keywords"] = target_roles
    else:
        preferences.setdefault("target_roles", [])
        preferences.setdefault("keywords", preferences.get("target_roles", []))
    if cities:
        preferences["cities"] = cities
        preferences["city"] = cities[0]
    else:
        preferences.setdefault("cities", [profile.get("profile", {}).get("location", "")] if profile.get("profile", {}).get("location") else [])
        preferences.setdefault("city", preferences.get("cities", [""])[0] if preferences.get("cities") else "")

    profile.setdefault("constraints", {})
    profile["constraints"].update({"do_not_invent": True, "must_mark_uncertain": True})
    return profile


def _try_parse_resume_json(content: str) -> dict | None:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_resume_profile(raw: dict) -> dict:
    if "profile" in raw:
        profile = raw
    else:
        profile = {
            "profile": {
                "name": raw.get("name", ""),
                "email": raw.get("email", ""),
                "phone": raw.get("phone", ""),
                "location": raw.get("location", raw.get("city", "")),
            },
            "skills": raw.get("skills", []),
            "projects": raw.get("projects", []),
            "experience": raw.get("experience", []),
            "education": raw.get("education", []),
            "preferences": raw.get("preferences", {}),
            "constraints": raw.get("constraints", {}),
        }
    base = _empty_resume_profile()
    base.update(profile)
    base["profile"] = {**_empty_resume_profile()["profile"], **profile.get("profile", {})}
    base["skills"] = _dedupe_strings(profile.get("skills", []))
    base["projects"] = profile.get("projects", []) if isinstance(profile.get("projects", []), list) else []
    base["experience"] = profile.get("experience", []) if isinstance(profile.get("experience", []), list) else []
    base["education"] = profile.get("education", []) if isinstance(profile.get("education", []), list) else []
    base["preferences"] = {**_empty_resume_profile()["preferences"], **profile.get("preferences", {})}
    return base


def _extract_resume_profile(content: str, source_label: str) -> dict:
    lines = [line.strip(" \t-*#>") for line in content.splitlines()]
    lines = [line for line in lines if line]
    compact = "\n".join(lines)
    sections = _split_resume_sections(lines)

    base = _empty_resume_profile()
    base["profile"] = {
        "name": _extract_name(lines),
        "email": _first_match(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", content),
        "phone": _first_match(r"(?:\+?86[-\s]?)?1[3-9]\d{9}", content),
        "location": _extract_location(compact),
    }
    base["skills"] = _dedupe_strings(_extract_skills(content, sections))
    base["projects"] = _extract_projects(sections, source_label)
    base["experience"] = _extract_experience(sections, source_label)
    base["education"] = _extract_education(sections)
    base["preferences"] = {
        "cities": [base["profile"]["location"]] if base["profile"]["location"] else [],
        "city": base["profile"]["location"],
        "target_roles": [],
        "keywords": [],
        "salary_range": "",
    }
    base["source"] = {"type": "imported_text", "label": source_label, "imported_at": _now_iso()}
    return base


def _split_resume_sections(lines: list[str]) -> dict[str, list[str]]:
    aliases = {
        "skills": ("技能", "技能栈", "专业技能", "技术栈", "technical skills"),
        "projects": ("项目", "项目经历", "项目经验", "project"),
        "experience": ("工作经历", "实习经历", "工作经验", "experience"),
        "education": ("教育", "教育经历", "education"),
    }
    sections: dict[str, list[str]] = {key: [] for key in aliases}
    current = ""
    for line in lines:
        lowered = line.lower().rstrip(":：")
        matched = next((key for key, names in aliases.items() if any(name in lowered for name in names)), "")
        if matched and len(line) <= 28:
            current = matched
            continue
        if current:
            sections[current].append(line)
    return sections


def _extract_name(lines: list[str]) -> str:
    for line in lines[:6]:
        if _first_match(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", line) or _first_match(r"1[3-9]\d{9}", line):
            continue
        cleaned = re.sub(r"(个人简历|简历|resume|姓名[:：])", "", line, flags=re.I).strip()
        if 1 < len(cleaned) <= 24:
            return cleaned
    return ""


def _extract_location(text: str) -> str:
    city_words = ["北京", "上海", "深圳", "广州", "杭州", "南京", "苏州", "成都", "武汉", "西安", "全国"]
    for city in city_words:
        if city in text:
            return city
    match = re.search(r"(?:城市|所在地|现居)[:：\s]*([\u4e00-\u9fff]{2,8})", text)
    return match.group(1) if match else ""


def _extract_skills(content: str, sections: dict[str, list[str]]) -> list[str]:
    known = [
        "Python", "Java", "Go", "C++", "C", "JavaScript", "TypeScript", "React", "Vue",
        "Node.js", "FastAPI", "Django", "Flask", "SQL", "MySQL", "PostgreSQL", "Redis",
        "Docker", "Kubernetes", "Linux", "Git", "LangGraph", "RAG", "OpenAI", "LLM",
        "STM32", "ARM", "RTOS", "BSP", "I2C", "SPI", "GPIO", "Device Tree",
    ]
    found = [skill for skill in known if _contains_token(content, skill)]
    section_text = "\n".join(sections.get("skills", []))
    found.extend(_parse_skills(section_text))
    return found


def _extract_projects(sections: dict[str, list[str]], source_label: str) -> list[dict]:
    return _lines_to_items(sections.get("projects", []), "项目", source_label)


def _extract_experience(sections: dict[str, list[str]], source_label: str) -> list[dict]:
    items = []
    for item in _lines_to_items(sections.get("experience", []), "经历", source_label):
        items.append({
            "company": item["name"],
            "role": "",
            "start": "",
            "end": "",
            "bullets": [item["description"]] if item["description"] else [],
            "evidence": item["evidence"],
        })
    return items


def _extract_education(sections: dict[str, list[str]]) -> list[dict]:
    education = []
    for line in sections.get("education", [])[:4]:
        education.append({"school": line, "degree": "", "major": "", "start": "", "end": ""})
    return education


def _lines_to_items(lines: list[str], fallback_name: str, source_label: str) -> list[dict]:
    items = []
    buffer: list[str] = []
    for line in lines:
        starts_item = bool(re.match(r"^([\u4e00-\u9fffA-Za-z0-9_. -]{2,40})[:：]", line))
        if starts_item and buffer:
            items.append(_buffer_to_item(buffer, fallback_name, source_label))
            buffer = [line]
        else:
            buffer.append(line)
    if buffer:
        items.append(_buffer_to_item(buffer, fallback_name, source_label))
    return items[:8]


def _buffer_to_item(buffer: list[str], fallback_name: str, source_label: str) -> dict:
    first = buffer[0]
    if "：" in first or ":" in first:
        name, desc = re.split(r"[:：]", first, 1)
    else:
        name, desc = first[:32], first
    details = "；".join([desc.strip(), *buffer[1:]]).strip("； ")
    return {
        "name": name.strip() or fallback_name,
        "description": details,
        "skills": _dedupe_strings(_extract_skills(details, {"skills": []}))[:10],
        "evidence": source_label or "imported_resume",
    }


def _first_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    return match.group(0) if match else ""


def _contains_token(text: str, token: str) -> bool:
    if re.fullmatch(r"[A-Za-z0-9+#. -]+", token):
        return bool(re.search(rf"(?<![A-Za-z0-9+#.-]){re.escape(token)}(?![A-Za-z0-9+#.-])", text, re.I))
    return token.lower() in text.lower()


def _dedupe_strings(values: list | tuple) -> list[str]:
    result = []
    for value in values:
        if isinstance(value, str):
            item = value.strip()
        else:
            item = str(value).strip()
        if item and item not in result:
            result.append(item)
    return result


def _parse_skills(raw: str) -> list[str]:
    parts = re.split(r"[,，、\n]+", raw)
    skills = [p.strip() for p in parts if p.strip()]
    return list(dict.fromkeys(skills))


def _github_user_from_url(url: str) -> str | None:
    if not url.strip():
        return None
    parsed = urlparse(url if "://" in url else f"https://{url}")
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise HTTPException(status_code=400, detail="请输入 github.com 的个人主页地址")
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        raise HTTPException(status_code=400, detail="GitHub 地址里没有用户名")
    if parts[0] in {"orgs", "topics", "marketplace", "features"}:
        raise HTTPException(status_code=400, detail="请传入 GitHub 个人主页，而不是功能页面")
    return parts[0]


async def _fetch_github_projects(username: str) -> tuple[list[GithubProject], str | None]:
    url = f"https://api.github.com/users/{username}/repos"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "jobmatch-agent"}
    params = {"sort": "updated", "per_page": 12}
    try:
        async with httpx.AsyncClient(timeout=8, headers=headers) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail=f"GitHub 用户不存在: {username}")
            resp.raise_for_status()
            repos = resp.json()
    except HTTPException:
        raise
    except Exception as exc:
        return [], f"无法读取 GitHub 项目，已先生成基础模板: {exc}"

    projects = []
    for repo in repos:
        if repo.get("fork"):
            continue
        projects.append(
            GithubProject(
                name=repo.get("name", ""),
                url=repo.get("html_url", ""),
                description=repo.get("description") or "",
                language=repo.get("language") or "",
                stars=repo.get("stargazers_count") or 0,
                topics=repo.get("topics") or [],
                updated_at=(repo.get("updated_at") or "")[:10],
            )
        )
    return projects[:6], None


def _build_resume_markdown(
    payload: ResumeGenerateRequest,
    skills: list[str],
    projects: list[GithubProject],
) -> str:
    name = payload.name.strip() or "你的姓名"
    contact = " | ".join(
        item for item in [payload.email.strip(), payload.phone.strip(), payload.location.strip()] if item
    )
    role = payload.target_role.strip()
    project_lines = [_project_bullet(project, role, skills) for project in projects]
    if not project_lines:
        project_lines = [
            f"- **项目名称待补充**: 围绕 {role} 的核心能力构建可展示项目，突出问题背景、技术方案、量化结果和代码链接。"
        ]

    notes = payload.notes.strip()
    notes_block = f"\n## 补充亮点\n{notes}\n" if notes else ""
    skill_text = "、".join(skills) if skills else "请补充你的核心技能"
    github_links = "\n".join(f"- {p.name}: {p.url}" for p in projects if p.url)

    return f"""# {name}

{contact}

## 求职目标
{role}

## 个人优势
- 面向 {role} 岗位，具备 {skill_text} 等能力基础。
- 能将项目经历拆解为业务问题、技术方案、工程实现和结果复盘，适合在简历与面试中展开说明。
- 代码项目可通过 GitHub 交叉验证，降低简历可信度风险。

## 技能栈
{skill_text}

## 项目经历
{chr(10).join(project_lines)}

## GitHub 作品集
{github_links or "- 暂未提供 GitHub 项目链接"}
{notes_block}
## 待补充信息
- 每段项目建议补充: 项目周期、你的职责、核心难点、性能/效率/用户指标。
- 所有不确定经历请先标记为待核实，避免简历中出现无法面试展开的内容。
"""


def _project_bullet(project: GithubProject, role: str, skills: list[str]) -> str:
    tags = [project.language, *project.topics, *skills]
    tag_text = "、".join([t for t in tags if t][:6])
    desc = project.description or f"围绕 {project.name} 的工程实践项目"
    evidence = f"{project.url}，最近更新 {project.updated_at}" if project.updated_at else project.url
    return (
        f"- **{project.name}**: {desc}。面向 {role} 简历可突出 {tag_text or '工程实现、问题拆解、持续迭代'}；"
        f"代码证据: {evidence}。"
    )


def _infer_gaps(role: str, skills: list[str], projects: list[GithubProject]) -> list[str]:
    text = " ".join([role, *skills, *(p.language for p in projects), *(p.description for p in projects)]).lower()
    expected = {
        "前端": ["React/Vue", "TypeScript", "性能优化", "组件化"],
        "后端": ["数据库", "缓存", "接口设计", "部署运维"],
        "嵌入式": ["C", "Linux", "驱动", "硬件调试"],
        "算法": ["数据结构", "模型评估", "Python", "项目指标"],
        "测试": ["自动化测试", "CI", "缺陷分析", "测试设计"],
    }
    wanted = []
    for key, values in expected.items():
        if key in role:
            wanted.extend(values)
    if not wanted:
        wanted = ["量化结果", "项目职责", "技术难点", "可验证链接"]
    return [item for item in wanted if item.lower() not in text][:5]


def _save_generated_resume(role: str, markdown: str) -> Path:
    settings.resume_versions_dir.mkdir(parents=True, exist_ok=True)
    safe_role = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", role).strip("_") or "resume"
    path = settings.resume_versions_dir / f"web_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_role}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.server:app", host="127.0.0.1", port=8000, reload=True)

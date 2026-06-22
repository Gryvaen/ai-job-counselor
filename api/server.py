"""FastAPI web console for the JobMatch Agent workspace."""

from __future__ import annotations

import json
import re
import base64
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config.settings import settings
from config.settings import PROJECT_ROOT
from agent.nodes.plan_node import parse_job_query
from models.agent_state import AgentState
from models.job import Job
from storage.db import (
    JobRecord,
    LearningPlanRecord,
    MatchRecord,
    ResumeVersionRecord,
    get_engine,
    get_session,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


class ResumeGenerateRequest(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    skills: str = Field(default="", description="Comma or newline separated skills")
    target_role: str = Field(min_length=1)
    github_url: str = ""
    notes: str = ""


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


app = FastAPI(title="JobMatch Agent Web Console")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

TASK_LOCK = threading.Lock()
TASK_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jobmatch-search")
SEARCH_TASKS: dict[str, dict] = {}
TASK_TTL_SECONDS = 60 * 60 * 6


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
    get_engine(settings.db_path)
    settings.resume_versions_dir.mkdir(parents=True, exist_ok=True)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "time": datetime.now().isoformat(timespec="seconds"),
        "db_path": str(settings.db_path),
        "resume_exists": settings.resume_path.exists(),
        "boss_login_exists": settings.boss_state_path.exists(),
        "openai_configured": bool(settings.openai_api_key),
        "model_provider": settings.model_provider,
        "ollama_configured": bool(settings.ollama_base_url and settings.ollama_model),
        "feishu_configured": bool(settings.feishu_webhook),
    }


@app.get("/api/commands")
def list_commands() -> dict:
    return {"commands": SLASH_COMMANDS}


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
        "config": _settings_to_config().model_dump(),
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
def create_search_task(payload: JobSearchRequest) -> SearchTaskCreateResponse:
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
        "result": None,
        "error": "",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    with TASK_LOCK:
        _prune_tasks_locked()
        SEARCH_TASKS[task_id] = task
    _append_task_event(task_id, "queued", 0, "任务已排队，等待 Agent 开始搜索。")
    TASK_EXECUTOR.submit(_run_search_task, task_id)
    return SearchTaskCreateResponse(
        task_id=task_id,
        status="queued",
        message="搜索任务已创建。",
    )


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    with TASK_LOCK:
        task = SEARCH_TASKS.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在或已过期")
        return json.loads(json.dumps(task, ensure_ascii=False, default=str))


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


def _run_search_task(task_id: str) -> None:
    with TASK_LOCK:
        task = SEARCH_TASKS.get(task_id)
        if not task:
            return
        request = dict(task["request"])

    try:
        result = _run_job_search_with_progress(
            keywords=request["keywords"],
            city=request["city"],
            threshold=request["threshold"],
            user_query=request["user_query"],
            progress=lambda stage, pct, msg: _append_task_event(task_id, stage, pct, msg),
            login_screenshot_callback=lambda image: _update_task_login_screenshot(task_id, image),
        )
        with TASK_LOCK:
            task = SEARCH_TASKS.get(task_id)
            if not task:
                return
            task["status"] = "completed"
            task["stage"] = "completed"
            task["progress"] = 100
            task["message"] = result.message
            task["result"] = result.model_dump()
            task["updated_at"] = _now_iso()
        _append_task_event(task_id, "completed", 100, result.message)
    except Exception as exc:
        message = str(exc)
        with TASK_LOCK:
            task = SEARCH_TASKS.get(task_id)
            if not task:
                return
            task["status"] = "failed"
            task["stage"] = "failed"
            task["progress"] = max(int(task.get("progress", 0)), 1)
            task["message"] = f"搜索失败: {message}"
            task["error"] = message
            task["updated_at"] = _now_iso()
        _append_task_event(task_id, "failed", 100, f"搜索失败: {message}")


def _run_job_search_with_progress(
    keywords: list[str],
    city: str,
    threshold: int,
    user_query: str,
    progress,
    login_screenshot_callback=None,
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
    }

    def apply_update(update: dict | None) -> None:
        if update:
            state.update(update)

    progress("planning", 8, f"解析搜索意图: {city} · {', '.join(keywords)}")
    apply_update(plan_node(state))

    progress("scraping", 18, "打开 Boss 并检索岗位。若登录态失效，请在弹出的浏览器中扫码。")
    apply_update(scrape_node(state))

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

    if any(word in text for word in ["找工作", "搜岗位", "搜索岗位", "找岗位"]):
        keywords, city, threshold = _parse_search_intent(text)
        return ChatResponse(
            action="suggest_search",
            reply=f"我建议搜索 {city} 的这些关键词: {', '.join(keywords)}。输入 /search 后按参数提示填写城市、岗位和分数即可运行。",
            data={"keywords": ",".join(keywords), "city": city, "threshold": threshold},
        )

    if any(word in text for word in ["改简历", "优化简历", "修改简历", "简历模板"]):
        profile = get_resume_profile()
        roles = profile.get("preferences", {}).get("target_roles", [])
        role_text = "、".join(roles) if roles else "你的目标岗位"
        return ChatResponse(
            action="resume_advice",
            reply=f"可以。我会基于 resume.json 的事实来改，不编造经历。当前建议先围绕 {role_text} 强化项目经历、量化结果和可验证链接。",
            data={"profile": profile},
        )

    if "状态" in text or "概览" in text or "dashboard" in lower:
        data = dashboard()
        metrics = data["metrics"]
        return ChatResponse(
            action="dashboard",
            reply=f"当前已记录 {metrics['jobs']} 个岗位、{metrics['matches']} 条匹配、{metrics['resumes']} 版简历、{metrics['plans']} 个学习计划。",
            data=data,
        )

    return ChatResponse(
        action="general",
        reply="我现在可以帮你搜岗位、解释匹配、生成定制简历、整理简历事实档案。输入 / 可以选择模式；选中 /search 后会显示参数提示。",
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
        task = create_search_task(JobSearchRequest(
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
        task = SEARCH_TASKS.get(task_id)
        if not task:
            return
        if task.get("status") not in {"failed", "completed"}:
            task["status"] = "running" if stage != "queued" else "queued"
        task["stage"] = stage
        task["progress"] = event["progress"]
        task["message"] = message
        task["updated_at"] = event["time"]
        task.setdefault("events", []).append(event)
        task["events"] = task["events"][-30:]


def _update_task_login_screenshot(task_id: str, image: bytes) -> None:
    encoded = base64.b64encode(image).decode("ascii")
    with TASK_LOCK:
        task = SEARCH_TASKS.get(task_id)
        if not task:
            return
        task["login_screenshot"] = encoded
        task["status"] = "running"
        task["stage"] = "login"
        task["progress"] = max(int(task.get("progress", 0)), 20)
        task["message"] = "等待 Boss 扫码登录。请扫描下方二维码，登录成功后任务会继续。"
        task["updated_at"] = _now_iso()


def _prune_tasks_locked() -> None:
    now = datetime.now().timestamp()
    expired = []
    for task_id, task in SEARCH_TASKS.items():
        try:
            updated = datetime.fromisoformat(task.get("updated_at", task.get("created_at"))).timestamp()
        except Exception:
            updated = now
        if now - updated > TASK_TTL_SECONDS:
            expired.append(task_id)
    for task_id in expired:
        SEARCH_TASKS.pop(task_id, None)


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
}


def _settings_to_config() -> AppConfig:
    return AppConfig(
        model_provider=settings.model_provider,
        openai_api_key=settings.openai_api_key,
        openai_base_url=_clean_config_value(settings.openai_base_url or ""),
        openai_model=settings.openai_model,
        openai_embedding_model=settings.openai_embedding_model,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
        ollama_embedding_model=settings.ollama_embedding_model,
        feishu_webhook=settings.feishu_webhook,
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
    )


def _apply_config(config: AppConfig) -> None:
    settings.openai_api_key = config.openai_api_key.strip()
    settings.model_provider = config.model_provider.strip()
    settings.openai_base_url = config.openai_base_url.strip() or None
    settings.openai_model = config.openai_model.strip()
    settings.openai_embedding_model = config.openai_embedding_model.strip()
    settings.ollama_base_url = config.ollama_base_url.strip()
    settings.ollama_model = config.ollama_model.strip()
    settings.ollama_embedding_model = config.ollama_embedding_model.strip()
    settings.feishu_webhook = config.feishu_webhook.strip()
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


def _write_env(config: AppConfig) -> None:
    env_path = PROJECT_ROOT / ".env"
    current = _read_env_file(env_path)
    values = config.model_dump()
    for field, env_key in CONFIG_ENV_KEYS.items():
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

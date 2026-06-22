"""FastAPI web console for the AI Agent interview workspace."""

from __future__ import annotations

import json
import logging
import re
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
from models.job import Job
from models.match import MatchResult
from storage.db import (
    JobRecord,
    LearningPlanRecord,
    MatchRecord,
    ResumeVersionRecord,
    get_engine,
    get_session,
    latest_knowledge_ingest,
    record_knowledge_ingest,
)

logger = logging.getLogger(__name__)

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
    projects: str = ""


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


class JobImportRequest(BaseModel):
    title: str = Field(min_length=1)
    company: str = Field(min_length=1)
    salary: str = ""
    city: str = "全国"
    description: str = Field(min_length=10)
    url: str = ""


class AnalysisRunRequest(BaseModel):
    resume_text: str = Field(min_length=20)
    jd_text: str = Field(min_length=20)
    title: str = "目标岗位"
    company: str = "目标公司"
    city: str = "全国"
    model: str = "rule"


class AnalysisRunResponse(BaseModel):
    job_id: str
    title: str
    company: str
    match_score: int
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    relevant_experience: list[str] = Field(default_factory=list)
    resume_advice: list[str] = Field(default_factory=list)
    learning_plan: list[str] = Field(default_factory=list)
    interview_questions: list[str] = Field(default_factory=list)
    job_requirements: list[str] = Field(default_factory=list)
    reasoning: str = ""


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    reply: str
    action: str
    data: dict = Field(default_factory=dict)


class InterviewRequest(BaseModel):
    target_role: str = Field(min_length=1)
    skills: str = ""
    projects: str = ""
    answer: str = ""
    history: list[dict] = Field(default_factory=list)


class InterviewResponse(BaseModel):
    question: str
    feedback: list[str] = Field(default_factory=list)
    focus: list[str] = Field(default_factory=list)
    round: int = 1
    stage: str = ""
    score: int = 0
    rubric: list[str] = Field(default_factory=list)
    answer_shape: list[str] = Field(default_factory=list)
    coverage: list[dict] = Field(default_factory=list)


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
    resume_path: str = "data/resume.json"
    knowledge_dir: str = "data/knowledge"
    resume_versions_dir: str = "data/resume_versions"
    db_path: str = "data/jobmatch.db"
    chroma_dir: str = "storage/vector_store"
    rag_chunk_size: int = Field(default=512, ge=64, le=8192)
    rag_chunk_overlap: int = Field(default=64, ge=0, le=4096)
    rag_top_k: int = Field(default=5, ge=1, le=50)
    match_threshold: int = Field(default=75, ge=0, le=100)
    webui_api_token: str = ""


class KnowledgeIngestResponse(BaseModel):
    chunks: int
    source_dir: str
    message: str


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

SLASH_COMMANDS = [
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
        "description": "跳转到模型和数据路径设置。",
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


def _check_chroma() -> tuple[bool, str]:
    try:
        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        return True, f"ready: {settings.chroma_dir}"
    except Exception as exc:
        return False, str(exc)


def _check_ollama() -> tuple[bool, str]:
    if settings.model_provider.lower().strip() != "ollama":
        return True, "skipped"
    if not settings.ollama_base_url or not settings.ollama_model:
        return False, "ollama base url/model is not configured"
    return True, "configured"


@app.get("/api/health")
async def health() -> dict:
    db_ok, db_msg = _check_db()
    chroma_ok, chroma_msg = _check_chroma()
    ollama_ok, ollama_msg = _check_ollama()
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
        "openai_configured": bool(settings.openai_api_key),
        "model_provider": settings.model_provider,
        "ollama_configured": bool(settings.ollama_base_url and settings.ollama_model),
        "auth_required": bool(settings.webui_api_token.strip()),
        "checks": checks,
        "knowledge_ingest": ingest,
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
    ingest = latest_knowledge_ingest()
    sources = []
    if ingest:
        sources = [{"source": ingest["source_dir"], "type": "latest_ingest"}]
    return {
        "knowledge_dir": str(settings.knowledge_dir),
        "latest_ingest": ingest,
        "indexed_sources": len(sources),
        "sources": sources[:20],
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
        message="已从传入简历生成新的简历事实档案，后续定制简历会使用这份档案。",
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
    gaps = _infer_gaps(payload.target_role, skills, projects, payload.projects)
    return ResumeGenerateResponse(
        markdown=markdown,
        skills=skills,
        github_user=github_user,
        projects=projects,
        saved_path=str(saved_path),
        gaps=gaps,
        warnings=warnings,
    )


@app.post("/api/interview/next", response_model=InterviewResponse)
def next_interview_question(payload: InterviewRequest) -> InterviewResponse:
    return _build_interview_turn(payload)


@app.post("/api/jobs/import")
def import_job(payload: JobImportRequest) -> dict:
    from storage.db import save_job

    job = Job(
        title=payload.title.strip(),
        company=payload.company.strip(),
        salary=payload.salary.strip(),
        city=payload.city.strip() or "全国",
        description=payload.description.strip(),
        url=payload.url.strip(),
    )
    with get_session() as sess:
        save_job(sess, job)
        sess.commit()
    return {"job": job.model_dump(mode="json"), "message": "岗位 JD 已保存到本地岗位库。"}


@app.post("/api/analysis/run", response_model=AnalysisRunResponse)
def run_analysis(payload: AnalysisRunRequest) -> AnalysisRunResponse:
    from storage.db import save_job, save_match

    analysis = _analyze_resume_jd(payload)
    job = Job(
        title=payload.title.strip() or analysis["title"],
        company=payload.company.strip() or analysis["company"],
        salary="",
        city=payload.city.strip() or "全国",
        description=payload.jd_text.strip(),
        url="",
    )
    match = MatchResult(
        job_id=job.id,
        score=analysis["match_score"],
        advantages=analysis["matched_skills"] + analysis["relevant_experience"][:3],
        missing=analysis["missing_skills"],
        suggest=_score_suggestion(analysis["match_score"]),
        rag_evidence=analysis["relevant_experience"][:3],
        reasoning=analysis["reasoning"],
    )
    with get_session() as sess:
        save_job(sess, job)
        save_match(sess, match)
        sess.commit()

    return AnalysisRunResponse(job_id=job.id, **analysis)


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
        context_parts.append(
            "用户想找岗位，但岗位搜索功能已删除。可以引导用户手动导入目标 JD，再查看已有匹配结果或生成定制简历。"
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
    "resume_path": "RESUME_PATH",
    "knowledge_dir": "KNOWLEDGE_DIR",
    "resume_versions_dir": "RESUME_VERSIONS_DIR",
    "db_path": "DB_PATH",
    "chroma_dir": "CHROMA_DIR",
    "rag_chunk_size": "RAG_CHUNK_SIZE",
    "rag_chunk_overlap": "RAG_CHUNK_OVERLAP",
    "rag_top_k": "RAG_TOP_K",
    "match_threshold": "MATCH_THRESHOLD",
    "webui_api_token": "WEBUI_API_TOKEN",
}


def _settings_to_config(mask_secrets: bool = True) -> AppConfig:
    api_key = settings.openai_api_key
    token = settings.webui_api_token
    if mask_secrets:
        api_key = _mask_api_key(api_key)
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
        resume_path=_display_path(settings.resume_path),
        knowledge_dir=_display_path(settings.knowledge_dir),
        resume_versions_dir=_display_path(settings.resume_versions_dir),
        db_path=_display_path(settings.db_path),
        chroma_dir=_display_path(settings.chroma_dir),
        rag_chunk_size=settings.rag_chunk_size,
        rag_chunk_overlap=settings.rag_chunk_overlap,
        rag_top_k=settings.rag_top_k,
        match_threshold=settings.match_threshold,
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
    if config.webui_api_token.strip() and not config.webui_api_token.strip().startswith("*"):
        settings.webui_api_token = config.webui_api_token.strip()
    settings.resume_path = _resolve_config_path(config.resume_path)
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


ANALYSIS_SKILLS = [
    "Python", "FastAPI", "Django", "Flask", "SQLAlchemy", "PostgreSQL", "SQLite",
    "MySQL", "Redis", "Docker", "Kubernetes", "Linux", "Git", "CI/CD",
    "React", "Vue", "TypeScript", "JavaScript", "TailwindCSS", "HTML", "CSS",
    "LangGraph", "LangChain", "RAG", "ChromaDB", "向量数据库", "Embedding",
    "OpenAI", "Claude", "Qwen", "DeepSeek", "LLM", "Agent", "Prompt",
    "PyTorch", "TensorFlow", "机器学习", "NLP", "数据分析", "Pandas",
    "C", "C++", "Java", "Go", "Rust", "微服务", "REST", "WebSocket",
    "测试", "部署", "监控", "性能优化",
]


def _analyze_resume_jd(payload: AnalysisRunRequest) -> dict:
    resume_text = payload.resume_text.strip()
    jd_text = payload.jd_text.strip()
    title = payload.title.strip() or _infer_title(jd_text)
    company = payload.company.strip() or "目标公司"
    resume_skills = _extract_known_skills(resume_text)
    jd_skills = _extract_known_skills(jd_text)
    requirements = _extract_requirements(jd_text, jd_skills)
    matched = [skill for skill in jd_skills if _skill_in_text(skill, resume_text)]
    missing = [skill for skill in jd_skills if skill not in matched]
    relevant = _relevant_experience(resume_text, matched or jd_skills)

    requirement_score = min(45, round((len(matched) / max(1, len(jd_skills))) * 45))
    evidence_score = min(30, len(relevant) * 8 + min(6, len(resume_skills)))
    baseline_score = 20 if resume_text and jd_text else 0
    bonus = 5 if any(word in resume_text.lower() for word in ["上线", "部署", "生产", "production", "用户", "性能"]) else 0
    score = max(0, min(100, baseline_score + requirement_score + evidence_score + bonus))
    if not jd_skills and requirements:
        score = max(35, min(72, 35 + len(relevant) * 7))

    advice = _resume_advice(title, matched, missing, relevant)
    plan = _learning_plan(missing)
    questions = _interview_questions(title, matched, missing, requirements)
    reasoning = (
        f"matched_skills={len(matched)}, missing_skills={len(missing)}, "
        f"relevant_experience={len(relevant)}, requirement_score={requirement_score}, "
        f"evidence_score={evidence_score}, bonus={bonus}"
    )
    return {
        "title": title,
        "company": company,
        "match_score": score,
        "matched_skills": matched[:12],
        "missing_skills": missing[:10],
        "relevant_experience": relevant[:6],
        "resume_advice": advice,
        "learning_plan": plan,
        "interview_questions": questions,
        "job_requirements": requirements[:8],
        "reasoning": reasoning,
    }


def _infer_title(jd_text: str) -> str:
    first_line = next((line.strip() for line in jd_text.splitlines() if line.strip()), "")
    if 2 <= len(first_line) <= 40 and not first_line.endswith(("。", ".", "；", ";")):
        return first_line
    return "目标岗位"


def _extract_known_skills(text: str) -> list[str]:
    return [skill for skill in ANALYSIS_SKILLS if _skill_in_text(skill, text)]


def _skill_in_text(skill: str, text: str) -> bool:
    lower = text.lower()
    needle = skill.lower()
    if re.fullmatch(r"[a-z0-9+#./-]+", needle):
        return bool(re.search(rf"(?<![a-z0-9+#./-]){re.escape(needle)}(?![a-z0-9+#./-])", lower))
    return needle in lower


def _extract_requirements(jd_text: str, jd_skills: list[str]) -> list[str]:
    lines = []
    for raw in jd_text.splitlines():
        line = raw.strip(" \t-•*0123456789.、")
        if 8 <= len(line) <= 140 and any(token in line for token in ["要求", "熟悉", "掌握", "负责", "经验", "能力", "优先", "需要"]):
            lines.append(line)
    skill_requirements = [f"具备 {skill} 相关经验" for skill in jd_skills]
    return list(dict.fromkeys(lines + skill_requirements))


def _relevant_experience(resume_text: str, target_skills: list[str]) -> list[str]:
    chunks = re.split(r"[\n。；;]+", resume_text)
    scored = []
    for chunk in chunks:
        item = chunk.strip(" -•\t")
        if len(item) < 12:
            continue
        hits = [skill for skill in target_skills if _skill_in_text(skill, item)]
        if hits or any(word in item for word in ["项目", "系统", "平台", "服务", "模块", "优化", "开发", "实现"]):
            scored.append((len(hits), len(item), item[:180]))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [item for _, _, item in scored[:6]]


def _resume_advice(title: str, matched: list[str], missing: list[str], relevant: list[str]) -> list[str]:
    advice = []
    if matched:
        advice.append(f"在简历摘要和技能栈前 1/3 位置突出 {', '.join(matched[:5])}，让 ATS 与面试官快速看到岗位关键词。")
    if relevant:
        advice.append("将最相关项目改写为“背景-职责-技术方案-量化结果”结构，并明确你个人负责的模块。")
    if missing:
        advice.append(f"对 {', '.join(missing[:4])} 标注为学习中或补充可验证项目，避免直接写成已熟练掌握。")
    advice.append(f"围绕 {title} 准备 2-3 个可展开的项目故事，覆盖技术选型、问题排查和结果复盘。")
    return advice[:5]


def _learning_plan(missing: list[str]) -> list[str]:
    if not missing:
        return ["第1周：整理岗位相关项目证据和量化指标。", "第2周：准备技术复盘和行为面试答案。"]
    return [
        f"第1周：补齐 {', '.join(missing[:2])} 基础概念，并完成官方教程或最小 Demo。",
        f"第2周：把 {missing[0]} 接入一个个人项目，形成可截图、可运行、可讲解的作品。",
        "第3周：整理项目 README、架构图和问题排查记录，用于简历与面试展开。",
        "第4周：用目标 JD 复盘缺口，进行 2 轮模拟面试并修订简历表达。",
    ]


def _interview_questions(title: str, matched: list[str], missing: list[str], requirements: list[str]) -> list[str]:
    focus = matched[:3] or missing[:3] or ["项目架构", "技术选型", "问题排查"]
    questions = [f"请介绍一个最能证明你适合 {title} 的项目，你负责了哪些关键模块？"]
    questions.extend([f"你在项目中如何使用或理解 {skill}？遇到过什么具体问题？" for skill in focus])
    if requirements:
        questions.append(f"JD 提到“{requirements[0][:36]}”，你会如何证明自己具备这项能力？")
    if missing:
        questions.append(f"如果入职后需要快速补齐 {missing[0]}，你会如何安排前两周学习和交付？")
    return questions[:6]


AGENT_INTERVIEW_STAGES = [
    {
        "name": "项目真实性",
        "focus": ["项目背景", "个人职责", "业务指标", "上线结果"],
        "rubric": ["能讲清问题背景和用户价值", "能区分团队成果与个人贡献", "能给出可验证结果"],
        "shape": ["背景和目标", "你的职责边界", "核心方案", "结果和复盘"],
    },
    {
        "name": "Agent 编排",
        "focus": ["LangGraph", "状态机", "Planner/Executor", "多步任务"],
        "rubric": ["能解释状态、节点和边的设计", "能说明失败重试和中断恢复", "能比较工作流与自由 Agent 的取舍"],
        "shape": ["任务拆解", "状态定义", "节点职责", "失败处理"],
    },
    {
        "name": "RAG 与知识库",
        "focus": ["Embedding", "向量数据库", "Chunking", "Rerank", "引用证据"],
        "rubric": ["能说明召回、精排和上下文拼装", "能处理幻觉和证据不足", "能设计检索评估指标"],
        "shape": ["数据入库", "召回策略", "上下文构造", "评估与改进"],
    },
    {
        "name": "工具调用",
        "focus": ["Function Calling", "MCP", "工具权限", "参数校验", "幂等性"],
        "rubric": ["能设计工具 schema 和错误返回", "能处理权限、超时和重试", "能避免危险工具误调用"],
        "shape": ["工具边界", "输入输出 schema", "异常路径", "安全策略"],
    },
    {
        "name": "记忆与上下文",
        "focus": ["短期记忆", "长期记忆", "摘要压缩", "会话状态"],
        "rubric": ["能区分消息历史、用户画像和任务状态", "能控制上下文窗口成本", "能说明隐私和过期策略"],
        "shape": ["记忆类型", "写入触发", "读取排序", "清理策略"],
    },
    {
        "name": "评估与安全",
        "focus": ["Eval", "测试集", "Guardrail", "幻觉检测", "Prompt 注入"],
        "rubric": ["能建立离线和在线评估", "能定义成功率、事实性和成本指标", "能处理 prompt 注入和越权"],
        "shape": ["风险清单", "评估样本", "指标阈值", "拦截与回退"],
    },
    {
        "name": "工程化部署",
        "focus": ["FastAPI", "Docker", "队列", "监控", "CI/CD", "成本"],
        "rubric": ["能设计 API、异步任务和持久化", "能说明日志、追踪和告警", "能考虑限流、缓存和模型降级"],
        "shape": ["服务架构", "数据流", "部署运维", "成本和降级"],
    },
    {
        "name": "系统设计",
        "focus": ["端到端架构", "多 Agent 协作", "人机协同", "产品闭环"],
        "rubric": ["能把需求拆成可交付模块", "能识别复杂度和边界", "能提出可验证迭代路线"],
        "shape": ["需求澄清", "模块架构", "关键链路", "里程碑"],
    },
]


AGENT_TECH_KEYWORDS = [
    "Python", "FastAPI", "LangGraph", "LangChain", "RAG", "Embedding", "向量数据库",
    "ChromaDB", "Milvus", "FAISS", "Rerank", "Function Calling", "MCP", "Tool",
    "OpenAI", "Claude", "Qwen", "DeepSeek", "LLM", "Prompt", "Agent", "Planner",
    "Executor", "Memory", "Eval", "Guardrail", "Docker", "Kubernetes", "Redis",
    "PostgreSQL", "SQLite", "SQLAlchemy", "队列", "监控", "日志", "CI/CD",
]


def _build_interview_turn(payload: InterviewRequest) -> InterviewResponse:
    skills = _parse_skills(payload.skills)
    projects = _parse_project_lines(payload.projects)
    answer = payload.answer.strip()
    round_no = len(payload.history or []) + 1
    stage = AGENT_INTERVIEW_STAGES[(round_no - 1) % len(AGENT_INTERVIEW_STAGES)]
    coverage = _agent_tech_coverage(skills, payload.projects, payload.history, answer)
    feedback = _interview_feedback(answer, skills, projects, stage, coverage) if answer else []
    score = _score_interview_answer(answer, skills, projects, stage) if answer else 0
    focus = _interview_focus(payload.target_role, skills, projects, answer, stage, coverage)

    context = f"""你是 AI Agent 面试官，正在模拟中文技术面试。
目标岗位: {payload.target_role}
当前阶段: {stage['name']}
必须考察: {', '.join(stage['focus'])}
候选人技能: {', '.join(skills) or '未填写'}
项目经历:
{payload.projects.strip() or '未填写'}
上一轮回答:
{answer or '这是第一轮，请开场提问'}
已覆盖技术: {', '.join(item['name'] for item in coverage if item['covered']) or '暂无'}

请输出一个具体、可回答的下一题。要求:
1. 只问一个问题。
2. 围绕当前阶段追问，不要泛泛而谈。
3. 尽量覆盖 AI Agent 岗位能力: Agent 编排、RAG、工具调用、记忆、评估、安全、部署。
3. 不要替候选人编造经历。
"""
    llm_question = llm_chat(
        "请给出下一道模拟面试问题，只输出问题本身。",
        context=context,
    )
    question = (llm_question or "").strip()
    if not question:
        question = _fallback_interview_question(payload.target_role, skills, projects, answer, round_no)

    return InterviewResponse(
        question=question,
        feedback=feedback,
        focus=focus,
        round=round_no,
        stage=stage["name"],
        score=score,
        rubric=stage["rubric"],
        answer_shape=stage["shape"],
        coverage=coverage,
    )


def _interview_feedback(
    answer: str,
    skills: list[str],
    projects: list[str],
    stage: dict,
    coverage: list[dict],
) -> list[str]:
    feedback = []
    if len(answer) < 40:
        feedback.append("回答偏短，可以补充背景、你的职责、技术方案和结果。")
    if not re.search(r"\d|%|ms|qps|用户|耗时|提升|降低|减少|增长", answer, re.I):
        feedback.append("建议加入可验证指标，例如性能、规模、耗时、准确率或交付结果。")
    if projects and not any(project[:8] in answer for project in projects):
        feedback.append("可以明确关联一个项目，说明你本人负责的模块和边界。")
    matched = [skill for skill in skills if _skill_in_text(skill, answer)]
    if skills and not matched:
        feedback.append("回答里还没有体现核心技能关键词，可以自然带出相关技术栈。")
    stage_hits = [item for item in stage["focus"] if _skill_in_text(item, answer)]
    if not stage_hits:
        feedback.append(f"这一轮重点是{stage['name']}，建议直接回应 {', '.join(stage['focus'][:3])}。")
    missing_core = [item["name"] for item in coverage if not item["covered"]][:3]
    if missing_core:
        feedback.append(f"后续还需要覆盖 {', '.join(missing_core)}，这是 AI Agent 岗位常见追问点。")
    if not feedback:
        feedback.append("回答结构清楚，下一步可以准备更深入的取舍、排查和复盘细节。")
    return feedback[:4]


def _interview_focus(
    role: str,
    skills: list[str],
    projects: list[str],
    answer: str,
    stage: dict,
    coverage: list[dict],
) -> list[str]:
    focus = list(stage["focus"][:3])
    if skills:
        focus.extend([skill for skill in skills[:4] if skill not in focus])
    if projects:
        focus.append("项目细节")
    if any(word in role.lower() for word in ["agent", "ai", "llm", "rag"]):
        focus.extend(["Agent 设计", "RAG 评估", "工具调用"])
    if answer and not re.search(r"为什么|取舍|权衡|trade", answer, re.I):
        focus.append("技术取舍")
    focus.extend(item["name"] for item in coverage if not item["covered"])
    return list(dict.fromkeys(focus))[:5]


def _fallback_interview_question(
    role: str,
    skills: list[str],
    projects: list[str],
    answer: str,
    round_no: int,
) -> str:
    project = projects[0] if projects else "你最有代表性的项目"
    skill = skills[(round_no - 1) % len(skills)] if skills else "核心技术栈"
    stage = AGENT_INTERVIEW_STAGES[(round_no - 1) % len(AGENT_INTERVIEW_STAGES)]
    stage_focus = "、".join(stage["focus"][:3])
    questions = [
        f"请用 2 分钟介绍一个最能证明你适合 {role} 的项目，重点讲你的职责、技术方案和结果。",
        f"在 {project} 中，如果要用 LangGraph 或类似状态机编排 Agent，你会如何定义状态、节点和失败重试？",
        f"请设计 {project} 的 RAG 链路：文档如何切分、召回如何评估、回答如何附带证据？",
        f"如果 Agent 需要调用外部工具，你会如何设计 tool schema、权限校验、超时重试和幂等性？",
        f"你会如何为 {project} 建立 Eval 和 Guardrail，覆盖幻觉、Prompt 注入、越权工具调用和成本失控？",
        f"如果把 {project} 部署到生产环境，你会如何设计 FastAPI 服务、任务队列、日志追踪、监控告警和模型降级？",
        f"围绕{stage['name']}，请结合 {stage_focus} 讲一个具体方案或经历。",
    ]
    if answer and len(answer) > 20:
        return f"你刚才的回答放到{stage['name']}场景下，最难验证的假设是什么？你会用什么数据、日志或实验确认它是对的？"
    return questions[(round_no - 1) % len(questions)]


def _score_interview_answer(answer: str, skills: list[str], projects: list[str], stage: dict) -> int:
    if not answer:
        return 0
    score = 35
    if len(answer) >= 80:
        score += 15
    if re.search(r"\d|%|ms|qps|用户|耗时|提升|降低|减少|增长", answer, re.I):
        score += 15
    if any(_skill_in_text(skill, answer) for skill in skills + stage["focus"]):
        score += 15
    if projects and any(project[:8] in answer for project in projects):
        score += 10
    if re.search(r"取舍|权衡|为什么|替代|trade|风险|回退|降级|监控|评估", answer, re.I):
        score += 10
    return max(0, min(100, score))


def _agent_tech_coverage(
    skills: list[str],
    projects_text: str,
    history: list[dict],
    answer: str,
) -> list[dict]:
    corpus = "\n".join(
        [
            ", ".join(skills),
            projects_text or "",
            answer or "",
            "\n".join(f"{item.get('question', '')}\n{item.get('answer', '')}" for item in history or []),
        ]
    )
    groups = [
        ("LLM/Prompt", ["LLM", "Prompt", "OpenAI", "Claude", "Qwen", "DeepSeek"]),
        ("Agent 编排", ["Agent", "LangGraph", "Planner", "Executor", "状态机", "多 Agent"]),
        ("RAG", ["RAG", "Embedding", "向量数据库", "ChromaDB", "Milvus", "FAISS", "Rerank"]),
        ("工具调用", ["Function Calling", "MCP", "Tool", "工具", "schema"]),
        ("记忆", ["Memory", "记忆", "会话", "上下文", "摘要"]),
        ("评估安全", ["Eval", "评估", "Guardrail", "幻觉", "注入", "安全"]),
        ("工程部署", ["FastAPI", "Docker", "Kubernetes", "监控", "日志", "CI/CD", "Redis", "队列"]),
    ]
    return [
        {
            "name": name,
            "covered": any(_skill_in_text(alias, corpus) for alias in aliases),
        }
        for name, aliases in groups
    ]


def _parse_project_lines(value: str) -> list[str]:
    lines = []
    for line in str(value or "").splitlines():
        item = line.strip(" -•\t")
        if item:
            lines.append(item[:120])
    if not lines and value.strip():
        lines = [part.strip()[:120] for part in re.split(r"[;；。]", value) if part.strip()]
    return lines[:8]


def _score_suggestion(score: int) -> str:
    if score >= 80:
        return "推荐投递"
    if score >= 60:
        return "观望"
    return "不推荐"


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
    project_lines.extend(_manual_project_bullets(payload.projects, role, skills))
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


def _manual_project_bullets(projects_text: str, role: str, skills: list[str]) -> list[str]:
    bullets = []
    skill_text = "、".join(skills[:5]) or "岗位相关技术栈"
    for line in _parse_project_lines(projects_text):
        if "：" in line or ":" in line:
            name, desc = re.split(r"[:：]", line, 1)
        else:
            name, desc = line[:24], line
        bullets.append(
            f"- **{name.strip() or '项目'}**: {desc.strip()}。面向 {role} 可突出 {skill_text}、个人职责、技术难点和可量化结果。"
        )
    return bullets[:8]


def _infer_gaps(role: str, skills: list[str], projects: list[GithubProject], projects_text: str = "") -> list[str]:
    text = " ".join([
        role,
        projects_text,
        *skills,
        *(p.language for p in projects),
        *(p.description for p in projects),
    ]).lower()
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

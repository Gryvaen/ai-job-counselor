"""LLM helpers — OpenAI-compatible chat with structured JSON fallback."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import OpenAI

from config.settings import settings
from models.job import Job
from models.match import MatchResult
from models.resume import OptimizedResume, ResumeBullet

logger = logging.getLogger(__name__)


def is_llm_available() -> bool:
    provider = settings.model_provider.lower().strip()
    if provider == "ollama":
        return bool(settings.ollama_base_url and settings.ollama_model)
    return bool(settings.openai_api_key)


def get_chat_client() -> OpenAI | None:
    if not is_llm_available():
        return None
    provider = settings.model_provider.lower().strip()
    if provider == "ollama":
        return OpenAI(api_key="ollama", base_url=settings.ollama_base_url)
    return OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)


def chat_model() -> str:
    if settings.model_provider.lower().strip() == "ollama":
        return settings.ollama_model
    return settings.openai_model


_CHAT_SYSTEM_PROMPT = """你是 JobMatch Agent 的求职助手，帮助用户搜索岗位、分析匹配、优化简历。
只能基于用户简历事实回答，不得编造经历。
可用斜杠指令：/search 搜岗位、/status 看概览、/matches 匹配结果、/profile 简历档案、/help 查看全部指令。
回答简洁实用，用中文。"""


def llm_chat(user_message: str, *, context: str = "") -> str | None:
    """Free-form chat reply via configured LLM (Ollama or OpenAI-compatible)."""
    client = get_chat_client()
    if client is None:
        return None

    system = _CHAT_SYSTEM_PROMPT
    if context.strip():
        system = f"{system}\n\n上下文:\n{context.strip()}"

    try:
        resp = client.chat.completions.create(
            model=chat_model(),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
        )
        content = (resp.choices[0].message.content or "").strip()
        return content or None
    except Exception as exc:
        logger.warning("LLM chat failed: %s", exc)
        return None


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def llm_match_job(
    job: Job,
    resume: dict,
    evidence: list[str],
    rule_score: int,
    threshold: int,
) -> MatchResult | None:
    client = get_chat_client()
    if client is None:
        return None

    resume_skills = resume.get("skills", [])
    prompt = f"""你是求职匹配助手。根据岗位 JD、候选人简历事实和 RAG 证据打分（0-100）。
只能使用简历和证据中可验证的信息，不得编造经历。
规则引擎预估分: {rule_score}，可作为参考。

岗位: {job.title} @ {job.company}
JD: {job.description[:2000]}

简历技能: {', '.join(str(s) for s in resume_skills[:30])}
RAG证据:
{chr(10).join(evidence[:5]) or '(无)'}

返回 JSON:
{{
  "score": 0-100,
  "advantages": ["..."],
  "missing": ["..."],
  "suggest": "推荐投递|观望|不推荐",
  "reasoning": "简短说明"
}}"""

    try:
        resp = client.chat.completions.create(
            model=chat_model(),
            messages=[
                {"role": "system", "content": "只输出合法 JSON，不要 markdown。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        data = _extract_json(resp.choices[0].message.content or "")
        if not data:
            return None
        score = int(max(0, min(100, int(data.get("score", rule_score)))))
        suggest = data.get("suggest", "观望")
        if suggest not in {"推荐投递", "观望", "不推荐"}:
            suggest = "推荐投递" if score >= threshold else ("观望" if score >= threshold - 15 else "不推荐")
        return MatchResult(
            job_id=job.id,
            score=score,
            advantages=[str(x) for x in data.get("advantages", [])][:8],
            missing=[str(x) for x in data.get("missing", [])][:5],
            suggest=suggest,
            rag_evidence=evidence[:3],
            reasoning=str(data.get("reasoning", f"llm_score={score}, rule={rule_score}")),
        )
    except Exception as exc:
        logger.warning("LLM match failed for %s: %s", job.id, exc)
        return None


def llm_optimize_resume(job: Job, match: MatchResult, resume: dict) -> OptimizedResume | None:
    client = get_chat_client()
    if client is None:
        return None

    prompt = f"""针对岗位生成定制简历草稿。只能改写 resume.json 和 RAG 证据中的事实，不得捏造。
缺失技能标记为待核实。

岗位: {job.title} @ {job.company}
JD: {job.description[:2000]}
匹配分: {match.score}
缺失: {', '.join(match.missing[:5])}

简历 JSON:
{json.dumps(resume, ensure_ascii=False)[:4000]}

返回 JSON:
{{
  "summary": "...",
  "skills_highlight": ["..."],
  "project_bullets": [{{"original":"...","optimized":"...","keywords_matched":[],"evidence_source":"...","confidence":"高|中|待核实"}}],
  "experience_bullets": [{{"original":"...","optimized":"...","keywords_matched":[],"evidence_source":"...","confidence":"高|中|待核实"}}],
  "missing_gaps": ["..."],
  "honest_notes": ["..."],
  "ats_keyword_coverage": 0.0-1.0,
  "cover_letter_hook": "...",
  "full_markdown": "完整 markdown 简历"
}}"""

    try:
        resp = client.chat.completions.create(
            model=chat_model(),
            messages=[
                {"role": "system", "content": "只输出合法 JSON。不得编造无证据经历。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        data = _extract_json(resp.choices[0].message.content or "")
        if not data:
            return None

        def _bullets(key: str) -> list[ResumeBullet]:
            items = []
            for item in data.get(key, []):
                conf = item.get("confidence", "中")
                if conf not in {"高", "中", "待核实"}:
                    conf = "中"
                items.append(ResumeBullet(
                    original=item.get("original"),
                    optimized=str(item.get("optimized", "")),
                    keywords_matched=[str(x) for x in item.get("keywords_matched", [])],
                    evidence_source=str(item.get("evidence_source", "resume.json")),
                    confidence=conf,
                ))
            return items

        coverage = float(data.get("ats_keyword_coverage", 0.5))
        coverage = max(0.0, min(1.0, coverage))
        full_md = str(data.get("full_markdown", ""))
        if not full_md.strip():
            full_md = f"# {job.title} @ {job.company}\n\n{data.get('summary', '')}"

        return OptimizedResume(
            job_id=job.id,
            company=job.company,
            title=job.title,
            summary=str(data.get("summary", "")),
            skills_highlight=[str(x) for x in data.get("skills_highlight", [])][:12],
            project_bullets=_bullets("project_bullets"),
            experience_bullets=_bullets("experience_bullets"),
            missing_gaps=[str(x) for x in data.get("missing_gaps", match.missing[:5])],
            honest_notes=[str(x) for x in data.get("honest_notes", [])],
            ats_keyword_coverage=round(coverage, 2),
            full_markdown=full_md,
            cover_letter_hook=str(data.get("cover_letter_hook", "")),
        )
    except Exception as exc:
        logger.warning("LLM resume optimize failed for %s: %s", job.id, exc)
        return None

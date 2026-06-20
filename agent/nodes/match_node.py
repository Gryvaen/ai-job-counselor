"""match_node.py — explainable job matching with resume and RAG signals."""

import json
import re
from typing import Literal

from config.settings import settings
from models.agent_state import AgentState
from models.match import MatchResult

_POSITIVE_KEYWORDS = [
    "linux", "驱动", "bsp", "嵌入式", "c", "stm32", "arm", "rtos",
    "device tree", "设备树", "内核", "kernel", "i2c", "spi", "gpio",
    "平台", "platform", "driver", "makefile",
]


def match_node(state: AgentState) -> dict:
    jobs = state["jobs"]
    threshold = state["threshold"]
    resume = _load_resume()
    contexts_by_job = _contexts_by_job(state.get("retrieved_context", []))
    results = []
    for job in jobs:
        evidence = contexts_by_job.get(job.id, [])
        score, advantages, missing, reasoning = _score_job(job, state, resume, evidence)
        results.append(MatchResult(
            job_id=job.id, score=score, advantages=advantages,
            missing=missing[:5], suggest=_suggest(score, threshold),
            rag_evidence=evidence[:3],
            reasoning=reasoning,
        ))
    print(f"[agent/match] Scored {len(results)} jobs, {sum(1 for r in results if r.score >= threshold)} >= {threshold}")
    return {"match_results": results}


def _load_resume() -> dict:
    if not settings.resume_path.exists():
        return {"skills": [], "preferences": {}}
    try:
        with open(settings.resume_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"[agent/match] Could not load resume profile: {exc}")
        return {"skills": [], "preferences": {}}


def _contexts_by_job(contexts: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for item in contexts:
        match = re.search(r"job_id=([0-9a-f]{32})", item)
        if match:
            grouped.setdefault(match.group(1), []).append(item)
    return grouped


def _contains(text: str, keyword: str) -> bool:
    kw = keyword.lower()
    if kw == "c":
        return bool(re.search(r"(?<![a-z0-9+#])c(?![a-z0-9+#])", text))
    if re.fullmatch(r"[a-z0-9+#.-]+", kw):
        return bool(re.search(rf"(?<![a-z0-9+#.-]){re.escape(kw)}(?![a-z0-9+#.-])", text))
    return kw in text


def _requested_hit(text: str, keyword: str) -> bool:
    if _contains(text, keyword):
        return True
    parts = re.findall(r"[a-z0-9+#.-]+|[\u4e00-\u9fff]+", keyword.lower())
    if len(parts) <= 1:
        return False
    return all(_contains(text, part) for part in parts)


def _score_job(job, state: AgentState, resume: dict, evidence: list[str]) -> tuple[int, list[str], list[str], str]:
    text = f"{job.title} {job.description}".lower()
    requested = [kw.strip() for kw in state.get("keywords", []) if kw.strip()]
    resume_skills = [str(skill) for skill in resume.get("skills", [])]
    preference_keywords = resume.get("preferences", {}).get("keywords", [])
    all_keywords = list(dict.fromkeys(_POSITIVE_KEYWORDS + requested + resume_skills + preference_keywords))

    matched = [kw for kw in all_keywords if _contains(text, kw)]
    requested_hits = [kw for kw in requested if _requested_hit(text, kw)]
    resume_hits = [kw for kw in resume_skills if _contains(text, kw)]
    evidence_hits = [kw for kw in resume_skills if any(_contains(ctx.lower(), kw) for ctx in evidence)]

    missing = [kw for kw in _POSITIVE_KEYWORDS if not _contains(text, kw)]

    keyword_score = min(60, len(matched) * 6)
    request_score = min(30, len(requested_hits) * 15)
    resume_score = min(15, len(resume_hits) * 4)
    rag_score = min(5, len(evidence_hits) * 2 + (2 if evidence else 0))
    penalty = 15 if re.search(r"高级|专家|架构师|leader|负责人", text) and "实习" in state.get("user_query", "") else 0
    score = max(0, min(100, keyword_score + request_score + resume_score + rag_score - penalty))

    advantages = list(dict.fromkeys(matched + [f"RAG evidence: {kw}" for kw in evidence_hits]))
    reasoning = (
        f"keyword={keyword_score}, requested={request_score}, resume={resume_score}, "
        f"rag={rag_score}, penalty={penalty}; matched={len(matched)}"
    )
    return score, advantages, missing, reasoning


def _suggest(score: int, threshold: int) -> Literal["推荐投递", "观望", "不推荐"]:
    if score >= threshold: return "推荐投递"
    elif score >= threshold - 15: return "观望"
    else: return "不推荐"

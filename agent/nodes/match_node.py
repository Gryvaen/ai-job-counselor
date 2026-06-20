"""
match_node.py — Rule-based job matching (Phase 1).
"""

from models.match import MatchResult
from models.agent_state import AgentState
from typing import Literal

_POSITIVE_KEYWORDS = [
    "linux", "驱动", "bsp", "嵌入式", "c", "stm32", "arm",
    "device tree", "设备树", "内核", "kernel", "i2c",
    "spi", "gpio", "平台", "platform",
]


def match_node(state: AgentState) -> dict:
    jobs = state["jobs"]
    threshold = state["threshold"]
    results = []
    for job in jobs:
        score, advantages, missing = _score_job(job)
        results.append(MatchResult(
            job_id=job.id, score=score, advantages=advantages,
            missing=missing[:5], suggest=_suggest(score, threshold),
            rag_evidence=[],
            reasoning=f"Rule-based match: {len(advantages)} keywords matched",
        ))
    print(f"[agent/match] Scored {len(results)} jobs, {sum(1 for r in results if r.score >= threshold)} >= {threshold}")
    return {"match_results": results}


def _score_job(job) -> tuple[int, list[str], list[str]]:
    text = f"{job.title} {job.description}".lower()
    matched = [kw for kw in _POSITIVE_KEYWORDS if kw.lower() in text]
    missing = [kw for kw in _POSITIVE_KEYWORDS if kw.lower() not in text]
    score = int((len(matched) / len(_POSITIVE_KEYWORDS)) * 80) if _POSITIVE_KEYWORDS else 50
    return max(0, min(100, score)), matched, missing


def _suggest(score: int, threshold: int) -> Literal["推荐投递", "观望", "不推荐"]:
    if score >= threshold: return "推荐投递"
    elif score >= threshold - 15: return "观望"
    else: return "不推荐"

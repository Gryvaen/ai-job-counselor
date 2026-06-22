"""
plan_node.py — Intent parser that extracts keywords from user query.
Phase 1: simple keyword extraction. Will use LLM in Phase 4.
"""

import re
from config.settings import settings
from models.agent_state import AgentState
from scraper.boss_scraper import CITY_CODES


FILLER_WORDS = {
    "帮我", "帮忙", "请", "我想", "想要", "想找", "找", "搜索", "检索", "看看",
    "岗位", "职位", "工作", "机会", "boss", "boss直聘", "直聘", "一下", "的",
}


def parse_job_query(query: str) -> tuple[list[str], str, int | None]:
    """Extract search keywords, city, and optional threshold from a natural query."""
    city = "全国"
    for name in sorted(CITY_CODES, key=len, reverse=True):
        if name != "全国" and name in query:
            city = name
            query = query.replace(name, " ")
            break

    threshold = None
    threshold_match = re.search(r'(\d+)\s*分以上?', query)
    if threshold_match:
        threshold = int(threshold_match.group(1))
        query = query.replace(threshold_match.group(0), " ")

    cleaned = query.lower()
    for word in FILLER_WORDS:
        cleaned = cleaned.replace(word.lower(), " ")
    cleaned = re.sub(r"[，,、/|；;]+|和|与|及", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    keywords = [k.strip() for k in cleaned.split(" ") if k.strip()]
    return keywords, city, threshold


def plan_node(state: AgentState) -> dict:
    """Parse user query to extract search keywords and threshold."""
    user_query = state.get("user_query", "")
    threshold = state.get("threshold", settings.match_threshold)
    keywords = state.get("keywords", [])
    city = state.get("city", "全国")

    # If keywords already provided, use them
    if keywords:
        print(f"[agent/plan] Using provided keywords: {keywords}")
        return {"user_query": user_query, "keywords": keywords, "city": city, "threshold": threshold}

    # Extract keywords from query: split by common separators
    if not user_query:
        print("[agent/plan] No query provided, using default keywords")
        keywords = ["Linux驱动", "嵌入式"]
    else:
        parsed_keywords, parsed_city, parsed_threshold = parse_job_query(user_query)
        keywords = parsed_keywords or ["Linux驱动", "嵌入式"]
        city = parsed_city
        if parsed_threshold is not None:
            threshold = parsed_threshold
        print(f"[agent/plan] Extracted threshold: {threshold}")

    print(f"[agent/plan] Extracted keywords: {keywords}, city: {city}")
    return {"user_query": user_query, "keywords": keywords, "city": city, "threshold": threshold}

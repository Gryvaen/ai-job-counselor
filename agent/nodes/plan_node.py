"""
plan_node.py — Intent parser that extracts keywords from user query.
Phase 1: simple keyword extraction. Will use LLM in Phase 4.
"""

import re
from config.settings import settings
from models.agent_state import AgentState


def plan_node(state: AgentState) -> dict:
    """Parse user query to extract search keywords and threshold."""
    user_query = state.get("user_query", "")
    threshold = state.get("threshold", settings.match_threshold)
    keywords = state.get("keywords", [])

    # If keywords already provided, use them
    if keywords:
        print(f"[agent/plan] Using provided keywords: {keywords}")
        return {"user_query": user_query, "keywords": keywords, "threshold": threshold}

    # Extract keywords from query: split by common separators
    if not user_query:
        print("[agent/plan] No query provided, using default keywords")
        keywords = ["Linux驱动", "嵌入式"]
    else:
        # Split by Chinese commas, English commas, spaces
        keywords = [k.strip() for k in re.split(r'[，,\s]+', user_query) if k.strip()]

    # Extract threshold from query (e.g., "80分以上")
    threshold_match = re.search(r'(\d+)\s*分以上?', user_query)
    if threshold_match:
        threshold = int(threshold_match.group(1))
        print(f"[agent/plan] Extracted threshold: {threshold}")

    print(f"[agent/plan] Extracted keywords: {keywords}")
    return {"user_query": user_query, "keywords": keywords, "threshold": threshold}

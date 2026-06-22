"""
agent/graph.py — Full pipeline LangGraph StateGraph.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langgraph.graph import StateGraph, END
from models.agent_state import AgentState
from agent.nodes.plan_node import plan_node
from agent.nodes.source_node import source_node
from agent.nodes.retrieve_node import retrieve_node
from agent.nodes.match_node import match_node
from agent.nodes.optimize_node import optimize_node
from agent.nodes.review_node import review_node
from agent.nodes.record_node import record_node


def build_graph():
    """Build and compile the full pipeline:
    plan → source → retrieve → match → optimize (if score>=th) → review → record
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("plan", plan_node)
    workflow.add_node("source", source_node)
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("match", match_node)
    workflow.add_node("optimize", optimize_node)
    workflow.add_node("review", review_node)
    workflow.add_node("record", record_node)

    workflow.set_entry_point("plan")
    workflow.add_edge("plan", "source")
    workflow.add_edge("source", "retrieve")
    workflow.add_edge("retrieve", "match")

    def _after_match(state):
        high = [r for r in state.get("match_results", []) if r.score >= state.get("threshold", 75)]
        return "optimize" if high else "record"

    workflow.add_conditional_edges("match", _after_match,
        {"optimize": "optimize", "record": "record"})

    workflow.add_edge("optimize", "review")
    workflow.add_edge("review", "record")
    workflow.add_edge("record", END)

    return workflow.compile()

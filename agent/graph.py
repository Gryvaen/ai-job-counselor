"""LangGraph counselor pipeline: job → gap → plan → projects."""

from langgraph.graph import END, StateGraph

from agent.nodes.job_analyzer import job_analyzer_node
from agent.nodes.learning_planner import learning_planner_node
from agent.nodes.project_recommender import project_recommender_node
from agent.nodes.skill_gap_analyzer import skill_gap_analyzer_node
from models.counselor import CounselorState


def build_counselor_graph():
    workflow = StateGraph(CounselorState)

    workflow.add_node("job_analyzer", job_analyzer_node)
    workflow.add_node("skill_gap_analyzer", skill_gap_analyzer_node)
    workflow.add_node("learning_planner", learning_planner_node)
    workflow.add_node("project_recommender", project_recommender_node)

    workflow.set_entry_point("job_analyzer")
    workflow.add_edge("job_analyzer", "skill_gap_analyzer")
    workflow.add_edge("skill_gap_analyzer", "learning_planner")
    workflow.add_edge("learning_planner", "project_recommender")
    workflow.add_edge("project_recommender", END)

    return workflow.compile()


# Backward-compatible alias for tests migrating from old graph
def build_graph():
    return build_counselor_graph()

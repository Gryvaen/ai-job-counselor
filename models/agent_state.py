"""
AgentState — LangGraph StateGraph state shared across all pipeline nodes.
"""

from typing import Annotated

from langgraph.graph import add_messages

from models.job import Job
from models.match import MatchResult
from models.resume import OptimizedResume
from models.optimizer import LearningPlan


class AgentState(dict):
    """
    LangGraph state. Defined as a TypedDict-like class with annotations.
    """

    user_query: str  # 用户输入的查询/问题
    keywords: list[str]  # 关键词列表，由查询抽取或用户指定
    city: str  # 岗位城市，默认全国
    threshold: int  # 匹配分数阈值，用于筛选合格岗位

    # Data accumulated through the pipeline
    jobs: list[Job]  # 待分析的岗位列表
    retrieved_context: list[str]  # RAG检索返回的上下文内容
    match_results: list[MatchResult]  # 岗位与简历的匹配结果
    optimized_resumes: list[OptimizedResume]  # 针对不同岗位优化后的简历
    learning_plans: list[LearningPlan]  # 针对岗位/能力要求生成的学习规划

    # Chat history (LangGraph-managed)
    messages: Annotated[list, add_messages]  # LangGraph自动维护的消息历史

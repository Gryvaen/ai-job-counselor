"""
retrieve_node.py — LangGraph node that calls RAG retriever for each job.
"""

from rag.retriever import RAGRetriever
from config.settings import settings
from models.agent_state import AgentState


def retrieve_node(state: AgentState) -> dict:
    jobs = state.get("jobs", [])
    if not jobs:
        return {"retrieved_context": []}

    try:
        retriever = RAGRetriever()
    except Exception as e:
        print(f"[agent/retrieve] RAG not available: {e}")
        return {"retrieved_context": []}

    all_context = []
    for job in jobs:
        query = f"{job.title} {job.description}"[:512]
        results = retriever.retrieve(query, top_k=settings.rag_top_k)
        for text, meta in results:
            all_context.append(f"[{meta.get('source', '?')}] {text}")
        print(f"[agent/retrieve] {job.title} @ {job.company}: {len(results)} snippets")

    print(f"[agent/retrieve] Total: {len(all_context)} context snippets")
    return {"retrieved_context": all_context}

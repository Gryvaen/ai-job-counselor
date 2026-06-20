#!/usr/bin/env python3
"""
rag-mcp — MCP Server for RAG (Chroma + OpenAI embeddings).

Tools: retrieve, ingest_document, list_sources
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastmcp import FastMCP
from config.settings import settings
from rag.retriever import RAGRetriever
from rag.ingest import ingest_file, ingest_directory
from rag.chunker import chunk_document

mcp = FastMCP("jobmatch-rag", port=8002)


@mcp.tool()
def retrieve(query: str, top_k: int = 5) -> list[dict]:
    """Retrieve relevant knowledge base snippets for a query.

    Args:
        query: Search query (typically job title + description)
        top_k: Number of results to return

    Returns:
        List of {text, metadata, similarity} dicts
    """
    retriever = RAGRetriever()
    results = retriever.retrieve(query, top_k=top_k)
    return [{"text": text, **meta} for text, meta in results]


@mcp.tool()
def ingest_document(file_path: str, source_type: str | None = None) -> int:
    """Ingest a single document file into the RAG knowledge base.

    Args:
        file_path: Path to the document file (.md, .txt, .rst, .json)
        source_type: Optional type override (projects/notes/interviews/past_jobs)

    Returns:
        Number of chunks ingested
    """
    return ingest_file(file_path, source_type=source_type)


@mcp.tool()
def ingest_all_documents(directory: str | None = None) -> int:
    """Recursively ingest all supported files from the knowledge directory.

    Args:
        directory: Knowledge directory (defaults to settings.knowledge_dir)

    Returns:
        Total number of chunks ingested
    """
    return ingest_directory(directory)


@mcp.tool()
def list_sources() -> list[dict]:
    """List all unique sources in the RAG knowledge base.

    Returns:
        List of {source, type} dicts
    """
    retriever = RAGRetriever()
    return retriever.list_sources()


if __name__ == "__main__":
    mcp.run(transport="stdio")

"""
RAG Chunker — splits text into overlapping chunks for Chroma embedding.
"""

from config.settings import settings


def chunk_text(text: str, chunk_size: int | None = None, chunk_overlap: int | None = None) -> list[str]:
    """Split text into overlapping character-based chunks."""
    if not text.strip():
        return []
    cs = chunk_size or settings.rag_chunk_size
    co = chunk_overlap or settings.rag_chunk_overlap
    chunks = []
    start = 0
    while start < len(text):
        end = start + cs
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start += cs - co
    return chunks


def chunk_document(content: str, metadata: dict, chunk_size: int | None = None,
                   chunk_overlap: int | None = None) -> list[tuple[str, dict]]:
    """Split a document into chunks, each with a copy of metadata."""
    chunks = chunk_text(content, chunk_size, chunk_overlap)
    result = []
    for i, chunk in enumerate(chunks):
        meta = metadata.copy()
        meta["chunk_id"] = i
        meta["source_type"], meta["__source__"] = meta.get("source_type", "unknown"), meta.get("source", "unknown")
        result.append((chunk, meta))
    return result

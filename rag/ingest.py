"""
RAG Knowledge ingestion — reads files from data/knowledge/ and indexes into Chroma.
"""

import hashlib
from pathlib import Path

from config.settings import settings
from rag.chunker import chunk_document
from rag.retriever import RAGRetriever


def ingest_file(file_path: str | Path, retriever: RAGRetriever | None = None,
                source_type: str | None = None) -> int:
    """Read a single file and ingest its chunks."""
    file_path = Path(file_path)
    if not file_path.exists():
        return 0
    content = file_path.read_text(encoding="utf-8")
    if not content.strip():
        return 0
    if source_type is None:
        parent = file_path.parent.name
        source_type = parent if parent in ("projects", "notes", "interviews", "past_jobs") else "document"
    chunks = chunk_document(
        content, {"source": str(file_path), "source_type": source_type},
        chunk_size=settings.rag_chunk_size, chunk_overlap=settings.rag_chunk_overlap,
    )
    texts = [c[0] for c in chunks]
    metadatas = [c[1] for c in chunks]
    ids = [hashlib.md5(f"{file_path}:{i}".encode()).hexdigest() for i in range(len(texts))]
    retriever = retriever or RAGRetriever()
    retriever.ingest(texts, metadatas, ids)
    return len(chunks)


def ingest_directory(directory: str | Path | None = None, retriever: RAGRetriever | None = None) -> int:
    """Recursively ingest all supported files from a knowledge directory."""
    dir_path = Path(directory or settings.knowledge_dir)
    if not dir_path.exists():
        print(f"[ingest] Directory not found: {dir_path}")
        return 0
    total = 0
    for fp in sorted(dir_path.rglob("*")):
        if fp.is_file() and fp.suffix in (".md", ".txt", ".rst", ".json"):
            total += ingest_file(fp, retriever)
    print(f"[ingest] Total: {total} chunks from {dir_path}")
    return total


if __name__ == "__main__":
    print("Ingesting knowledge documents...")
    ingest_directory()

"""
RAG Retriever — queries Chroma vector store for job-related knowledge.
"""

import hashlib
from pathlib import Path

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from openai import OpenAI

from config.settings import settings


class OpenAIEmbeddingFunction(EmbeddingFunction[Documents]):
    """Chroma-compatible embedding adapter for current Chroma releases."""

    def __init__(self, api_key: str, base_url: str | None, model: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def __call__(self, input: Documents) -> Embeddings:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for RAG embeddings.")
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        resp = client.embeddings.create(input=list(input), model=self.model)
        return [r.embedding for r in resp.data]


class RAGRetriever:
    """Retrieve relevant knowledge base snippets using Chroma + OpenAI embeddings."""

    def __init__(self, persist_directory: Path | None = None, collection_name: str = "knowledge"):
        self.persist_dir = persist_directory or settings.chroma_dir
        self.collection_name = collection_name
        self._client = None
        self._collection = None
        self._embed_fn = None

    def _get_embed_fn(self):
        """Lazy-load embedding function."""
        if self._embed_fn is None:
            self._embed_fn = OpenAIEmbeddingFunction(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.openai_embedding_model,
            )
        return self._embed_fn

    def _get_client(self):
        if self._client is None:
            Path(self.persist_dir).mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        return self._client

    def _get_collection(self):
        client = self._get_client()
        if self._collection is None:
            try:
                self._collection = client.get_collection(
                    self.collection_name,
                    embedding_function=self._get_embed_fn(),
                )
            except Exception:
                self._collection = client.create_collection(
                    name=self.collection_name,
                    metadata={"hnsw:space": "cosine"},
                    embedding_function=self._get_embed_fn(),
                )
        return self._collection

    def retrieve(self, query: str, top_k: int | None = None) -> list[tuple[str, dict]]:
        """Retrieve top-k relevant documents. Returns [(text, metadata)]."""
        k = top_k or settings.rag_top_k
        try:
            collection = self._get_collection()
            results = collection.query(
                query_texts=[query], n_results=k,
                include=["documents", "metadatas", "distances"],
            )
            items = []
            if results["documents"] and results["documents"][0]:
                for doc, meta, dist in zip(
                    results["documents"][0], results["metadatas"][0], results["distances"][0]
                ):
                    meta["similarity"] = round(1.0 - dist, 4)
                    items.append((doc, meta))
            return items
        except Exception as e:
            print(f"[rag] Retrieval failed: {e}")
            return []

    def ingest(self, texts: list[str], metadatas: list[dict], ids: list[str] | None = None):
        """Add document chunks to Chroma."""
        if not texts:
            return
        collection = self._get_collection()
        if ids is None:
            ids = [hashlib.md5(t.encode()).hexdigest() for t in texts]
        collection.add(documents=texts, metadatas=metadatas, ids=ids)
        print(f"[rag] Ingested {len(texts)} chunks.")

    def list_sources(self) -> list[dict]:
        """List unique sources in Chroma."""
        try:
            collection = self._get_collection()
            results = collection.get(include=["metadatas"])
            sources, seen = [], set()
            for meta in results.get("metadatas", []):
                src = meta.get("source", "unknown")
                if src not in seen:
                    seen.add(src)
                    sources.append({"source": src, "type": meta.get("source_type", "unknown")})
            return sources
        except Exception as e:
            print(f"[rag] Failed to list sources: {e}")
            return []

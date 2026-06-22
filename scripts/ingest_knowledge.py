#!/usr/bin/env python3
"""
RAG knowledge ingestion script.
Reads documents from data/knowledge/ and indexes them into Chroma.

Usage:
    python scripts/ingest_knowledge.py
    python scripts/ingest_knowledge.py --dir data/knowledge/projects
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.logging import setup_logging
from config.settings import settings
from rag.ingest import ingest_directory
from storage.db import get_engine, record_knowledge_ingest


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest knowledge documents into Chroma")
    parser.add_argument("--dir", default="", help="Knowledge directory (default: settings.knowledge_dir)")
    args = parser.parse_args()

    setup_logging()
    get_engine(settings.db_path)

    target = Path(args.dir) if args.dir else settings.knowledge_dir
    print("=" * 50)
    print("Knowledge Ingestion")
    print("=" * 50)
    print(f"Knowledge dir: {target}")
    print(f"Chroma dir: {settings.chroma_dir}")
    print()

    chunks = ingest_directory(target)
    record_knowledge_ingest(chunks, str(target))
    print(f"\nDone: indexed {chunks} chunks.")
    return 0 if chunks >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

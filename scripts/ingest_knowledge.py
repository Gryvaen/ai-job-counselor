#!/usr/bin/env python3
"""
RAG knowledge ingestion script.
Reads documents from data/knowledge/ and indexes them into Chroma.

Usage:
    python scripts/ingest_knowledge.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from config.settings import settings
from models.job import Job
from models.match import MatchResult


def main():
    print("=" * 50)
    print("Knowledge Ingestion (Phase 2)")
    print("=" * 50)
    print(f"Knowledge dir: {settings.knowledge_dir}")
    print(f"Chroma dir: {settings.chroma_dir}")
    print()
    print("Not implemented yet — coming in Phase 2 (RAG).")
    print("For now, place your markdown/text/PDF files in data/knowledge/ subdirectories.")


if __name__ == "__main__":
    main()

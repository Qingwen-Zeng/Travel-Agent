"""Builds the FAISS semantic-search index over city_stories, for the get_city_context
chat tool. Run this after scripts/import_stories.py (or any time city_stories changes).

Usage: python scripts/build_story_index.py [--db travel.db] [--index stories.faiss]
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_readonly_connection
from app.rag import SentenceTransformerEmbedder, build_index, save_index


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build the FAISS index over city_stories.")
    parser.add_argument("--db", default="travel.db", type=Path)
    parser.add_argument("--index", default="stories.faiss", type=Path)
    args = parser.parse_args(argv)

    conn = get_readonly_connection(args.db)
    index = build_index(conn, SentenceTransformerEmbedder())

    if index is None:
        print("No stories in city_stories — nothing to index.", file=sys.stderr)
        return 1

    save_index(index, args.index)
    print(f"{args.index}: indexed {index.ntotal} stories")
    return 0


if __name__ == "__main__":
    sys.exit(main())

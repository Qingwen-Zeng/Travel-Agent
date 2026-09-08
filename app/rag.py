import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

import faiss
import numpy as np

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
DEFAULT_TOP_K = 5


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    """Loads the model lazily on first use, so importing this module never triggers a
    network call or a model load — only calling `embed` does."""

    def __init__(self, model_name: str = EMBEDDING_MODEL_NAME):
        self._model_name = model_name
        self._model = None

    def embed(self, texts: list[str]) -> np.ndarray:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return np.asarray(
            self._model.encode(texts, normalize_embeddings=True), dtype="float32"
        )


@dataclass(frozen=True)
class StoryMatch:
    story: str
    city: Optional[str]


def build_index(conn: sqlite3.Connection, embedder: Embedder) -> Optional[faiss.Index]:
    """Embeds every row in city_stories and returns a FAISS index keyed by
    city_stories.id, or None if there are no stories to index."""
    rows = conn.execute("SELECT id, story FROM city_stories ORDER BY id").fetchall()
    if not rows:
        return None

    vectors = embedder.embed([row["story"] for row in rows])
    ids = np.array([row["id"] for row in rows], dtype="int64")

    index = faiss.IndexIDMap2(faiss.IndexFlatIP(vectors.shape[1]))
    index.add_with_ids(vectors, ids)
    return index


def save_index(index: faiss.Index, path: str | Path) -> None:
    faiss.write_index(index, str(path))


def load_index(path: str | Path) -> Optional[faiss.Index]:
    if not Path(path).exists():
        return None
    return faiss.read_index(str(path))


def search(
    conn: sqlite3.Connection,
    index: Optional[faiss.Index],
    embedder: Embedder,
    query: str,
    k: int = DEFAULT_TOP_K,
) -> list[StoryMatch]:
    """Semantic search over the whole story corpus. Matches from `_unmatched` entries
    come back with city=None."""
    if index is None or index.ntotal == 0:
        return []

    query_vector = embedder.embed([query])
    _, ids = index.search(query_vector, min(k, index.ntotal))

    matches = []
    for story_id in ids[0]:
        if story_id == -1:
            continue
        row = conn.execute(
            "SELECT city_stories.story AS story, cities.name AS city\n"
            "  FROM city_stories\n"
            "  LEFT JOIN cities ON cities.id = city_stories.city_id\n"
            " WHERE city_stories.id = ?;",
            (int(story_id),),
        ).fetchone()
        if row is not None:
            matches.append(StoryMatch(story=row["story"], city=row["city"]))
    return matches

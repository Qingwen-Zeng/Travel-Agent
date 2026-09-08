import numpy as np

from app.db import get_writable_connection
from app.rag import build_index, load_index, save_index, search


class FakeEmbedder:
    """Deterministic toy embedder: maps each known text to a fixed 3-d unit vector, so
    nearest-neighbor results are predictable without loading a real model."""

    def __init__(self, vectors: dict[str, list[float]]):
        self._vectors = vectors

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.array([self._vectors[t] for t in texts], dtype="float32")


def _seed_city(conn, name: str) -> int:
    conn.execute("INSERT INTO cities (name) VALUES (?)", (name,))
    return conn.execute("SELECT id FROM cities WHERE name = ?", (name,)).fetchone()["id"]


def test_build_index_returns_none_for_empty_corpus(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")

    index = build_index(conn, FakeEmbedder({}))

    assert index is None


def test_search_finds_nearest_story_by_vector_similarity(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    tokyo_id = _seed_city(conn, "Tokyo")
    paris_id = _seed_city(conn, "Paris")
    conn.execute(
        "INSERT INTO city_stories (city_id, story) VALUES (?, 'ramen and neon lights')",
        (tokyo_id,),
    )
    conn.execute(
        "INSERT INTO city_stories (city_id, story) VALUES (?, 'croissants and the Seine')",
        (paris_id,),
    )
    conn.commit()

    embedder = FakeEmbedder(
        {
            "ramen and neon lights": [1.0, 0.0, 0.0],
            "croissants and the Seine": [0.0, 1.0, 0.0],
            "best food in Tokyo": [0.9, 0.1, 0.0],
        }
    )
    index = build_index(conn, embedder)

    results = search(conn, index, embedder, "best food in Tokyo", k=1)

    assert len(results) == 1
    assert results[0].story == "ramen and neon lights"
    assert results[0].city == "Tokyo"


def test_search_returns_none_city_for_unmatched_stories(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    conn.execute(
        "INSERT INTO city_stories (city_id, story) VALUES (NULL, 'an untagged trip diary entry')"
    )
    conn.commit()

    embedder = FakeEmbedder(
        {
            "an untagged trip diary entry": [1.0, 0.0, 0.0],
            "anything": [1.0, 0.0, 0.0],
        }
    )
    index = build_index(conn, embedder)

    results = search(conn, index, embedder, "anything", k=1)

    assert results[0].story == "an untagged trip diary entry"
    assert results[0].city is None


def test_search_returns_empty_list_when_no_index_exists(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")

    results = search(conn, None, FakeEmbedder({}), "anything")

    assert results == []


def test_save_and_load_index_roundtrips(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    city_id = _seed_city(conn, "Tokyo")
    conn.execute(
        "INSERT INTO city_stories (city_id, story) VALUES (?, 'ramen and neon lights')",
        (city_id,),
    )
    conn.commit()
    embedder = FakeEmbedder(
        {"ramen and neon lights": [1.0, 0.0, 0.0], "food": [0.9, 0.1, 0.0]}
    )
    index = build_index(conn, embedder)
    index_path = tmp_path / "stories.faiss"

    save_index(index, index_path)
    loaded = load_index(index_path)

    results = search(conn, loaded, embedder, "food", k=1)
    assert results[0].story == "ramen and neon lights"


def test_load_index_returns_none_when_file_missing(tmp_path):
    assert load_index(tmp_path / "does-not-exist.faiss") is None

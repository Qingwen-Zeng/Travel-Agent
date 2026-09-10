# 08 — RAG: grounding answers in your own text

The model knows a lot about the world, but it does not know what *Joey* wrote in
his private travel diary. **Retrieval-Augmented Generation (RAG)** is how you feed
your own text into the model's context so its answers are grounded in that text
rather than in generic knowledge. This app uses it for one thing: the
`get_city_context` tool, which pulls relevant diary paragraphs into the reply.

Files: `app/rag.py` (the retrieval layer) and `scripts/build_story_index.py` (the
offline index build). The database table is `city_stories` (chapter `04` §5).

---

## 1. Why RAG instead of just putting everything in the prompt

Joey's diary is a few hundred paragraphs. You *could* paste all of it into the
system prompt on every request. Problems: it costs tokens on every call whether
or not the diary is relevant, it pushes against the context window, and it buries
the two relevant sentences in a wall of unrelated text.

RAG's move: **at query time, find the handful of paragraphs actually relevant to
this question, and insert only those.** For *"tell me about Kyoto temples"* you
retrieve the three diary entries that mention Kyoto temples and hand those to the
model. Everything else stays out.

The retrieval has to be by *meaning*, not keyword — a diary entry that says "the
moss garden at Saihō-ji" should match a query about "Kyoto temples" even with no
word in common. That is what embeddings give you.

## 2. Embeddings and similarity

An **embedding model** turns a piece of text into a vector — a fixed-length list
of numbers (here, 384 of them) — such that texts with similar *meaning* produce
vectors that point in similar directions.

"Similar direction" is measured by **cosine similarity**: the cosine of the angle
between two vectors. 1.0 = identical direction, 0 = unrelated, −1 = opposite. If
you first **normalise** every vector to length 1, cosine similarity equals the
plain **inner product** (dot product) — which is cheaper to compute. This app
normalises, so it can use the fast inner-product index.

So the recipe is:

1. Offline: embed every diary paragraph, store the vectors.
2. At query time: embed the query, find the stored vectors with the highest inner
   product with it, return the paragraphs they came from.

## 3. The embedding model: `sentence-transformers`

```python
# app/rag.py
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

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
```

- **`all-MiniLM-L6-v2`** is a small, fast, well-regarded open embedding model
  (~90 MB). It runs **locally** — `sentence-transformers` downloads it once and
  caches it; there is no API call and no per-query network at all. This is a
  deliberate contrast with the *chat* model (a paid API): embeddings are cheap and
  local, chat is expensive and remote.
- **Lazy loading.** The `import` and the `SentenceTransformer(...)` construction
  happen inside `embed`, on first call. So `import app.rag` — which
  `app/main.py` does at startup — costs nothing; the ~90 MB model only loads if
  `get_city_context` is actually used. `app/main.py` builds
  `_story_embedder = SentenceTransformerEmbedder()` at startup precisely because
  that line is free.
- `normalize_embeddings=True` — every returned vector has length 1 (section 2).
- `dtype="float32"` — FAISS wants 32-bit floats.
- **`Embedder` is a `Protocol`** (chapter `01` §1.19). `app/rag.py` also has an
  `Embedder` protocol so tests can pass a `FakeEmbedder` that maps known strings
  to fixed toy vectors — no model load, fully deterministic (chapter `10`).

## 4. The vector index: FAISS

**FAISS** ("Facebook AI Similarity Search") stores many vectors and finds the
nearest ones to a query vector, fast. This app uses the CPU build (`faiss-cpu` in
`requirements.txt`).

```python
# app/rag.py
def build_index(conn, embedder) -> Optional[faiss.Index]:
    rows = conn.execute("SELECT id, story FROM city_stories ORDER BY id").fetchall()
    if not rows:
        return None
    vectors = embedder.embed([row["story"] for row in rows])
    ids = np.array([row["id"] for row in rows], dtype="int64")
    index = faiss.IndexIDMap2(faiss.IndexFlatIP(vectors.shape[1]))
    index.add_with_ids(vectors, ids)
    return index
```

- `IndexFlatIP(dim)` — a "flat" (exhaustive, exact) index over `dim`-dimensional
  vectors, scored by **I**nner **P**roduct. "Flat" means it compares the query
  against *every* stored vector. For a few hundred diary paragraphs that is
  instant; a flat index is the simplest correct choice and only needs replacing
  when you have millions of vectors.
- `IndexIDMap2(...)` wraps it so each vector is stored **under its real
  `city_stories.id`**, not a 0-based position. So a search result is a database id
  you can look the paragraph up by directly — no separate id-mapping file.
- `build_index` returns `None` if there are no stories, so the whole feature
  degrades cleanly to "no results" rather than crashing.

### Building it offline

```python
# app/rag.py
def save_index(index, path): faiss.write_index(index, str(path))
def load_index(path) -> Optional[faiss.Index]:
    if not Path(path).exists():
        return None
    return faiss.read_index(str(path))
```

`scripts/build_story_index.py` (chapter `09`) opens the database, calls
`build_index`, and `save_index`s the result to a single file, `stories.faiss`.
That file is a build artifact — git-ignored, rebuilt from the database whenever
`city_stories` changes, and copied into the Docker image the same way `travel.db`
is (chapter `12`).

## 5. Searching at query time

```python
# app/rag.py
def search(conn, index, embedder, query, k: int = DEFAULT_TOP_K) -> list[StoryMatch]:
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
```

- **Guard first.** If the index is missing (`None`) or empty (`ntotal == 0`),
  return `[]`. This is the graceful-degradation path: a dev machine without
  `stories.faiss` still runs the whole app; `get_city_context` just returns
  nothing and the model is instructed to skip the diary opening.
- Embed the query into one vector.
- `index.search(query_vector, k)` returns the `k` nearest stored vectors'
  **ids** (and their scores, ignored here). `min(k, ntotal)` avoids asking for
  more than exist. When fewer than `k` exist, FAISS pads with `-1`, which the
  loop skips.
- For each returned id, look the paragraph up in `city_stories`, `LEFT JOIN`ing
  `cities` so an unmatched diary entry (`city_id IS NULL`) comes back with
  `city = None`.
- Return a list of `StoryMatch(story, city)` — a small frozen dataclass.

`DEFAULT_TOP_K` is `5`, so at most five paragraphs come back per query.

## 6. How the tool uses it

Back in `app/chat.py`, when the model calls `get_city_context`:

```python
if tool_call.name == CONTEXT_TOOL_NAME:
    query = tool_call.input["query"]
    matches = search(conn, story_index, embedder, query)
    return _context_result_content(matches), None

def _context_result_content(matches) -> str:
    return json.dumps([{"story": m.story, "city": m.city} for m in matches])
```

The matches are serialised to JSON and handed back as the tool result. The second
return value is **always `None`** — `get_city_context` never produces a map. The
model then weaves the relevant excerpts into its first-person reply (or ignores
them if none fit — the prompt tells it not to force an excerpt in).

## 7. RAG vs the structured-query tool — two different retrieval styles

This app has *two* ways of pulling in its own data, and the contrast is
instructive:

| | `show_city_map` | `get_city_context` |
|---|---|---|
| Retrieval | **Structured** — exact SQL filter on city/category/name | **Semantic** — nearest embeddings |
| Input from model | An `enum`-constrained city + categories | A free-text `query` |
| Good for | "All Bangkok dessert spots" — a precise, enumerable set | "The vibe of Kyoto in autumn" — fuzzy, meaning-based |
| Output | Rows → a map + a title/note/category list | A few prose paragraphs |
| Produces a map? | Yes | Never |

Use structured retrieval when the thing you want is a well-defined set your schema
can express. Use semantic retrieval (RAG) when the query is about meaning and the
relevant text cannot be selected with a `WHERE` clause. This app needs both, so it
has both, as separate tools.

## 8. What a bigger RAG system adds

This implementation is deliberately minimal. If the corpus were much larger or
changed constantly, you would add:

- **Chunking strategy** — splitting long documents into overlapping passages of a
  target size, rather than one embedding per paragraph.
- **An approximate index** (`IndexIVFFlat`, HNSW, or a hosted vector database) —
  once exact/flat search over every vector is too slow.
- **Metadata filtering** — "only search entries tagged Japan" combined with the
  vector search.
- **Re-ranking** — a second, slower model that re-scores the top ~50 candidates
  for precision.
- **Incremental updates** — adding/removing single vectors instead of rebuilding
  the whole index.
- **Evaluation** — a set of query→expected-passage pairs to catch retrieval
  regressions.

None of that is warranted here. A few hundred paragraphs, rebuilt in seconds, exact
search, one file. Match the machinery to the problem.

---

## Exercises & checkpoints

App running locally (chapter `13`). You need `stories.faiss` present; if you do
not have the diary source, skip 1–3 and do 4–5 by reading.

1. **Rebuild the index.** Add one row to `city_stories` via a Python shell against
   a *writable* connection:
   ```python
   from app.db import get_writable_connection
   c = get_writable_connection("travel.db")
   c.execute("INSERT INTO city_stories (city_id, story) VALUES (NULL, 'I ate the best gelato of my life in a tiny shop in Bologna near the two towers.')")
   c.commit()
   ```
   Then `.venv/bin/python scripts/build_story_index.py`. What does it print for
   `ntotal` before and after?
2. **Search it directly.** In a Python shell:
   ```python
   from app.db import get_readonly_connection
   from app.rag import load_index, search, SentenceTransformerEmbedder
   c = get_readonly_connection("travel.db")
   idx = load_index("stories.faiss")
   for m in search(c, idx, SentenceTransformerEmbedder(), "Italian ice cream"):
       print(m.city, "—", m.story[:80])
   ```
   Does your Bologna gelato entry come back for "Italian ice cream" even though
   the words differ? That is semantic retrieval.
3. **Trigger it in the app.** Ask the chat *"what do you remember about Bologna?"*
   Watch the server console (add a `print` in the `CONTEXT_TOOL_NAME` branch of
   `_resolve_tool_call`) to see the query the model sent and the matches returned.
4. **Prove graceful degradation.** Rename `stories.faiss` to
   `stories.faiss.bak`, restart the server, and ask a question about any city.
   Does the app still work? What does `search` return, and which line of
   `app/rag.py` short-circuits? Rename it back.
5. **Reason about `IndexIDMap2`.** Why does the index store vectors under
   `city_stories.id` rather than under 0, 1, 2, ...? What would break in `search`
   if it used positions instead? (Hint: what happens to positions when a row is
   deleted and the index is rebuilt?)

Continue to `09-offline-data-pipeline.md`.

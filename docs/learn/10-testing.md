# 10 — Testing: offline, deterministic, fake everything external

This project has ~179 automated test cases in 14 files, and they run in about a
second with **no network access and no real API keys**. That is not an accident —
it is a direct consequence of the dependency-injection pattern you have seen in
every chapter. This chapter covers `pytest` from scratch, the fixtures and fakes
this suite uses, and a few of the cleverer things it verifies.

Run the suite from the repo root:

```
.venv/bin/python -m pytest
```

(As a module, `-m`, so `app` is importable — chapter `01` §1.1 and §11.)

---

## 1. What a test is, mechanically

A test is a function whose name starts with `test_`, in a file whose name starts
with `test_`, that *asserts* something is true. `pytest` discovers all of them,
runs each, and reports pass/fail. A minimal example:

```python
# tests/test_geo.py (shape)
from app.geo import haversine_km

def test_haversine_zero_distance_is_zero():
    assert haversine_km(48.0, 2.0, 48.0, 2.0) == 0
```

`assert X` — if `X` is truthy, the test passes silently; if not, `pytest` fails
the test and shows you both sides of the comparison. That is the whole framework
at its core. Everything else (fixtures, parametrisation, plugins) is convenience
on top.

## 2. The suite's layout

Roughly one test file per module:

| File | ~Tests | Covers |
|------|--------|--------|
| `test_chat.py` | 32 | the agent loop, tool dispatch, coordinate stripping, chaining |
| `test_llm.py` | 30 | tool-schema builders, the system prompt, `AnthropicClient` |
| `test_queries.py` | 21 | every SQL read function |
| `test_import_saved_places.py` | 19 | filename parsing, merge, idempotency, retry |
| `test_main.py` | 18 | the FastAPI routes, DI overrides, SSE, rate limits |
| `test_db.py` | 11 | schema, constraints, cascades, read-only enforcement |
| `test_maps.py` | 9 | `build_map_payload` shape, photo URL, null-field omission |
| `test_limits.py` | 7 | both limiters, with a fake clock |
| `test_rag.py` | 6 | `build_index` / `search` with a `FakeEmbedder` |
| `test_config.py` | 5 (+3) | required/optional env vars |
| `test_geo.py` | 5 | `haversine_km`, `filter_within_radius` |
| `test_enrich_places.py` | 5 | `run_enrich`, photo download, idempotency |
| `test_assign_countries.py` | 4 | mapping, unmapped reporting, NFC, idempotency |
| `test_import_stories.py` | 4 | tagging, `_unmatched`, unknown cities, idempotency |

## 3. `conftest.py` — shared setup

`tests/conftest.py` is a special file `pytest` loads automatically before any
test. This one is 11 lines:

```python
import os

_REQUIRED_DEFAULTS = {
    "GOOGLE_MAPS_BROWSER_KEY": "test-browser-key",
    "GOOGLE_MAPS_MAP_ID": "test-map-id",
    "LLM_API_KEY": "test-llm-key",
    "LLM_MODEL": "claude-sonnet-4-5",
}

for _key, _value in _REQUIRED_DEFAULTS.items():
    os.environ.setdefault(_key, _value)
```

Why it is needed: importing `app.config` runs `load_settings()`, which raises if
the four required environment variables are missing (chapter `03` §5). Tests
import `app.*` modules, so those variables must exist. `conftest.py` sets *dummy*
values for exactly those four, using `setdefault` (so a real `.env`-populated
environment is left alone). The values are fake strings — the tests never make a
real call that would use them.

It deliberately does **not** set `GOOGLE_PLACES_API_KEY` (the web app must never
load it) or the optional variables (they have code defaults, and `test_config.py`
checks those defaults).

## 4. The testing philosophy

Stated as rules the suite follows:

- **No network, ever.** The design spec lists "the full test suite passes with no
  network access" as an acceptance criterion. Nothing in `tests/` opens a socket.
- **No real API keys.** `conftest` injects dummies;
  `AnthropicClient(api_key="unused", raw_client=fake)` etc.
- **Fake every external system.** Where production talks to Anthropic, Google, a
  model, or the clock, the test passes a hand-written fake with the same method
  shape (thanks to `Protocol`s and injectable parameters — chapters `01` §1.19,
  `06`, `09`).
- **Real SQLite, temp files.** Almost every test builds a *real* database in a
  temporary directory with `get_writable_connection(tmp_path / "travel.db")` and
  seeds it with plain `INSERT`s. The schema, foreign keys, cascades, and `UNIQUE`
  constraints are exercised for real — only the *external* systems are faked.
- **Deterministic over realistic for ML.** `FakeEmbedder` maps known strings to
  fixed toy vectors, so nearest-neighbour results are exactly predictable without
  loading `all-MiniLM-L6-v2`.
- **Assert the safety property directly.** Multiple tests read the actual
  `tool_result` content sent to the model and assert `"lat" not in
  content.lower()` — the coordinate rule (chapter `07`) is checked, not assumed.

## 5. The fakes, catalogued

| Fake | Stands in for | Behaviour |
|------|---------------|-----------|
| `StubClient` / `StubStreamClient` | `AnthropicClient` | Holds a *list* of canned `LLMResponse` objects, pops one per call, records every `(system, messages, tools)` it was called with. |
| `FakeGeocoder` | `GooglePlacesGeocoder` | Returns results from a `{title: GeocodeResult}` dict; records `.calls`. |
| `FakeDetailsFetcher` / `FakePhotoDownloader` | the `enrich_places` Google clients | Return from dicts; record `.calls`. |
| `FakeEmbedder` | `SentenceTransformerEmbedder` | Maps known strings to fixed 3-D unit vectors. |
| `FakeClock` | `time.time` | `clock.now` is a number you set; calling it returns that number. |
| fake `requests.Session` (`_FlakyThenOkSession`, `_AlwaysFailsSession`) | the real HTTP session inside the Google client classes | Raise `ReadTimeout` a set number of times, then return a fake response — to test retry/back-off without real requests or real sleeping. |

## 6. Worked example: testing the agent loop

From `test_chat.py`. `StubClient` scripts the model:

```python
class StubClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
    def send(self, *, system, messages, tools):
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        return self._responses.pop(0)
```

A single-tool turn is a two-element script: first a response that asks for
`show_city_map`, then a plain-text final answer.

```python
client = StubClient([
    LLMResponse(text="", tool_call=ToolCall(name="show_city_map", input={"city": "Zurich"}, id="toolu_1")),
    LLMResponse(text="Here's everything saved in Zurich.", tool_call=None),
])
result = handle_message(conn, client, tools, system, "what's in zurich?", [])

assert len(client.calls) == 2                          # the loop ran twice
assert result["map"]["markers"] == <expected from the DB>
# and — crucially — reach into the SECOND call's messages, find the tool_result block,
# json.loads its content, and assert:
assert loaded == [{"title": "Botanical Garden", "note": "nice", "category": "Park"}]
# no "lat", no "lng" — the coordinate rule, verified.
```

**Chaining** is a three-element script (`get_city_context` → `show_city_map` →
final text), asserting `len(client.calls) == 3` and that both text and a map come
back.

**Proximity** is tested against real haversine distances between three seeded
Zurich spots: a `radius_km: 0.5` call keeps only the closest; an omitted radius
uses the ~1.5 km default; a far `near_lat`/`near_lng` empties the result and
produces `{"text": ...}` with no `"map"` key.

## 7. Worked example: testing the SSE endpoint

From `test_main.py`. A tiny helper parses the stream body:

```python
def _parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:"):].strip()))
    return events
```

`StubStreamClient.stream()` is a generator yielding `("delta", "Hello")`,
`("delta", " there")`, `("done", LLMResponse(...))`. A test hits
`GET /api/chat/stream?message=hi&history=[]` and asserts the parsed events are
exactly `[{"type": "delta", "text": "Hello"}, {"type": "delta", "text": " there"},
{"type": "done"}]`. Another uses a two-stream stub (first stream yields a `done`
with a `tool_call`; second yields prose) and asserts a `{"type": "map", ...}`
event appears between the deltas and the terminal `done`.

The **capped** case overrides `get_daily_cap` with `DailyMessageCap(limit=0)` and
asserts `events[0]` is a `delta` containing "message limit", `events[1]` is
`{"type": "done"}`, and the stub client was called **zero** times — the model was
never invoked.

## 8. Overriding dependencies in a route test

`app/main.py`'s routes depend on `get_db`, `get_llm_client`, etc. A test swaps
them:

```python
app.dependency_overrides[get_db] = lambda: override_get_db()          # a seeded temp DB
app.dependency_overrides[get_llm_client] = lambda: stub_client
app.dependency_overrides[get_per_ip_limiter] = lambda: PerIPRateLimiter(limit=1000, window_seconds=3600)
app.dependency_overrides[get_daily_cap] = lambda: DailyMessageCap(limit=1000)
# ... run the request via FastAPI's TestClient ...
app.dependency_overrides.clear()   # in teardown
```

This is the payoff for wrapping the singletons in trivial `get_*` functions
(chapter `03` §7): the route code is untouched, but every dependency is now a
test-controlled object. Fresh generous limiters per test also stop tests from
interfering with each other through the shared module-level counters.

## 9. Two neat verification tricks

### "Exactly one query"

`test_queries.py` verifies the "no N+1" rule literally:

```python
statements = []
conn.set_trace_callback(statements.append)   # SQLite calls this for every statement
get_city_spots(conn, "Zurich")
assert len(statements) == 1
```

`set_trace_callback` registers a function SQLite calls with the text of every
statement it executes. If `get_city_spots` ever issued a second query (e.g. a
per-row lookup), this test would fail.

### Read-only really means read-only

`test_db.py`:

```python
conn = get_readonly_connection(db_path)
with pytest.raises(sqlite3.OperationalError):
    conn.execute("INSERT INTO cities (name) VALUES ('X')")
```

`pytest.raises(...)` asserts the block *does* raise that exception. This proves
the website's connection cannot write, at the database level (chapter `04` §3).

## 10. What is *not* tested — and why that is OK

The tests verify the **plumbing**: given a scripted model response, does the right
query run, does the right SSE event come out, are coordinates stripped, is the
rate limit enforced. They do **not** verify the model's *judgement* — whether it
correctly decides to show a map, whether its prose is good, whether it follows the
system prompt. That would require real API calls (slow, costs money, non-
deterministic) and a rubric-based "eval" harness. For a personal project, those
model-judgement checks are done by hand; everything mechanical is automated. Know
this boundary: a green test suite here means "the code around the model is
correct," not "the model behaves well."

---

## Exercises & checkpoints

Venv set up (chapter `13`).

1. **Run it.** `.venv/bin/python -m pytest -q`. How many pass? How long did it
   take? Now run `.venv/bin/python -m pytest tests/test_geo.py -v` to see
   individual test names.
2. **Make one fail.** In `app/geo.py`, change `EARTH_RADIUS_KM` to `1.0`. Run
   `pytest tests/test_geo.py`. Read the failure output — it shows the expected and
   actual numbers. Revert.
3. **Add a test.** You added `get_city_spot_count` in chapter `04`'s exercises.
   Write `tests/test_queries.py::test_get_city_spot_count_matches_row_count`: open
   a `get_writable_connection(tmp_path / "t.db")`, insert a city + a category +
   two spots, then assert `get_city_spot_count(conn, "Testville") == 2`. Run it.
4. **Add a safety assertion.** In `tests/test_chat.py`, find a test that triggers
   a `show_city_map` tool call. Add an assertion that the tool-result content
   passed to the model contains neither `"lat"` nor `"lng"` (mirror the existing
   pattern). Confirm it passes, then temporarily add `"lat"` back in
   `_tool_result_content` and confirm your test catches it. Revert.
5. **Explain the trace callback.** In your own words, how does
   `conn.set_trace_callback(statements.append)` let a test count SQL statements?
   What would `len(statements)` be if `get_city_spots` did a `LEFT JOIN` — is a
   join one statement or several?

Continue to `11-git-and-github.md`.

# 03 — The backend: FastAPI, Uvicorn, and the request lifecycle

This chapter is a complete tour of the server side of the web layer: the framework
(**FastAPI**), the program that runs it (**Uvicorn**), request validation
(**Pydantic**), the templating engine (**Jinja2**), the pattern that wires it all
together (**dependency injection**), and the streaming endpoint. The worked
example is `app/main.py`, with `app/config.py` alongside.

By the end you should be able to read `app/main.py` top to bottom.

---

## 1. What a web framework does

Writing a web server from raw sockets means implementing HTTP parsing, routing,
request bodies, concurrency, error handling — thousands of lines before you write
a single line of *your* logic. A **framework** provides all of that. You write:

- **routes** — "when a request matches `GET /api/city/{name}`, call this
  function,"
- and the function bodies.

The framework does the rest. This project's framework is **FastAPI**. Its selling
points, all of which this app uses:

- Routes are plain Python functions with a decorator.
- Request data (path parts, query params, JSON body) is declared as function
  parameters with type hints, and FastAPI parses and validates it for you.
- **Dependency injection** (section 6) for shared setup like "open a database
  connection for this request."
- Built-in support for streaming responses.

## 2. ASGI, WSGI, and Uvicorn

FastAPI is a *framework*, not a *server*. It defines an application object; it
does not itself listen on a port. The thing that listens, accepts TCP
connections, speaks HTTP, and calls into FastAPI is a **server** — here,
**Uvicorn**.

The contract between them is **ASGI** ("Asynchronous Server Gateway Interface") —
a Python standard for how a server hands a request to an application and gets a
response back. (The older, synchronous version is **WSGI**; ASGI adds streaming
and websockets, which is why a streaming app like this one uses it.)

You start the whole thing with:

```
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- `app.main:app` — "in the module `app.main`, use the object named `app`." That
  object is created in `app/main.py` by `app = FastAPI()`.
- `--host 0.0.0.0` — listen on all network interfaces (necessary inside a
  container; `127.0.0.1` would be unreachable from outside).
- `--port 8000` — the port.
- In development the README adds `--reload`, which watches the source files and
  restarts the server whenever you save a change.

That command is also the last line of the `Dockerfile` (chapter `12`).

## 3. Creating the app and mounting static files

The top of `app/main.py`:

```python
BASE_DIR = Path(__file__).resolve().parent

app = FastAPI()
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
```

- `Path(__file__).resolve().parent` — `__file__` is the path of `main.py` itself;
  `.resolve()` makes it absolute; `.parent` is the folder it lives in (`app/`). So
  `BASE_DIR` is an absolute path to `app/`, regardless of where you started the
  server from.
- `app = FastAPI()` — the application object Uvicorn will run.
- `app.mount("/static", StaticFiles(directory=...))` — "any request whose path
  starts with `/static/` is served directly from the `app/static/` folder on
  disk." That is how `app.js`, `style.css`, and the spot photos reach the
  browser. No route function needed — `StaticFiles` handles reading the file,
  guessing the content type, and returning it.
- `templates = Jinja2Templates(directory=...)` — the templating engine, pointed at
  `app/templates/`. Used to render `index.html` (section 5).

## 4. Module-level singletons

Right after that:

```python
_llm_client = AnthropicClient(api_key=settings.llm_api_key, model=settings.llm_model)
_per_ip_limiter = PerIPRateLimiter(limit=settings.rate_limit_per_hour, window_seconds=3600)
_daily_cap = DailyMessageCap(limit=settings.daily_message_cap)
_story_embedder = SentenceTransformerEmbedder()
_story_index = load_index(settings.story_index_path)
```

These are created **once**, when the module is first imported (i.e. when the
server starts), and shared by every request:

- `_llm_client` — one wrapper around the Anthropic SDK (chapter `06`).
- `_per_ip_limiter` / `_daily_cap` — the two throttles (chapter `03` §8). They
  hold in-memory counters, so they must persist across requests — hence
  module-level, not per-request.
- `_story_embedder` — the embedding model wrapper. Constructing it is cheap
  because the actual model loads lazily on first use (chapter `08`).
- `_story_index` — the FAISS index, loaded from `stories.faiss` now. If the file
  is absent, `load_index` returns `None` and the RAG tool simply returns nothing
  (graceful degradation).

The leading underscore is the "internal, do not import this from elsewhere"
convention. Code that needs them goes through the dependency functions in the next
section, so tests can substitute fakes.

## 5. Configuration: `app/config.py`

Covered line-by-line in chapter `01` §1.21. The essentials for this chapter:

- Config comes from **environment variables**, read via `os.environ`. Not a
  config file format, not command-line flags.
- `python-dotenv`'s `load_dotenv()` runs at import time and copies a `.env` file
  (if present) into the environment — a convenience for local development.
  Variables already set in the real environment (e.g. by `docker run --env-file`)
  win.
- Four variables are **required** (`GOOGLE_MAPS_BROWSER_KEY`,
  `GOOGLE_MAPS_MAP_ID`, `LLM_API_KEY`, `LLM_MODEL`). If any is missing,
  `load_settings()` raises `RuntimeError` **at startup** with all the missing
  names in the message. The server refuses to run half-configured — a "fail fast"
  design.
- Everything else has a default: `DATABASE_PATH` → `travel.db`,
  `STORY_INDEX_PATH` → `stories.faiss`, `RATE_LIMIT_PER_HOUR` → `10`,
  `DAILY_MESSAGE_CAP` → `300`.
- `GOOGLE_PLACES_API_KEY` is **deliberately not a field** on `Settings`. The
  running server has no way to read it. It is used only by the offline scripts
  (chapter `09`). This is a security boundary: the key that costs money to use
  cannot leak from the web server because the web server never loads it.
- The result is one immutable `settings` object that every module imports.

FastAPI has a fancier config mechanism (`pydantic-settings`); this project chose
the plainest possible thing — a dataclass and `os.environ.get` — and it is enough.

## 6. Templating: rendering `index.html`

The one HTML route:

```python
@app.get("/")
def index(request: Request, conn=Depends(get_db)):
    known_city_names = {row["name"] for row in list_cities(conn)}
    suggestion_chips = [
        label for city, label in FAVORITE_EXAMPLES if city in known_city_names
    ]
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "suggestion_chips": suggestion_chips,
            "google_maps_browser_key": settings.google_maps_browser_key,
            "google_maps_map_id": settings.google_maps_map_id,
            "asset_version": _asset_version("app.js", "style.css"),
        },
    )
```

- `@app.get("/")` — registers this function for `GET /`.
- `request: Request` — FastAPI passes in the incoming request object.
- `conn=Depends(get_db)` — dependency injection (section 7); FastAPI calls
  `get_db`, and `conn` receives its yielded value (a read-only DB connection).
- The body: get the set of city names that actually exist; from the hard-coded
  `FAVORITE_EXAMPLES` list of `(city, label)` pairs, keep only the labels whose
  city exists; that becomes `suggestion_chips`.
- `templates.TemplateResponse(request, "index.html", {...})` — render
  `app/templates/index.html`, substituting the values in the dict, and return the
  resulting HTML as the response.

Inside `index.html`, those keys are available as template variables:

```html
<link rel="stylesheet" href="/static/style.css?v={{ asset_version }}">
...
<script>
  window.APP_CONFIG = { mapId: {{ google_maps_map_id | tojson }} };
</script>
...
{% if suggestion_chips %}
  {% for label in suggestion_chips %}
  <button type="button" class="suggestion-chip" data-question="{{ label }}"> ... </button>
  {% endfor %}
{% endif %}
```

### The `| tojson` filter — and why it matters

`{{ google_maps_map_id | tojson }}` passes the value through Jinja2's `tojson`
filter, which produces a **valid JavaScript literal**, quotes included. If the Map
ID is `abc123`, the output is `mapId: "abc123"`. If it were empty, the output is
`mapId: null` — still valid JS, no broken page.

Why not just write `mapId: "{{ google_maps_map_id }}"`? Because if the value ever
contained a `"` or a `</script>`, it could break out of the string or the script
tag. `tojson` escapes it correctly. Rule of thumb: **any server value dropped into
an inline `<script>` goes through `tojson`.**

### The `?v={{ asset_version }}` cache-buster

```python
def _asset_version(*relative_paths: str) -> str:
    """A cache-busting value derived from each file's last-modified time..."""
    return "-".join(
        str(int((BASE_DIR / "static" / name).stat().st_mtime)) for name in relative_paths
    )
```

Browsers cache `/static/*` files aggressively (this app sets no `Cache-Control`
header). If you edit `style.css` and redeploy, a returning visitor might keep
using the old cached copy. The fix: append `?v=<something that changes when the
file changes>` to the URL. Here that "something" is the file's last-modified time
(`st_mtime`) as an integer. `_asset_version("app.js", "style.css")` returns e.g.
`"1757462640-1757462700"`. Same files → same string → browser reuses its cache.
Edited file → new string → new URL → browser refetches. No content hashing, no
build tool, no manifest.

## 7. Dependency injection

A route often needs shared setup: a database connection, the current user, a
rate-limiter. FastAPI's **dependency injection** lets you declare that need as a
parameter and have FastAPI satisfy it.

```python
def get_db():
    conn = get_readonly_connection(settings.database_path)
    try:
        yield conn
    finally:
        conn.close()


def get_llm_client():
    return _llm_client


def get_per_ip_limiter():
    return _per_ip_limiter


def get_daily_cap():
    return _daily_cap
```

- `get_db` is a **generator dependency**. FastAPI runs it up to the `yield`,
  hands the yielded `conn` to the route, lets the route run, then resumes the
  generator (the `finally:` closes the connection). So every request gets a fresh
  read-only connection that is reliably closed afterward — even for a long
  streaming response, the connection stays open until the stream is fully
  consumed.
- `get_llm_client` / `get_per_ip_limiter` / `get_daily_cap` just return the
  module-level singletons. Why bother wrapping a `return _llm_client` in a
  function? **Testability.** A test can do
  `app.dependency_overrides[get_llm_client] = lambda: fake_client` and every route
  that depends on it now gets the fake, with zero changes to the route code. You
  will see this used throughout chapter `10`.

A route declares a dependency with `Depends`:

```python
@app.post("/api/chat")
def api_chat(
    payload: ChatRequest,
    request: Request,
    conn=Depends(get_db),
    client=Depends(get_llm_client),
    ip_limiter=Depends(get_per_ip_limiter),
    daily=Depends(get_daily_cap),
):
    ...
```

FastAPI sees the `Depends(...)` defaults, calls each one, and passes the results
in as `conn`, `client`, `ip_limiter`, `daily`.

## 8. Request validation with Pydantic

For `POST /api/chat`, the request body is JSON. You declare its shape as a
**Pydantic model**:

```python
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
```

A route parameter typed as a Pydantic model tells FastAPI "parse the JSON body
into this shape, and if it does not fit, reject the request with a `422` error and
a description of what was wrong." So inside `api_chat`, `payload.message` is
guaranteed to be a string and `payload.history` a list of `{role, content}`
objects — no manual checking.

`payload.history` is a list of `ChatMessage` *objects*; `[m.model_dump() for m in
payload.history]` converts each back to a plain `dict`, which is what the chat
layer expects.

## 9. The routes, one by one

### `GET /` — the page

Covered in section 6.

### `GET /api/city/{name}` — one city's map payload

```python
@app.get("/api/city/{name}")
def api_city(name: str, conn=Depends(get_db)):
    known_cities = {row["name"] for row in list_cities(conn)}
    if name not in known_cities:
        raise HTTPException(status_code=404, detail="Unknown city")
    spots = get_city_spots(conn, name)
    return build_map_payload(name, spots)
```

`{name}` in the path is a **path parameter**; FastAPI binds it to the `name`
parameter. If the city is unknown, `raise HTTPException(status_code=404, ...)` —
FastAPI turns that into a `404 Not Found` response. Otherwise it queries the spots
and returns the map payload; FastAPI serialises the returned dict to JSON
automatically. This endpoint is used by the homepage's "browse a city" feature and
has nothing to do with the chat.

### `POST /api/chat` — non-streaming chat

```python
@app.post("/api/chat")
def api_chat(payload: ChatRequest, request: Request, conn=..., client=..., ip_limiter=..., daily=...):
    capped_message = _capped_message_if_limited(request, ip_limiter, daily)
    if capped_message is not None:
        return {"text": capped_message}

    tools, system = _build_tools_and_system(conn)
    history = [message.model_dump() for message in payload.history]

    return handle_message(
        conn, client, tools, system, payload.message, history,
        story_index=_story_index, embedder=_story_embedder,
    )
```

1. **Rate check first** (section 10). If capped, return
   `{"text": "<friendly message>"}` and stop — the model is never called.
2. Build the tools and system prompt from the live database (section 11).
3. Convert history to plain dicts.
4. Hand off to `handle_message` in `app/chat.py` (chapter `07`), which runs the
   agent loop and returns `{"text": ...}` or `{"text": ..., "map": ...}`. FastAPI
   serialises it to JSON.

The browser does not actually use this endpoint (it uses the streaming one), but
it exists, and the test suite exercises it heavily because it is easier to assert
against a single JSON blob than a stream.

### `GET /api/chat/stream` — streaming chat (the one the browser uses)

```python
@app.get("/api/chat/stream")
def api_chat_stream(message: str, request: Request, history: str = "[]", conn=..., client=..., ip_limiter=..., daily=...):
    capped_message = _capped_message_if_limited(request, ip_limiter, daily)
    if capped_message is not None:

        def capped_stream():
            yield f"data: {json.dumps({'type': 'delta', 'text': capped_message})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        return StreamingResponse(capped_stream(), media_type="text/event-stream")

    tools, system = _build_tools_and_system(conn)
    history_list = json.loads(history)

    def event_stream():
        for event in stream_message(
            conn, client, tools, system, message, history_list,
            story_index=_story_index, embedder=_story_embedder,
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

Points to notice:

- It is a **`GET`**, because the browser's `EventSource` can only do `GET`
  (chapter `02` §6). So `message` and `history` arrive as **query parameters**.
  `message: str` and `history: str = "[]"` — FastAPI reads them from the query
  string; `history` defaults to the string `"[]"` and is parsed with
  `json.loads`.
- **Capped path:** even when rate-limited, it returns a *stream* — one `delta`
  with the friendly message, then `done` — so the browser's streaming code needs
  no special case. Note it returns a normal `200`, not a `429`: the visitor sees
  the cap as an ordinary chat reply, not an error.
- **Normal path:** `event_stream()` is a generator. For each event `dict` that
  `stream_message` yields (`{"type": "delta", "text": ...}`,
  `{"type": "map", ...}`, `{"type": "done"}`), it formats one SSE frame:
  `f"data: {json.dumps(event)}\n\n"`. The blank line (`\n\n`) terminates the
  frame.
- `StreamingResponse(gen, media_type="text/event-stream")` — FastAPI keeps the
  connection open and forwards each yielded chunk to the browser as it is
  produced. That is the whole streaming implementation: a generator + this one
  class.

## 10. Rate limiting: `_capped_message_if_limited`

```python
def _capped_message_if_limited(request, ip_limiter, daily):
    try:
        ip_limiter.check(request.client.host)
        daily.check()
    except RateLimitExceeded as exc:
        return exc.message
    return None
```

`request.client.host` is the caller's IP address. `ip_limiter.check(ip)` raises
`RateLimitExceeded` if that IP has sent too many messages this hour; `daily.check()`
raises if the whole site has sent too many today. Either way, this function
returns the friendly `CAPPED_MESSAGE` string, and both chat routes short-circuit
before calling the model. The limiter classes themselves (`app/limits.py`) are
covered in chapter `06` §"cost control"; the key design points:

- The per-IP check runs first, so a per-IP rejection does not consume a slot in
  the site-wide daily count.
- The counters are plain in-memory dictionaries. They reset when the server
  restarts and are **not** shared if you run multiple server processes. For a
  single-process personal site that is fine; a bigger deployment would move this
  to a shared store like Redis.
- These app-level caps are a *second* line of defence. The real spend ceiling is
  set at the provider (Anthropic monthly limit, Google Cloud quota) — chapter
  `12`.

## 11. `_build_tools_and_system` — the prompt reflects the live database

```python
def _build_tools_and_system(conn) -> tuple[list[dict], str]:
    city_names = [row["name"] for row in list_cities(conn)]
    category_names = [row["name"] for row in list_categories(conn)]
    country_names = [row["country"] for row in list_countries(conn)]

    city_breakdown: dict[str, list[dict]] = {}
    for row in get_all_city_categories(conn):
        city_breakdown.setdefault(row["city"], []).append(
            {"name": row["category"], "spot_count": row["spot_count"]}
        )

    tools = [
        build_tool_definition(city_names, category_names, country_names),
        build_context_tool_definition(),
    ]
    system = build_system_prompt(city_breakdown.items())
    return tools, system
```

Rebuilt on **every** chat request. Why not once at startup? Because the tool
definitions embed the *actual* list of cities, categories, and countries as
allowed values (`enum`s), and the system prompt embeds the full "Taipei:
Restaurants (37), Cafes (12); Bangkok: ..." breakdown. If the database is ever
rebuilt with new data and the server restarted, everything stays in sync
automatically. It is a handful of fast indexed queries, so the cost is
negligible. Chapter `07` covers what `build_tool_definition` and
`build_system_prompt` actually produce.

## 12. Reading `app/main.py` end to end

You now have every piece. The file's shape:

1. Imports.
2. `BASE_DIR`, `app = FastAPI()`, static mount, templates.
3. The five module-level singletons.
4. The dependency functions (`get_db`, `get_llm_client`, …).
5. Helpers: `_capped_message_if_limited`, `_build_tools_and_system`,
   `_asset_version`.
6. The Pydantic models `ChatMessage`, `ChatRequest`.
7. `FAVORITE_EXAMPLES`.
8. The four routes: `/`, `/api/city/{name}`, `/api/chat`, `/api/chat/stream`.

Nothing in it talks to the model or the database directly — it delegates to
`app/chat.py`, `app/llm.py`, `app/queries.py`. `main.py` is pure *wiring*.

---

## Exercises & checkpoints

App running locally (chapter `13`).

1. **Add a health check.** Add a route `@app.get("/api/health")` that returns
   `{"status": "ok"}`. Restart, then `curl http://127.0.0.1:8000/api/health`.
   Confirm you get that JSON with a `200`.
2. **Add a config value.** In `app/config.py`, add a field `site_name: str` to
   `Settings`, defaulting to `os.environ.get("SITE_NAME", "Travel Agent")`. Read
   it in your `/api/health` route and return it. Confirm the default works, then
   set `SITE_NAME=Joeys Trips` in `.env`, restart, and confirm it changes.
3. **Break a required variable.** Comment out `LLM_API_KEY` in your `.env` and
   start the server. What exact error do you get, and from which file/function?
   Put it back.
4. **Watch dependency injection.** Add a `print("opening db")` in `get_db` before
   the `yield` and `print("closing db")` after it. Load `/` once and watch the
   order in the server console. Then load `/api/chat/stream` and note *when*
   "closing db" prints relative to the stream finishing.
5. **Cache-buster.** Load `/`, view source, and find the `?v=` value on
   `style.css`. Touch the file (`touch app/static/style.css`), reload, view
   source again. Did the value change? Why?

Continue to `04-data-layer.md`.

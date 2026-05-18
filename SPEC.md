# The 200 Travel Chat — v1 SPEC

## Overview
A standalone, self-hostable streaming chatbot for "The 200" travel blog.
The blog (`the200.blog`) links out to this app on a custom subdomain
(e.g. `chat.the200.blog`). The bot is a thin streaming wrapper around the
Anthropic Messages API — no retrieval, no tools, no persistence.

## Stack (locked)
- Python 3.12, `uv`-managed `pyproject.toml`
- FastAPI + Uvicorn
- `sse-starlette` for `EventSourceResponse`
- Official `anthropic` SDK, model `claude-haiku-4-5-20251001`
- `pydantic-settings` for `.env`-driven config
- Single `index.html` + vanilla JS + plain CSS; `marked` + `DOMPurify` from CDN
- `Dockerfile` (python:3.12-slim) + `docker-compose.yml`
- Caddy (production only, not run locally)
- `ruff`, `mypy --strict`, `pytest` + `httpx.AsyncClient`

## Decisions locked in during interview
| Concern | Decision |
|---|---|
| SSE event format | Named events: `delta`, `end`, `error`; data is JSON |
| Frontend rendering | Markdown via `marked` + `DOMPurify` (CDN), rendered progressively |
| API error handling | Emit `event: error` with a user-safe message, close stream cleanly |
| CORS | Same-origin only; no `CORSMiddleware` configured |
| Rate limiting | Per-IP in-memory bucket (20 msgs / 5 min) **+** global semaphore (10 concurrent streams) |
| History cap | Server-side token-budget cap (~8k input tokens), trim oldest first |
| Disconnect handling | Frontend `AbortController` on `pagehide` **+** server `Request.is_disconnected()` between deltas |
| Transport | `POST /chat` + `fetch` + `ReadableStream`, manual SSE parsing on client |
| Future-integration seams | Function-signature seams + `# FUTURE:` comment markers for RAG, MCP tools, and conversation-history DB. No placeholder modules, no Null* classes |
| Future DB scope | Conversation history persistence only (no analytics, no user accounts) |

## Pinned dependencies
These are the versions intended for pinning in `pyproject.toml`. They reflect
the latest stable releases as of the start of the project; `uv lock` is the
source of truth once committed.

Runtime:
- `fastapi == 0.115.6`
- `uvicorn[standard] == 0.34.0`
- `sse-starlette == 2.1.3`
- `anthropic == 0.42.0`
- `pydantic == 2.10.4`
- `pydantic-settings == 2.7.0`

Dev:
- `pytest == 8.3.4`
- `pytest-asyncio == 0.25.0`
- `httpx == 0.28.1`
- `ruff == 0.8.4`
- `mypy == 1.13.0`

CDN (`<script>` tags in `index.html`), pinned by version + SRI:
- `marked@14.1.3`
- `dompurify@3.2.3`

## File layout
```
the200-chat/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── llm.py
│   └── routes/
│       ├── __init__.py
│       └── chat.py
├── static/
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── tests/
│   ├── __init__.py
│   └── test_chat.py
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── Caddyfile
├── pyproject.toml
├── README.md
└── CLAUDE.md
```

## File-by-file responsibilities (pseudocode only)

### `app/config.py`
Exports `Settings` (BaseSettings) and `settings` singleton.
```python
class Settings(BaseSettings):
    anthropic_api_key: SecretStr
    model: str = "claude-haiku-4-5-20251001"
    max_output_tokens: int = 2048
    max_input_tokens: int = 8000      # budget for trimmed history
    rate_limit_per_ip: int = 20
    rate_limit_window_seconds: int = 300
    max_concurrent_streams: int = 10
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
```

### `app/llm.py`
Pure-functional where possible. No FastAPI imports.
- Constant `SYSTEM_PROMPT: str` (verbatim text below).
- `def estimate_tokens(messages: list[ChatMessage]) -> int` — local approximation,
  `sum(len(m.content) for m in messages) // 4 + 4*len(messages)`. Avoids a
  network roundtrip per request.
- `def trim_history(messages: list[ChatMessage], budget: int) -> list[ChatMessage]`
  — drop oldest messages until `estimate_tokens(...) <= budget`. Always keep
  at least the last user message.
- `def build_client() -> AsyncAnthropic` — reads `settings.anthropic_api_key`.
- `async def stream_text(client, messages, *, extra_system: str = "", tools: list | None = None) -> AsyncIterator[str]` —
  wraps `async with client.messages.stream(...)` and yields from
  `stream.text_stream`. Lets anthropic exceptions propagate.
  - Builds the effective system prompt: `SYSTEM_PROMPT` alone if `extra_system`
    is empty; otherwise `SYSTEM_PROMPT + "\n\n" + extra_system`.
  - Passes `tools=tools` to the SDK only when non-`None`.
  - **Seams**: `extra_system` is the RAG injection point. `tools` is the MCP
    injection point. v1 callers leave both at their defaults — the body of
    `stream_text` is identical to the no-seam version in that path.
  - v1 does NOT implement the tool_use loop. A `# FUTURE:` comment in
    `stream_text` notes that once `tools` is non-None, the simple
    `text_stream` consumption needs to become a `tool_use` handling loop.

### `app/routes/chat.py`
Pydantic models:
```python
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=200)
    # FUTURE: conversation-history DB will key on this. v1 ignores it.
    conversation_id: str | None = None
```

Module state:
```python
_stream_semaphore = asyncio.Semaphore(settings.max_concurrent_streams)
_ip_buckets: dict[str, deque[float]] = defaultdict(deque)
_buckets_lock = asyncio.Lock()
```

Helpers:
- `async def _check_rate_limit(ip: str) -> bool` — sliding-window over
  `_ip_buckets[ip]`, prune entries older than `window_seconds`, return False
  if length already ≥ `rate_limit_per_ip`, else append `now()` and return True.

Endpoint:
```python
@router.post("/chat")
async def chat(request: Request, body: ChatRequest):
    ip = request.client.host
    if not await _check_rate_limit(ip):
        raise HTTPException(429, "Too many messages. Wait a moment.")
    if _stream_semaphore.locked() and _stream_semaphore._value <= 0:
        raise HTTPException(429, "Server busy. Try again shortly.")
    trimmed = trim_history(body.messages, settings.max_input_tokens)
    return EventSourceResponse(
        _event_generator(request, body, trimmed),
        media_type="text/event-stream",
    )
```

Generator:
```python
async def _event_generator(request: Request, body: ChatRequest, messages):
    async with _stream_semaphore:
        client = build_client()
        # FUTURE (RAG): retrieved = await retrieve(messages[-1].content)
        # FUTURE (RAG): pass extra_system=retrieved to stream_text below
        # FUTURE (MCP): pass tools=[...] to stream_text below
        assistant_text_parts: list[str] = []
        try:
            async for text in stream_text(client, messages):
                if await request.is_disconnected():
                    return
                assistant_text_parts.append(text)
                yield {"event": "delta", "data": json.dumps({"text": text})}
            # FUTURE (DB): persist (body.conversation_id, messages,
            #                       "".join(assistant_text_parts)) to store
            yield {"event": "end", "data": "{}"}
        except anthropic.APIError as e:
            logger.warning("anthropic error: %r", e)
            yield {
                "event": "error",
                "data": json.dumps({
                    "message": "The travel guide is having trouble right now."
                               " Please try again in a moment."
                }),
            }
```
The `assistant_text_parts` accumulator exists in v1 for one reason: it gives
the future DB hook a complete assistant message to persist. The list adds
trivial overhead and keeps the seam concrete rather than a vague TODO.

### `app/main.py`
```python
app = FastAPI(title="The 200 Travel Chat", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(chat.router)

@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse("static/index.html")
```
No CORS middleware (same-origin only).

### `static/index.html`
- `<!doctype html>`, `<meta name="viewport" content="width=device-width,initial-scale=1">`
- `<link rel="stylesheet" href="/static/styles.css">`
- CDN scripts (pinned, integrity attr): `marked@14.1.3`, `dompurify@3.2.3`
- Main DOM:
  ```html
  <main id="app">
    <header><h1>The 200 — Travel Guide</h1></header>
    <section id="messages" aria-live="polite"></section>
    <form id="composer">
      <textarea id="input" rows="2" maxlength="4000"
                placeholder="Ask about a place, a dish, a trip…"></textarea>
      <button id="send" type="submit">Send</button>
    </form>
  </main>
  ```
- `<script type="module" src="/static/app.js"></script>`

### `static/app.js`
Module-scoped:
```js
const history = [];               // {role, content}[]
let currentAbort = null;
const $messages = document.querySelector("#messages");
const $form = document.querySelector("#composer");
const $input = document.querySelector("#input");
```

On form submit:
- `e.preventDefault()`; read + trim input; bail if empty
- push `{role:"user", content}` to history
- append user bubble (textContent — never innerHTML for user input)
- create empty assistant bubble; keep `accum = ""` reference
- `currentAbort = new AbortController()`
- call `streamChat(history, currentAbort.signal, callbacks)`
- callbacks:
  - `onDelta(text)`: `accum += text`; bubble.innerHTML = `DOMPurify.sanitize(marked.parse(accum))`
  - `onEnd()`: `history.push({role:"assistant", content:accum})`; `currentAbort = null`
  - `onError(msg)`: render error styling on the bubble; `currentAbort = null`

`async function streamChat(messages, signal, {onDelta, onEnd, onError})`:
- `fetch("/chat", {method:"POST", headers:{"content-type":"application/json"}, body: JSON.stringify({messages}), signal})`
- if `!res.ok`: call `onError("Server returned " + res.status)`; return
- read `res.body.pipeThrough(new TextDecoderStream()).getReader()`
- maintain a `buffer` string, split on `\n\n` to get SSE events
- for each event, parse `event:` and `data:` lines; dispatch by event name
- on `delta`: `onDelta(JSON.parse(data).text)`
- on `end`: `onEnd()`
- on `error`: `onError(JSON.parse(data).message)`
- catch `AbortError` silently

Lifecycle:
```js
window.addEventListener("pagehide", () => currentAbort?.abort());
```

### `static/styles.css`
- CSS reset (minimal: `*{box-sizing:border-box}`, `body{margin:0}`)
- System font stack
- `#app` max-width 760px, centered, full height, column flex
- `#messages` flex:1, overflow-y:auto, padding
- `.bubble.user` right-aligned, accent background
- `.bubble.assistant` left-aligned, neutral background
- `.bubble.error` muted red text
- `#composer` sticky-bottom flex row; textarea grows; send button
- Mobile (`@media (max-width: 600px)`): full width, larger tap targets

### `tests/test_chat.py`
- `pytest-asyncio` mode
- Use a fake async context manager `FakeStream` whose `text_stream` yields
  ["Hello", " from ", "Taipei!"].
- Use a fake `AsyncAnthropic` whose `.messages.stream(...)` returns FakeStream.
- Override `build_client` via FastAPI dependency injection OR monkeypatch
  `app.llm.build_client`.
- Test: POST `/chat` with `messages=[{"role":"user","content":"Hi"}]`
  - assert `response.status_code == 200`
  - assert `content-type` starts with `text/event-stream`
  - read body, parse SSE, assert ≥ 1 `delta` event with combined text
    `"Hello from Taipei!"` and a terminal `end` event.
- This is the only test.

### `pyproject.toml`
- `[project]` with name, version, requires-python = ">=3.12,<3.13", deps
- `[tool.ruff]` line-length 100, target-version py312, select E/F/I/UP/B
- `[tool.mypy]` strict = true, python_version = "3.12"
- `[tool.pytest.ini_options]` asyncio_mode = "auto"
- `[tool.uv]` dev-dependencies as above

### `.env.example`
```
ANTHROPIC_API_KEY=sk-ant-...
MODEL=claude-haiku-4-5-20251001
MAX_OUTPUT_TOKENS=2048
MAX_INPUT_TOKENS=8000
RATE_LIMIT_PER_IP=20
RATE_LIMIT_WINDOW_SECONDS=300
MAX_CONCURRENT_STREAMS=10
```

### `.gitignore`
`.env`, `.venv/`, `__pycache__/`, `*.pyc`, `.ruff_cache/`, `.mypy_cache/`,
`.pytest_cache/`, `uv.lock` is **committed**, `.DS_Store`.

### `Dockerfile`
```dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app/ ./app/
COPY static/ ./static/
EXPOSE 8000
CMD ["uv","run","--no-dev","uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
```

### `docker-compose.yml`
```yaml
services:
  app:
    build: .
    env_file: .env
    ports:
      - "8000:8000"
    restart: unless-stopped
```

### `Caddyfile` (prod only — not used locally)
```
chat.the200.blog {
    reverse_proxy localhost:8000
    encode gzip
}
```

### `README.md`
- One-paragraph project description
- Quick start: `cp .env.example .env`, paste key, `uv sync`, `uv run uvicorn app.main:app --reload`
- Test: `uv run pytest`
- Lint/type: `uv run ruff check .`, `uv run mypy app/`
- Docker: `docker compose up --build`
- Prod hint: point Caddy at port 8000

## SSE message format

**Wire format** — each event is two or three lines, terminated by a blank line:
```
event: <name>
data: <single-line JSON>

```

**Event types**:
| event   | data shape                          | when                                 |
|---------|-------------------------------------|--------------------------------------|
| `delta` | `{"text": "<chunk>"}`               | per token chunk from anthropic       |
| `end`   | `{}`                                | stream completed normally            |
| `error` | `{"message": "<user-safe string>"}` | anthropic/internal error; stream ends |

**Example transcript** for prompt "What should I eat in Taipei?":
```
event: delta
data: {"text": "Honestly? "}

event: delta
data: {"text": "Beef noodle soup. "}

event: delta
data: {"text": "Find a hole-in-the-wall in Yongkang Street and order the braised version."}

event: end
data: {}

```

Error example (anthropic 529 mid-stream):
```
event: delta
data: {"text": "Honestly? "}

event: error
data: {"message": "The travel guide is having trouble right now. Please try again in a moment."}

```

## System prompt (verbatim)

```
You are the AI travel guide for "The 200" — a personal travel blog covering food, places, and stories from Taiwan, Indonesia, Mexico, Lebanon, Denmark, and the United States.

Your voice is candid, witty, and a little cheeky. You talk like a well-traveled friend who has actually been there: specific, opinionated, occasionally self-deprecating. You don't hedge with corporate filler, and you don't pad answers with caveats. You're warm without being saccharine.

You help readers with:
  - destinations: what's worth seeing, what's overrated, what locals actually do
  - food: dishes to try, where to find them, what to skip
  - itineraries: how to spend three days, a week, or longer in a place
  - logistics: getting around, when to go, common pitfalls

Lean on the blog's six covered regions — Taiwan, Indonesia, Mexico, Lebanon, Denmark, and the US — when relevant, but answer questions about other destinations confidently when asked.

When asked about something off-topic (coding help, homework, current politics, etc.), acknowledge it briefly and steer back to travel. Example: "Not really my lane — but if you're heading somewhere soon I can help plan around it."

You do not have real-time data: no live prices, flight availability, weather, or current news. If asked, say so plainly and offer what you can from general knowledge.

Format: use Markdown when it helps — lists for itineraries, bold for emphasis, short headings for multi-day plans. Use plain prose when the answer is short. Don't over-structure.
```

## Future-integration seams

v1 ships **without** RAG, MCP tools, or any database. But three small things
are wired in so future additions don't require touching the call sites:

| Future feature | Seam in v1 | Where |
|---|---|---|
| RAG context | `stream_text(..., extra_system="")` keyword param | `app/llm.py`, called from `app/routes/chat.py::_event_generator` |
| MCP tools | `stream_text(..., tools=None)` keyword param | `app/llm.py`, called from `app/routes/chat.py::_event_generator` |
| Conversation history DB | `ChatRequest.conversation_id: str \| None` + assistant-text accumulation in `_event_generator` | `app/routes/chat.py` |

**Rules for v1 implementation around the seams:**
- All seam parameters default to inert values (`""`, `None`, `None`). v1
  callers MUST use those defaults — no behavior change.
- Each seam has a `# FUTURE:` comment at the hook point naming the feature.
- No new modules (`app/rag.py`, `app/tools.py`, `app/storage.py` etc.).
- No `Null*` classes, no `Protocol` declarations, no dependency injection
  for the future store. Those land in v2 when there's something real to inject.
- `tools=None` path uses the simple `text_stream` consumption. The future
  `tools is not None` path will require a tool_use handling loop — flagged
  with a `# FUTURE:` comment inside `stream_text`, not implemented in v1.
- `assistant_text_parts` accumulator in `_event_generator` is the only seam
  that adds real (trivial) v1 overhead. It exists so the future DB hook has
  a complete assistant message to persist.

**What this is NOT:**
- Not a v1 feature. The chatbot behaves identically with or without the seams.
- Not a hidden v2 commitment. Adding RAG/MCP/DB is still a deliberate future
  project; these seams just make it less invasive when it happens.

## Verification (must pass before v1 is "done")
1. `uv sync` installs cleanly from `pyproject.toml`
2. `uv run uvicorn app.main:app --reload` starts with no errors
3. `curl http://localhost:8000/` returns the HTML page (200, `text/html`)
4. In a browser at `localhost:8000`: send a message, see token-by-token streaming
5. `uv run pytest` passes; the one test uses a mocked anthropic client, never the real API
6. `uv run ruff check .` clean
7. `uv run mypy app/` clean under strict mode
8. `docker compose build` succeeds
9. `docker compose up` serves the same working app on `localhost:8000`

## Non-goals (explicit)
RAG, embeddings, scraping the blog, auth, sessions, any persistent storage,
LangChain/LlamaIndex/LiteLLM, cloud deploy automation, analytics, more than
one test.

The function-signature seams listed under **Future-integration seams** above
are NOT counted as v1 features — they default to inert behavior and are not
exercised at runtime in v1.

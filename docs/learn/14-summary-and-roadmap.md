# 14 — Summary, and where to go next

You have now seen every part of this system. This chapter ties it together in one
narrative, names what the project deliberately leaves out, and gives you a staged
plan for continuing to learn web development and LLMOps.

---

## 1. The whole system, as one story

A visitor opens `https://travelai.the200.blog/` and asks *"Where should I get
dessert in Boston?"*

- Their browser's DNS lookup resolves the name to the server's IP (chapter `02`).
  The connection is HTTPS; **Caddy** on the server terminates the TLS and forwards
  plain HTTP to the app container on `localhost:8000` (chapter `12`).
- The first request, `GET /`, hits `app/main.py`'s `index` route. It queries
  `list_cities` (`app/queries.py`) for the suggestion chips, and **Jinja2**
  renders `app/templates/index.html` with the Maps key, Map ID, and a
  cache-busting asset version (chapter `03`). The browser gets HTML, then fetches
  `style.css` and `app.js` (chapter `05`).
- The visitor types and submits. `app/static/app.js`'s `sendChatMessage` opens an
  **`EventSource`** to `GET /api/chat/stream?message=...&history=...` — the whole
  conversation so far rides in the query string, because the **server keeps no
  memory** (chapters `05`, `06`).
- `api_chat_stream` (`app/main.py`) checks the rate limits (`app/limits.py`),
  opens a **read-only** SQLite connection (`app/db.py`), and builds the two tool
  definitions and the system prompt from the *live* database contents
  (`_build_tools_and_system` → `app/queries.py` + `app/llm.py`). The system prompt
  literally lists every city and category, and the `show_city_map` tool's `city`
  parameter is an `enum` locked to real names (chapter `07`).
- It calls `stream_message` (`app/chat.py`), which runs the **agent loop**:
  - Ask the model (via `AnthropicClient.stream` → the Anthropic SDK). The model
    streams *"Boston desserts — yes, I have opinions..."* which is forwarded to
    the browser as `delta` events, then asks to call `get_city_context` with
    `{"query": "Boston desserts"}`.
  - `_resolve_tool_call` runs `rag.search` (`app/rag.py`): embed the query with a
    **local** `sentence-transformers` model, find the nearest diary paragraphs in
    the **FAISS** index, return them as JSON. No map.
  - Ask again. The model streams more prose weaving in a diary detail, then asks
    for `show_city_map` with `{"city": "Boston", "categories": ["Dessert Spots"]}`.
  - `_resolve_tool_call` runs `get_city_spots_by_categories`. It returns **two**
    things: a JSON list of `{title, note, category}` for the model — **with no
    coordinates** (`_tool_result_content`) — and a full `map_payload` **with**
    coordinates, built by `build_map_payload` (`app/maps.py`) straight from the
    database rows.
  - Ask again. The model writes its closing sentences and asks for no tool →
    the loop ends.
- `stream_message` yields the accumulated `delta`s (already sent), then one
  `{"type": "map", "map": {...}}`, then `{"type": "done"}`. `app/main.py` wraps
  each as `data: {...}\n\n` (chapter `03`).
- Back in `app.js`: `delta` events append text to the assistant's bubble
  (rendering the safe Markdown subset); the `map` event is held; on `done` the
  browser closes the stream, records the exchange in the in-memory conversation
  state, makes the mentioned spot names clickable (the `TreeWalker` trick), loads
  the **Google Maps** libraries (once), and draws the map with **Advanced
  Markers** whose "pins" are styled HTML badges (chapter `05`).
- The server has stored **nothing**. The database was never written. The model
  never saw a single coordinate. Refreshing the page discards the conversation.

## 2. The architecture in one diagram

```
                          the visitor's browser
        ┌───────────────────────────────────────────────────────────┐
        │  index.html  +  style.css  +  app.js                        │
        │                                                            │
        │  app.js: EventSource ──▶ /api/chat/stream                   │
        │          renderMapPayload ◀── {type:"map", ...}             │
        │          Google Maps JS API (Advanced Markers)              │
        └───────────────┬───────────────────────────▲────────────────┘
                        │ HTTPS                       │ SSE (text/event-stream)
                        ▼                             │
                 ┌──────────────┐                     │
                 │    Caddy      │  (TLS, reverse proxy, auto-HTTPS)
                 └──────┬───────┘
                        │ HTTP localhost:8000
                        ▼
   ┌────────────────────────────────────────────────────────────────┐
   │  the container:  uvicorn  →  app/main.py  (FastAPI)             │
   │                                                                │
   │   routes ─▶ app/chat.py  (the agent loop)                       │
   │              │      │           │                               │
   │              │      │           └─▶ app/rag.py ─▶ FAISS + local  │
   │              │      │                              embedder      │
   │              │      └─▶ app/queries.py ─▶ travel.db (READ-ONLY)  │
   │              │      └─▶ app/maps.py    ─▶ map payload            │
   │              │      └─▶ app/geo.py     ─▶ radius filter          │
   │              └─▶ app/llm.py ─▶ Anthropic Messages API (network)  │
   │                                                                │
   │   app/config.py (env vars)   app/limits.py (rate caps)          │
   │   travel.db, stories.faiss  ← baked into the image at build     │
   └────────────────────────────────────────────────────────────────┘
                        ▲
                        │ built offline, on a laptop
   ┌────────────────────┴───────────────────────────────────────────┐
   │  scripts/import_saved_places.py  (Saved/*.csv + Google Places)  │
   │  scripts/assign_countries.py                                    │
   │  scripts/enrich_places.py        (Google Places Details/Photos) │
   │  scripts/import_stories.py       (stories.json)                 │
   │  scripts/build_story_index.py    (→ stories.faiss)              │
   └────────────────────────────────────────────────────────────────┘
```

## 3. The ideas worth carrying to your next project

- **Two hard rules, enforced structurally.** "The LLM never emits coordinates"
  and "the data never changes at runtime" are not comments — they are enforced by
  a read-only database connection and by stripping fields before they reach the
  model. Pick your invariants and make them impossible to violate, not just
  discouraged.
- **Constrain the model with `enum`s from real data.** The city menu is the
  database's city list. Hallucination becomes impossible, not merely unlikely.
- **The business logic is a prompt; the code is plumbing + guardrails.** When to
  show a map, how to talk, when to search — all in `SYSTEM_PROMPT_INTRO`. The
  Python just executes tool calls and enforces safety.
- **Inject dependencies at the edge.** The model client, the geocoder, the
  embedder, the clock — all constructed in `main()` / at startup, passed inward.
  The result: a ~179-test suite that runs offline in a second.
- **Freeze what you can.** Immutable data → no volumes, no migrations, no
  backups, a read-only connection, deploy = rebuild. Enormous simplification for
  the right kind of app.
- **Match the machinery to the problem.** Flat FAISS index, hand-rolled 40-line
  Markdown renderer, no frontend framework, `os.environ` instead of a config
  library, one media query. Each is "too simple" for a big app and exactly right
  for this one.
- **A stateless server is a gift.** No sessions, no per-user storage, trivial to
  reason about, trivial to scale. The browser holds the conversation.

## 4. What this project deliberately leaves out

Understanding the *absences* is as instructive as the code. A larger system would
add:

| Area | This project | A bigger system |
|------|--------------|-----------------|
| **Auth** | none — public, read-only | user accounts, sessions, OAuth, roles |
| **Database** | one SQLite file, read-only | Postgres; connection pooling; read replicas |
| **Migrations** | one hand-written `ALTER TABLE` | Alembic / a migration framework, run on deploy |
| **Writes at runtime** | forbidden | an API layer, validation, transactions, optimistic locking |
| **Background work** | none | a task queue (Celery/RQ) for slow jobs |
| **Caching** | browser cache-busting only | Redis for computed results; HTTP caching headers; a CDN |
| **Rate limiting** | in-process counters | a shared store (Redis) so it works across many processes |
| **Observability** | `print` + the server log | structured logging, metrics (Prometheus), tracing, error tracking (Sentry) |
| **CI/CD** | run `pytest` by hand | GitHub Actions: tests + lint + build + deploy on every push |
| **Frontend** | 3 hand-written files | a framework (React/Svelte), a build step, a component library, TypeScript |
| **LLM prompt management** | one string in a `.py` file | versioned prompts, A/B tests, an eval harness with a rubric |
| **LLM guardrails** | field-stripping + `enum`s | a moderation pass, jailbreak detection, output validation, PII redaction |
| **Scaling** | one process, one machine | multiple workers, a load balancer, autoscaling, health checks |
| **Secrets** | `.env` file | a secrets manager (Vault, AWS/GCP Secret Manager) |

None of these are missing by mistake. Each one is complexity you add *when a real
requirement forces it* — not before.

## 5. A staged learning roadmap

Each stage lists what to learn, one project to build that forces you to learn it,
and where this codebase already showed you a piece of it.

### Stage 0 — Fundamentals (2–4 weeks)

- **The command line** — navigating, pipes, environment variables, exit codes
  (chapter `01` Part 6).
- **Git** — the daily commands, branches, resolving a conflict, reading `git log`
  (chapter `11`).
- **How the web works** — HTTP methods, status codes, headers, JSON, DNS, TLS
  (chapter `02`).
- **One language, deeply: Python.** Do a full course or book. Functions, data
  structures, classes, exceptions, generators, type hints, the standard library
  (chapter `01` Part 1).
- **Project:** a command-line tool that reads a CSV, transforms it, writes JSON,
  with `argparse`, proper exit codes, and a handful of `pytest` tests. (This is
  exactly what `scripts/assign_countries.py` is.)

### Stage 1 — The frontend (3–5 weeks)

- **HTML** semantics and forms; **CSS** box model, flexbox, grid, custom
  properties, media queries (chapter `01` Parts 3–4, chapter `05` §11).
- **JavaScript in the browser** — the DOM, events, `fetch`, Promises/`async`,
  `EventSource`, modules (chapter `01` Part 2, chapter `05`).
- **Then one framework** — React is the default choice. Build something in it,
  specifically so you can feel *what a framework buys you* versus this project's
  hand-written approach: components, reactivity, a build step, routing.
- **Project:** rebuild this app's frontend in React — same three screens (empty
  state, chat, map). You will appreciate both the framework and why the original
  did without one.

### Stage 2 — Backend and APIs (4–6 weeks)

- **HTTP API design** — REST conventions, status codes, pagination, error shapes.
- **A web framework** — FastAPI (you have a head start — chapter `03`) or
  Flask/Django. Routing, request validation, dependency injection, middleware.
- **Databases and SQL** — schema design, joins, indexes, transactions,
  `EXPLAIN`, then an ORM (SQLAlchemy) and migrations (Alembic) (chapters `01`
  Part 5, `04`).
- **Auth** — sessions vs tokens (JWT), password hashing, OAuth.
- **Testing** — fixtures, mocking, dependency overrides, test databases (chapter
  `10`).
- **Project:** a CRUD app *with* writes — a small bookmarking service with user
  accounts, a real Postgres database, migrations, and an authenticated API. This
  is everything chapter `04`'s Rule 2 let this project skip.

### Stage 3 — LLM application development (3–5 weeks)

- **The Messages API** — roles, `max_tokens`, temperature, context windows,
  token counting and cost (chapter `06`).
- **Prompt design** — system prompts, few-shot examples, output formatting,
  structured output / JSON mode.
- **Tool / function calling** — JSON Schema tools, the agent loop, multi-step
  tool use, error handling in tools (chapter `07`).
- **RAG** — chunking, embeddings, a vector database (start with FAISS, then try a
  hosted one like pgvector or Pinecone), retrieval evaluation, re-ranking
  (chapter `08`).
- **Streaming** — SSE and the newer streaming patterns (chapters `02`, `05`).
- **Project:** a "chat with your documents" app — upload PDFs, chunk and embed
  them, answer questions with citations, stream the response, and expose one or
  two tools (e.g. "search the web", "do a calculation").

### Stage 4 — LLMOps and production (ongoing)

- **Cost and rate control** — token budgets, per-user quotas, a shared rate-limit
  store, caching identical requests, `max_tokens` discipline (chapter `06` §6,
  chapter `12` §10).
- **Evaluation** — build an eval set (inputs + expected properties), score prompt
  changes against it, catch regressions before deploy. This is the gap chapter
  `10` §10 names.
- **Observability** — log every model call (prompt, response, tokens, latency,
  cost), trace multi-step turns, alert on error rates and spend.
- **Guardrails** — input moderation, jailbreak/prompt-injection resistance,
  output validation, PII handling.
- **Prompt/version management** — treat prompts as versioned artifacts, not
  strings buried in code; be able to roll one back independently.
- **Deployment and CI/CD** — Docker (chapter `12`), a real CI pipeline (tests +
  build + deploy on push), staged environments, health checks, rollbacks.
- **Project:** take your Stage 3 app and make it *operable* — add an eval suite, a
  cost dashboard, structured logging of every call, a GitHub Actions pipeline, and
  a staging environment. Deploy it behind a reverse proxy with real HTTPS.

### Stage 5 — Depth (pick what you need)

- **Vector search at scale** — approximate indexes (HNSW, IVF), sharding, hybrid
  (keyword + vector) search, hosted vector databases.
- **Prompting vs fine-tuning** — when each is worth it; how fine-tuning and
  distillation actually work in practice.
- **Multi-agent orchestration** — frameworks and patterns for agents that call
  other agents; when this helps and when it is over-engineering.
- **Security** — prompt injection in depth, data exfiltration via tools, supply-
  chain risks, the OWASP Top 10 for web apps and the emerging one for LLM apps.
- **Frontend depth** — state management, accessibility, performance, testing
  component trees.

## 6. Capstone: rebuild this project from an empty folder

The best way to prove you have internalised all of it. Give yourself an empty
directory and a checklist:

- [ ] `git init`, a `.gitignore` that excludes secrets and regenerable data.
- [ ] A `venv`, a `requirements.txt` with pinned versions.
- [ ] `app/config.py` — settings from `os.environ`, fail-fast on missing required
      vars, a frozen dataclass.
- [ ] `app/db.py` — a schema, a writable and a read-only connection factory.
- [ ] `app/queries.py` — parameterised reads, one query per function, `conn`
      injected.
- [ ] An offline import script — parse an input, call an external API through an
      injected client, write the DB, be idempotent, skip-and-report, meaningful
      exit codes.
- [ ] `app/llm.py` — a thin client wrapper with an injectable raw client, a system
      prompt, at least one JSON-Schema tool with an `enum` from the DB.
- [ ] `app/chat.py` — the bounded agent loop; strip anything sensitive from tool
      results before the model sees them.
- [ ] `app/main.py` — FastAPI, dependency injection, a Jinja2-rendered page, a
      streaming SSE endpoint, rate limiting.
- [ ] A vanilla-JS frontend that consumes the stream and renders the result.
- [ ] A `pytest` suite that runs fully offline with fakes for every external
      system.
- [ ] A `Dockerfile` (dependencies layer before code layer), a `.dockerignore`
      that excludes secrets.
- [ ] A `Caddyfile` and a written deploy runbook.

If you can produce that from memory, you can build LLM-backed web applications.
This one is 2,000-ish lines of code; yours can be too.

---

## Exercises & checkpoints

1. **Retell the story.** Without looking, write the "life of a request" from
   chapter `00` §5 again — but now with every file *and function* named. Compare
   to §1 of this chapter.
2. **Defend an absence.** Pick three rows from the "deliberately leaves out"
   table (§4). For each, describe the specific requirement that would *force* you
   to add it, and roughly what adding it would involve.
3. **Place yourself on the roadmap.** Which stage are you actually at? Pick the
   one project from that stage and schedule it.
4. **Start the capstone checklist.** Create the empty folder, do the first three
   boxes (`git init` + `.gitignore`, the venv + `requirements.txt`,
   `app/config.py`). You have working examples of all three in this repo.

That is the course. The code is `..`; go read it again — it will read differently
now.

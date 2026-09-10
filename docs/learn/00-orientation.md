# 00 — Orientation: the whole project on one page

Before any technology, you need a picture of what this thing *is*. This chapter
gives you that picture, a glossary you can return to whenever a word is unfamiliar,
a map of every file in the repository, and a first, deliberately shallow walk
through what happens when a visitor asks a question.

Read this chapter slowly. Everything after it assumes you have this model in your
head.

---

## 1. What the application does

It is a website with exactly one page. On that page:

1. A visitor types a question like *"What are your favourite restaurants in
   Taipei?"* and presses send.
2. The question goes to a **server** — a program running on a computer somewhere
   on the internet.
3. The server forwards the question to a **large language model** (Anthropic's
   Claude), along with a hidden instruction block telling the model to answer in
   the first person as "Joey", a well-travelled person who saved these places
   himself.
4. The model writes a reply. While writing, it can decide to call a **tool** — a
   function the server exposes to it — called `show_city_map`. Calling that tool
   is the model's way of saying *"show the visitor a map of Joey's saved spots in
   this city."*
5. The server runs that tool: it queries its own **database** for the saved spots
   in that city, and builds a data structure describing where each pin goes.
6. The reply text streams back to the browser word by word, and when it is done,
   the map appears underneath it — an interactive Google Map with a pin (and a
   little rating badge) for each saved spot, plus a scrollable list and a detail
   card.

There is **no login**. There is **no sign-up**. Visitors can only read and ask;
they can never add, edit, or delete anything. The list of saved places is fixed
when the site is deployed and does not change while it is running.

That last sentence is not an accident. It is one of the two rules the entire
codebase is organised around.

---

## 2. The two rules everything follows from

These two sentences explain most of the design decisions you will meet later. If
something in the code looks more careful or more restrictive than you expected,
it is almost always one of these two rules being enforced.

### Rule 1 — The LLM never emits coordinates

> The model's only job is to decide **whether** to show a map and **which** city
> or country. The application builds the map itself, from its own database query.
> The model never produces latitude/longitude values that end up on the map.

Why: language models generate *plausible-looking* text. If you let a model output
map coordinates, it will happily invent `25.0330, 121.5654` for a restaurant it
has never heard of, and the pin will land in a car park. So the model is kept on
the *decision* side of the line ("show Taipei restaurants") and never touches the
*data* side ("the restaurant is at exactly this point"). The server reads the
real coordinates straight out of its database and sends them to the browser
without the model ever seeing them.

You will see this rule enforced in **three separate places** in `app/chat.py` and
`app/maps.py` (chapter `07` covers all three).

There is exactly one narrow, deliberate exception: the model may supply
`near_lat` / `near_lng` for a request like *"restaurants near the Eiffel Tower"*.
Those numbers are used **only to filter** which saved spots are close enough to
show — they are never plotted as a pin. Every pin's position still comes from a
database row.

### Rule 2 — The data never changes at runtime

> An offline script, run on the owner's own laptop, turns a pile of CSV files into
> a database file. The running website only ever **reads** that file. There is no
> upload form, no "add a place" button, no background job, and no code path
> anywhere in the running server that writes to the database.

Why: it makes the whole system dramatically simpler and safer. No user accounts,
no permissions, no "what if two people edit at once", no database migrations on
deploy, no backups to worry about (the data is rebuilt from source any time), and
a much smaller attack surface. The database connection the website uses is opened
in **read-only mode** at the operating-system level — a bug or a malicious input
literally *cannot* write to it; the attempt raises an error.

Deploying a new version of the site means: build a fresh database file on your
laptop, then rebuild and redeploy the whole application bundle. Rolling back means
redeploying the previous bundle. Data version and code version move together.

---

## 3. Glossary

Come back here whenever a term is unfamiliar. Terms are grouped, not alphabetical,
so related ideas sit together.

### The web

- **Client** — the program making a request. For this app, the visitor's web
  browser.
- **Server** — a program that waits for requests and sends back responses. This
  app's server is a Python program.
- **Request / response** — one round trip. The client sends a request ("give me
  the page at `/`"), the server sends back a response (the HTML for that page).
- **HTTP** — the rules for how requests and responses are formatted. "HyperText
  Transfer Protocol." HTTPS is HTTP with encryption.
- **URL** — the address of something on the web, e.g.
  `https://travelai.the200.blog/api/chat/stream`. Made of a scheme (`https`), a
  host (`travelai.the200.blog`), a path (`/api/chat/stream`), and optionally a
  query string (`?message=hi`).
- **Endpoint** — one specific path on the server that does one job, e.g.
  `POST /api/chat`. A server is a collection of endpoints.
- **Route** — the code that handles one endpoint. "The `/api/chat` route."
- **Port** — a numbered channel on a computer. Web servers usually listen on port
  80 (HTTP) or 443 (HTTPS); during development this app listens on 8000.
- **localhost** — a name that always means "this same computer." `localhost:8000`
  is "port 8000 on my own machine."
- **JSON** — a plain-text format for structured data: objects `{ }`, arrays
  `[ ]`, strings, numbers, booleans, null. The universal language for sending
  data between a browser and a server.
- **API** — "Application Programming Interface." Loosely, a set of endpoints
  designed to return data (usually JSON) rather than a web page. The app's
  `/api/...` endpoints are its API.
- **DNS** — the system that turns a name like `travelai.the200.blog` into a
  numeric IP address like `2.28.113.54`.
- **SSE (Server-Sent Events)** — a way for the server to send a response in
  pieces over a long-lived connection, instead of all at once. This app uses it
  to stream the model's reply word by word.

### The code

- **Framework** — a library that provides the skeleton of an application so you
  only write the parts specific to your app. This project's web framework is
  **FastAPI**.
- **Dependency** — a third-party library your code needs. Listed in
  `requirements.txt`.
- **Virtual environment** (`venv`) — a private folder holding one project's
  dependencies, so different projects don't collide.
- **Environment variable** — a named value passed to a program by whoever starts
  it, instead of being written in the code. Used for secrets (API keys) and
  per-machine settings.
- **Module** — one `.py` file. **Package** — a folder of modules.
- **Type hint** — an optional annotation like `name: str` that says what kind of
  value a variable holds. Python does not enforce these; they are for humans and
  tools.

### The data and the model

- **Database** — an organised store of data you can query. This app uses
  **SQLite**, where the entire database is a single file (`travel.db`).
- **SQL** — the language for querying a relational database.
- **Schema** — the definition of a database's tables and columns.
- **Geocoding** — turning a place name ("Le Pantruche, Paris") into coordinates.
- **LLM** — large language model. Here, Anthropic's Claude.
- **Token** — the unit an LLM reads and writes in; roughly ¾ of a word. Model
  pricing and context limits are measured in tokens.
- **System prompt** — a block of instructions given to the model before the
  conversation, setting its role and rules. The visitor never sees it.
- **Tool / function calling** — a mechanism where you describe functions to the
  model in a structured way, and instead of answering in prose the model can
  respond "call `show_city_map` with `{city: "Taipei"}`". Your code runs the
  function and hands the result back.
- **Agent loop** — the pattern of: call the model → it asks for a tool → run the
  tool → call the model again with the result → repeat until it produces a final
  answer.
- **RAG (Retrieval-Augmented Generation)** — fetching relevant text from your own
  data and putting it into the model's context so its answer is grounded in that
  text. This app uses it for Joey's private travel-diary entries.
- **Embedding** — a list of numbers (a vector) representing the meaning of a piece
  of text, such that similar meanings produce nearby vectors. The basis of
  semantic search.
- **FAISS** — a library for storing many embeddings and finding the nearest ones
  to a query vector, fast.

### Running and shipping

- **Git** — a tool that records the history of a folder of files as a series of
  snapshots ("commits").
- **GitHub** — a website that hosts Git repositories.
- **Docker** — a tool that packages an application plus everything it needs into
  one portable unit called an **image**; a running copy of an image is a
  **container**.
- **VPS** — "Virtual Private Server." A rented Linux computer in a data centre.
- **Reverse proxy** — a server that sits in front of your application, receives
  the public traffic, and forwards it inward. This app uses **Caddy**, which also
  gives it HTTPS automatically.

---

## 4. Map of the repository

Here is every file and folder that matters, with a one-line description. Paths are
relative to the repository root.

### The running application — `app/`

| File | Role |
|------|------|
| `app/__init__.py` | Empty. Its existence makes `app/` an importable package. |
| `app/config.py` | Reads settings and secrets from environment variables into one `settings` object. Refuses to start if a required one is missing. |
| `app/db.py` | The database schema (as SQL text) and two functions to open a connection — one writable (for the offline scripts), one read-only (for the website). |
| `app/queries.py` | Every SQL read the app performs, one function per query. Nothing else. |
| `app/maps.py` | Turns database rows into the "map payload" — the JSON the browser's map code consumes. |
| `app/geo.py` | Pure maths: distance between two lat/lng points, and "keep only the spots within N km of here." |
| `app/llm.py` | Everything about talking to the model: the system-prompt text, the two tool definitions, and a client class wrapping the Anthropic SDK. |
| `app/chat.py` | The orchestrator of one chat turn: the agent loop, dispatching each tool call, and the coordinate-stripping enforcement. |
| `app/rag.py` | The retrieval layer: embed diary entries, build/search a FAISS index. Backs the `get_city_context` tool. |
| `app/limits.py` | Two in-memory throttles: per-IP messages-per-hour, and a site-wide messages-per-day cap. |
| `app/main.py` | The FastAPI application itself: wires everything together and defines the four routes. |
| `app/templates/index.html` | The single HTML page, rendered once per visit by the templating engine. |
| `app/static/app.js` | All the browser-side behaviour: sending messages, consuming the stream, rendering the map. One file, no build step. |
| `app/static/style.css` | All the styling. One file, hand-written. |
| `app/static/spot_photos/` | Downloaded place photos (created by an offline script; not committed to Git). |

### The offline data pipeline — `scripts/`

These run on the owner's laptop, never on the server. They build `travel.db` and
`stories.faiss`.

| File | Role |
|------|------|
| `scripts/import_saved_places.py` | Parses the Google Maps "Saved lists" CSV export, geocodes each new place via the Google Places API, and writes the `cities` / `categories` / `spots` tables. |
| `scripts/assign_countries.py` | Fills in each city's country from a hand-written name→country map. |
| `scripts/enrich_places.py` | Fetches a rating, phone, website, and one photo per saved spot and writes the `spot_details` table. |
| `scripts/import_stories.py` | Loads Joey's private travel-diary JSON into the `city_stories` table. |
| `scripts/build_story_index.py` | Turns those diary rows into embeddings and writes the FAISS index file `stories.faiss`. |

### The tests — `tests/`

`tests/conftest.py` plus 14 `test_*.py` files, roughly one per module above.
~179 test cases. They run with **no network and no real API keys** (chapter `10`).

### Configuration and deployment — repository root

| File | Role |
|------|------|
| `requirements.txt` | The exact list of Python dependencies, with pinned versions. |
| `.env.example` | A template for the `.env` file that holds secrets and settings. Copy it to `.env` and fill it in. `.env` itself is never committed. |
| `Dockerfile` | The recipe for packaging the app into a Docker image. |
| `.dockerignore` | Files to keep *out* of that image (secrets, tests, docs, the raw CSVs). |
| `Caddyfile` | The reverse-proxy config: "serve this domain over HTTPS, forward to the app on port 8000." |
| `.gitignore` | Files Git should never track (secrets, the database, caches, the virtual environment). |
| `README.md` | Quick-start and reference for someone already comfortable with the stack. |
| `BUILD_INSTRUCTIONS.md` | The original design specification — a 15-step build plan. Useful as design history; slightly behind the current code (it predates `enrich_places.py` and the `spot_details` table). |
| `DEPLOY.md` | A step-by-step walkthrough of deploying to a specific hosting provider (Hetzner). Summarised in chapter `12`. |
| `docs/learn/` | This course. |

---

## 5. Life of a request (the shallow version)

Here is what happens when a visitor asks *"Favourite restaurants in Taipei?"* Each
step names the file involved; every step is expanded in a later chapter. Do not
worry about the details yet — just follow the shape.

1. The browser already has the page open. The visitor types into the `<input>`
   and the form's submit handler in **`app/static/app.js`** runs.
2. `app.js` opens a streaming connection to
   `GET /api/chat/stream?message=...&history=...`. The whole prior conversation
   is sent along in the URL, because — Rule 2's cousin — **the server keeps no
   memory between requests**. The browser is the only thing that remembers the
   conversation.
3. **`app/main.py`** receives the request at its `api_chat_stream` route. It
   checks the rate limits (**`app/limits.py`**). It opens a read-only database
   connection (**`app/db.py`**).
4. It builds the two tool definitions and the system prompt, using the current
   contents of the database (**`app/queries.py`** + **`app/llm.py`**). The system
   prompt literally contains the list of every city and category Joey has saved.
5. It calls **`app/chat.py`**'s `stream_message`, which runs the **agent loop**:
   - Send the conversation to the model (**`app/llm.py`** → the Anthropic SDK).
   - The model streams back some text, then asks to call `show_city_map` with
     `{city: "Taipei", categories: ["Restaurants"]}`.
   - `chat.py` runs that tool: `get_city_spots_by_categories` in
     **`app/queries.py`** returns the matching rows; `build_map_payload` in
     **`app/maps.py`** turns them into a map payload.
   - Crucially, the text `chat.py` sends *back to the model* contains only each
     spot's title, note, and category — **no coordinates** (Rule 1).
   - `chat.py` calls the model again with the tool result. This time the model
     just writes its final prose answer and stops.
6. As all this happens, `chat.py` `yield`s a sequence of small events:
   `{"type": "delta", "text": "..."}` for each chunk of prose, then one
   `{"type": "map", "map": {...}}`, then `{"type": "done"}`.
7. **`app/main.py`** wraps each event as a line of Server-Sent-Events text
   (`data: {...}\n\n`) and streams it to the browser.
8. Back in **`app/static/app.js`**, the `EventSource` receives each event:
   `delta` events append text to the assistant's chat bubble (re-rendering the
   little bit of Markdown the model uses); the `map` event is held; on `done` the
   map is drawn beneath the bubble using the Google Maps JavaScript API.
9. The connection closes. The server has stored nothing.

That is the entire system. Every remaining chapter is a zoom-in on one part of
this loop.

---

## Exercises & checkpoints

You cannot run anything yet (chapter `13` sets that up), so these are
reading-comprehension checkpoints. Write your answers down; you will confirm them
later.

1. **In your own words**, why can the model choose *which* city to map but not
   *where* a specific restaurant's pin goes? Which of the two rules is that?
2. The server "keeps no memory between requests." Where, then, does the ongoing
   conversation live between one message and the next? (Hint: step 2 above.)
3. List the files a single `/api/chat/stream` request touches, in order, from the
   "Life of a request" section. You should be able to name at least six.
4. `travel.db` is in `.gitignore` — Git never stores it. Given Rule 2, why is
   that fine? Where does `travel.db` come from when the app is deployed?

When you can answer all four without re-reading, move on to `languages.md`.

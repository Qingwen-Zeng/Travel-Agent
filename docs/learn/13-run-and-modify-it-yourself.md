# 13 — Run it, and change it

Reading takes you only so far. This chapter gets the app running on your machine
and walks you through three real modifications and a break-and-fix. Everything
here has been run against this repository; the expected output is shown.

---

## 1. Prerequisites

- **Python 3.11 or newer.** Check: `python3 --version`.
- **Git.** Check: `git --version`.
- A terminal.
- (Optional, for the deployment exercises in chapter `12`) Docker.

You do **not** need any Google or Anthropic keys to *start* the server and read
the code. You need them only to actually chat with the model or rebuild the data.

## 2. Get the code and the data

You are (probably) already inside a clone of this repo. If not:

```
git clone https://github.com/Qingwen-Zeng/Travel-Agent.git
cd Travel-Agent
```

Two data files are **not** in Git (chapter `11` §5): `travel.db` and
`stories.faiss`.

- If your checkout **already has them** (run `ls travel.db stories.faiss` — the
  owner's working copy has both), you are set.
- If it does **not** (a fresh clone), you would normally rebuild them with the
  scripts in chapter `09`, which need `Saved/`, `stories.json`, and a Google
  Places key. Without those, you can still run the server against an **empty**
  database:

  ```
  python3 -c "from app.db import get_writable_connection; get_writable_connection('travel.db').close()"
  ```

  The app boots, the page loads, but there are no cities to ask about. Fine for
  reading code and doing exercises 1–3 below.

## 3. Set up the environment

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

The `pip install` pulls in FastAPI, the Anthropic SDK, FAISS, and
`sentence-transformers` (which drags in PyTorch — this step downloads a few
hundred MB and takes a couple of minutes the first time).

Now open `.env` in an editor. To just *start* the server, put any non-empty
placeholder in the four required variables:

```
GOOGLE_MAPS_BROWSER_KEY=placeholder
GOOGLE_MAPS_MAP_ID=placeholder
LLM_API_KEY=placeholder
LLM_MODEL=claude-sonnet-4-5
```

With placeholders: the page loads and you can read/inspect everything, but the
map will not render (bad Maps key) and sending a chat message will error (bad LLM
key). To use those features for real, put in genuine keys (chapter `12` §9
explains the two Google keys; the Anthropic key comes from
`console.anthropic.com`).

## 4. Start the server

```
.venv/bin/uvicorn app.main:app --reload
```

Expected output (roughly):

```
INFO:     Will watch for changes in these directories: ['/Users/.../Travel-Agent']
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [...]
INFO:     Started server process [...]
INFO:     Application startup complete.
```

Open `http://127.0.0.1:8000/` in a browser. You should see the chat page: a
greeting, an input box, and (if your database has cities) a row of "Try asking"
chips.

`--reload` means the server restarts automatically whenever you save a `.py`,
`.html`, `.js`, or `.css` file — leave it running in one terminal and edit in
another.

If you get `Missing required environment variable(s): ...` — you skipped or
mistyped one of the four in `.env` (chapter `03` §5).

## 5. Run the tests

In a second terminal, from the repo root:

```
.venv/bin/python -m pytest -q
```

Expected (the exact number may drift as the code evolves):

```
.................................................................. [ 37%]
.................................................................. [ 74%]
...............................................                    [100%]
179 passed in 1.05s
```

These run offline; no keys, no network (chapter `10`).

## 6. Change #1 — add a suggestion chip

**Goal:** add a starter question to the empty-state screen.

Open `app/main.py`, find `FAVORITE_EXAMPLES`, and add a pair for a city that
exists in your database (run
`.venv/bin/python -c "import sqlite3,os; c=sqlite3.connect('travel.db'); print([r[0] for r in c.execute('SELECT name FROM cities ORDER BY spot_count DESC LIMIT 8')])"`
to see candidates):

```python
FAVORITE_EXAMPLES = [
    ("Taipei", "Taipei Restaurant Recommendations"),
    ("NYC", "New York City Things To Do"),
    ("Bangkok", "Bangkok Bars And Clubs"),
    ("Boston", "Boston Dessert Spots"),
    ("Lebanon", "Lebanon Restaurants"),
    ("Paris", "Best coffee in Paris"),        # <-- your new line
]
```

Save. The server reloads. Refresh `http://127.0.0.1:8000/`.

**Expected:** a new chip reading "Best coffee in Paris" appears (only if "Paris"
is a real city in your DB — the route filters chips to known cities, chapter `03`
§6). Clicking it sends that exact text as a chat message.

**What you touched:** the Python route → the Jinja2 `{% for %}` loop in
`index.html` → the `data-question` attribute → `bindSuggestionChips` in `app.js`.

## 7. Change #2 — retune one line of the system prompt

**Goal:** see how much behaviour lives in the prompt. (Needs a real `LLM_API_KEY`.)

Open `app/llm.py`. Near the top of `SYSTEM_PROMPT_INTRO`, the model is told to
"Speak in the first person, from real experience." Add a sentence right after it:

```python
"...not a third party summarizing a database. "
"Always end every reply with a single relevant emoji. "     # <-- add this
"Your saved spots are organized by city..."
```

Save (server reloads). Ask any question in the chat.

**Expected:** replies now end with an emoji. You changed *zero* lines of Python
logic — the behaviour is entirely in the prompt string. Revert the change when
you have seen it.

## 8. Change #3 — a visual token

**Goal:** confirm the design-token system and the cache-buster.

Open `app/static/style.css`. In the `:root` block, change:

```css
--color-accent: #3f4f4a;   /* to, say, */  #7a3b2e;
```

Save. Hard-reload the page (Cmd/Ctrl-Shift-R).

**Expected:** the user chat bubbles, the send button, and the spot-name links all
change colour together — because they all reference `var(--color-accent)`
(chapter `05` §11). Also: view source before and after and note the `?v=` value
on the `style.css` URL changes, because you edited the file and its modification
time changed (chapter `03` §6). Revert.

## 9. Break a test, read the failure, fix it

**Goal:** learn to read `pytest` output.

Open `app/geo.py` and change:

```python
EARTH_RADIUS_KM = 6371.0   # to
EARTH_RADIUS_KM = 3000.0
```

Run `.venv/bin/python -m pytest tests/test_geo.py -q`.

**Expected:** one or more failures. The output shows something like:

```
    def test_haversine_known_distance():
>       assert abs(haversine_km(...) - 111.19) < 1.0
E       assert abs(52.35... - 111.19) < 1.0
```

Read it top to bottom: the test name, the failing `assert` line (marked `>`), and
the expanded values (marked `E`) — the actual number no longer matches the
expected. Restore `6371.0` and re-run; it passes. This is the whole debugging
loop: change → run the relevant test → read the expanded assert → fix.

## 10. Watch the machinery in the browser

With a real setup (real keys, non-empty DB), open the browser DevTools (F12):

- **Network tab.** Send a chat message. Find the request to
  `chat/stream?message=...`. Its type is `eventsource`. Click it → "EventStream"
  (Chrome) or "Response" and watch the `data:` events arrive: several `delta`s,
  maybe one `map`, then `done` (chapters `02` §6, `05` §6).
- **Sources tab.** Open `app.js` (via `/static/app.js?v=...`). Set a breakpoint
  inside `eventSource.onmessage` (around the `if (data.type === "delta")` line).
  Send a message. Execution pauses on each event; inspect `data` in the scope
  panel. Continue (F8) to resume.
- **Console tab.** Type `document.querySelectorAll(".chat-bubble").length` after a
  couple of exchanges to see how many bubbles are in the DOM.

## 11. Troubleshooting table

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `Missing required environment variable(s): ...` at startup | a blank/missing value in `.env` | fill in the four required vars (chapter `03` §5) |
| `Address already in use` | a server is already on port 8000 | stop it, or run `uvicorn ... --port 8001` |
| Page loads but the map area is blank / console shows a Google error | bad or unrestricted `GOOGLE_MAPS_BROWSER_KEY`, or missing `GOOGLE_MAPS_MAP_ID` (Advanced Markers need it) | use a real key + Map ID (chapter `05` §8) |
| Chat message → "Sorry, something went wrong" | bad `LLM_API_KEY` or `LLM_MODEL`, or no network to Anthropic | check the server console for the real error |
| No cities, no chips, model says it has nothing saved | empty `travel.db` | run the import pipeline (chapter `09`) or use the owner's data files |
| `get_city_context` never adds diary colour | `stories.faiss` missing | run `import_stories.py` + `build_story_index.py`, or accept the graceful no-op (chapter `08`) |
| Tests fail with `ModuleNotFoundError: No module named 'app'` | ran `pytest` not as a module | use `.venv/bin/python -m pytest` from the repo root (chapter `01` §1.1) |

---

## Exercises & checkpoints

1. **Full loop.** From scratch: create the venv, install, copy `.env`, start the
   server, load the page, run the tests. Write down anything that did not match
   the expected output above.
2. **Do all three changes** (chip, prompt line, colour token), verify each, then
   revert each. For each, name the files involved.
3. **Break something else.** Change `MAX_TOOL_CALLS_PER_TURN` in `app/chat.py` to
   `1`. Run `pytest tests/test_chat.py`. Which tests fail, and what does the
   failure tell you about what a value of 1 prevents? (Hint: chaining
   `get_city_context` → `show_city_map`.) Revert.
4. **Add and keep a real feature.** Combine chapter `03` exercise 1 (the
   `/api/health` route) and chapter `04` exercise 4 (`get_city_spot_count`): make
   `/api/health` return `{"status": "ok", "cities": <count of rows in cities>}`.
   Restart, `curl` it, confirm the count matches
   `SELECT COUNT(*) FROM cities`.
5. **Read your own diff.** After doing exercise 4, run `git diff`. Read every
   changed line and be able to explain why it is there. Then `git restore` the
   files (or commit them on a branch — chapter `11`).

Continue to `14-summary-and-roadmap.md`.

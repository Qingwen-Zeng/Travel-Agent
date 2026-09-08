# Travel Agent — Build Instructions

Instructions for building the project. Work through the steps in order, lowest level
first. Do not start a step until the previous step's "Done when" conditions are met.

---

## Project

A personal website that shares the owner's saved travel spots. Visitors open the site
and chat with an AI travel consultant. There is **no sign-up and no login** — anyone with
the link can read and ask questions. Visitors never write data.

When the AI judges that a city's saved spots are relevant to the question, it calls a tool.
The reply is prose **plus** an interactive Google Map with those spots pinned on it.

### The rule everything else follows from

> **The LLM never emits coordinates.** The model's only job is to decide *whether* to show
> a map and *which city*. The application builds the map from its own database query. If
> the model were allowed to produce map data it would invent plausible-looking coordinates.

### The second structural rule

> **The data never changes at runtime.** An offline import script transforms the owner's
> CSVs into SQLite. The web application only ever reads. There is no upload endpoint, no
> runtime geocoding, no background worker.

---

## Stack

| Concern | Choice |
|---|---|
| Language | Python 3.11+ |
| Web framework | FastAPI + Uvicorn |
| Templating | Jinja2 |
| Frontend interactivity | HTMX + vanilla JS. **No Node, no build step, no React.** |
| Database | SQLite (WAL mode) |
| Map | Google Maps JavaScript API with Advanced Markers |
| Geocoding | Google Places API (New) Text Search — **import time only** |
| AI | One LLM API with tool calling |
| Semantic retrieval | FAISS (local index) + `sentence-transformers` (local embeddings) |
| Rate limiting | `slowapi` or equivalent |
| Deployment | Docker image → VPS behind Caddy |

**Do not add:** Postgres, PostGIS, Redis, Celery, React, an ORM, user accounts, an upload
UI, or background workers. If a step seems to need one of these, stop and flag it instead
of adding it.

**Retrieval-augmented generation was out of scope for the original twelve steps** — the
saved spots didn't need it, because a city holds around ten spots and the Step 4 query
returns the complete, exact set. It became worthwhile once a second, much richer source of
*additional* material existed that was too large to always sit in the prompt: the owner's
personal travel diary entries (`stories.json`). See Step 13 for how it's built — a real
embedding index (FAISS + a local sentence-transformers model), not just a direct city-keyed
lookup, kept in a separate tool from `show_city_map` so it never implies a map and works even
for cities with no saved spots at all.

---

## Repository layout

Create exactly this structure. Do not add directories that are not listed.

```
travel-agent/
├── app/
│   ├── __init__.py
│   ├── config.py            settings from environment
│   ├── db.py                connection helpers + schema
│   ├── queries.py           all SQL reads
│   ├── maps.py              map payload construction
│   ├── geo.py               haversine distance + radius filtering
│   ├── llm.py               LLM client + tool definitions
│   ├── chat.py              chat orchestration
│   ├── rag.py               story embedding + FAISS index build/search
│   ├── limits.py            rate limiting
│   ├── main.py              FastAPI app, routes
│   ├── templates/
│   │   └── index.html
│   └── static/
│       ├── app.js
│       └── style.css
├── scripts/
│   ├── import_saved_places.py  offline Saved/ export → SQLite
│   ├── import_stories.py       offline stories.json → city_stories table
│   ├── build_story_index.py    city_stories → FAISS index file
│   └── assign_countries.py     hand-curated city → country mapping
├── Saved/                    owner's Google Maps "Saved lists" export, one CSV per
│                              city+category (git-ignored)
├── stories.json               owner's personal travel diary entries (git-ignored)
├── tests/
│   ├── test_import_saved_places.py
│   ├── test_import_stories.py
│   ├── test_assign_countries.py
│   ├── test_queries.py
│   ├── test_maps.py
│   ├── test_geo.py
│   ├── test_rag.py
│   └── test_chat.py
├── Dockerfile
├── Caddyfile
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Working method

Follow this for every step:

1. Write the failing test first.
2. Write the minimum code to pass it.
3. Run the full suite before moving on.
4. Keep the change inside the files the step names. Do not refactor other files.

Every step below states its acceptance tests. Those are the minimum, not the maximum.

---

# Step 1 — Skeleton and configuration

**Goal:** an installable project that starts and reads its settings from the environment.

**Files:** `requirements.txt`, `.env.example`, `.gitignore`, `app/__init__.py`, `app/config.py`

### Requirements

`requirements.txt` pins: `fastapi`, `uvicorn[standard]`, `jinja2`, `python-dotenv`,
`requests`, `slowapi`, the LLM provider SDK, and `pytest`.

### Configuration

`app/config.py` exposes a single settings object read from environment variables. Every
setting is required except where a default is given.

| Variable | Purpose |
|---|---|
| `DATABASE_PATH` | path to the SQLite file (default `travel.db`) |
| `GOOGLE_MAPS_BROWSER_KEY` | Maps JavaScript API key, sent to the browser |
| `GOOGLE_MAPS_MAP_ID` | Map ID, required by Advanced Markers |
| `LLM_API_KEY` | LLM provider key |
| `LLM_MODEL` | model identifier |
| `RATE_LIMIT_PER_HOUR` | per-IP message cap (default 10) |
| `DAILY_MESSAGE_CAP` | site-wide message cap per day (default 300) |

`GOOGLE_PLACES_API_KEY` is **not** in this list. It belongs to the import script only and
must never be loaded by the web application.

`.gitignore` must exclude `Saved/`, `*.db`, `.env`, and `__pycache__/`.

### Done when

- `python -c "from app.config import settings"` succeeds with a populated `.env`.
- Missing a required variable raises a clear error naming the variable.

---

# Step 2 — Database schema

**Goal:** the schema exists and can be created from nothing.

**Files:** `app/db.py`

### Schema

```sql
CREATE TABLE IF NOT EXISTS cities (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL UNIQUE,
    center_lat REAL,
    center_lng REAL,
    spot_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS categories (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS spots (
    id          INTEGER PRIMARY KEY,
    city_id     INTEGER NOT NULL REFERENCES cities(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    title       TEXT    NOT NULL,
    lat         REAL    NOT NULL,
    lng         REAL    NOT NULL,
    note        TEXT,
    place_id    TEXT,
    ftid        TEXT    NOT NULL,
    maps_url    TEXT,
    UNIQUE (city_id, category_id, ftid)
);

CREATE INDEX IF NOT EXISTS idx_spots_city ON spots(city_id);
CREATE INDEX IF NOT EXISTS idx_spots_category ON spots(category_id);
```

Column notes:

- `name` (on both `cities` and `categories`) — parsed from the CSV filename, which follows
  `{City} {Category}.csv` (e.g. `Paris Restaurants.csv`). Category names are normalised to
  Title Case at import time, and a handful of near-duplicate raw category phrases (spelling
  variants, punctuation artefacts) are merged into one canonical name — see Step 3.
- `ftid` — Google Maps feature identifier extracted from the saved URL. This is the dedupe
  key that makes re-imports idempotent.
- **`UNIQUE (city_id, category_id, ftid)` is a composite key, not a global-unique `ftid`.**
  The real data proves a place can legitimately be saved under more than one category for
  the same city (e.g. a restaurant that's also a bar) — the composite key allows that, one
  `spots` row per (city, category) a place was actually saved under, while still preventing
  a true duplicate within the same city+category.
- `place_id` — Google place identifier. This is the only Google-derived field that may be
  stored indefinitely under their terms.
- `center_lat` / `center_lng` / `spot_count` — derived from the city's spots, recomputed by
  the import script. Never written by the web application.

### Connections

Provide two connection helpers:

- A **writable** connection used only by the import script. Enables `PRAGMA foreign_keys`
  and `PRAGMA journal_mode = WAL`, and creates the schema if absent.
- A **read-only** connection used by the web application. Open the database in read-only
  mode so the app is structurally incapable of writing.

Both set `row_factory` to `sqlite3.Row`.

### Acceptance tests

- Creating a connection against a fresh path produces all three tables and both indexes.
- Inserting two spots with the same `(city_id, category_id, ftid)` raises an integrity
  error; the same `ftid` under a *different* category for the same city is allowed.
- Deleting a city cascades to its spots; deleting a category cascades to its spots.
- The read-only connection raises on an attempted write.

### Done when

The tests pass and a database file can be created from nothing.

---

# Step 3 — The import process

**Goal:** transform the owner's Google Maps "Saved lists" export into the database. This
runs on the owner's machine, never on the server, and is the only thing that ever writes to
the database.

**Files:** `scripts/import_saved_places.py`, `tests/test_import_saved_places.py`

## Input

**Files:** `Saved/<City> <Category>.csv` — one file per city **and** category, exported
from Google Maps' "Saved lists" feature (e.g. `Paris Restaurants.csv`,
`Bangkok Desserts.csv`). The filename encodes both: strip a trailing `(1)`/`(2)`
re-export-duplicate suffix, then match the longest known category phrase at the end of the
name (or, for the one observed category-first filename shape, at the start); whatever
remains is the city. Category names are normalised to Title Case and a fixed set of raw
phrase variants are merged into one canonical category (spelling/punctuation drift observed
in the real export — e.g. `Bars` and `Bars and Clubs` both become `Bars And Clubs`; every
gay-related variant becomes `Gay Experience`).

Files that don't match a known city+category pattern — generic, non-city buckets like
`Want to go.csv`, `Just Ok.csv`, `Default list.csv` — are skipped entirely, not imported.

Two or more files can parse to the *same* (city, category) pair (Google's own re-export
duplicates, e.g. `Chicago Restaurants.csv` + `Chicago Restaurants(1).csv`). Their rows must
be merged **before** processing that pair — a naive one-file-at-a-time pass will cause the
"delete rows no longer present" cleanup (see below) to wrongly delete rows that only existed
in the other file. This happened for real during the first production run and was fixed by
grouping all rows by (city, category) across every contributing file first.

**Columns:** `Title`, `Note`, `URL` (a `Tags` and `Comment` column are also present in the
real export but are always empty and are not used). Accept the header case-insensitively and
tolerate surrounding whitespace. Some real files have a stray free-text line (a list
description) before the actual header row — scan for the header rather than assuming it's
always line 1. Read the file as UTF-8 with BOM stripping, so titles containing accented or
non-Latin characters survive byte-for-byte.

**The URL format is the important part.** A row's URL looks like:

```
https://www.google.com/maps/place/Botanical+Garden/data=!4m2!3m1!1s0x479aa749a2e9c621:0xb15b2441c5c23f1
                                                            └─────── feature ID ────────┘
```

Two facts to build around:

1. **These URLs contain no coordinates.** There is no `@lat,lng` segment and no `!3d`/`!4d`
   pair. Do not write code that tries to parse coordinates out of them.
2. **The hex pair after `!1s` is the feature ID.** No Google API converts it into a place
   ID or coordinates, so it cannot be used for lookup — but it is a stable unique
   identifier, which is exactly what is needed to deduplicate across repeated imports.

**Environment:** `GOOGLE_PLACES_API_KEY` — a server-side key restricted to the Places API.
This key must never appear in any file served to a browser.

**Real pricing, checked before writing any import code:** the Places API (New) Text Search
field mask used here (`places.id,places.location` — no `places.primaryType`, since category
now comes from the filename, not Places) requires the Pro SKU ($32/1,000 calls), but Google
Maps Platform gives 5,000 free Pro-tier calls per month per SKU. A one-time import of the
full real dataset (1,322 spots) costs **$0**, comfortably under that allowance.

## Output

`travel.db`, populated against the Step 2 schema: one `cities` row and one `categories` row
per distinct name parsed from the in-scope filenames, one `spots` row per CSV data row (keyed
by city **and** category — the same physical place can produce two rows if saved under two
categories), with coordinates resolved and city summaries computed.

Console summary on success, for example:

```
travel.db: 1348 added, 1 updated, 0 removed, 1314 already located
2 skipped (no match found):
  "Ilham Gallery" (Dubai / Things To Do)
  "KHIRI Thai Tea Emsphere" (Oslo / Restaurants)
```

## Process

Group all in-scope files by the (city, category) pair their filename parses to (merging
rows from Google's own re-export duplicates — see "Input" above), then for each pair:

1. Insert the city and category if they don't already exist.
2. Parse the rows. Skip rows with an empty title or URL. Extract the feature ID from each
   URL — a row with no feature ID (a non-Maps URL) is skipped and reported, not aborted.
3. For each row, decide between two paths:
   - **The (city, category, feature ID) triple is already in the database** → do **not**
     call the geocoding API. Update the stored title, note, and URL from the CSV, so edits
     made in Google Maps flow through at zero cost.
   - **It's new** → resolve it (step 4) and insert.
4. Resolve a new spot with **one Google Places Text Search** on the query
   `"<title>, <city>"`. The city name is the only disambiguating context a bare title gets,
   so it must always be included. Request a narrow field mask covering only the place
   identifier and location — a wide field mask moves the call into a more expensive tier
   (though `location` alone already requires Pro). Take the first result and store its
   latitude, longitude, and place identifier. If Text Search returns no result, or the
   request fails after retries (see below), record the spot as skipped and continue — do
   **not** abort the run.
5. After processing a (city, category) pair's rows, delete any spot in that pair whose
   feature ID was not present among the merged rows. A place the owner removed from their
   Google list must disappear from the site.
6. After every pair has been processed, recompute each touched city's `center_lat`,
   `center_lng` (mean of its spots) and `spot_count`.

## Transaction and failure behaviour

The entire run is **one transaction**. Unlike the schema's earlier, single-city design, an
unresolvable spot does **not** abort the run — it's recorded and the run continues, printing
every skipped spot (title, city, category) in the final summary for manual review. At this
scale (1,300+ spots, one HTTP call each), treating an occasional "no match" or transient
network failure as fatal would make the whole import fragile; skip-and-report keeps a
mostly-successful run mostly successful.

**Geocoding calls retry transient failures.** A single dropped connection among ~1,300
sequential HTTPS calls is expected, not exceptional — `GooglePlacesGeocoder.geocode` retries
up to 3 times with backoff before giving up on a spot (which then joins the skipped list,
same as a genuine "no match").

A structurally malformed CSV (missing a required column, no header row at all) still aborts
the whole run immediately, before any geocoding call is made — there's no sensible way to
partially import a file whose shape can't be understood at all.

**Geocoding accuracy is not guaranteed.** Text Search occasionally matches a same-named
place in the wrong city entirely (confirmed for real: a Taipei-saved "Coba Pizzeria" matched
to a same-named restaurant in New York). This is a Places API limitation, not an import bug.
After a real run, scan for spots whose coordinates are unusually far from their city's other
spots (e.g. haversine distance from the city's median position) and manually review outliers
— most large deviations are legitimate (a big region like Morocco or Lapland genuinely spans
100+ km), but a handful may be genuine mismatches worth deleting or re-resolving by hand.

## Command line

```
python scripts/import_saved_places.py --saved-dir Saved --db travel.db
```

`--saved-dir` defaults to `Saved`, `--db` defaults to `travel.db`.

Exit codes: `0` success (even with some spots skipped), `1` a structurally malformed CSV,
`2` `GOOGLE_PLACES_API_KEY` not set.

## Structure requirement

Parsing, geocoding, and database writing must be separable. The geocoder is **injected**
into the import routine rather than constructed inside it, so the entire test suite runs
offline with a fake geocoder and never issues an HTTP request.

## Acceptance tests

Filename parsing (city/category split, category merging) is tested directly with plain
strings; import behaviour is tested with synthetic CSVs written to `tmp_path`.

- A filename splits into the correct (city, category); the one category-first shape
  (`"Gay Things To Do San Diego"`) is handled; a trailing `(1)`/`(2)` is stripped first.
- Category normalisation title-cases and merges known raw phrase variants (e.g. `"bars"` and
  `"bars and clubs"` both become `"Bars And Clubs"`; every gay-related variant becomes
  `"Gay Experience"`).
- An unknown filename pattern is skipped (returns no match), not an error.
- Import geocodes and writes spots with the correct city/category/title/lat/lng/note.
- Import computes each touched city's centroid and `spot_count` correctly.
- An unresolvable spot is skipped and reported (not aborted) — the rest of the run still
  commits, including other spots in the same (city, category) pair.
- The same place saved under two categories for the same city produces two `spots` rows.
- **Re-running the import issues zero geocoding calls for already-resolved spots** (matched
  by city, category, and feature ID) and creates zero duplicates.
- A changed title or note updates the row without a geocoding call.
- A row removed from a CSV is deleted from that city+category, and `spot_count` drops.
- **Two files that parse to the same (city, category) pair (a Google re-export duplicate)
  are merged before processing — a row unique to one file is not deleted by the other
  file's cleanup pass.** This was a real bug caught by comparing a production run's database
  against the raw CSVs directly, not by a test failure — worth remembering as a class of bug
  test fixtures alone won't catch.
- Generic non-city lists (`Want to go`, `Just Ok`, etc.) are excluded from the import.
- A row with no feature ID (a non-Maps URL) is skipped and reported, not a hard error.
- A structurally malformed CSV (missing a required column) raises and aborts the whole run.
- `GooglePlacesGeocoder` retries a transient request failure up to 3 times before giving up
  and returning no match.

### Done when

All tests pass offline, and running the script against the real `Saved/` export with a real
key produces a populated database. (Done for real on 2026-08-20: 1,342 spots across 110
cities and 20 categories, at $0 cost, with 2 permanently unresolvable spots reported and 6
geocoding mismatches found via the outlier scan above and manually removed.)

---

# Step 4 — Query layer

**Goal:** every read the application performs, in one module, with no SQL anywhere else.

**Files:** `app/queries.py`, `tests/test_queries.py`

### Functions

- `list_cities(conn)` → every city with its name and spot count, ordered by name. Used for
  the suggestion chips and for building the AI tool's city argument list.
- `list_categories(conn)` → every distinct category name that has at least one spot, ordered
  by name. Used for building the AI tool's `categories` argument list.
- `get_city_categories(conn, city_name)` → that city's categories with spot counts, ordered
  by count descending then name. Used to build the "which categories?" part of the system
  prompt for one city.
- `get_all_city_categories(conn)` → every (city, category, spot_count) triple across the
  whole database, **in one query** — used to build the full system prompt in a single call
  instead of one `get_city_categories` call per city (110+ cities would otherwise mean
  110+ queries on every chat request).
- `get_city_spots(conn, city_name)` → every spot in that city, across all categories: title,
  latitude, longitude, note, category name, and Google Maps URL.
- `get_city_spots_by_categories(conn, city_name, categories)` → the same row shape, filtered
  to spots whose category name is in the given list.
- `search_city_spots(conn, city_name, query)` → spots in that city whose title or note
  contains `query`, case-insensitively (LIKE-metacharacter-escaped). Returns title, category,
  note only — **no coordinates** — the same safety property as every other model-facing
  query. Used by Step 7's tool when the model needs to verify whether something ambiguous
  actually exists rather than guessing a category.

`get_city_spots` must be **one query**, joining through `categories` for the name (the row
shape callers see is unchanged from before the schema had a separate `categories` table):

```sql
SELECT spots.title, spots.lat, spots.lng, spots.note, categories.name AS category,
       spots.maps_url
  FROM spots
  JOIN categories ON categories.id = spots.category_id
 WHERE spots.city_id = (SELECT id FROM cities WHERE name = ?)
 ORDER BY spots.title;
```

No per-spot lookups, no loops issuing further queries, no assembly across multiple calls.
`get_city_spots_by_categories` follows the same one-query shape, adding a
`categories.name IN (...)` filter.

City and category name matching is exact. There is no fuzzy matching, no alias table, and no
normalisation beyond what SQLite does (category *normalisation* happens once, at import
time — see Step 3) — Step 7 constrains the AI to valid names, so an unknown name is a bug
rather than an expected input.

### Acceptance tests

- `list_cities` returns cities alphabetically with correct counts.
- `list_categories` returns only categories that have at least one spot.
- `get_city_categories` returns a city's categories with correct counts, sorted by count.
- `get_city_spots` returns every spot for a city (all categories) and nothing from another
  city; an unknown city name returns an empty list rather than raising; executes exactly one
  statement.
- `get_city_spots_by_categories` filters correctly for one category and for multiple
  categories combined; an unknown category returns an empty list.
- `get_all_city_categories` returns every city/category/count triple in exactly one
  statement.
- `search_city_spots` matches against title and note, case-insensitively; scoped to the
  given city; a query with no match returns an empty list; the result never includes
  `lat`/`lng`.

---

# Step 5 — Map payload

**Goal:** turn spot rows into the exact JSON the browser needs to draw a map.

**Files:** `app/maps.py`, `tests/test_maps.py`

### Payload shape

```json
{
  "city": "Zurich",
  "markers": [
    {
      "title": "Botanical Garden",
      "lat": 47.3595,
      "lng": 8.5605,
      "note": "",
      "category": "park",
      "maps_url": "https://www.google.com/maps/place/..."
    }
  ]
}
```

The browser computes framing itself from the marker coordinates, so the payload carries no
centre or zoom.

### Acceptance tests

- Rows from `get_city_spots` convert to the payload shape with coordinates unchanged.
- An empty spot list produces a payload with an empty marker array, not `None`.
- The payload is JSON-serialisable.

---

# Step 6 — Web application with the map, no AI

**Goal:** a working site that lists cities and draws their maps. Build and verify this
**before** any AI code exists, so that a later map problem is unambiguously a map problem.

**Files:** `app/main.py`, `app/templates/index.html`, `app/static/app.js`,
`app/static/style.css`

### Routes

- `GET /` — renders the page. Passes the city list, the browser Maps key, and the Map ID
  into the template.
- `GET /api/city/{name}` — returns the Step 5 payload as JSON. 404 for an unknown city.

### Page

Superseded by Step 9 — once the chat interface exists, it is the only page; there is no
standalone city-list/sidebar view. This step still delivers and verifies: `GET
/api/city/{name}` returning the correct map payload (404 on unknown city), and the
underlying Advanced Marker rendering code (`renderMapPayload` in `app/static/app.js`) that
Step 9 reuses for every inline chat map.

### Map rendering

Load the Maps JavaScript API with the browser key and the `maps` and `marker` libraries.

Requirements:

- Use `google.maps.marker.AdvancedMarkerElement`. **Do not use `google.maps.Marker`** — it
  was deprecated in February 2024. Any example using it is out of date.
- Pass the configured **Map ID** when constructing the map. Advanced Markers do not work
  without one.
- Set `gestureHandling: "cooperative"` so scrolling the page past a map does not trap the
  scroll inside it.
- Frame the map by extending a `LatLngBounds` over every marker and calling `fitBounds`
  with padding. **Special-case a single marker** — the bounds of one point are degenerate;
  centre on it and set an explicit zoom of about 15.
- Give each marker an info window showing its title, its note when present, and a link to
  its Google Maps URL that opens in a new tab.
- Build info window content with DOM nodes and `textContent`. **Never** concatenate titles
  or notes into an HTML string — they originate from a CSV and would be an injection vector.
- Render each map into its own container element. Keep the map instances keyed by container
  so they can be discarded when their container is removed.

### API key restrictions

The browser key is public by nature. In the Google Cloud console restrict it to HTTP
referrers matching the site's domain, and restrict it to the Maps JavaScript API alone. It
must not be able to call the Places API.

### Done when

`GET /api/city/{name}` returns correctly shaped payloads (verified directly, e.g. via
`curl`/tests) and `renderMapPayload` places pins correctly, frames both a compact and a
widely spread city, does not zoom to maximum for a single spot, and opens working info
windows — verified live once wired into the Step 9 chat page.

---

# Step 7 — LLM client and tool definition

**Goal:** a thin wrapper over the LLM API that can be stubbed in tests.

**Files:** `app/llm.py`

### Tool

Define exactly one tool for the saved-spots map. (Step 13 adds a second, independent
`get_city_context` tool for diary retrieval — it does not touch this one.)

- **Name:** `show_city_map`
- **Description:** state that calling it shows the visitor a map of the owner's saved spots
  in a city, optionally filtered to one or more categories, and returns the list of those
  spots (title, category, note) for the model to describe. State the trigger condition
  explicitly: call it once the visitor has said which categories they want, or that they
  want everything — not the instant a city is merely mentioned. Omitting `categories`
  entirely means show every category.
- **Parameters:**
  - `city` (required string) — **constrained by an `enum` generated from the database at
    application startup**. Constraining the argument to the exact set of existing cities
    removes the possibility of the model naming a city that does not exist.
  - `categories` (optional array of strings) — each item **constrained by an `enum`
    generated from every distinct category name in the database**. Omitted means "every
    category in this city."
  - `search_query` (optional string, no enum) — a keyword to search saved spot titles and
    notes with, as an *alternative* to `categories`, for requests that don't obviously map
    to a known category (e.g. "sauna"). When set, `categories` is ignored and the tool
    returns matching spots' titles/categories/notes with **no map** — searching is a
    verification step, not a map-rendering one. **Deliberately not a second tool:** a
    second tool definition would duplicate the full city `enum` a second time in every
    request's tool schema, and there's no prompt caching set up, so that would cost real
    tokens on every single request. One extra optional parameter on the existing tool avoids
    that duplication entirely.

### System prompt

Establish the persona: a travel consultant discussing one specific person's saved places,
organised by city and, within each city, by category. Include a full city→category
breakdown (name and spot count per category, per city — built from `get_all_city_categories`
in one query, not one query per city) so the model can name real categories when asking.
Instruct the model explicitly to:

- Ask which categories the visitor wants (or whether they want everything) before calling
  the tool, unless they already named categories in their message.
- Call the tool again for a new city or a new category selection later in the same
  conversation — a map shown earlier does not carry over.
- **Use judgment about when a map actually helps** — don't call the tool for a general travel
  question that isn't really about browsing saved spots, and don't reflexively attach a map
  to every reply just because a city was mentioned in passing.
- When showing "everything" for a city with many saved spots, narrate only a handful in the
  reply (not every single one), grounded in each spot's real note, and mention there's more
  to explore on the map.
- When you introduce or discuss a spot, use its saved note as context but don't limit
  yourself to it — draw on general knowledge too (cuisine, atmosphere, practical tips), the
  same depth as answering directly with no saved-spots context at all. Never deflect to "go
  look it up yourself."
- **When a request doesn't obviously match a known category, don't guess** — call the tool
  with `search_query` set and answer from the real result, not a speculative "it might be
  under X" list.
- **When a visitor asks about a city with no saved spots at all**, give a genuine, complete
  recommendation from general knowledge, with the same depth as if there were no saved-spots
  context — not a short teaser. Mention there's nothing saved for that city, and what else
  is saved, only as a brief aside, not the focus of the reply.

Keep the prompt stable across requests (rebuilt fresh each request from the same
unchanging-at-runtime data, so it's byte-identical between requests) so it remains cacheable.

### Client

Expose a small interface — send messages with tools, return either a tool call or text —
so `app/chat.py` depends on this interface and tests can substitute a stub. Do not build a
provider-agnostic abstraction layer; one provider, one thin wrapper.

---

# Step 8 — Chat orchestration

**Goal:** the feature. Turn a visitor's message into prose plus, when the model decides,
a map.

**Files:** `app/chat.py`, `tests/test_chat.py`

### Sequence

1. Receive the visitor's message and recent conversation history.
2. Send it to the LLM with the system prompt and the tool.
3. If the model does **not** call the tool, return its text with no map. This is correct
   for general travel questions, and for any request the model judges a map wouldn't help.
4. If the model calls `show_city_map(city=..., search_query=...)` (i.e. `search_query` is
   set): run `search_city_spots` for that city and query. **Return the result as a
   text-only tool result — no map.** Searching is a verification step, not a
   map-rendering one; if the visitor then wants to see the results, that's a normal
   follow-up call in the next turn with `categories` set.
5. Otherwise, if the model calls `show_city_map(city=..., categories=[...])`: run
   `get_city_spots_by_categories` for that city and those categories if `categories` was
   given, or `get_city_spots` (every category) if it was omitted.
6. **Retain those rows in the handler.**
7. Return the tool result to the model containing **only** title, note, and category.
   **Strip the coordinates.** The model does not need them, they cost tokens on every
   request, and withholding them removes any path by which a coordinate could originate
   from the model. This applies to both the search path and the map path.
8. Let the model write its prose from the titles and notes.
9. Respond with:

```json
{
  "text": "<the model's prose>",
  "map":  { "city": "...", "markers": [ ... ] }
}
```

The `map` object is built from the rows retained at step 6 — **never** parsed out of the
model's text. Omit `map` entirely when no tool call occurred, **or** when the tool call used
`search_query`.

### Conversation history

Keep history in the browser session and send it with each request. The server stores
nothing. Cap the history at roughly the last six turns.

### Acceptance tests

Use a stub LLM client throughout — no test may make a network call.

- A stubbed reply with no tool call produces text and no map.
- A stubbed tool call with no `categories` produces both text and a map covering every
  category in the requested city.
- A stubbed tool call with one category filters the map to just that category; with
  multiple categories, the map combines spots from all of them.
- The map's markers match what the corresponding query function returns for that
  city/category selection.
- A tool call with `search_query` set produces text only, **no `map` key at all** — not an
  empty map, the key is absent entirely — and the tool result sent back to the model
  contains the matching spots' title/category/note. `categories`, if also present, is
  ignored when `search_query` is set.
- **The tool result sent back to the model contains no latitude or longitude, for both the
  map path and the search path.** Assert this explicitly; it is the safety property the
  whole design rests on.
- A tool call for a city with no spots produces an empty marker array, not an error.
- History longer than the cap is truncated before being sent.

---

# Step 9 — Chat endpoint and frontend wiring

**Goal:** the chat works end to end in the browser.

**Files:** `app/main.py`, `app/templates/index.html`, `app/static/app.js`

- `POST /api/chat` accepts the message and history, returns the Step 8 response.
- The page appends the visitor's message, then the reply.
- When the reply includes a `map`, append a map container beneath the text bubble and
  render it with the Step 6 code. Reuse that function; do not write a second renderer.
- Show a pending indicator while the request is in flight, and a readable error message on
  failure.

### Page

The entire page is a single AI chat interface — no sidebar, no separate map-browsing view.
One centered column: a light header, a scrollable chat log, and a message input pinned to
the bottom. Styled like a general-purpose LLM chat UI (e.g. Claude.ai): user messages as
right-aligned bubbles, assistant replies as plain left-aligned text with no bubble chrome.

On first load, before any message is sent, show a brief greeting plus one clickable
suggestion chip per saved city (e.g. "What's good in Zurich?"), built from the real city
list. Clicking a chip fills and sends that question through the same flow as typing it.

When a reply includes a `map`, append a map container beneath that reply's text and render
it with the shared `renderMapPayload` function — the same code used everywhere maps are
drawn. Do not write a second renderer. Because each reply's map is appended as a new
element in the growing chat log, earlier maps stay visible in the scrollback as the
conversation continues — asking a follow-up question does not remove or replace a previous
city's map.

### Done when

Asking about a city returns prose with a correct map beneath it, and asking a general
travel question returns prose alone. A second city question later in the same conversation
shows its own map beneath the new reply while the first city's map remains visible above it
in the scrollback.

---

# Step 10 — Streaming

**Goal:** the reply appears as it is written rather than after a pause.

**Files:** `app/main.py`, `app/chat.py`, `app/static/app.js`

- Add `GET /api/chat/stream` as a Server-Sent Events endpoint.
- Stream text deltas as they arrive from the model.
- After the text completes, send **one final event carrying the map payload**.
- The client appends text incrementally, then renders the map on the final event.

A tool round-trip takes several seconds; without streaming the interface reads as broken.

---

# Step 11 — Rate limiting and spend caps

**Goal:** an open chat box cannot generate an unbounded bill. There are no accounts, so
limits are applied by IP and globally.

**Files:** `app/limits.py`, `app/main.py`

### In-application limits

- **Per IP:** `RATE_LIMIT_PER_HOUR` messages per hour.
- **Site-wide:** `DAILY_MESSAGE_CAP` messages per calendar day. This is the real ceiling,
  because it holds regardless of how many addresses appear.
- Apply both to the chat endpoints only. City browsing and map rendering must keep working
  when a cap is reached — they never needed the LLM.
- When a cap trips, return a friendly message inviting the visitor to browse the maps.

### External limits — configure these outside the code

Record these in the README as required deployment steps:

- A hard monthly spend limit in the LLM provider's billing console.
- In Google Cloud, a billing budget **and** per-API **quota limits** on the Maps JavaScript
  API. A budget alert only sends an email; it does not stop spending. Only a quota limit
  actually caps usage. Both are needed.

### Acceptance tests

- The per-IP limit rejects the request after the threshold and resets after the window.
- The global cap rejects requests once reached.
- City and map endpoints still succeed while the chat endpoint is capped.

---

# Step 12 — Packaging and deployment

**Goal:** one command builds a runnable image; one command deploys it.

**Files:** `Dockerfile`, `Caddyfile`, `README.md`

### Image

- Python slim base, install `requirements.txt`, copy `app/`, run Uvicorn.
- **The database file is built before the image and copied into it.** The import script
  runs on the owner's machine; the image ships a read-only database. There is no volume, no
  migration at deploy time, and no runtime write path.
- Do not copy `Saved/`, `.env`, or `tests/` into the image.
- Redeploying is rebuilding the image; rolling back is deploying the previous one.

### Reverse proxy

A Caddyfile that terminates TLS automatically for the domain and proxies to the application
port. Keep it minimal.

### README

Document: environment variables and where each key comes from; the two distinct Google API
keys and their restrictions; how to run the import; how to build and run the image; and the
external spend-limit steps from Step 11.

### Done when

The image builds, runs locally with a populated database, and serves the site over HTTPS
behind Caddy on the target host.

---

# Step 13 — Story RAG (semantic diary retrieval)

**Goal:** let the model draw on the owner's personal travel diary entries
(`stories.json`) for authentic, first-person detail when discussing a specific city —
genuine RAG, since the corpus (275+ entries) is real retrieval material, not something
small enough to always sit in the prompt like the saved spots are.

**Files:** `app/db.py`, `app/rag.py`, `app/llm.py`, `app/chat.py`, `app/main.py`,
`app/config.py`, `scripts/import_stories.py`, `scripts/build_story_index.py`

### Storage

`city_stories(id, city_id NULLABLE, story)` — one row per diary entry, FK to `cities.id`
(cascade delete). `city_id` is nullable: `stories.json`'s `"_unmatched"` bucket (entries
never tied to one city) is imported with `city_id = NULL` and still fully searchable —
excluding it structurally would throw away real content just because it wasn't tagged.

`scripts/import_stories.py` reads `stories.json`, matches each real city key against
`cities.name` (exact match — no alias table needed, verified against the real data), skips
and reports any key with no matching city, and replaces the full contents of
`city_stories` on every run (idempotent).

### Embedding and index

`app/rag.py` defines an `Embedder` protocol (mirrors the `Client`/`Geocoder` pattern
elsewhere) so tests never load a real model. `SentenceTransformerEmbedder` is the real
implementation — a local model (`all-MiniLM-L6-v2`), loaded lazily on first use, no API
key, no network dependency at request time. `build_index` embeds every `city_stories` row
and returns a FAISS `IndexIDMap2` over an `IndexFlatIP`, keyed directly by
`city_stories.id` — no separate id-mapping file needed. `save_index`/`load_index`
persist it to a single file (`stories.faiss`, git-ignored, rebuilt from `city_stories` via
`scripts/build_story_index.py`, analogous to how `travel.db` is a build artifact).

### Tool

A second, independent tool — deliberately **not** folded into `show_city_map`'s result
and **not** given a `city` enum:

- **Name:** `get_city_context`
- **Parameters:** `query` (required string, free text, no enum — the corpus is searched
  semantically, not by exact city-name filter, so `_unmatched` entries can still surface
  when they're genuinely relevant to the query).
- **Description:** states explicitly that it is independent of `show_city_map` — never
  returns or implies a map, doesn't require the city to have saved spots, and doesn't
  require calling `show_city_map` at all.

System prompt instruction: when discussing a specific city, call `get_city_context` with a
natural-language query and weave any genuinely relevant excerpts' authentic voice and
detail into the reply — using judgment, not on every message, and never forcing in a
result that isn't actually relevant.

### Orchestration

`app/chat.py`'s `handle_message`/`stream_message` take `tools: list[dict]` (both tool
definitions) plus `story_index`/`embedder`. `_resolve_tool_call` now dispatches on
`tool_call.name`: `get_city_context` runs `app.rag.search` and returns
`[{"story": ..., "city": ...}]` as a **text-only** result (`city` is `null` for
`_unmatched` matches) — same "no map" contract as the `search_query` path on the other
tool. A missing/unbuilt index (`story_index=None`) degrades to an empty result, not an
error — the app must still run before the index has ever been built.

### Acceptance tests

Use a fake `Embedder` throughout (fixed toy vectors) — no test loads the real model or
touches the network.

- `build_index` returns `None` for an empty `city_stories` table.
- `search` returns the nearest story by vector similarity, with `city` populated for a
  tagged story and `None` for an `_unmatched` one.
- `search` against `story_index=None` returns `[]`, not an error.
- `save_index`/`load_index` round-trip correctly.
- A `get_city_context` tool call produces a text-only result — no `map` key — for both
  `handle_message` and `stream_message`.
- `scripts/import_stories.py` tags real city keys correctly, tags `"_unmatched"` with
  `city_id = NULL`, reports (not aborts on) unknown city keys, and is idempotent.

---

# Step 14 — Country-level requests

**Goal:** fix a real bug — a country-level request ("everything in France") had no valid
path: `city` is a hard `enum` (correctly preventing "France" as a `city` value), so the
model had nowhere to put the request, and a resulting empty-marker map left the frontend
showing an unstyled whole-world view at `{lat: 0, lng: 0}, zoom: 2` (`getOrCreateMapEntry`'s
default, never overwritten when `frameMap` gets zero markers to fit bounds around).

**Files:** `app/db.py`, `app/queries.py`, `app/maps.py`, `app/llm.py`, `app/chat.py`,
`app/main.py`, `app/static/app.js`, `scripts/assign_countries.py`

### Schema and data

`cities.country` (nullable `TEXT`, indexed). Existing databases are migrated in Python
(`PRAGMA table_info` check + `ALTER TABLE ... ADD COLUMN`) since SQLite has no
`ADD COLUMN IF NOT EXISTS`. Populated by a **hand-curated** mapping in
`scripts/assign_countries.py`, not inferred — the real city names include typo'd
duplicates (`"Milan"`/`"Milano"`, `"Talinn"`/`"Tallin"`) and country names used as city
buckets (`"Lebanon"`, `"Cuba"`), which automated geocoding would only get partially
right. Compare names with Unicode NFC normalization (`unicodedata.normalize`), not raw
string equality — the real data has visually-identical accented names stored in different
composed/decomposed forms. Skip-and-report unmapped city names, same pattern as every
other import script; safe to re-run.

### Query layer and map payload

`get_country_spots`/`get_country_spots_by_categories` join `spots` through `cities` on
`country`, combining every city's spots into one result, each row carrying `cities.name AS
city` so the source city survives into both the map markers and the tool result text
(needed since a country payload spans multiple cities — the model needs to know which
spot is in which city to describe them well). `build_map_payload` includes a per-marker
`city` field whenever the underlying row has one (a single-city call's rows don't, so its
marker shape — and every existing test asserting it — is unchanged).

### Tool and system prompt

`show_city_map` gains `country` (optional, `enum` of distinct countries) alongside `city`
(now optional too, since exactly one of them is set per call, never both). `categories`
applies to either. `search_query` remains `city`-only — country-wide free-text search
isn't in scope here. System prompt instructs: a country-level request sets `country`, never
a guessed single city standing in for the whole country, and never one tool call per city
to fake a country view.

### Frontend

`getOrCreateMapEntry`'s empty-marker fallback was the proximate bug: creating a map (at its
uninitialized default center/zoom) for a payload with zero markers. Fixed at the call site
in `app.js` — a `map` payload with an empty `markers` array is now treated exactly like no
map at all (never rendered), regardless of why it came back empty. This is a real
independent hardening, not just a side effect of adding `country`.

### Acceptance tests

- `assign_countries.run_assign` sets `country` for every mapped name, reports unmapped
  ones, matches accented names regardless of NFC/NFD normalization, and is idempotent.
- `get_country_spots`/`_by_categories` combine every city in a country and never leak a
  different country's spots.
- A `country` tool call produces a map payload labeled with the country, markers tagged
  with their source city, and a tool-result text that likewise carries `city` per spot —
  still zero coordinates.
- `build_tool_definition`'s schema has no `required` list (neither `city` nor `country`
  is unconditionally required) and states the two are mutually exclusive.

---

# Step 15 — Single-spot map and proximity ("near X") filtering

**Goal:** fix two real gaps a live user hit — asking for one specific saved spot by name,
or for saved spots near a landmark, both fell back to "I can't filter to just that," even
though the underlying data supported it.

**Files:** `app/geo.py`, `app/queries.py`, `app/chat.py`, `app/llm.py`

### Single-spot map (search_query now renders)

`search_query` was built as a "does this exist" verification step and deliberately never
returned a map — a reasonable original scope, but it meant "show me just Pralus" had no
path to a map even though the exact spot was found. Fix: `search_city_spots`
(`app/queries.py`) now also selects `lat`, `lng`, `maps_url` (matching the shape of
`get_city_spots`), and `_resolve_tool_call` (`app/chat.py`) builds a map from the match(es)
whenever `search_query` finds at least one — `map_payload = build_map_payload(city, spots)
if spots else None`. A miss still omits the map entirely, unchanged. The coordinate-
stripping safety property does **not** weaken: it was never about what a query fetches, it's
enforced at `_tool_result_content`, which explicitly picks `title`/`note`/`category`/`city`
regardless of what extra columns a row happens to carry — verified by
`test_tool_result_sent_to_model_contains_no_lat_or_lng` and its search-query equivalents.

### Proximity filtering (near_lat/near_lng/radius_km)

No part of the schema filtered by distance from a point — every request was "everything in
this city/country," optionally by category. A "near the Eiffel Tower" request has no
landmark coordinates stored anywhere to filter against. Two ways to get one without an
import-time-only geocoding call at request time (ruled out — see the Stack section's "No
geocoding call is made at request time" rule): a hand-curated landmark list (doesn't scale
to arbitrary places), or letting the model supply an approximate coordinate itself from its
own general knowledge. Chose the latter, as a **narrow, explicit exception** to "the LLM
never emits coordinates" — bounded specifically to filtering, never to plotting:

- `app/geo.py`: `haversine_km(lat1, lng1, lat2, lng2)` (great-circle distance in km, pure
  function, no dependencies) and `filter_within_radius(spots, lat, lng, radius_km)`.
- `show_city_map` gains three optional parameters: `near_lat`, `near_lng` (plain numbers,
  no enum — the model fills these from memory of the named landmark), and `radius_km`
  (defaults to ~1.5 km, comfortable walking distance, if omitted).
- `_resolve_tool_call` applies `filter_within_radius` as a final post-filter step, after
  whichever branch (city, country, categories, or search_query) produced the initial spot
  list — so `near_lat`/`near_lng` composes with everything else already in the tool
  (e.g. "cafes in Paris near the Louvre" = `city` + `categories` + `near_lat`/`near_lng`).
- **The exception is bounded**: `near_lat`/`near_lng` only ever decide which *already-saved*
  spots pass the filter. Every marker's actual plotted position still comes only from that
  spot's own database row — a wrong landmark guess narrows or misses results, it can never
  place a marker at a hallucinated location. System prompt and tool description both state
  this explicitly.

### Acceptance tests

- `haversine_km`/`filter_within_radius` (`tests/test_geo.py`): correct for identical points
  and a known real-world distance; filters correctly; empty input/no-match returns `[]`.
- A `near_lat`/`near_lng` tool call filters city and country spots correctly, respects an
  explicit `radius_km` and the ~1.5 km default, and composes with `categories` and with
  `search_query` (including a match that's outside the radius producing no map at all).
- `search_city_spots` now carries `lat`/`lng` for map rendering, while the tool result text
  sent to the model still contains zero coordinates — both properties tested explicitly.

---

## Verification checklist

Confirm each before considering the project complete.

- [ ] The import script is the only code that writes to the database.
- [ ] The web application opens the database read-only.
- [ ] No CSV is parsed at request time.
- [ ] No geocoding call is made at request time.
- [ ] `get_city_spots` is one query; there is no N+1 anywhere.
- [ ] The tool result sent to the model contains no coordinates.
- [ ] Every marker coordinate originates from the database, never from the model. (The
      model-supplied `near_lat`/`near_lng` on `show_city_map` is the one place it provides
      coordinates — verify it is used only to filter which saved spots pass, never to plot
      a marker's own position.)
- [ ] `google.maps.Marker` appears nowhere; Advanced Markers are used with a Map ID.
- [ ] Info window content is built from DOM nodes, never concatenated HTML.
- [ ] The browser key is referrer-restricted and cannot call the Places API.
- [ ] The Places key exists only in the import script's environment.
- [ ] Chat endpoints are rate limited per IP and capped globally.
- [ ] The site remains browsable when the chat cap is reached.
- [ ] `get_city_context` never returns or implies a map, and works for cities with no
      saved spots at all.
- [ ] `stories.json` and `stories.faiss` are git-ignored, never committed.
- [ ] A country-level request never produces an empty-marker map falling back to the
      whole-world default view — the frontend treats zero markers as no map at all.
- [ ] The full test suite passes with no network access.

# Travel Agent

A personal travel-spots site. Visitors chat with an AI travel consultant that can show a
Google Map of the owner's saved spots for a city. Full design spec: `BUILD_INSTRUCTIONS.md`.

Two structural rules the whole app is built around:

- The LLM never emits coordinates — the app builds the map from its own database query.
- The data never changes at runtime — only the offline import script (run on the owner's
  machine) ever writes to the database.

## Environment variables

Copy `.env.example` to `.env` and fill in real values.

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_PATH` | No (default `travel.db`) | Path to the SQLite database the web app reads. |
| `GOOGLE_MAPS_BROWSER_KEY` | Yes | See "Google API keys" below. |
| `GOOGLE_MAPS_MAP_ID` | Yes | From Google Cloud Console → Map Management. Required for Advanced Markers. |
| `LLM_API_KEY` | Yes | Anthropic API key. |
| `LLM_MODEL` | Yes | e.g. `claude-sonnet-4-5`. |
| `RATE_LIMIT_PER_HOUR` | No (default `10`) | Per-IP chat message cap, per hour. |
| `DAILY_MESSAGE_CAP` | No (default `300`) | Site-wide chat message cap, per calendar day — the real ceiling, since it holds regardless of how many IPs appear. |
| `GOOGLE_PLACES_API_KEY` | Only for the offline scripts | Never loaded by the web app — see below. |
| `LANGSMITH_API_KEY` | No | Enables LangSmith tracing when set — see "Observability" below. |
| `LANGSMITH_PROJECT` | No (default `travel-agent`) | LangSmith project name traces are grouped under. Only meaningful if `LANGSMITH_API_KEY` is set. |

## Google API keys

This project uses **two separate Google API keys** for two separate purposes. Do not mix
them up — each must be restricted to only its own API.

- **`GOOGLE_MAPS_BROWSER_KEY`** — sent to visitors' browsers to load the Maps JavaScript
  API. It's public by nature. In the Google Cloud Console, restrict it:
  - **Application restrictions** → Websites → your production domain (and `localhost` for
    local dev).
  - **API restrictions** → Maps JavaScript API only. It must not be able to call the Places
    API.
- **`GOOGLE_PLACES_API_KEY`** — used only by the offline scripts (`import_saved_places.py`
  for geocoding, `enrich_places.py` for ratings/contact info/photos), which run on your own
  machine, never on the server, and is never loaded by the web app (it isn't even a field
  on `app.config.Settings`). Restrict it to the Places API only.

Also set an API **quota limit** (not just a billing alert — see "Spend limits" below) on the
Maps JavaScript API, since the browser key is necessarily public.

## Observability (optional)

Setting `LANGSMITH_API_KEY` turns on [LangSmith](https://smith.langchain.com) tracing for
every chat turn — no other configuration needed, and no LangChain dependency is added
anywhere in the app. With it set:

- Each visitor message produces one connected trace: the turn (`handle_message` /
  `stream_message`) → the underlying model calls → each tool call (`resolve_tool_call`) →
  RAG retrieval (`rag_search`, when `get_city_context` fires) → the final answer. Token
  counts and latency are recorded per step.
- Traces are grouped under `LANGSMITH_PROJECT` (defaults to `travel-agent`).

Leave `LANGSMITH_API_KEY` unset for no tracing at all — the app behaves identically either
way, and nothing else needs to change.

**Privacy note:** tracing sends prompt/response content to LangSmith's cloud, including the
system prompt's full saved-city inventory and any diary excerpts retrieved via RAG. Treat
`LANGSMITH_API_KEY` with the same care as the other keys in this table, and only enable
tracing in environments where sending that content off-server is acceptable.

## Running the import

The database is built offline, on your machine, from a Google Maps "Saved lists" export —
one CSV per city+category (e.g. `Saved/Paris Restaurants.csv`), placed in `Saved/`:

```
python scripts/import_saved_places.py --saved-dir Saved --db travel.db
```

`--saved-dir` defaults to `Saved`, `--db` defaults to `travel.db`. Requires
`GOOGLE_PLACES_API_KEY` in your environment, used to geocode each new spot via the Places
API (New) Text Search — one call per spot not already resolved. Unresolvable spots (no
Places match) are skipped and reported at the end, not aborted. Exit codes: `0` success
(even with some spots skipped), `1` a structurally malformed CSV, `2`
`GOOGLE_PLACES_API_KEY` not set.

Re-running the import against updated CSVs is idempotent — it upserts by (city, category,
feature ID), issues zero geocoding calls for spots already resolved, updates changed
titles/notes without a geocoding call, and removes spots no longer present in a CSV.
Files that don't follow the `{City} {Category}.csv` naming convention (generic lists like
"Want to go", "Just Ok") are skipped entirely.

## Post-import scripts

Both run offline, are safe to re-run, and report (not abort on) rows they can't handle.

```
python scripts/assign_countries.py --db travel.db
python scripts/enrich_places.py --db travel.db --photos-dir app/static/spot_photos
```

- **`assign_countries.py`** fills `cities.country` from a hand-curated name→country map
  (the raw data has typo'd duplicates and country-as-city buckets, so it isn't
  auto-inferable). Needed for country-level requests. No API key required.
- **`enrich_places.py`** adds a rating, phone, website, and one photo per spot via the
  Places API (New) Place Details, keyed off each spot's `place_id`. Photos are downloaded
  once into `--photos-dir` and served by the app itself. Requires `GOOGLE_PLACES_API_KEY`;
  spots already enriched are skipped, so re-runs only spend money on new spots.

## Personal diary RAG (get_city_context)

The chat's `get_city_context` tool draws on personal travel diary entries (`stories.json`,
git-ignored — not part of this repo) via a local FAISS index. Build it after the main
import:

```
.venv/bin/python scripts/import_stories.py --stories stories.json --db travel.db
.venv/bin/python scripts/build_story_index.py --db travel.db --index stories.faiss
```

Both are optional for local development — if `stories.faiss` doesn't exist, the app runs
fine and that tool just returns no results. Re-run both any time `stories.json` changes.
**`docker build` does require `stories.faiss` to exist** (see "Building and running the
image" below), the same way it requires `travel.db`.

## Local development

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in real values
.venv/bin/python scripts/import_saved_places.py   # builds travel.db from Saved/
.venv/bin/python scripts/assign_countries.py      # fills cities.country
.venv/bin/python scripts/enrich_places.py         # optional — ratings, contact info, photos
.venv/bin/python scripts/import_stories.py        # optional — see "Personal diary RAG" below
.venv/bin/python scripts/build_story_index.py     # optional
.venv/bin/uvicorn app.main:app --reload
```

Run the test suite (all tests run offline — no network calls, no real API keys needed).
Run it as a module from the repo root so `app` is importable:

```
.venv/bin/python -m pytest
```

## Building and running the image

The database file and story index are built **before** the image and copied into it — the
import scripts run on your machine, and the image ships read-only. There's no volume, no
migration step, and no runtime write path. Redeploying means rebuilding the image; rolling
back means deploying the previous one.

```
# 1. Build travel.db and stories.faiss locally first (see sections above)
docker build -t travel-agent .

# 2. Run it, passing real config as environment variables (never baked into the image)
docker run -d --name travel-agent -p 8000:8000 --env-file .env travel-agent
```

Verify locally: `curl http://localhost:8000/` should return the chat page.

## Deploying behind Caddy

`Caddyfile` is a minimal reverse proxy that terminates TLS automatically for your domain:

```
your-domain.com {
    reverse_proxy localhost:8000
}
```

On the VPS: replace `your-domain.com` with your real domain, run the container as above
(publishing to `localhost:8000`), install and run Caddy with that Caddyfile. Caddy handles
certificate issuance and renewal automatically.

## Spend limits (do this before going live)

Nothing in the code can bound spend on its own — these external steps are required:

- **LLM provider:** set a hard monthly spend limit in the Anthropic console billing
  settings.
- **Google Cloud:** set **both** of these — a budget alert only sends an email, it does not
  stop spending; only a quota limit actually caps usage:
  - A billing budget (for visibility/alerts).
  - A **quota limit** ("Requests per day") on the Maps JavaScript API, under
    APIs & Services → Enabled APIs → Maps JavaScript API → Quotas & System Limits.

The app's own `RATE_LIMIT_PER_HOUR` / `DAILY_MESSAGE_CAP` env vars bound *chat* volume, but
they're a second layer, not a replacement for the provider-side caps above.

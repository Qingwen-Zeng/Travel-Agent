# 09 — The offline data pipeline

The website only ever *reads* `travel.db` and `stories.faiss`. This chapter is
about the programs that *build* those files: five scripts in `scripts/`, run by
hand on the owner's laptop, never on the server. They are where the Google Places
API is called, where CSV exports become tables, and where the RAG index is
constructed. They also demonstrate the **dependency-injection** pattern that keeps
the entire test suite offline.

---

## 1. Why the data is frozen at build time (chapter 00, Rule 2 — the "how")

The alternative to "build offline" would be: the server geocodes places on demand,
accepts uploads, has an admin UI. Every one of those adds a write path, which adds
permissions, validation, concurrency, backups, and a much bigger attack surface.

Instead:

1. On a laptop, you run the scripts. They read source files (`Saved/*.csv`,
   `stories.json`), call Google's API where needed, and write `travel.db` +
   `stories.faiss`.
2. Those two files are copied into the Docker image at build time (chapter `12`).
3. The running server opens `travel.db` **read-only** and never touches
   `stories.faiss` except to read it once at startup.
4. To change the data: re-run the scripts on your laptop, rebuild, redeploy.

"Deploy a data update" and "deploy a code update" are the same operation.

## 2. The shape every script shares

All five scripts follow the same template:

- A module docstring stating the purpose and a `Usage:` line.
- `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` so
  `import app.db` works when you run the file from the repo root.
- They import a connection helper from `app.db`: `get_writable_connection` for the
  four that write, `get_readonly_connection` for `build_story_index.py`.
- `def main(argv=None) -> int:` parses arguments with `argparse` and returns an
  **exit code**.
- `if __name__ == "__main__": sys.exit(main())` (chapter `01` §1.20).
- The ones that write wrap everything in one transaction:
  `try: ...; conn.commit() except Exception: conn.rollback(); raise finally: conn.close()`.
  Either the whole run's changes land, or none of them do.
- **Skip-and-report, never abort on one bad record.** An individual place that
  will not geocode, a story tagged to an unknown city — these are collected into a
  summary and printed at the end. Only a *structurally* broken input (a CSV
  missing its header) is fatal.
- **Idempotent.** Running a script twice on the same input produces the same
  result — no duplicates, no wasted API calls.

## 3. `import_saved_places.py` — CSV export → `cities` / `categories` / `spots`

The biggest script. It turns Joey's Google Maps "Saved lists" export into the core
tables.

```
python scripts/import_saved_places.py [--saved-dir Saved] [--db travel.db]
```

### The input

`Saved/` holds one CSV per saved list, named `{City} {Category}.csv`, e.g.
`Paris Restaurants.csv`, `Bangkok Bars and Clubs.csv`. Each CSV has a header row
with at least `Title` and `URL` columns, then one row per saved place.

The script derives `(city, category)` from the **filename**:

- Files whose name is a generic list ("Want to go", "Just Ok", "Favorite
  places", …) are skipped entirely.
- A trailing `(1)` — from re-exporting the same list — is stripped, so
  `Chicago Restaurants(1).csv` parses as `Chicago Restaurants`.
- The category is matched from a hand-maintained list of ~40 known category
  phrases, sorted longest-first so "Bars and Clubs" matches before "Bars".
  Whatever precedes it is the city.
- Categories are then normalised/merged (e.g. `coffee shops`,
  `coffee _ tea shops` → `Coffee And Tea Shops`).
- A file that matches no known pattern is skipped (reported, not an error).

**Merging re-export duplicates matters.** Two files can parse to the same
`(city, category)` (`Chicago Restaurants.csv` + `Chicago Restaurants(1).csv`).
The script groups *all rows across all contributing files* before processing that
pair. A naive one-file-at-a-time pass would make the "delete rows no longer in the
CSV" step wrongly delete rows that only existed in the sibling file — a real bug
the current code exists to avoid.

### Per-row: the feature ID and the geocoding decision

Each row's saved URL contains a Google **feature ID** (a `0x...:0x...` hex pair),
extracted with a regex. It contains **no coordinates** — it is used purely as a
stable dedupe key.

For each row, the script looks for an existing `spots` row by
`(city_id, category_id, feature_id)`:

- **Exists, unchanged** (same title/note/url) → count as "unchanged", **no API
  call**.
- **Exists, changed** → `UPDATE` the title/note/url, **no API call** (editing a
  place in Google Maps costs nothing on re-import).
- **New** → call **Google Places API (New) Text Search** with
  `"{title}, {city}"`, requesting only `places.id,places.location` (a narrow field
  mask keeps the call in the cheaper pricing tier). The response gives a Place ID
  and a lat/lng. `INSERT` a new `spots` row with those coordinates.
- After all rows for a pair: `DELETE` any `spots` rows for that city+category
  whose feature ID was not seen this run — so removing a place from a Google list
  removes it from the site.

Then, for each touched city, it recomputes `center_lat`/`center_lng` (average of
its spots) and `spot_count`.

### Retry, failure, exit codes

Network errors on a geocode retry up to 3 times with a growing back-off; after
that the place joins the "skipped" list (same as a genuine "no match"). The run
still commits, and the summary prints every skipped `(title, city, category)`:

```
travel.db: 1348 added, 1 updated, 0 removed, 1314 already located
2 skipped (no match found):
  "Ilham Gallery" (Dubai / Things To Do)
```

Exit codes: `0` success (even with skips), `1` a structurally malformed CSV
(caught *before* any API call), `2` `GOOGLE_PLACES_API_KEY` not set.

## 4. `assign_countries.py` — fill in `cities.country`

```
python scripts/assign_countries.py [--db travel.db]
```

- No API. Just a hand-curated `CITY_TO_COUNTRY` dict (~110 entries).
- It is hand-curated because the real city names cannot be auto-mapped: there are
  typo'd duplicates (`"Milan"` / `"Milano"`, `"Copenhagen"` / `"Coppenhagen"`) and
  country names used as city buckets (`"Lebanon"`, `"Cuba"`, `"Malta"`).
- Names are compared after Unicode NFC normalisation, so a precomposed `é` and a
  decomposed `e` + accent compare equal.
- For each city, `UPDATE cities SET country = ? WHERE name = ?`. Unmapped cities
  are reported, never fatal.
- Fully idempotent — every run overwrites `country` for every mapped name with the
  same value. Exit code always `0`.

This exists because of chapter `07`'s country-level tool path: without
`cities.country`, "everything in France" has nowhere to look.

## 5. `enrich_places.py` — ratings, contact info, and one photo per spot

```
python scripts/enrich_places.py [--db travel.db] [--photos-dir app/static/spot_photos]
```

Writes the `spot_details` table, using each spot's `place_id` (captured by the
import). Two Google endpoints:

- **Place Details** — `GET .../v1/places/{place_id}` with field mask
  `rating,nationalPhoneNumber,websiteUri,photos`. Deliberately **no review count**
  in the mask — the detail card shows Joey's own note instead. Returns the rating,
  phone, website, and the resource name of the first photo.
- **Photo Media** — `GET .../v1/{photo_name}/media?maxWidthPx=800&key=...` returns
  the raw JPEG bytes.

For each spot without a `spot_details` row: fetch details; if there is a photo,
download it once to `app/static/spot_photos/{spot_id}.jpg` and record the relative
`photo_path`; `INSERT` the `spot_details` row. Same 3-try back-off as the
importer.

**Idempotent by skipping.** `spot_details.spot_id` is the primary key; spots that
already have a row are skipped, so re-running after adding new saved spots only
spends money on the new ones. Exit codes `0` / `2` (no `1` path).

Photos are downloaded **once** and served by the app's own static mount — the
running server never fetches from Google. `app/maps.py` turns
`"spot_photos/42.jpg"` into the URL `/static/spot_photos/42.jpg` (chapter `04`
§8).

(Note: `enrich_places.py` and its table were added after `BUILD_INSTRUCTIONS.md`
was written, which is why that spec does not mention them.)

## 6. `import_stories.py` — diary JSON → `city_stories`

```
python scripts/import_stories.py [--stories stories.json] [--db travel.db]
```

- No API. Reads a local JSON file shaped
  `{ "<City Name>": ["entry", "entry", ...], ..., "_unmatched": [...] }`.
- City keys must match `cities.name` **exactly** — no alias normalisation.
- It `DELETE`s everything from `city_stories` first, then re-inserts. That is what
  makes it idempotent: each run *replaces* the table's contents.
- `"_unmatched"` entries are inserted with `city_id = NULL`.
- A city key with no matching `cities` row is reported and skipped, not fatal.
- Exit code always `0`.

This is the first half of the RAG pipeline; chapter `08` covers the second half
(`build_story_index.py`).

## 7. `build_story_index.py` — `city_stories` → `stories.faiss`

```
python scripts/build_story_index.py [--db travel.db] [--index stories.faiss]
```

The whole file (it is 38 lines):

```python
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(...)
    parser.add_argument("--db", default="travel.db", type=Path)
    parser.add_argument("--index", default="stories.faiss", type=Path)
    args = parser.parse_args(argv)

    conn = get_readonly_connection(args.db)
    index = build_index(conn, SentenceTransformerEmbedder())

    if index is None:
        print("No stories in city_stories — nothing to index.", file=sys.stderr)
        return 1

    save_index(index, args.index)
    print(f"{args.index}: indexed {index.ntotal} stories")
    return 0
```

- It is the one script that opens the database **read-only** — it does not write
  the DB, it writes a separate file.
- It is also the one script that loads a real ML model (the embedder — chapter
  `08`), lazily, on the `build_index` call.
- `build_index` returns `None` (→ exit code `1`) if `city_stories` is empty.
- Otherwise `save_index` writes the single `stories.faiss` file.

Run it after `import_stories.py`, or any time `city_stories` changes.

## 8. The dependency-injection pattern (and why the tests never touch the network)

Look at how `import_saved_places.py` structures its work. The function that does
the importing does **not** create the Google client:

```python
# conceptually:
def run_import(saved_dir, db_path, geocoder):     # geocoder is passed IN
    ...
    result = geocoder.geocode(title, city)        # ...and just used
    ...

def main(argv=None) -> int:
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        return 2
    geocoder = GooglePlacesGeocoder(api_key)       # the REAL client, built here
    return 0 if run_import(args.saved_dir, args.db, geocoder) else 1
```

- `run_import` takes a `geocoder` parameter, typed against a `Protocol`
  (`Geocoder` — anything with a `.geocode(title, city)` method).
- `main()` constructs the real `GooglePlacesGeocoder` from the API key and passes
  it in.
- A **test** calls `run_import(dir, db, FakeGeocoder({...}))` with a hand-written
  fake that returns canned results from a dict and records which calls were made.
  No socket is ever opened.

Every script that touches the network or a model does this:

| Script | Injected dependency (`Protocol`) | Real implementation | Fake in tests |
|--------|----------------------------------|---------------------|---------------|
| `import_saved_places.py` | `Geocoder.geocode(title, city)` | `GooglePlacesGeocoder` | `FakeGeocoder(results dict)` |
| `enrich_places.py` | `DetailsFetcher.fetch(place_id)`, `PhotoDownloader.download(name)` | `GooglePlaceDetailsFetcher`, `GooglePhotoDownloader` | `FakeDetailsFetcher`, `FakePhotoDownloader` |
| `build_story_index.py` / `app/rag.py` | `Embedder.embed(texts)` | `SentenceTransformerEmbedder` | `FakeEmbedder(toy vectors)` |
| `assign_countries.py`, `import_stories.py` | *(none — no network)* | — | tests call `run_*` directly on a temp DB |

The retry logic *inside* the real Google classes is tested separately by injecting
a fake `requests.Session` object that fails twice then succeeds, asserting the
call count is 3.

This is the same idea you saw in `app/llm.py` (`Client` protocol, injectable
`raw_client`), `app/rag.py` (`Embedder` protocol), and `app/limits.py`
(injectable `clock`). **Construct dependencies at the edge (`main()`, app
startup), pass them inward, and tests can substitute fakes anywhere.** It is the
single most repeated design decision in the codebase, and chapter `10` shows what
it buys you.

## 9. The end-to-end build

To go from raw source to a runnable app:

```
.venv/bin/python scripts/import_saved_places.py    # Saved/*.csv  → cities, categories, spots  (needs GOOGLE_PLACES_API_KEY)
.venv/bin/python scripts/assign_countries.py       # → cities.country
.venv/bin/python scripts/enrich_places.py          # → spot_details + app/static/spot_photos/  (needs the key; optional)
.venv/bin/python scripts/import_stories.py         # stories.json → city_stories               (optional)
.venv/bin/python scripts/build_story_index.py      # city_stories → stories.faiss              (optional)
```

The first two are needed for the core app. The last three add enrichment and the
diary RAG; without them the app still runs (no ratings/photos, and
`get_city_context` returns nothing). `docker build`, however, *requires*
`travel.db` and `stories.faiss` to exist (chapter `12`).

---

## Exercises & checkpoints

You need the venv set up (chapter `13`). You do **not** need real Google API keys
for 1–3 — you will read the tests that stand in for them.

1. **Read a fake.** Open `tests/test_import_saved_places.py`. Find `FakeGeocoder`.
   What does its `geocode` method do, and what does it record? How does a test use
   it to assert that a *re-run* of the import issues **zero** new geocoding calls?
2. **Run an offline script for real.** `stories.json` may not be in your checkout,
   but you can still exercise `assign_countries.py`: run
   `.venv/bin/python scripts/assign_countries.py`. What does it print? Run it a
   second time — is the output identical? Which property is that demonstrating?
3. **Idempotency by design.** For each of the five scripts, name the mechanism
   that makes re-running it safe (dedupe key / overwrite / skip-if-present /
   delete-all-then-insert). They are not all the same.
4. **Trace a photo.** `enrich_places.py` writes `photo_path = "spot_photos/7.jpg"`
   into `spot_details`. Follow that string: which query in `app/queries.py`
   selects it, which function in `app/maps.py` transforms it, into what URL, and
   which line of `app/main.py` makes that URL serve a real file?
5. **Why read-only for the index build?** `build_story_index.py` opens the
   database with `get_readonly_connection`, while the other four writers use
   `get_writable_connection`. Why does the index builder not need write access?

Continue to `10-testing.md`.

# 04 — The data layer: SQLite, the schema, and read-only-by-design

This chapter covers where the app's data lives and how it is read: relational
databases in general, **SQLite** specifically, this project's schema table by
table, and the deliberate split between a **writable** connection (used only by
the offline scripts) and a **read-only** one (used by the website). The files are
`app/db.py`, `app/queries.py`, `app/maps.py`, and `app/geo.py`.

Read chapter `01` Part 5 (SQL) first if `SELECT ... JOIN ... WHERE` is unfamiliar.

---

## 1. Why a database (and why a *relational* one)

The data is: ~1,300 saved places, each belonging to a city and a category, some
with a rating/photo, plus a few hundred private diary paragraphs. You could keep
that in JSON files. A database is better here because:

- **Queries.** "All restaurants in Taipei, sorted by name" is one line of SQL and
  runs in microseconds against an index. In JSON you would load everything and
  filter in Python every time.
- **Integrity.** The schema *enforces* that every spot points to a real city
  (foreign keys), that you cannot save the same place twice in one category
  (a unique constraint), and that required fields are never empty.
- **One file.** SQLite's entire database — every table, every row, every index —
  is a single file, `travel.db`. No separate database server to install, run, or
  secure.

A **relational** database organises data into tables with typed columns and links
between them (foreign keys), as opposed to a document store (a pile of JSON blobs)
or a key-value store. The links are exactly what this data has: spot → city, spot
→ category, spot → details, story → city.

## 2. SQLite

SQLite is a relational database that runs *inside* your program as a library,
reading and writing one file. There is no `sqlite` server process. Python has
built-in support via the standard-library `sqlite3` module — no `pip install`
needed.

Trade-offs, all fine for this project:

- One writer at a time (many readers concurrently — see WAL below). This app has
  *zero* runtime writers, so it never matters.
- Not built for many machines sharing one database over a network. This app is
  one process on one machine.
- Ships in the image as a plain file (chapter `12`).

## 3. Opening a connection: `app/db.py`

`app/db.py` is short. It has the schema as a string, a migration helper, and two
connection factories. Here is the whole file's structure.

### The two factories

```python
def get_writable_connection(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    _ensure_cities_country_column(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cities_country ON cities(country)")
    conn.commit()
    return conn


def get_readonly_connection(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn
```

**`get_writable_connection`** — used **only by the offline scripts**
(`scripts/import_*.py`, `scripts/enrich_places.py`, `scripts/build_story_index.py`
opens it read-only actually — see chapter 09; the *writing* scripts use this). It:

- `sqlite3.connect(db_path)` — opens the file read-write, creating it if absent.
- `conn.row_factory = sqlite3.Row` — makes result rows behave like dicts: you can
  write `row["title"]` and `row.keys()` instead of `row[0]`. Every query in the
  codebase relies on this.
- `PRAGMA foreign_keys = ON` — SQLite, for historical reasons, does **not**
  enforce foreign keys unless you turn them on per connection. This turns on the
  `REFERENCES ... ON DELETE CASCADE` behaviour.
- `PRAGMA journal_mode = WAL` — see section 4.
- `conn.executescript(SCHEMA)` — runs every `CREATE TABLE IF NOT EXISTS` /
  `CREATE INDEX IF NOT EXISTS` statement. Safe to run every time; existing tables
  are left alone.
- `_ensure_cities_country_column(conn)` — a hand-written migration (section 6).
- creates one more index, `commit()`s, returns.

**`get_readonly_connection`** — used by **the website** (`app/main.py`'s
`get_db`). It:

- `sqlite3.connect("file:travel.db?mode=ro", uri=True)` — the `file:...?mode=ro`
  URI form opens the database **read-only at the SQLite level**. Any `INSERT`,
  `UPDATE`, `DELETE`, or `ALTER` on this connection raises
  `sqlite3.OperationalError`. This is not a convention or a code review rule — the
  running server is *structurally incapable* of changing the data.
- sets `row_factory` and returns. It runs no `PRAGMA`s and no schema: it assumes
  the file already exists and was already set to WAL mode by a writer.

This is the enforcement of chapter `00`'s **Rule 2**. A bug, a bad input, even an
attacker who somehow controlled a query string, cannot write to `travel.db`
through the website, because the connection physically forbids it.

## 4. WAL mode

`PRAGMA journal_mode = WAL` switches SQLite to **Write-Ahead Logging**. Instead of
writing changes directly into the main database file (and blocking readers while
it does), a writer appends them to a separate `-wal` file, and readers keep
reading the main file undisturbed. You will see two sidecar files next to the
database: `travel.db-wal` and `travel.db-shm`.

WAL mode is a property stored in the database file's header, so once *any* writer
sets it, every later connection — including read-only ones — operates in WAL mode
without having to set it (and the read-only connection could not set it anyway).

For this app the practical benefit is small (there is only ever one writer, on a
laptop, and it is not running at the same time as the website). It is set mostly
because it is the sensible default and because it lets you run an offline import
against a copy of the database while a dev server is reading it.

## 5. The schema, table by table

From `app/db.py`'s `SCHEMA` string.

### `cities`

```sql
CREATE TABLE IF NOT EXISTS cities (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL UNIQUE,
    center_lat REAL,
    center_lng REAL,
    spot_count INTEGER NOT NULL DEFAULT 0,
    country    TEXT
);
```

| Column | Type | Meaning |
|--------|------|---------|
| `id` | `INTEGER PRIMARY KEY` | Auto-numbered unique identifier. Other tables point at this. |
| `name` | `TEXT NOT NULL UNIQUE` | The canonical city name, e.g. `"Taipei"`. The app always looks cities up by name, never by id. `UNIQUE` — no two rows may share a name. |
| `center_lat`, `center_lng` | `REAL` (nullable) | Average position of the city's spots, precomputed by the import script. Optional. |
| `spot_count` | `INTEGER NOT NULL DEFAULT 0` | How many spots the city has. **Denormalised** — it duplicates information you could get with `COUNT(*)`, kept here so the homepage list is one cheap query. The import script keeps it correct. |
| `country` | `TEXT` (nullable) | Filled in by `scripts/assign_countries.py`. Nullable because a city might not be mapped yet. |

### `categories`

```sql
CREATE TABLE IF NOT EXISTS categories (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
```

Just an id and a unique name (`"Restaurants"`, `"Bars And Clubs"`, `"Desserts"`,
…).

### `spots` — the heart of the data

```sql
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
```

| Column | Notes |
|--------|-------|
| `city_id`, `category_id` | **Foreign keys.** Must reference real rows. `ON DELETE CASCADE`: delete a city and its spots vanish automatically. |
| `title` | The place name. `NOT NULL`. |
| `lat`, `lng` | The pin's position. `NOT NULL` — a spot with no coordinates is meaningless. **These come from geocoding at import time and are the *only* source of pin positions** (chapter `00`, Rule 1). |
| `note` | Joey's personal saved note. Nullable. Shown in the reply and the detail card. |
| `place_id` | Google's Place ID, captured at import. Used later by `enrich_places.py` to fetch ratings/photos. Nullable. |
| `ftid` | Google's "feature ID," extracted from the saved URL. A stable identifier used purely for deduplication. `NOT NULL`. |
| `maps_url` | Link to the place on Google Maps. Nullable. |
| `UNIQUE (city_id, category_id, ftid)` | A **composite unique constraint**: the same place can be saved under two categories, but not twice in the same city+category. This is what makes re-running the import idempotent. |

Plus two indexes so joins and filters on those foreign keys are fast:

```sql
CREATE INDEX IF NOT EXISTS idx_spots_city ON spots(city_id);
CREATE INDEX IF NOT EXISTS idx_spots_category ON spots(category_id);
```

### `city_stories` — the RAG corpus

```sql
CREATE TABLE IF NOT EXISTS city_stories (
    id      INTEGER PRIMARY KEY,
    city_id INTEGER REFERENCES cities(id) ON DELETE CASCADE,
    story   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_city_stories_city ON city_stories(city_id);
```

One row per paragraph of Joey's private travel diary. `city_id` is **nullable**
here (unlike in `spots`): some diary entries were never matched to a specific
city, and those are stored with `city_id = NULL`. The `id` column is important —
it is the key the FAISS index stores (chapter `08`).

### `spot_details` — optional enrichment

```sql
CREATE TABLE IF NOT EXISTS spot_details (
    spot_id      INTEGER PRIMARY KEY REFERENCES spots(id) ON DELETE CASCADE,
    rating       REAL,
    review_count INTEGER,
    phone        TEXT,
    website      TEXT,
    photo_path   TEXT
);
```

At most one row per spot (`spot_id` is both the primary key *and* a foreign key —
a 1-to-1 relationship). Written by `scripts/enrich_places.py`. A spot with no
`spot_details` row still works everywhere; the enrichment columns just come back
as `NULL` (which is why the queries use `LEFT JOIN`). `review_count` is stored but
deliberately never shown — the detail card shows Joey's own note instead of review
counts.

## 6. The Python-side migration

`CREATE TABLE IF NOT EXISTS` will not *add a column* to a table that already
exists. So when `country` was added to `cities` after the first version shipped,
databases created earlier needed patching:

```python
def _ensure_cities_country_column(conn: sqlite3.Connection) -> None:
    """Migrates a pre-existing cities table (created before the country column existed)."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(cities)")}
    if "country" not in columns:
        conn.execute("ALTER TABLE cities ADD COLUMN country TEXT")
```

`PRAGMA table_info(cities)` returns one row per column; if `country` is not among
them, `ALTER TABLE ... ADD COLUMN` adds it. This runs inside
`get_writable_connection`, so it happens whenever a script opens the database.
This is a hand-rolled, minimal version of what a "migrations framework" does in
bigger apps; here one function is enough.

## 7. All the reads: `app/queries.py`

Every SQL read the app performs is a function in this one module. Rules the module
follows:

- One function, one `SELECT`. No function runs two queries. (There is a test that
  literally counts the SQL statements a query function issues and asserts it is
  exactly one — see chapter `10`.)
- Every function takes `conn` as its first parameter. It never opens a
  connection. This makes the functions trivial to test against a temporary
  database.
- Every function returns `list[sqlite3.Row]` (or a single value for the small
  `list_*` ones).
- Look-ups are by **name**, resolved with a scalar subquery
  `(SELECT id FROM cities WHERE name = ?)`. Ids never leave this module.
- Values are **always** passed as `?` parameters, never string-formatted
  (chapter `01` §5.4).

### The small list queries

```python
def list_cities(conn):
    return conn.execute("SELECT name, spot_count FROM cities ORDER BY name").fetchall()

def list_countries(conn):
    return conn.execute(
        "SELECT DISTINCT country FROM cities WHERE country IS NOT NULL ORDER BY country;"
    ).fetchall()

def list_categories(conn):
    return conn.execute(
        "SELECT DISTINCT categories.name FROM categories "
        "JOIN spots ON spots.category_id = categories.id ORDER BY categories.name;"
    ).fetchall()
```

`list_categories` joins through `spots`, so it only returns categories that are
actually used. These three feed the tool `enum`s in chapter `07`.

### `get_all_city_categories` — one query for the whole prompt

```python
def get_all_city_categories(conn):
    return conn.execute(
        "SELECT cities.name AS city, categories.name AS category, COUNT(spots.id) AS spot_count\n"
        "  FROM spots\n"
        "  JOIN cities ON cities.id = spots.city_id\n"
        "  JOIN categories ON categories.id = spots.category_id\n"
        " GROUP BY cities.id, categories.id\n"
        " ORDER BY cities.name, spot_count DESC, categories.name;"
    ).fetchall()
```

Three-table join + `GROUP BY` + `COUNT` produces every `(city, category, count)`
triple in one shot. `app/main.py` reshapes this into the "Taipei: Restaurants
(37), Cafes (12)" text embedded in the system prompt. Doing it in one query — not
one query per city — is a deliberate "no N+1" rule.

### `get_city_spots` and friends — the map data

```python
_DETAIL_COLUMNS = (
    "spot_details.rating, spot_details.review_count, spot_details.phone, "
    "spot_details.website, spot_details.photo_path"
)
_DETAIL_JOIN = "LEFT JOIN spot_details ON spot_details.spot_id = spots.id"

def get_city_spots(conn, city_name):
    return conn.execute(
        "SELECT spots.title, spots.lat, spots.lng, spots.note, categories.name AS category, "
        f"spots.maps_url, {_DETAIL_COLUMNS}\n"
        "  FROM spots\n"
        "  JOIN categories ON categories.id = spots.category_id\n"
        f"  {_DETAIL_JOIN}\n"
        " WHERE spots.city_id = (SELECT id FROM cities WHERE name = ?)\n"
        " ORDER BY spots.title;",
        (city_name,),
    ).fetchall()
```

- `_DETAIL_COLUMNS` and `_DETAIL_JOIN` are string fragments spliced into several
  queries so they all pull in the enrichment columns the same way. The `f"..."`
  interpolation here is safe — it inserts *column-name SQL fragments the
  programmer wrote*, never user input. User input is still `?`.
- `LEFT JOIN spot_details` — keep every spot; fill rating/phone/etc. with `NULL`
  if there is no details row.
- `WHERE spots.city_id = (SELECT id FROM cities WHERE name = ?)` — the scalar
  subquery pattern.
- Note the columns selected: `title, lat, lng, note, category, maps_url` + the
  detail columns. `lat` and `lng` are here — but as you will see in chapter `07`,
  they are stripped out before anything goes to the model.

`get_city_spots_by_categories` adds `AND categories.name IN (?,?,...)` with the
placeholder count built dynamically (chapter `01` §5.4).
`get_country_spots` / `get_country_spots_by_categories` join `cities` and filter
`WHERE cities.country = ?`, and also `SELECT cities.name AS city` so a
multi-city map can label which city each pin is in.

### `search_city_spots` — free text

```python
def _escape_like(text):
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

def search_city_spots(conn, city_name, query):
    pattern = f"%{_escape_like(query)}%"
    return conn.execute(
        "... WHERE spots.city_id = (SELECT id FROM cities WHERE name = ?)\n"
        "   AND (spots.title LIKE ? ESCAPE '\\' OR spots.note LIKE ? ESCAPE '\\')\n"
        " ORDER BY spots.title;",
        (city_name, pattern, pattern),
    ).fetchall()
```

Matches the query against titles *and* notes. `_escape_like` neutralises the SQL
`LIKE` wildcards (`%`, `_`) and backslash so a search for "50%" is a literal
search. The `%...%` wrapping means "contains." The value is still a `?` parameter;
only the wildcards around it are added.

## 8. From rows to a map: `app/maps.py`

`build_map_payload` turns query rows into the JSON structure the browser's map
code expects. It is the **only** place pin coordinates are assembled.

```python
_OPTIONAL_DETAIL_FIELDS = ("rating", "phone", "website")

def _photo_url(row):
    if "photo_path" in row.keys() and row["photo_path"]:
        return f"/static/{row['photo_path']}"
    return None

def build_map_payload(label, spots):
    markers = []
    for row in spots:
        marker = {
            "title": row["title"],
            "lat": row["lat"],
            "lng": row["lng"],
            "note": row["note"] or "",
            "category": row["category"],
            "maps_url": row["maps_url"],
        }
        if "city" in row.keys():
            marker["city"] = row["city"]
        for field in _OPTIONAL_DETAIL_FIELDS:
            if field in row.keys() and row[field] is not None:
                marker[field] = row[field]
        photo_url = _photo_url(row)
        if photo_url:
            marker["photo_url"] = photo_url
        markers.append(marker)
    return {"city": label, "markers": markers}
```

- Every marker always has `title`, `lat`, `lng`, `note` (empty string if `NULL`),
  `category`, `maps_url`.
- `if "city" in row.keys()` — country-wide results carry a `city` column; per-city
  results do not. `row.keys()` lets the same function handle both row shapes.
- `rating` / `phone` / `website` are added **only if the row has that column and
  it is not `NULL`**. So a marker for an un-enriched spot simply omits them, and
  the frontend shows a plain badge instead of a rating.
- `photo_path` (e.g. `"spot_photos/42.jpg"`) becomes the URL
  `"/static/spot_photos/42.jpg"` — served by the static mount from chapter `03`.
- The returned key is literally `"city"` even when `label` is a country name; the
  frontend just uses it as the map's heading text.

This payload is what travels to the browser (via the `map` SSE event) and what
`app.js`'s `renderMapPayload` consumes (chapter `05`).

## 9. Distance maths: `app/geo.py`

Two pure functions, no I/O:

```python
def haversine_km(lat1, lng1, lat2, lng2) -> float:
    """Great-circle distance between two lat/lng points, in kilometers."""
    ...
    a = min(1.0, max(0.0, a))  # guard against floating-point drift pushing a fraction past 1
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))

def filter_within_radius(spots, lat, lng, radius_km) -> list:
    return [row for row in spots if haversine_km(lat, lng, row["lat"], row["lng"]) <= radius_km]
```

- `haversine_km` — the standard great-circle formula for distance between two
  points on a sphere. The `min(1.0, max(0.0, a))` clamp exists because tiny
  floating-point errors can push the intermediate value a hair above 1.0, which
  would make `math.asin`/`math.sqrt` raise.
- `filter_within_radius` — a list comprehension keeping only the rows within
  `radius_km` of a centre point.

This backs the "restaurants near the Eiffel Tower" feature. The centre point comes
from the model's `near_lat` / `near_lng` — **the one place the model supplies
coordinates**, and even here they are only used to *filter* this list, never to
place a pin (chapter `07`).

---

## Exercises & checkpoints

App set up locally (chapter `13`); you will use a Python shell.

1. **Explore the real database.** From the repo root, with the venv active:
   `sqlite3 travel.db` (if you have the `sqlite3` CLI) or a Python shell:
   ```python
   import sqlite3
   c = sqlite3.connect("file:travel.db?mode=ro", uri=True)
   c.row_factory = sqlite3.Row
   for r in c.execute("SELECT name, spot_count FROM cities ORDER BY spot_count DESC LIMIT 5"):
       print(r["name"], r["spot_count"])
   ```
   Which five cities have the most saved spots?
2. **Try to write on the read-only connection.** On that same `c`, run
   `c.execute("UPDATE cities SET spot_count = 0")`. What exception do you get?
   Which line of `app/db.py` is responsible?
3. **See the `LEFT JOIN` matter.** Run
   `SELECT COUNT(*) FROM spots` and
   `SELECT COUNT(*) FROM spots JOIN spot_details ON spot_details.spot_id = spots.id`
   and
   `SELECT COUNT(*) FROM spots LEFT JOIN spot_details ON spot_details.spot_id = spots.id`.
   Explain the three numbers.
4. **Write a new query function.** In `app/queries.py`, add
   `get_city_spot_count(conn, city_name) -> int` that returns just the count of
   spots in a city (one `SELECT COUNT(*)`, one `?` parameter,
   `.fetchone()[0]`). Call it from a Python shell and check it matches the
   `spot_count` column for a couple of cities.
5. **Follow a coordinate.** Pick a spot title from the database. Trace, by
   reading code, how its `lat`/`lng` gets from the `spots` table into the JSON
   the browser receives — name every function it passes through. (Answer spans
   `app/queries.py` and `app/maps.py`.) Then confirm: does that same `lat`/`lng`
   ever reach the model? (Preview of chapter `07`: no — find where it is dropped.)

Continue to `05-frontend.md`.

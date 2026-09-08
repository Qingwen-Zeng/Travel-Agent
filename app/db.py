import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS cities (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL UNIQUE,
    center_lat REAL,
    center_lng REAL,
    spot_count INTEGER NOT NULL DEFAULT 0,
    country    TEXT
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

CREATE TABLE IF NOT EXISTS city_stories (
    id      INTEGER PRIMARY KEY,
    city_id INTEGER REFERENCES cities(id) ON DELETE CASCADE,
    story   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_city_stories_city ON city_stories(city_id);
"""


def _ensure_cities_country_column(conn: sqlite3.Connection) -> None:
    """Migrates a pre-existing cities table (created before the country column existed)."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(cities)")}
    if "country" not in columns:
        conn.execute("ALTER TABLE cities ADD COLUMN country TEXT")


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

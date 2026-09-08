"""Imports the real Google Maps "Saved lists" export (Saved/*.csv, one file per
city+category, e.g. "Paris Restaurants.csv") into the app's cities/categories/spots
database, geocoding each new spot via the Google Places API (New) Text Search.

Only the 291 files following the "{City} {Category}.csv" naming convention are imported;
generic non-city buckets (Want to go, Just Ok, Default list, etc.) are skipped.

Unresolvable spots (Places has no match) are skipped and reported at the end, not aborted —
the rest of the run still commits. A structurally malformed CSV (missing required columns)
still aborts the whole run, since there's no sensible way to partially import it.

Safe to re-run: already-resolved spots are matched by (city, category, feature ID) and are
not re-geocoded; changed titles/notes are updated without a new geocoding call; spots removed
from a CSV are deleted from that city+category.

Usage: python scripts/import_saved_places.py [--saved-dir Saved] [--db travel.db]
"""

import argparse
import csv
import io
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_writable_connection

# --- filename -> (city, category) parsing -----------------------------------------------

GENERIC_LISTS = {
    "default list", "favorite places", "saved for later", "want to go",
    "want to do", "just ok", "not worth it", "my cookbook", "images",
    "screenshots",
}

# Suffix categories, longest word-count first so "Bars and Clubs" matches before "Bars".
SUFFIX_CATEGORIES = [
    "Coffee And Tea Shops",
    "Coffee _ Tea Shops",
    "Gay _ Gay Friendly",
    "Gay Bars_Clubs",
    "Bars and Clubs",
    "Dessert Places",
    "Things To See",
    "Things to do",
    "Things To Do",
    "Things to Do",
    "Coffee Shops",
    "Hot Springs",
    "Night Markets",
    "date spots",
    "Gay Stuff",
    "Gay Bars",
    "Gay Bar",
    "Restaurants",
    "Desserts",
    "Lifestyle",
    "Shopping",
    "Cosmetic",
    "Wellness",
    "Massage",
    "Laundry",
    "Beaches",
    "Medical",
    "Hotels",
    "Cafes",
    "Towns",
    "Bars",
    "Gay",
]
SUFFIX_CATEGORIES.sort(key=lambda c: -len(c.split()))

# One observed category-first filename: "Gay Things To Do San Diego".
PREFIX_CATEGORIES = ["Gay Things To Do"]

# Raw category phrases (lowercased) that collapse into one canonical merged category.
CATEGORY_MERGE_GROUPS: dict[str, set[str]] = {
    "Gay Experience": {
        "gay", "gay bar", "gay bars", "gay stuff", "gay bars_clubs",
        "gay _ gay friendly", "gay things to do",
    },
    "Things To Do": {"things to do", "things to see"},
    "Coffee And Tea Shops": {"coffee and tea shops", "coffee shops", "coffee _ tea shops"},
    "Bars And Clubs": {"bars", "bars and clubs"},
    "Desserts": {"dessert places", "desserts"},
}
CATEGORY_ALIASES = {
    alias: canonical
    for canonical, aliases in CATEGORY_MERGE_GROUPS.items()
    for alias in aliases
}

DUPLICATE_SUFFIX = re.compile(r"\s*\(\d+\)\s*$")


def normalize_category(raw: str) -> str:
    key = re.sub(r"\s+", " ", raw).strip().lower()
    if key in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[key]
    return re.sub(r"\s+", " ", raw).strip().title()


def parse_filename(stem: str) -> Optional[tuple[str, str]]:
    """Returns (city, normalized category) or None if no known category matches."""
    base = DUPLICATE_SUFFIX.sub("", stem).strip()

    for category in PREFIX_CATEGORIES:
        if base.lower().startswith(category.lower()):
            city = base[len(category) :].strip()
            if city:
                return city, normalize_category(category)

    for category in SUFFIX_CATEGORIES:
        if base.lower().endswith(category.lower()):
            city = base[: -len(category)].strip()
            if city:
                return city, normalize_category(category)

    return None


# --- CSV row parsing ----------------------------------------------------------------------

FEATURE_ID_PATTERN = re.compile(r"!1s(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)")
REQUIRED_COLUMNS = ("title", "url")

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_FIELD_MASK = "places.id,places.location"


class ImportAbortError(Exception):
    """A structural CSV problem (missing required column) that stops the whole run."""


@dataclass(frozen=True)
class ParsedRow:
    title: str
    note: str
    url: str
    feature_id: Optional[str]


@dataclass(frozen=True)
class GeocodeResult:
    place_id: str
    lat: float
    lng: float


class Geocoder(Protocol):
    def geocode(self, title: str, city: str) -> Optional[GeocodeResult]: ...


@dataclass
class ImportSummary:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    skipped: list[tuple[str, str, str]] = field(default_factory=list)  # (city, category, title)

    def __str__(self) -> str:
        lines = [
            f"{self.added} added, {self.updated} updated, "
            f"{self.removed} removed, {self.unchanged} already located"
        ]
        if self.skipped:
            lines.append(f"{len(self.skipped)} skipped (no match found):")
            for city, category, title in self.skipped:
                lines.append(f'  "{title}" ({city} / {category})')
        return "\n".join(lines)


def _normalize_header(fieldnames) -> dict[str, str]:
    return {name.strip().lower(): name for name in fieldnames if name is not None}


def _find_header_line(lines: list[str]) -> int:
    """Some exports have a stray free-text line (a list description/note) before the
    real header, e.g. "Straight bar. Great vibe" followed by a blank line and then
    "Title,Note,URL,Tags,Comment". Scan for the actual header instead of assuming
    it's always line 1."""
    for i, line in enumerate(lines[:5]):
        fields = {f.strip().lower() for f in line.split(",")}
        if REQUIRED_COLUMNS[0] in fields and REQUIRED_COLUMNS[1] in fields:
            return i
    return 0


def parse_csv(path: Path) -> list[ParsedRow]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        lines = f.readlines()

    if not lines:
        raise ImportAbortError(f"{path}: file has no header row")

    header_index = _find_header_line(lines)
    reader = csv.DictReader(io.StringIO("".join(lines[header_index:])))

    if reader.fieldnames is None:
        raise ImportAbortError(f"{path}: file has no header row")

    header_map = _normalize_header(reader.fieldnames)
    missing = [col for col in REQUIRED_COLUMNS if col not in header_map]
    if missing:
        raise ImportAbortError(f"{path} is missing required column(s): {', '.join(missing)}")

    rows: list[ParsedRow] = []
    for raw_row in reader:
        title = (raw_row.get(header_map["title"]) or "").strip()
        note = (raw_row.get(header_map.get("note", ""), "") or "").strip()
        url = (raw_row.get(header_map["url"]) or "").strip()

        if not title or not url:
            continue

        feature_id = extract_feature_id(url)
        rows.append(ParsedRow(title=title, note=note, url=url, feature_id=feature_id))

    return rows


def extract_feature_id(url: str) -> Optional[str]:
    match = FEATURE_ID_PATTERN.search(url)
    return match.group(1).lower() if match else None


# --- import ---------------------------------------------------------------------------

def _get_or_create(conn, table: str, name: str) -> int:
    row = conn.execute(f"SELECT id FROM {table} WHERE name = ?", (name,)).fetchone()
    if row is not None:
        return row["id"]
    cursor = conn.execute(f"INSERT INTO {table} (name) VALUES (?)", (name,))
    return cursor.lastrowid


def _process_city_category(
    conn,
    city_name: str,
    category_name: str,
    rows: list[ParsedRow],
    geocoder: Geocoder,
    summary: ImportSummary,
) -> None:
    city_id = _get_or_create(conn, "cities", city_name)
    category_id = _get_or_create(conn, "categories", category_name)
    seen_ftids: list[str] = []

    for row in rows:
        if row.feature_id is None:
            summary.skipped.append((city_name, category_name, row.title))
            continue

        seen_ftids.append(row.feature_id)
        existing = conn.execute(
            "SELECT id, title, note, maps_url FROM spots "
            "WHERE city_id = ? AND category_id = ? AND ftid = ?",
            (city_id, category_id, row.feature_id),
        ).fetchone()

        if existing is not None:
            if (existing["title"], existing["note"], existing["maps_url"]) == (row.title, row.note, row.url):
                summary.unchanged += 1
            else:
                conn.execute(
                    "UPDATE spots SET title = ?, note = ?, maps_url = ? WHERE id = ?",
                    (row.title, row.note, row.url, existing["id"]),
                )
                summary.updated += 1
            continue

        result = geocoder.geocode(row.title, city_name)
        if result is None:
            summary.skipped.append((city_name, category_name, row.title))
            continue

        conn.execute(
            "INSERT INTO spots (city_id, category_id, title, lat, lng, note, place_id, ftid, maps_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                city_id,
                category_id,
                row.title,
                result.lat,
                result.lng,
                row.note,
                result.place_id,
                row.feature_id,
                row.url,
            ),
        )
        summary.added += 1

    if seen_ftids:
        placeholders = ",".join("?" * len(seen_ftids))
        cursor = conn.execute(
            f"DELETE FROM spots WHERE city_id = ? AND category_id = ? AND ftid NOT IN ({placeholders})",
            (city_id, category_id, *seen_ftids),
        )
    else:
        cursor = conn.execute(
            "DELETE FROM spots WHERE city_id = ? AND category_id = ?", (city_id, category_id)
        )
    summary.removed += cursor.rowcount


def run_import(saved_dir: Path, db_path: Path, geocoder: Geocoder) -> ImportSummary:
    csv_paths = sorted(Path(saved_dir).glob("*.csv"))
    in_scope = [p for p in csv_paths if p.stem.lower().strip() not in GENERIC_LISTS]

    # Files like "Chicago Restaurants.csv" and "Chicago Restaurants(1).csv" (a re-export
    # duplicate) both parse to the same (city, category) — merge their rows before
    # processing so the "delete rows no longer present" cleanup sees every contributing
    # file's rows, not just the last one processed for that pair.
    grouped: dict[tuple[str, str], list[ParsedRow]] = {}
    for path in in_scope:
        result = parse_filename(path.stem)
        if result is None:
            continue
        city, category = result
        grouped.setdefault((city, category), []).extend(parse_csv(path))

    conn = get_writable_connection(db_path)
    summary = ImportSummary()

    try:
        touched_cities: set[int] = set()
        for (city_name, category_name), rows in grouped.items():
            _process_city_category(conn, city_name, category_name, rows, geocoder, summary)
            touched_cities.add(_get_or_create(conn, "cities", city_name))

        for city_id in touched_cities:
            conn.execute(
                "UPDATE cities SET "
                "center_lat = (SELECT AVG(lat) FROM spots WHERE city_id = ?), "
                "center_lng = (SELECT AVG(lng) FROM spots WHERE city_id = ?), "
                "spot_count = (SELECT COUNT(*) FROM spots WHERE city_id = ?) "
                "WHERE id = ?",
                (city_id, city_id, city_id, city_id),
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return summary


GEOCODE_MAX_ATTEMPTS = 3
GEOCODE_TIMEOUT_SECONDS = 30
GEOCODE_RETRY_BACKOFF_SECONDS = 2


class GooglePlacesGeocoder:
    def __init__(self, api_key: str, session: Optional[requests.Session] = None):
        self._api_key = api_key
        self._session = session or requests.Session()

    def geocode(self, title: str, city: str) -> Optional[GeocodeResult]:
        response = None
        for attempt in range(1, GEOCODE_MAX_ATTEMPTS + 1):
            try:
                response = self._session.post(
                    PLACES_SEARCH_URL,
                    json={"textQuery": f"{title}, {city}"},
                    headers={
                        "X-Goog-Api-Key": self._api_key,
                        "X-Goog-FieldMask": PLACES_FIELD_MASK,
                        "Content-Type": "application/json",
                    },
                    timeout=GEOCODE_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                break
            except requests.exceptions.RequestException:
                if attempt == GEOCODE_MAX_ATTEMPTS:
                    return None
                time.sleep(GEOCODE_RETRY_BACKOFF_SECONDS * attempt)

        places = response.json().get("places", [])
        if not places:
            return None

        place = places[0]
        location = place.get("location", {})
        return GeocodeResult(
            place_id=place.get("id", ""),
            lat=location.get("latitude"),
            lng=location.get("longitude"),
        )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Import Saved/ places into SQLite.")
    parser.add_argument("--saved-dir", default="Saved", type=Path)
    parser.add_argument("--db", default="travel.db", type=Path)
    args = parser.parse_args(argv)

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        print("GOOGLE_PLACES_API_KEY is not set.", file=sys.stderr)
        return 2

    geocoder = GooglePlacesGeocoder(api_key)

    try:
        summary = run_import(args.saved_dir, args.db, geocoder)
    except ImportAbortError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"{args.db}: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

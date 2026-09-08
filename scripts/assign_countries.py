"""Assigns each city in the cities table a country, from a hand-curated mapping (the real
data has typo'd duplicates like "Milan"/"Milano" and country-as-city buckets like "Lebanon",
so this isn't automatically inferable — see BUILD_INSTRUCTIONS.md Step 14).

Safe to re-run: each run overwrites cities.country for every mapped name. Any city in the
database with no entry in CITY_TO_COUNTRY is reported, not aborted — the rest of the run
still commits.

Usage: python scripts/assign_countries.py [--db travel.db]
"""

import argparse
import sys
import unicodedata
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_writable_connection


def _normalize(name: str) -> str:
    """NFC-normalizes so visually-identical accented names (e.g. a precomposed 'é' vs
    'e' + combining acute) always compare equal, regardless of how either side's bytes
    happen to be composed."""
    return unicodedata.normalize("NFC", name)

# Hand-curated, not inferred — the underlying city names include typo'd duplicates
# ("Milan"/"Milano", "Talinn"/"Tallin") and country names used as city buckets
# ("Lebanon", "Cuba"). Fix a name here (or in the source CSVs) rather than adding
# special-case logic. A few genuinely low-confidence calls are marked below; correct
# them here if wrong and re-run.
CITY_TO_COUNTRY: dict[str, str] = {
    "Amman": "Jordan",
    "Amsterdam": "Netherlands",
    "Bali": "Indonesia",
    "Bangkok": "Thailand",
    "Belgrade": "Serbia",
    "Bergen": "Norway",
    "Berlin": "Germany",
    "Bologna": "Italy",
    "Boracay": "Philippines",
    "Boston": "USA",
    "Brussels": "Belgium",
    "Budapest": "Hungary",
    "Capadocia": "Turkey",
    "Cappadocia": "Turkey",
    "Chengdu": "China",
    "Chiang Mai": "Thailand",
    "Chicago": "USA",
    "Copenhagen": "Denmark",
    "Coppenhagen": "Denmark",
    "Corfu": "Greece",
    "Costa Rica": "Costa Rica",
    "Cote D’Azur": "France",
    "Côte Dazure": "France",
    "Côte D’azure": "France",
    "Côte d’Azur": "France",
    "Cuba": "Cuba",
    "Cusco": "Peru",
    "Cyprus": "Cyprus",
    "DC": "USA",  # assumed Washington DC
    "Da Nang": "Vietnam",
    "Da Nang Area": "Vietnam",
    "Dallas": "USA",
    "Denver": "USA",
    "Dubai": "UAE",
    "Dubrovnik": "Croatia",
    "Faroe Islands": "Faroe Islands",  # low confidence — could be filed under Denmark
    "Fethiye": "Turkey",
    "Hakone": "Japan",
    "Helsinki": "Finland",
    "Hiroshima": "Japan",
    "Ho Chi Min": "Vietnam",
    "Ho Chi Minh": "Vietnam",
    "Hokkaido": "Japan",
    "Hong Kong": "Hong Kong",
    "Ireland": "Ireland",
    "Istanbul": "Turkey",
    "Jakarta": "Indonesia",
    "KL": "Malaysia",  # Kuala Lumpur
    "Krakow": "Poland",
    "Kyoto": "Japan",
    "LA": "USA",
    "Lapland": "Finland",  # low confidence — Lapland spans Finland/Sweden/Norway
    "Las Vegas Trips": "USA",
    "Lebanon": "Lebanon",
    "Lima": "Peru",
    "Ljubljana": "Slovenia",
    "London": "United Kingdom",
    "Lyon": "France",
    "Madrid": "Spain",
    "Mallorca": "Spain",
    "Malta": "Malta",
    "Manila": "Philippines",
    "Mexico": "Mexico",
    "Mexico City": "Mexico",
    "Milan": "Italy",
    "Milano": "Italy",
    "Montreal": "Canada",
    "Morocco": "Morocco",
    "Myanmar": "Myanmar",
    "NYC": "USA",
    "Napoli": "Italy",
    "New Orleans": "USA",
    "Osaka": "Japan",
    "Oslo": "Norway",
    "Palawan": "Philippines",
    "Paris": "France",
    "Penang": "Malaysia",
    "Provincetown": "USA",
    "Puerto Vallarta": "Mexico",
    "Qatar": "Qatar",
    "Rio": "Brazil",
    "Rome": "Italy",
    "San Diego": "USA",
    "San Sebastián": "Spain",
    "Santiago": "Chile",
    "Sao Paolo": "Brazil",
    "Sao Paul": "Brazil",
    "São Paulo": "Brazil",
    "Seattle": "USA",
    "Singapore": "Singapore",
    "South of France": "France",
    "Sri Lanka": "Sri Lanka",
    "Stockholm": "Sweden",
    "Taipei": "Taiwan",
    "Talinn": "Estonia",
    "Tallin": "Estonia",
    "Tbilisi": "Georgia",
    "Tenerife": "Spain",
    "Tokyo": "Japan",
    "Tuscany": "Italy",
    "Valencia": "Spain",
    "Vancouver": "Canada",
    "Vegas": "USA",
    "Vienna": "Austria",
    "Xian": "China",
    "Yerevan": "Armenia",
    "Yokohama": "Japan",
    "York": "United Kingdom",  # low confidence — could be a mislabeled "New York"
    "Zadar": "Croatia",
    "Zurich": "Switzerland",
}

_NORMALIZED_CITY_TO_COUNTRY = {_normalize(k): v for k, v in CITY_TO_COUNTRY.items()}


def run_assign(db_path: Path) -> tuple[int, list[str]]:
    conn = get_writable_connection(db_path)
    updated = 0
    unmapped: list[str] = []

    try:
        for row in conn.execute("SELECT name FROM cities"):
            country = _NORMALIZED_CITY_TO_COUNTRY.get(_normalize(row["name"]))
            if country is None:
                unmapped.append(row["name"])
                continue
            conn.execute(
                "UPDATE cities SET country = ? WHERE name = ?", (country, row["name"])
            )
            updated += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return updated, unmapped


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Assign cities.country from a curated mapping.")
    parser.add_argument("--db", default="travel.db", type=Path)
    args = parser.parse_args(argv)

    updated, unmapped = run_assign(args.db)

    print(f"{args.db}: {updated} cities assigned a country")
    if unmapped:
        print(f"{len(unmapped)} city name(s) with no mapping, left unset:")
        for name in unmapped:
            print(f"  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

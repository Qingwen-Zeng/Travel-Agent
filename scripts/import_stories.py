"""Imports stories.json (personal travel-diary entries, keyed by city name, plus an
"_unmatched" bucket of entries never tied to a specific city) into the city_stories table.

Real city keys must match cities.name exactly (no alias normalization is performed);
any story-json city key with no matching row in `cities` is reported and skipped, not
aborted. Entries under "_unmatched" are imported with city_id = NULL — still embedded and
searchable, just not attributable to a specific city.

Safe to re-run: each run replaces the full contents of city_stories.

Usage: python scripts/import_stories.py [--stories stories.json] [--db travel.db]
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_writable_connection

UNMATCHED_KEY = "_unmatched"


@dataclass
class ImportSummary:
    imported: int = 0
    unmatched: int = 0
    unknown_cities: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        lines = [f"{self.imported} stories imported ({self.unmatched} untagged)"]
        if self.unknown_cities:
            lines.append(
                f"{len(self.unknown_cities)} story-json city key(s) with no matching "
                f"city, skipped: {', '.join(self.unknown_cities)}"
            )
        return "\n".join(lines)


def run_import(stories_path: Path, db_path: Path) -> ImportSummary:
    with Path(stories_path).open(encoding="utf-8") as f:
        data = json.load(f)

    conn = get_writable_connection(db_path)
    summary = ImportSummary()

    try:
        conn.execute("DELETE FROM city_stories")

        for city_name, stories in data.items():
            if city_name == UNMATCHED_KEY:
                for story in stories:
                    conn.execute(
                        "INSERT INTO city_stories (city_id, story) VALUES (NULL, ?)", (story,)
                    )
                    summary.imported += 1
                    summary.unmatched += 1
                continue

            row = conn.execute("SELECT id FROM cities WHERE name = ?", (city_name,)).fetchone()
            if row is None:
                summary.unknown_cities.append(city_name)
                continue

            city_id = row["id"]
            for story in stories:
                conn.execute(
                    "INSERT INTO city_stories (city_id, story) VALUES (?, ?)", (city_id, story)
                )
                summary.imported += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return summary


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Import stories.json into city_stories.")
    parser.add_argument("--stories", default="stories.json", type=Path)
    parser.add_argument("--db", default="travel.db", type=Path)
    args = parser.parse_args(argv)

    summary = run_import(args.stories, args.db)
    print(f"{args.db}: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

import json
from pathlib import Path

from app.db import get_writable_connection
from scripts.import_stories import run_import


def _write_stories(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_run_import_writes_stories_tagged_to_matching_cities(tmp_path):
    db_path = tmp_path / "travel.db"
    conn = get_writable_connection(db_path)
    conn.execute("INSERT INTO cities (name) VALUES ('Tokyo')")
    conn.commit()
    conn.close()

    stories_path = tmp_path / "stories.json"
    _write_stories(stories_path, {"Tokyo": ["story one", "story two"]})

    summary = run_import(stories_path, db_path)

    conn = get_writable_connection(db_path)
    rows = conn.execute(
        "SELECT story, city_id FROM city_stories ORDER BY id"
    ).fetchall()
    city_id = conn.execute("SELECT id FROM cities WHERE name = 'Tokyo'").fetchone()["id"]

    assert [r["story"] for r in rows] == ["story one", "story two"]
    assert all(r["city_id"] == city_id for r in rows)
    assert summary.imported == 2
    assert summary.unmatched == 0


def test_run_import_tags_unmatched_bucket_with_null_city_id(tmp_path):
    db_path = tmp_path / "travel.db"
    get_writable_connection(db_path).close()

    stories_path = tmp_path / "stories.json"
    _write_stories(stories_path, {"_unmatched": ["untagged story"]})

    summary = run_import(stories_path, db_path)

    conn = get_writable_connection(db_path)
    row = conn.execute("SELECT story, city_id FROM city_stories").fetchone()

    assert row["story"] == "untagged story"
    assert row["city_id"] is None
    assert summary.imported == 1
    assert summary.unmatched == 1


def test_run_import_reports_city_keys_with_no_matching_city(tmp_path):
    db_path = tmp_path / "travel.db"
    get_writable_connection(db_path).close()

    stories_path = tmp_path / "stories.json"
    _write_stories(stories_path, {"Nowhereville": ["a story"]})

    summary = run_import(stories_path, db_path)

    conn = get_writable_connection(db_path)
    count = conn.execute("SELECT COUNT(*) AS n FROM city_stories").fetchone()["n"]

    assert count == 0
    assert summary.imported == 0
    assert summary.unknown_cities == ["Nowhereville"]


def test_run_import_is_idempotent_replacing_prior_contents(tmp_path):
    db_path = tmp_path / "travel.db"
    conn = get_writable_connection(db_path)
    conn.execute("INSERT INTO cities (name) VALUES ('Tokyo')")
    conn.commit()
    conn.close()

    stories_path = tmp_path / "stories.json"
    _write_stories(stories_path, {"Tokyo": ["old story"]})
    run_import(stories_path, db_path)

    _write_stories(stories_path, {"Tokyo": ["new story"]})
    run_import(stories_path, db_path)

    conn = get_writable_connection(db_path)
    rows = conn.execute("SELECT story FROM city_stories").fetchall()

    assert [r["story"] for r in rows] == ["new story"]

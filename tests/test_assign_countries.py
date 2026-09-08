import unicodedata

from app.db import get_writable_connection
from scripts.assign_countries import run_assign


def _seed_cities(db_path, names):
    conn = get_writable_connection(db_path)
    for name in names:
        conn.execute("INSERT INTO cities (name) VALUES (?)", (name,))
    conn.commit()
    conn.close()


def test_run_assign_sets_country_for_mapped_cities(tmp_path):
    db_path = tmp_path / "travel.db"
    _seed_cities(db_path, ["Paris", "Lyon"])

    updated, unmapped = run_assign(db_path)

    conn = get_writable_connection(db_path)
    rows = {r["name"]: r["country"] for r in conn.execute("SELECT name, country FROM cities")}

    assert rows == {"Paris": "France", "Lyon": "France"}
    assert updated == 2
    assert unmapped == []


def test_run_assign_reports_unmapped_city_names(tmp_path):
    db_path = tmp_path / "travel.db"
    _seed_cities(db_path, ["Paris", "Nowhereville"])

    updated, unmapped = run_assign(db_path)

    conn = get_writable_connection(db_path)
    row = conn.execute("SELECT country FROM cities WHERE name = 'Nowhereville'").fetchone()

    assert row["country"] is None
    assert updated == 1
    assert unmapped == ["Nowhereville"]


def test_run_assign_matches_accented_names_regardless_of_unicode_normalization(tmp_path):
    db_path = tmp_path / "travel.db"
    # Build the accented name from a codepoint the mapping dict actually uses
    # ("San Sebasti" + LATIN SMALL LETTER A WITH ACUTE + "n"), then re-decompose it
    # into NFD form (base letter + combining accent) — a different byte sequence for
    # the same visible text, independent of how this source file itself is encoded.
    precomposed_name = "San Sebasti" + "á" + "n"
    decomposed_name = unicodedata.normalize("NFD", precomposed_name)
    assert decomposed_name != precomposed_name
    _seed_cities(db_path, [decomposed_name])

    updated, unmapped = run_assign(db_path)

    conn = get_writable_connection(db_path)
    row = conn.execute(
        "SELECT country FROM cities WHERE name = ?", (decomposed_name,)
    ).fetchone()

    assert row["country"] == "Spain"
    assert updated == 1
    assert unmapped == []


def test_run_assign_is_idempotent(tmp_path):
    db_path = tmp_path / "travel.db"
    _seed_cities(db_path, ["Paris"])

    run_assign(db_path)
    updated, unmapped = run_assign(db_path)

    conn = get_writable_connection(db_path)
    row = conn.execute("SELECT country FROM cities WHERE name = 'Paris'").fetchone()

    assert row["country"] == "France"
    assert updated == 1

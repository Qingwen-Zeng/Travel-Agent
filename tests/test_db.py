import sqlite3

import pytest

from app.db import get_readonly_connection, get_writable_connection


def _insert_city_and_category(conn, city="Zurich", category="Restaurants"):
    conn.execute("INSERT INTO cities (name) VALUES (?)", (city,))
    city_id = conn.execute("SELECT id FROM cities WHERE name = ?", (city,)).fetchone()["id"]
    conn.execute("INSERT INTO categories (name) VALUES (?)", (category,))
    category_id = conn.execute(
        "SELECT id FROM categories WHERE name = ?", (category,)
    ).fetchone()["id"]
    return city_id, category_id


def test_fresh_path_creates_tables_and_index(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")

    names = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
        )
    }

    assert {
        "cities",
        "categories",
        "spots",
        "idx_spots_city",
        "idx_spots_category",
        "city_stories",
        "idx_city_stories_city",
        "idx_cities_country",
        "spot_details",
    } <= names


def test_writable_connection_uses_row_factory(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")

    assert conn.row_factory is sqlite3.Row


def test_duplicate_ftid_within_same_city_and_category_raises_integrity_error(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    city_id, category_id = _insert_city_and_category(conn)
    conn.execute(
        "INSERT INTO spots (city_id, category_id, title, lat, lng, ftid) "
        "VALUES (?, ?, 'A', 1.0, 2.0, 'ftid-1')",
        (city_id, category_id),
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO spots (city_id, category_id, title, lat, lng, ftid) "
            "VALUES (?, ?, 'B', 3.0, 4.0, 'ftid-1')",
            (city_id, category_id),
        )


def test_same_ftid_allowed_under_a_different_category_for_the_same_city(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    city_id, restaurants_id = _insert_city_and_category(conn, category="Restaurants")
    conn.execute("INSERT INTO categories (name) VALUES ('Bars And Clubs')")
    bars_id = conn.execute(
        "SELECT id FROM categories WHERE name = 'Bars And Clubs'"
    ).fetchone()["id"]

    conn.execute(
        "INSERT INTO spots (city_id, category_id, title, lat, lng, ftid) "
        "VALUES (?, ?, 'A', 1.0, 2.0, 'ftid-1')",
        (city_id, restaurants_id),
    )
    # A place saved under two categories for the same city is not a duplicate.
    conn.execute(
        "INSERT INTO spots (city_id, category_id, title, lat, lng, ftid) "
        "VALUES (?, ?, 'A', 1.0, 2.0, 'ftid-1')",
        (city_id, bars_id),
    )

    count = conn.execute("SELECT COUNT(*) AS n FROM spots WHERE ftid = 'ftid-1'").fetchone()["n"]
    assert count == 2


def test_deleting_city_cascades_to_spots(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    city_id, category_id = _insert_city_and_category(conn)
    conn.execute(
        "INSERT INTO spots (city_id, category_id, title, lat, lng, ftid) "
        "VALUES (?, ?, 'A', 1.0, 2.0, 'ftid-1')",
        (city_id, category_id),
    )

    conn.execute("DELETE FROM cities WHERE id = ?", (city_id,))

    remaining = conn.execute("SELECT COUNT(*) AS n FROM spots WHERE city_id = ?", (city_id,)).fetchone()
    assert remaining["n"] == 0


def test_writable_connection_migrates_pre_existing_cities_table_without_country(tmp_path):
    db_path = tmp_path / "travel.db"
    raw = sqlite3.connect(db_path)
    raw.execute(
        "CREATE TABLE cities (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, "
        "center_lat REAL, center_lng REAL, spot_count INTEGER NOT NULL DEFAULT 0)"
    )
    raw.execute("INSERT INTO cities (name) VALUES ('Zurich')")
    raw.commit()
    raw.close()

    conn = get_writable_connection(db_path)

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(cities)")}
    assert "country" in columns
    row = conn.execute("SELECT country FROM cities WHERE name = 'Zurich'").fetchone()
    assert row["country"] is None


def test_city_stories_allows_null_city_id_for_untagged_entries(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")

    conn.execute("INSERT INTO city_stories (city_id, story) VALUES (NULL, 'a diary entry')")

    row = conn.execute("SELECT city_id, story FROM city_stories").fetchone()
    assert row["city_id"] is None
    assert row["story"] == "a diary entry"


def test_deleting_category_cascades_to_spots(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    city_id, category_id = _insert_city_and_category(conn)
    conn.execute(
        "INSERT INTO spots (city_id, category_id, title, lat, lng, ftid) "
        "VALUES (?, ?, 'A', 1.0, 2.0, 'ftid-1')",
        (city_id, category_id),
    )

    conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))

    remaining = conn.execute(
        "SELECT COUNT(*) AS n FROM spots WHERE category_id = ?", (category_id,)
    ).fetchone()
    assert remaining["n"] == 0


def test_readonly_connection_uses_row_factory(tmp_path):
    db_path = tmp_path / "travel.db"
    get_writable_connection(db_path)

    conn = get_readonly_connection(db_path)

    assert conn.row_factory is sqlite3.Row


def test_readonly_connection_can_read_existing_data(tmp_path):
    db_path = tmp_path / "travel.db"
    writable = get_writable_connection(db_path)
    writable.execute("INSERT INTO cities (name) VALUES ('Zurich')")
    writable.commit()

    conn = get_readonly_connection(db_path)

    row = conn.execute("SELECT name FROM cities WHERE name = 'Zurich'").fetchone()
    assert row["name"] == "Zurich"


def test_readonly_connection_rejects_writes(tmp_path):
    db_path = tmp_path / "travel.db"
    get_writable_connection(db_path)

    conn = get_readonly_connection(db_path)

    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO cities (name) VALUES ('Zurich')")

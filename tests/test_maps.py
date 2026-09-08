import json

from app.db import get_writable_connection
from app.maps import build_map_payload
from app.queries import get_city_spots


def test_rows_convert_to_payload_shape():
    rows = [
        {
            "title": "Botanical Garden",
            "lat": 47.359999,
            "lng": 8.560555,
            "note": None,
            "category": "park",
            "maps_url": "https://maps/1",
        }
    ]

    payload = build_map_payload("Zurich", rows)

    assert payload == {
        "city": "Zurich",
        "markers": [
            {
                "title": "Botanical Garden",
                "lat": 47.359999,
                "lng": 8.560555,
                "note": "",
                "category": "park",
                "maps_url": "https://maps/1",
            }
        ],
    }


def test_note_is_preserved_when_present():
    rows = [
        {"title": "A", "lat": 1.0, "lng": 2.0, "note": "great coffee", "category": "cafe", "maps_url": "u"}
    ]

    payload = build_map_payload("Zurich", rows)

    assert payload["markers"][0]["note"] == "great coffee"


def test_empty_spot_list_produces_empty_markers_not_none():
    payload = build_map_payload("Zurich", [])

    assert payload["markers"] == []
    assert payload["markers"] is not None
    assert payload["city"] == "Zurich"


def test_payload_is_json_serialisable():
    rows = [{"title": "A", "lat": 1.0, "lng": 2.0, "note": "n", "category": "c", "maps_url": "u"}]

    payload = build_map_payload("Zurich", rows)

    json.dumps(payload)


def test_rows_with_city_column_include_it_per_marker():
    rows = [
        {
            "title": "Botanical Garden",
            "lat": 47.36,
            "lng": 8.56,
            "note": None,
            "category": "Park",
            "maps_url": "https://maps/1",
            "city": "Zurich",
        }
    ]

    payload = build_map_payload("Switzerland", rows)

    assert payload["city"] == "Switzerland"
    assert payload["markers"][0]["city"] == "Zurich"


def test_works_with_real_db_rows(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    conn.execute("INSERT INTO cities (name) VALUES ('Zurich')")
    city_id = conn.execute("SELECT id FROM cities WHERE name = 'Zurich'").fetchone()["id"]
    conn.execute("INSERT INTO categories (name) VALUES ('Park')")
    category_id = conn.execute("SELECT id FROM categories WHERE name = 'Park'").fetchone()["id"]
    conn.execute(
        "INSERT INTO spots (city_id, category_id, title, lat, lng, note, maps_url, ftid) "
        "VALUES (?, ?, 'Botanical Garden', 47.3595, 8.5605, NULL, 'https://maps/1', 'f1')",
        (city_id, category_id),
    )
    conn.commit()

    payload = build_map_payload("Zurich", get_city_spots(conn, "Zurich"))

    assert payload == {
        "city": "Zurich",
        "markers": [
            {
                "title": "Botanical Garden",
                "lat": 47.3595,
                "lng": 8.5605,
                "note": "",
                "category": "Park",
                "maps_url": "https://maps/1",
            }
        ],
    }

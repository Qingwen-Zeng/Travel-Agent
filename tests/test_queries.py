from app.db import get_writable_connection
from app.queries import (
    get_all_city_categories,
    get_city_categories,
    get_city_spots,
    get_city_spots_by_categories,
    get_country_spots,
    get_country_spots_by_categories,
    list_categories,
    list_cities,
    list_countries,
    search_city_spots,
)


def _conn(tmp_path):
    return get_writable_connection(tmp_path / "travel.db")


def _seed_city(conn, name, country=None):
    conn.execute("INSERT INTO cities (name, country) VALUES (?, ?)", (name, country))
    return conn.execute("SELECT id FROM cities WHERE name = ?", (name,)).fetchone()["id"]


def _seed_category(conn, name):
    conn.execute("INSERT INTO categories (name) VALUES (?)", (name,))
    return conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()["id"]


def _seed_spot(conn, city_id, category_id, title, lat, lng, note, ftid, maps_url="https://maps/x"):
    conn.execute(
        "INSERT INTO spots (city_id, category_id, title, lat, lng, note, maps_url, ftid) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (city_id, category_id, title, lat, lng, note, maps_url, ftid),
    )


def test_list_cities_returns_alphabetical_with_counts(tmp_path):
    conn = _conn(tmp_path)
    conn.execute("INSERT INTO cities (name, spot_count) VALUES ('Zurich', 5)")
    conn.execute("INSERT INTO cities (name, spot_count) VALUES ('Barcelona', 3)")
    conn.execute("INSERT INTO cities (name, spot_count) VALUES ('Amsterdam', 7)")
    conn.commit()

    cities = list_cities(conn)

    assert [(row["name"], row["spot_count"]) for row in cities] == [
        ("Amsterdam", 7),
        ("Barcelona", 3),
        ("Zurich", 5),
    ]


def test_get_city_spots_returns_only_that_citys_spots(tmp_path):
    conn = _conn(tmp_path)
    zurich_id = _seed_city(conn, "Zurich")
    barcelona_id = _seed_city(conn, "Barcelona")
    park_id = _seed_category(conn, "Park")
    cafe_id = _seed_category(conn, "Cafe")
    _seed_spot(conn, zurich_id, park_id, "Botanical Garden", 47.36, 8.55, "nice", "f1", "https://maps/1")
    _seed_spot(conn, zurich_id, cafe_id, "Aardvark Cafe", 47.37, 8.56, None, "f2")
    _seed_spot(conn, barcelona_id, park_id, "Sagrada Familia", 41.4, 2.17, None, "f3")
    conn.commit()

    spots = get_city_spots(conn, "Zurich")

    assert [row["title"] for row in spots] == ["Aardvark Cafe", "Botanical Garden"]
    garden = spots[1]
    assert garden["lat"] == 47.36
    assert garden["lng"] == 8.55
    assert garden["note"] == "nice"
    assert garden["category"] == "Park"
    assert garden["maps_url"] == "https://maps/1"


def test_get_city_spots_unknown_city_returns_empty_list(tmp_path):
    conn = _conn(tmp_path)

    assert get_city_spots(conn, "Nowhereville") == []


def test_get_city_spots_executes_exactly_one_statement(tmp_path):
    conn = _conn(tmp_path)
    city_id = _seed_city(conn, "Zurich")
    category_id = _seed_category(conn, "Park")
    _seed_spot(conn, city_id, category_id, "A", 1.0, 2.0, None, "f1")
    conn.commit()

    statements = []
    conn.set_trace_callback(statements.append)
    try:
        get_city_spots(conn, "Zurich")
    finally:
        conn.set_trace_callback(None)

    assert len(statements) == 1


def test_get_city_categories_returns_names_and_counts(tmp_path):
    conn = _conn(tmp_path)
    zurich_id = _seed_city(conn, "Zurich")
    barcelona_id = _seed_city(conn, "Barcelona")
    park_id = _seed_category(conn, "Park")
    cafe_id = _seed_category(conn, "Cafe")
    _seed_spot(conn, zurich_id, park_id, "Botanical Garden", 47.36, 8.55, None, "f1")
    _seed_spot(conn, zurich_id, cafe_id, "Aardvark Cafe", 47.37, 8.56, None, "f2")
    _seed_spot(conn, zurich_id, cafe_id, "Beanhouse", 47.38, 8.57, None, "f3")
    _seed_spot(conn, barcelona_id, park_id, "Sagrada Familia", 41.4, 2.17, None, "f4")
    conn.commit()

    categories = get_city_categories(conn, "Zurich")

    assert [(row["name"], row["spot_count"]) for row in categories] == [
        ("Cafe", 2),
        ("Park", 1),
    ]


def test_get_city_categories_unknown_city_returns_empty_list(tmp_path):
    conn = _conn(tmp_path)

    assert get_city_categories(conn, "Nowhereville") == []


def test_get_city_spots_by_categories_filters_to_named_categories(tmp_path):
    conn = _conn(tmp_path)
    city_id = _seed_city(conn, "Zurich")
    park_id = _seed_category(conn, "Park")
    cafe_id = _seed_category(conn, "Cafe")
    bar_id = _seed_category(conn, "Bar")
    _seed_spot(conn, city_id, park_id, "Botanical Garden", 47.36, 8.55, None, "f1")
    _seed_spot(conn, city_id, cafe_id, "Aardvark Cafe", 47.37, 8.56, None, "f2")
    _seed_spot(conn, city_id, bar_id, "Night Owl", 47.38, 8.57, None, "f3")
    conn.commit()

    spots = get_city_spots_by_categories(conn, "Zurich", ["Cafe", "Bar"])

    assert {row["title"] for row in spots} == {"Aardvark Cafe", "Night Owl"}


def test_get_city_spots_by_categories_single_category(tmp_path):
    conn = _conn(tmp_path)
    city_id = _seed_city(conn, "Zurich")
    park_id = _seed_category(conn, "Park")
    cafe_id = _seed_category(conn, "Cafe")
    _seed_spot(conn, city_id, park_id, "Botanical Garden", 47.36, 8.55, None, "f1")
    _seed_spot(conn, city_id, cafe_id, "Aardvark Cafe", 47.37, 8.56, None, "f2")
    conn.commit()

    spots = get_city_spots_by_categories(conn, "Zurich", ["Park"])

    assert [row["title"] for row in spots] == ["Botanical Garden"]


def test_get_city_spots_by_categories_unknown_category_returns_empty_list(tmp_path):
    conn = _conn(tmp_path)
    city_id = _seed_city(conn, "Zurich")
    park_id = _seed_category(conn, "Park")
    _seed_spot(conn, city_id, park_id, "Botanical Garden", 47.36, 8.55, None, "f1")
    conn.commit()

    assert get_city_spots_by_categories(conn, "Zurich", ["Nonexistent"]) == []


def test_list_categories_returns_distinct_names_with_at_least_one_spot(tmp_path):
    conn = _conn(tmp_path)
    city_id = _seed_city(conn, "Zurich")
    park_id = _seed_category(conn, "Park")
    cafe_id = _seed_category(conn, "Cafe")
    _seed_category(conn, "Orphaned")  # exists but has no spots
    _seed_spot(conn, city_id, park_id, "Botanical Garden", 47.36, 8.55, None, "f1")
    _seed_spot(conn, city_id, cafe_id, "Aardvark Cafe", 47.37, 8.56, None, "f2")
    conn.commit()

    assert [row["name"] for row in list_categories(conn)] == ["Cafe", "Park"]


def test_get_all_city_categories_returns_every_city_and_category_in_one_call(tmp_path):
    conn = _conn(tmp_path)
    zurich_id = _seed_city(conn, "Zurich")
    barcelona_id = _seed_city(conn, "Barcelona")
    park_id = _seed_category(conn, "Park")
    cafe_id = _seed_category(conn, "Cafe")
    _seed_spot(conn, zurich_id, park_id, "Botanical Garden", 47.36, 8.55, None, "f1")
    _seed_spot(conn, zurich_id, cafe_id, "Aardvark Cafe", 47.37, 8.56, None, "f2")
    _seed_spot(conn, zurich_id, cafe_id, "Beanhouse", 47.38, 8.57, None, "f3")
    _seed_spot(conn, barcelona_id, park_id, "Sagrada Familia", 41.4, 2.17, None, "f4")
    conn.commit()

    rows = get_all_city_categories(conn)

    assert [(r["city"], r["category"], r["spot_count"]) for r in rows] == [
        ("Barcelona", "Park", 1),
        ("Zurich", "Cafe", 2),
        ("Zurich", "Park", 1),
    ]


def test_get_all_city_categories_executes_exactly_one_statement(tmp_path):
    conn = _conn(tmp_path)
    city_id = _seed_city(conn, "Zurich")
    category_id = _seed_category(conn, "Park")
    _seed_spot(conn, city_id, category_id, "Botanical Garden", 47.36, 8.55, None, "f1")
    conn.commit()

    statements = []
    conn.set_trace_callback(statements.append)
    try:
        get_all_city_categories(conn)
    finally:
        conn.set_trace_callback(None)

    assert len(statements) == 1


def test_search_city_spots_matches_title(tmp_path):
    conn = _conn(tmp_path)
    city_id = _seed_city(conn, "Bangkok")
    category_id = _seed_category(conn, "Lifestyle")
    _seed_spot(conn, city_id, category_id, "Riverside Sauna House", 13.7, 100.5, None, "f1")
    _seed_spot(conn, city_id, category_id, "Some Other Spot", 13.8, 100.6, None, "f2")
    conn.commit()

    results = search_city_spots(conn, "Bangkok", "sauna")

    assert [r["title"] for r in results] == ["Riverside Sauna House"]


def test_search_city_spots_matches_note(tmp_path):
    conn = _conn(tmp_path)
    city_id = _seed_city(conn, "Bangkok")
    category_id = _seed_category(conn, "Bars And Clubs")
    _seed_spot(conn, city_id, category_id, "BEEF. BKK", 13.7, 100.5, "Gay club with a sauna area", "f1")
    conn.commit()

    results = search_city_spots(conn, "Bangkok", "sauna")

    assert [r["title"] for r in results] == ["BEEF. BKK"]
    assert results[0]["category"] == "Bars And Clubs"


def test_search_city_spots_is_case_insensitive(tmp_path):
    conn = _conn(tmp_path)
    city_id = _seed_city(conn, "Bangkok")
    category_id = _seed_category(conn, "Lifestyle")
    _seed_spot(conn, city_id, category_id, "SAUNA Palace", 13.7, 100.5, None, "f1")
    conn.commit()

    results = search_city_spots(conn, "Bangkok", "sauna")

    assert [r["title"] for r in results] == ["SAUNA Palace"]


def test_search_city_spots_no_match_returns_empty_list(tmp_path):
    conn = _conn(tmp_path)
    city_id = _seed_city(conn, "Bangkok")
    category_id = _seed_category(conn, "Lifestyle")
    _seed_spot(conn, city_id, category_id, "Some Spot", 13.7, 100.5, None, "f1")
    conn.commit()

    assert search_city_spots(conn, "Bangkok", "sauna") == []


def test_search_city_spots_scoped_to_the_given_city(tmp_path):
    conn = _conn(tmp_path)
    bangkok_id = _seed_city(conn, "Bangkok")
    taipei_id = _seed_city(conn, "Taipei")
    category_id = _seed_category(conn, "Lifestyle")
    _seed_spot(conn, bangkok_id, category_id, "Bangkok Sauna", 13.7, 100.5, None, "f1")
    _seed_spot(conn, taipei_id, category_id, "Taipei Sauna", 25.0, 121.5, None, "f2")
    conn.commit()

    results = search_city_spots(conn, "Bangkok", "sauna")

    assert [r["title"] for r in results] == ["Bangkok Sauna"]


def test_search_city_spots_includes_coordinates_for_map_rendering(tmp_path):
    # A matched spot can now be shown on a map (app.chat._resolve_tool_call), so this
    # query — unlike the others — does carry lat/lng. The coordinate-stripping safety
    # property lives at app.chat._tool_result_content, which explicitly picks fields
    # before anything is sent to the model; it never trusts what a query happens to return.
    conn = _conn(tmp_path)
    city_id = _seed_city(conn, "Bangkok")
    category_id = _seed_category(conn, "Lifestyle")
    _seed_spot(conn, city_id, category_id, "Sauna Spot", 13.7, 100.5, "great sauna", "f1")
    conn.commit()

    results = search_city_spots(conn, "Bangkok", "sauna")

    assert results[0]["lat"] == 13.7
    assert results[0]["lng"] == 100.5


def test_list_countries_returns_distinct_non_null_countries_alphabetically(tmp_path):
    conn = _conn(tmp_path)
    _seed_city(conn, "Paris", country="France")
    _seed_city(conn, "Lyon", country="France")
    _seed_city(conn, "Zurich", country="Switzerland")
    _seed_city(conn, "Nowhere", country=None)
    conn.commit()

    countries = [r["country"] for r in list_countries(conn)]

    assert countries == ["France", "Switzerland"]


def test_get_country_spots_combines_every_city_in_that_country(tmp_path):
    conn = _conn(tmp_path)
    paris_id = _seed_city(conn, "Paris", country="France")
    lyon_id = _seed_city(conn, "Lyon", country="France")
    zurich_id = _seed_city(conn, "Zurich", country="Switzerland")
    restaurants_id = _seed_category(conn, "Restaurants")
    _seed_spot(conn, paris_id, restaurants_id, "Paris Bistro", 48.8, 2.3, None, "f1")
    _seed_spot(conn, lyon_id, restaurants_id, "Lyon Bouchon", 45.7, 4.8, None, "f2")
    _seed_spot(conn, zurich_id, restaurants_id, "Zurich Cafe", 47.4, 8.5, None, "f3")
    conn.commit()

    results = get_country_spots(conn, "France")

    assert {(r["title"], r["city"]) for r in results} == {
        ("Paris Bistro", "Paris"),
        ("Lyon Bouchon", "Lyon"),
    }


def test_get_country_spots_by_categories_filters_across_cities(tmp_path):
    conn = _conn(tmp_path)
    paris_id = _seed_city(conn, "Paris", country="France")
    lyon_id = _seed_city(conn, "Lyon", country="France")
    restaurants_id = _seed_category(conn, "Restaurants")
    bars_id = _seed_category(conn, "Bars And Clubs")
    _seed_spot(conn, paris_id, restaurants_id, "Paris Bistro", 48.8, 2.3, None, "f1")
    _seed_spot(conn, lyon_id, bars_id, "Lyon Bar", 45.7, 4.8, None, "f2")
    conn.commit()

    results = get_country_spots_by_categories(conn, "France", ["Restaurants"])

    assert [r["title"] for r in results] == ["Paris Bistro"]

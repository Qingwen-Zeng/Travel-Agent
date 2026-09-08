import sqlite3


def list_cities(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT name, spot_count FROM cities ORDER BY name").fetchall()


def list_countries(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT DISTINCT country FROM cities WHERE country IS NOT NULL ORDER BY country;"
    ).fetchall()


def list_categories(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT DISTINCT categories.name\n"
        "  FROM categories\n"
        "  JOIN spots ON spots.category_id = categories.id\n"
        " ORDER BY categories.name;"
    ).fetchall()


def get_city_categories(conn: sqlite3.Connection, city_name: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT categories.name, COUNT(spots.id) AS spot_count\n"
        "  FROM spots\n"
        "  JOIN categories ON categories.id = spots.category_id\n"
        " WHERE spots.city_id = (SELECT id FROM cities WHERE name = ?)\n"
        " GROUP BY categories.id\n"
        " ORDER BY spot_count DESC, categories.name;",
        (city_name,),
    ).fetchall()


def get_all_city_categories(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT cities.name AS city, categories.name AS category, COUNT(spots.id) AS spot_count\n"
        "  FROM spots\n"
        "  JOIN cities ON cities.id = spots.city_id\n"
        "  JOIN categories ON categories.id = spots.category_id\n"
        " GROUP BY cities.id, categories.id\n"
        " ORDER BY cities.name, spot_count DESC, categories.name;"
    ).fetchall()


def get_city_spots(conn: sqlite3.Connection, city_name: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT spots.title, spots.lat, spots.lng, spots.note, categories.name AS category, "
        "spots.maps_url\n"
        "  FROM spots\n"
        "  JOIN categories ON categories.id = spots.category_id\n"
        " WHERE spots.city_id = (SELECT id FROM cities WHERE name = ?)\n"
        " ORDER BY spots.title;",
        (city_name,),
    ).fetchall()


def get_city_spots_by_categories(
    conn: sqlite3.Connection, city_name: str, categories: list[str]
) -> list[sqlite3.Row]:
    placeholders = ",".join("?" * len(categories))
    return conn.execute(
        "SELECT spots.title, spots.lat, spots.lng, spots.note, categories.name AS category, "
        "spots.maps_url\n"
        "  FROM spots\n"
        "  JOIN categories ON categories.id = spots.category_id\n"
        " WHERE spots.city_id = (SELECT id FROM cities WHERE name = ?)\n"
        f"   AND categories.name IN ({placeholders})\n"
        " ORDER BY spots.title;",
        (city_name, *categories),
    ).fetchall()


def get_country_spots(conn: sqlite3.Connection, country_name: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT spots.title, spots.lat, spots.lng, spots.note, categories.name AS category, "
        "spots.maps_url, cities.name AS city\n"
        "  FROM spots\n"
        "  JOIN categories ON categories.id = spots.category_id\n"
        "  JOIN cities ON cities.id = spots.city_id\n"
        " WHERE cities.country = ?\n"
        " ORDER BY cities.name, spots.title;",
        (country_name,),
    ).fetchall()


def get_country_spots_by_categories(
    conn: sqlite3.Connection, country_name: str, categories: list[str]
) -> list[sqlite3.Row]:
    placeholders = ",".join("?" * len(categories))
    return conn.execute(
        "SELECT spots.title, spots.lat, spots.lng, spots.note, categories.name AS category, "
        "spots.maps_url, cities.name AS city\n"
        "  FROM spots\n"
        "  JOIN categories ON categories.id = spots.category_id\n"
        "  JOIN cities ON cities.id = spots.city_id\n"
        " WHERE cities.country = ?\n"
        f"   AND categories.name IN ({placeholders})\n"
        " ORDER BY cities.name, spots.title;",
        (country_name, *categories),
    ).fetchall()


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_city_spots(conn: sqlite3.Connection, city_name: str, query: str) -> list[sqlite3.Row]:
    pattern = f"%{_escape_like(query)}%"
    return conn.execute(
        "SELECT spots.title, spots.lat, spots.lng, spots.note, categories.name AS category, "
        "spots.maps_url\n"
        "  FROM spots\n"
        "  JOIN categories ON categories.id = spots.category_id\n"
        " WHERE spots.city_id = (SELECT id FROM cities WHERE name = ?)\n"
        "   AND (spots.title LIKE ? ESCAPE '\\' OR spots.note LIKE ? ESCAPE '\\')\n"
        " ORDER BY spots.title;",
        (city_name, pattern, pattern),
    ).fetchall()

from typing import Any, Iterable


def build_map_payload(label: str, spots: Iterable[Any]) -> dict:
    """`label` is a city name for a single-city map, or a country name when `spots` spans
    multiple cities (in which case each row also carries a `city` column, included per
    marker so the map/model can tell them apart)."""
    markers = []
    for row in spots:
        marker = {
            "title": row["title"],
            "lat": row["lat"],
            "lng": row["lng"],
            "note": row["note"] or "",
            "category": row["category"],
            "maps_url": row["maps_url"],
        }
        if "city" in row.keys():
            marker["city"] = row["city"]
        markers.append(marker)
    return {"city": label, "markers": markers}

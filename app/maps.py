from typing import Any, Iterable

# Optional per-spot enrichment columns (from spot_details, via scripts/enrich_places.py).
# Included in a marker only when the underlying row actually carries the column (older
# queries, or a spot never enriched, simply won't have it) and the value isn't NULL.
# review_count is deliberately excluded — the detail view shows the owner's own saved
# note instead of anything review-related.
_OPTIONAL_DETAIL_FIELDS = ("rating", "phone", "website")


def _photo_url(row: Any) -> str | None:
    if "photo_path" in row.keys() and row["photo_path"]:
        return f"/static/{row['photo_path']}"
    return None


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
        for field in _OPTIONAL_DETAIL_FIELDS:
            if field in row.keys() and row[field] is not None:
                marker[field] = row[field]
        photo_url = _photo_url(row)
        if photo_url:
            marker["photo_url"] = photo_url
        markers.append(marker)
    return {"city": label, "markers": markers}

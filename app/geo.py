import math
from typing import Any, Iterable

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two lat/lng points, in kilometers."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    a = min(1.0, max(0.0, a))  # guard against floating-point drift pushing a fraction past 1
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def filter_within_radius(spots: Iterable[Any], lat: float, lng: float, radius_km: float) -> list:
    """Keeps only rows whose (lat, lng) is within radius_km of (lat, lng)."""
    return [row for row in spots if haversine_km(lat, lng, row["lat"], row["lng"]) <= radius_km]

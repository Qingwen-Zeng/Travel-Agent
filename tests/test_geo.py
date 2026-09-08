from app.geo import filter_within_radius, haversine_km


def test_haversine_km_is_zero_for_identical_points():
    assert haversine_km(48.8584, 2.2945, 48.8584, 2.2945) == 0.0


def test_haversine_km_matches_known_distance_paris_landmarks():
    # Eiffel Tower to the Louvre is a well-known ~3.2 km distance.
    eiffel = (48.8584, 2.2945)
    louvre = (48.8606, 2.3376)

    distance = haversine_km(*eiffel, *louvre)

    assert 3.0 < distance < 3.5


def test_filter_within_radius_keeps_only_nearby_rows():
    eiffel_lat, eiffel_lng = 48.8584, 2.2945
    rows = [
        {"title": "Near Eiffel", "lat": 48.8590, "lng": 2.2950},  # a few hundred meters away
        {"title": "Far Away (Louvre)", "lat": 48.8606, "lng": 2.3376},  # ~3.2 km away
    ]

    results = filter_within_radius(rows, eiffel_lat, eiffel_lng, radius_km=1.0)

    assert [r["title"] for r in results] == ["Near Eiffel"]


def test_filter_within_radius_returns_empty_list_when_nothing_matches():
    rows = [{"title": "Far Away", "lat": 0.0, "lng": 0.0}]

    results = filter_within_radius(rows, 48.8584, 2.2945, radius_km=1.0)

    assert results == []


def test_filter_within_radius_returns_empty_list_for_empty_input():
    assert filter_within_radius([], 48.8584, 2.2945, radius_km=1.0) == []

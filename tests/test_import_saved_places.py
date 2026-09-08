import csv
from pathlib import Path

import pytest
import requests

from app.db import get_writable_connection
from scripts.import_saved_places import (
    GeocodeResult,
    GooglePlacesGeocoder,
    ImportAbortError,
    normalize_category,
    parse_filename,
    run_import,
)


class FakeGeocoder:
    def __init__(self, results: dict[str, GeocodeResult]):
        self._results = results
        self.calls: list[tuple[str, str]] = []

    def geocode(self, title, city):
        self.calls.append((title, city))
        return self._results.get(title)


def _write_csv(path: Path, rows: list[tuple[str, str, str]]):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Title", "Note", "URL", "Tags", "Comment"])
        writer.writerow(["", "", "", "", ""])
        for title, note, url in rows:
            writer.writerow([title, note, url, "", ""])


def _url(feature_id: str) -> str:
    return f"https://www.google.com/maps/place/Spot/data=!4m2!3m1!1s{feature_id}"


# --- filename parsing (relocated from saved_places_db/build_db.py) ---


def test_parse_filename_splits_city_and_category():
    assert parse_filename("Paris Restaurants") == ("Paris", "Restaurants")


def test_parse_filename_handles_category_first_pattern():
    assert parse_filename("Gay Things To Do San Diego") == ("San Diego", "Gay Experience")


def test_parse_filename_strips_duplicate_suffix():
    assert parse_filename("Chicago Restaurants(1)") == ("Chicago", "Restaurants")


def test_parse_filename_returns_none_for_unknown_category():
    assert parse_filename("Totally Unknown Bucket") is None


def test_normalize_category_merges_and_title_cases():
    assert normalize_category("things to do") == "Things To Do"
    assert normalize_category("things to see") == "Things To Do"
    assert normalize_category("gay bars") == "Gay Experience"
    assert normalize_category("bars") == "Bars And Clubs"
    assert normalize_category("desserts") == "Desserts"
    assert normalize_category("dessert places") == "Desserts"


# --- run_import ---


def test_run_import_geocodes_and_writes_spots(tmp_path):
    saved_dir = tmp_path / "Saved"
    saved_dir.mkdir()
    _write_csv(
        saved_dir / "Testville Restaurants.csv",
        [("Cafe A", "Great coffee", _url("0x1:0x1")), ("Cafe B", "", _url("0x1:0x2"))],
    )

    geocoder = FakeGeocoder(
        {
            "Cafe A": GeocodeResult(place_id="p1", lat=1.0, lng=2.0),
            "Cafe B": GeocodeResult(place_id="p2", lat=3.0, lng=4.0),
        }
    )

    db_path = tmp_path / "travel.db"
    summary = run_import(saved_dir, db_path, geocoder)

    assert summary.added == 2
    assert summary.skipped == []

    conn = get_writable_connection(db_path)
    rows = conn.execute(
        "SELECT s.title, s.lat, s.lng, s.note, c.name AS category, ci.name AS city "
        "FROM spots s JOIN categories c ON c.id = s.category_id "
        "JOIN cities ci ON ci.id = s.city_id ORDER BY s.title"
    ).fetchall()
    assert [dict(r) for r in rows] == [
        {"title": "Cafe A", "lat": 1.0, "lng": 2.0, "note": "Great coffee", "category": "Restaurants", "city": "Testville"},
        {"title": "Cafe B", "lat": 3.0, "lng": 4.0, "note": "", "category": "Restaurants", "city": "Testville"},
    ]


def test_run_import_computes_city_centroid_and_spot_count(tmp_path):
    saved_dir = tmp_path / "Saved"
    saved_dir.mkdir()
    _write_csv(saved_dir / "Testville Restaurants.csv", [("A", "", _url("0x1:0x1"))])
    _write_csv(saved_dir / "Testville Desserts.csv", [("B", "", _url("0x1:0x2"))])

    geocoder = FakeGeocoder(
        {
            "A": GeocodeResult(place_id="p1", lat=10.0, lng=20.0),
            "B": GeocodeResult(place_id="p2", lat=30.0, lng=40.0),
        }
    )

    db_path = tmp_path / "travel.db"
    run_import(saved_dir, db_path, geocoder)

    conn = get_writable_connection(db_path)
    city = conn.execute("SELECT center_lat, center_lng, spot_count FROM cities WHERE name = 'Testville'").fetchone()
    assert city["center_lat"] == 20.0
    assert city["center_lng"] == 30.0
    assert city["spot_count"] == 2


def test_unresolvable_spot_is_skipped_and_reported_not_aborted(tmp_path):
    saved_dir = tmp_path / "Saved"
    saved_dir.mkdir()
    _write_csv(
        saved_dir / "Testville Restaurants.csv",
        [("Findable", "", _url("0x1:0x1")), ("Ghost Cafe", "", _url("0x1:0x2"))],
    )

    geocoder = FakeGeocoder({"Findable": GeocodeResult(place_id="p1", lat=1.0, lng=2.0)})

    db_path = tmp_path / "travel.db"
    summary = run_import(saved_dir, db_path, geocoder)

    assert summary.added == 1
    assert len(summary.skipped) == 1
    assert summary.skipped[0][2] == "Ghost Cafe"

    conn = get_writable_connection(db_path)
    count = conn.execute("SELECT COUNT(*) AS n FROM spots").fetchone()["n"]
    assert count == 1


def test_same_place_saved_under_two_categories_produces_two_rows(tmp_path):
    saved_dir = tmp_path / "Saved"
    saved_dir.mkdir()
    _write_csv(saved_dir / "Testville Restaurants.csv", [("Dual Spot", "", _url("0x1:0x1"))])
    _write_csv(saved_dir / "Testville Bars.csv", [("Dual Spot", "", _url("0x1:0x1"))])

    geocoder = FakeGeocoder({"Dual Spot": GeocodeResult(place_id="p1", lat=1.0, lng=2.0)})

    db_path = tmp_path / "travel.db"
    summary = run_import(saved_dir, db_path, geocoder)

    assert summary.added == 2
    conn = get_writable_connection(db_path)
    count = conn.execute("SELECT COUNT(*) AS n FROM spots WHERE ftid = '0x1:0x1'").fetchone()["n"]
    assert count == 2


def test_duplicate_suffixed_files_for_same_city_category_are_merged_not_overwritten(tmp_path):
    # "Chicago Restaurants.csv" and "Chicago Restaurants(1).csv" both parse to the same
    # (city, category) pair. Rows unique to one file must not be deleted by the other
    # file's "remove rows no longer present" cleanup.
    saved_dir = tmp_path / "Saved"
    saved_dir.mkdir()
    _write_csv(saved_dir / "Testville Restaurants.csv", [("Only In First", "", _url("0x1:0x1"))])
    _write_csv(saved_dir / "Testville Restaurants(1).csv", [("Only In Second", "", _url("0x1:0x2"))])

    geocoder = FakeGeocoder(
        {
            "Only In First": GeocodeResult(place_id="p1", lat=1.0, lng=2.0),
            "Only In Second": GeocodeResult(place_id="p2", lat=3.0, lng=4.0),
        }
    )

    db_path = tmp_path / "travel.db"
    summary = run_import(saved_dir, db_path, geocoder)

    assert summary.added == 2
    assert summary.removed == 0
    conn = get_writable_connection(db_path)
    titles = {r["title"] for r in conn.execute("SELECT title FROM spots")}
    assert titles == {"Only In First", "Only In Second"}


def test_rerun_does_not_reissue_geocoding_calls_for_already_resolved_spots(tmp_path):
    saved_dir = tmp_path / "Saved"
    saved_dir.mkdir()
    _write_csv(saved_dir / "Testville Restaurants.csv", [("Cafe A", "", _url("0x1:0x1"))])

    db_path = tmp_path / "travel.db"
    first_geocoder = FakeGeocoder({"Cafe A": GeocodeResult(place_id="p1", lat=1.0, lng=2.0)})
    run_import(saved_dir, db_path, first_geocoder)
    assert first_geocoder.calls == [("Cafe A", "Testville")]

    second_geocoder = FakeGeocoder({"Cafe A": GeocodeResult(place_id="p1", lat=1.0, lng=2.0)})
    summary = run_import(saved_dir, db_path, second_geocoder)

    assert second_geocoder.calls == []
    assert summary.unchanged == 1
    assert summary.added == 0


def test_rerun_updates_changed_note_without_a_geocoding_call(tmp_path):
    saved_dir = tmp_path / "Saved"
    saved_dir.mkdir()
    _write_csv(saved_dir / "Testville Restaurants.csv", [("Cafe A", "old note", _url("0x1:0x1"))])

    db_path = tmp_path / "travel.db"
    run_import(saved_dir, db_path, FakeGeocoder({"Cafe A": GeocodeResult(place_id="p1", lat=1.0, lng=2.0)}))

    _write_csv(saved_dir / "Testville Restaurants.csv", [("Cafe A", "new note", _url("0x1:0x1"))])
    second_geocoder = FakeGeocoder({"Cafe A": GeocodeResult(place_id="p1", lat=1.0, lng=2.0)})
    summary = run_import(saved_dir, db_path, second_geocoder)

    assert second_geocoder.calls == []
    assert summary.updated == 1

    conn = get_writable_connection(db_path)
    note = conn.execute("SELECT note FROM spots WHERE ftid = '0x1:0x1'").fetchone()["note"]
    assert note == "new note"


def test_rerun_removes_spot_no_longer_in_the_csv(tmp_path):
    saved_dir = tmp_path / "Saved"
    saved_dir.mkdir()
    _write_csv(
        saved_dir / "Testville Restaurants.csv",
        [("Cafe A", "", _url("0x1:0x1")), ("Cafe B", "", _url("0x1:0x2"))],
    )
    db_path = tmp_path / "travel.db"
    run_import(
        saved_dir,
        db_path,
        FakeGeocoder(
            {
                "Cafe A": GeocodeResult(place_id="p1", lat=1.0, lng=2.0),
                "Cafe B": GeocodeResult(place_id="p2", lat=3.0, lng=4.0),
            }
        ),
    )

    _write_csv(saved_dir / "Testville Restaurants.csv", [("Cafe A", "", _url("0x1:0x1"))])
    summary = run_import(saved_dir, db_path, FakeGeocoder({"Cafe A": GeocodeResult(place_id="p1", lat=1.0, lng=2.0)}))

    assert summary.removed == 1
    conn = get_writable_connection(db_path)
    count = conn.execute("SELECT COUNT(*) AS n FROM spots").fetchone()["n"]
    assert count == 1


def test_generic_non_city_lists_are_excluded(tmp_path):
    saved_dir = tmp_path / "Saved"
    saved_dir.mkdir()
    _write_csv(saved_dir / "Want to go.csv", [("Random Spot", "", _url("0x1:0x1"))])

    db_path = tmp_path / "travel.db"
    summary = run_import(saved_dir, db_path, FakeGeocoder({}))

    assert summary.added == 0
    conn = get_writable_connection(db_path)
    count = conn.execute("SELECT COUNT(*) AS n FROM spots").fetchone()["n"]
    assert count == 0


def test_row_with_no_feature_id_is_skipped_not_aborted(tmp_path):
    saved_dir = tmp_path / "Saved"
    saved_dir.mkdir()
    with (saved_dir / "Testville Restaurants.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Title", "Note", "URL", "Tags", "Comment"])
        writer.writerow(["", "", "", "", ""])
        writer.writerow(["No Maps Link", "", "https://example.com/not-a-maps-url", "", ""])
        writer.writerow(["Real Spot", "", _url("0x1:0x1"), "", ""])

    db_path = tmp_path / "travel.db"
    summary = run_import(
        saved_dir, db_path, FakeGeocoder({"Real Spot": GeocodeResult(place_id="p1", lat=1.0, lng=2.0)})
    )

    assert summary.added == 1
    assert len(summary.skipped) == 1
    assert summary.skipped[0][2] == "No Maps Link"


def test_missing_required_column_raises_abort_error(tmp_path):
    saved_dir = tmp_path / "Saved"
    saved_dir.mkdir()
    with (saved_dir / "Testville Restaurants.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Note", "URL"])
        writer.writerow(["n", "u"])

    db_path = tmp_path / "travel.db"
    with pytest.raises(ImportAbortError):
        run_import(saved_dir, db_path, FakeGeocoder({}))


def test_stray_leading_description_line_before_header_is_handled(tmp_path):
    saved_dir = tmp_path / "Saved"
    saved_dir.mkdir()
    with (saved_dir / "Testville Bars.csv").open("w", newline="", encoding="utf-8") as f:
        f.write("Straight bar. Great vibe\n\n")
        writer = csv.writer(f)
        writer.writerow(["Title", "Note", "URL", "Tags", "Comment"])
        writer.writerow(["", "", "", "", ""])
        writer.writerow(["Real Spot", "", _url("0x1:0x1"), "", ""])

    db_path = tmp_path / "travel.db"
    summary = run_import(
        saved_dir, db_path, FakeGeocoder({"Real Spot": GeocodeResult(place_id="p1", lat=1.0, lng=2.0)})
    )

    assert summary.added == 1
    assert summary.skipped == []


class _FlakyThenOkSession:
    def __init__(self, fail_times):
        self._fail_times = fail_times
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise requests.exceptions.ReadTimeout("simulated timeout")
        return _FakeResponse({"places": [{"id": "p1", "location": {"latitude": 1.0, "longitude": 2.0}}]})


class _AlwaysFailsSession:
    def __init__(self):
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        raise requests.exceptions.ReadTimeout("simulated timeout")


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_google_places_geocoder_retries_transient_failures(monkeypatch):
    monkeypatch.setattr("scripts.import_saved_places.time.sleep", lambda seconds: None)
    session = _FlakyThenOkSession(fail_times=2)
    geocoder = GooglePlacesGeocoder(api_key="unused", session=session)

    result = geocoder.geocode("Cafe A", "Testville")

    assert result == GeocodeResult(place_id="p1", lat=1.0, lng=2.0)
    assert session.calls == 3


def test_google_places_geocoder_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr("scripts.import_saved_places.time.sleep", lambda seconds: None)
    session = _AlwaysFailsSession()
    geocoder = GooglePlacesGeocoder(api_key="unused", session=session)

    result = geocoder.geocode("Cafe A", "Testville")

    assert result is None
    assert session.calls == 3

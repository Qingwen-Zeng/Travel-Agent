from app.db import get_writable_connection
from scripts.enrich_places import PlaceDetails, run_enrich


class FakeDetailsFetcher:
    def __init__(self, results: dict[str, PlaceDetails]):
        self._results = results
        self.calls: list[str] = []

    def fetch(self, place_id):
        self.calls.append(place_id)
        return self._results.get(place_id)


class FakePhotoDownloader:
    def __init__(self, photos: dict[str, bytes]):
        self._photos = photos
        self.calls: list[str] = []

    def download(self, photo_name):
        self.calls.append(photo_name)
        return self._photos.get(photo_name)


def _seed_spot(conn, title="Pralus", place_id="place-1", ftid="f1"):
    conn.execute("INSERT INTO cities (name) VALUES ('Paris')")
    city_id = conn.execute("SELECT id FROM cities WHERE name = 'Paris'").fetchone()["id"]
    conn.execute("INSERT INTO categories (name) VALUES ('Desserts')")
    category_id = conn.execute("SELECT id FROM categories WHERE name = 'Desserts'").fetchone()["id"]
    conn.execute(
        "INSERT INTO spots (city_id, category_id, title, lat, lng, place_id, ftid, maps_url) "
        "VALUES (?, ?, ?, 48.86, 2.35, ?, ?, 'https://maps/1')",
        (city_id, category_id, title, place_id, ftid),
    )
    conn.commit()
    return conn.execute("SELECT id FROM spots WHERE title = ?", (title,)).fetchone()["id"]


def test_run_enrich_writes_rating_phone_website(tmp_path):
    db_path = tmp_path / "travel.db"
    conn = get_writable_connection(db_path)
    spot_id = _seed_spot(conn)
    conn.close()

    details_fetcher = FakeDetailsFetcher(
        {
            "place-1": PlaceDetails(
                rating=4.5,
                phone="+33 1 23 45 67 89",
                website="https://pralus.fr",
                photo_name=None,
            )
        }
    )
    photo_downloader = FakePhotoDownloader({})

    summary = run_enrich(db_path, tmp_path / "photos", details_fetcher, photo_downloader)

    conn = get_writable_connection(db_path)
    row = conn.execute("SELECT * FROM spot_details WHERE spot_id = ?", (spot_id,)).fetchone()

    assert row["rating"] == 4.5
    assert row["phone"] == "+33 1 23 45 67 89"
    assert row["website"] == "https://pralus.fr"
    assert row["photo_path"] is None
    assert summary.enriched == 1
    assert summary.photos_saved == 0


def test_run_enrich_downloads_and_saves_photo(tmp_path):
    db_path = tmp_path / "travel.db"
    conn = get_writable_connection(db_path)
    spot_id = _seed_spot(conn)
    conn.close()

    details_fetcher = FakeDetailsFetcher(
        {
            "place-1": PlaceDetails(
                rating=4.5,
                phone=None,
                website=None,
                photo_name="places/place-1/photos/abc",
            )
        }
    )
    photo_downloader = FakePhotoDownloader({"places/place-1/photos/abc": b"fake-jpeg-bytes"})
    photos_dir = tmp_path / "photos"

    summary = run_enrich(db_path, photos_dir, details_fetcher, photo_downloader)

    conn = get_writable_connection(db_path)
    row = conn.execute("SELECT photo_path FROM spot_details WHERE spot_id = ?", (spot_id,)).fetchone()

    assert row["photo_path"] == f"spot_photos/{spot_id}.jpg"
    assert (photos_dir / f"{spot_id}.jpg").read_bytes() == b"fake-jpeg-bytes"
    assert summary.photos_saved == 1


def test_run_enrich_skips_spot_with_no_place_id(tmp_path):
    db_path = tmp_path / "travel.db"
    conn = get_writable_connection(db_path)
    conn.execute("INSERT INTO cities (name) VALUES ('Paris')")
    city_id = conn.execute("SELECT id FROM cities WHERE name = 'Paris'").fetchone()["id"]
    conn.execute("INSERT INTO categories (name) VALUES ('Desserts')")
    category_id = conn.execute("SELECT id FROM categories WHERE name = 'Desserts'").fetchone()["id"]
    conn.execute(
        "INSERT INTO spots (city_id, category_id, title, lat, lng, ftid, maps_url) "
        "VALUES (?, ?, 'No Place ID', 48.86, 2.35, 'f1', 'https://maps/1')",
        (city_id, category_id),
    )
    conn.commit()
    conn.close()

    summary = run_enrich(db_path, tmp_path / "photos", FakeDetailsFetcher({}), FakePhotoDownloader({}))

    assert summary.enriched == 0
    assert summary.skipped == [("No Place ID", "no place_id")]


def test_run_enrich_skips_and_reports_failed_details_fetch(tmp_path):
    db_path = tmp_path / "travel.db"
    conn = get_writable_connection(db_path)
    _seed_spot(conn)
    conn.close()

    summary = run_enrich(
        db_path, tmp_path / "photos", FakeDetailsFetcher({}), FakePhotoDownloader({})
    )

    assert summary.enriched == 0
    assert summary.skipped == [("Pralus", "Place Details request failed")]


def test_run_enrich_is_idempotent_skipping_already_enriched_spots(tmp_path):
    db_path = tmp_path / "travel.db"
    conn = get_writable_connection(db_path)
    _seed_spot(conn)
    conn.close()

    details_fetcher = FakeDetailsFetcher(
        {"place-1": PlaceDetails(rating=4.5, phone=None, website=None, photo_name=None)}
    )
    photo_downloader = FakePhotoDownloader({})

    run_enrich(db_path, tmp_path / "photos", details_fetcher, photo_downloader)
    summary = run_enrich(db_path, tmp_path / "photos", details_fetcher, photo_downloader)

    assert summary.enriched == 0
    assert summary.already_enriched == 1
    assert len(details_fetcher.calls) == 1  # not called again on the second run

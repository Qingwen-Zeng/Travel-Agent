"""Enriches saved spots with real Google Place data — rating, review count, phone,
website, and one photo — via Places API (New) Place Details, using each spot's
`place_id` already captured at import time. Runs offline, once, on the owner's machine
(same as scripts/import_saved_places.py): the web app never calls this API itself.

Photos are downloaded once and saved as local files under --photos-dir (served by the
app's own StaticFiles mount), not re-fetched from Google on every request.

Safe to re-run: spots that already have a spot_details row are skipped, so re-running
after adding new saved spots only spends money on the new ones. Unresolvable spots (no
place_id, or every field request fails) are skipped and reported, not aborted.

Usage: python scripts/enrich_places.py [--db travel.db] [--photos-dir app/static/spot_photos]
"""

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_writable_connection

PLACE_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
# No review count — the owner's own saved note is shown instead of anything review-related.
PLACE_DETAILS_FIELD_MASK = "rating,nationalPhoneNumber,websiteUri,photos"
PHOTO_MEDIA_URL = "https://places.googleapis.com/v1/{photo_name}/media"
PHOTO_MAX_WIDTH_PX = 800

REQUEST_MAX_ATTEMPTS = 3
REQUEST_TIMEOUT_SECONDS = 30
REQUEST_RETRY_BACKOFF_SECONDS = 2


@dataclass(frozen=True)
class PlaceDetails:
    rating: Optional[float]
    phone: Optional[str]
    website: Optional[str]
    photo_name: Optional[str]  # Google's photo resource name, not yet downloaded


class DetailsFetcher(Protocol):
    def fetch(self, place_id: str) -> Optional[PlaceDetails]: ...


class PhotoDownloader(Protocol):
    def download(self, photo_name: str) -> Optional[bytes]: ...


@dataclass
class EnrichSummary:
    enriched: int = 0
    photos_saved: int = 0
    already_enriched: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (title, reason)

    def __str__(self) -> str:
        lines = [
            f"{self.enriched} enriched ({self.photos_saved} with a photo), "
            f"{self.already_enriched} already done"
        ]
        if self.skipped:
            lines.append(f"{len(self.skipped)} skipped:")
            for title, reason in self.skipped:
                lines.append(f'  "{title}": {reason}')
        return "\n".join(lines)


def run_enrich(
    db_path: Path,
    photos_dir: Path,
    details_fetcher: DetailsFetcher,
    photo_downloader: PhotoDownloader,
) -> EnrichSummary:
    conn = get_writable_connection(db_path)
    summary = EnrichSummary()

    try:
        already_done = {
            row["spot_id"] for row in conn.execute("SELECT spot_id FROM spot_details")
        }
        spots = conn.execute("SELECT id, title, place_id FROM spots").fetchall()

        for spot in spots:
            if spot["id"] in already_done:
                summary.already_enriched += 1
                continue

            if not spot["place_id"]:
                summary.skipped.append((spot["title"], "no place_id"))
                continue

            details = details_fetcher.fetch(spot["place_id"])
            if details is None:
                summary.skipped.append((spot["title"], "Place Details request failed"))
                continue

            photo_path = None
            if details.photo_name:
                photo_bytes = photo_downloader.download(details.photo_name)
                if photo_bytes:
                    photos_dir.mkdir(parents=True, exist_ok=True)
                    file_path = photos_dir / f"{spot['id']}.jpg"
                    file_path.write_bytes(photo_bytes)
                    photo_path = f"spot_photos/{spot['id']}.jpg"
                    summary.photos_saved += 1

            conn.execute(
                "INSERT INTO spot_details (spot_id, rating, phone, website, photo_path) "
                "VALUES (?, ?, ?, ?, ?)",
                (spot["id"], details.rating, details.phone, details.website, photo_path),
            )
            summary.enriched += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return summary


class GooglePlaceDetailsFetcher:
    def __init__(self, api_key: str, session: Optional[requests.Session] = None):
        self._api_key = api_key
        self._session = session or requests.Session()

    def fetch(self, place_id: str) -> Optional[PlaceDetails]:
        response = None
        for attempt in range(1, REQUEST_MAX_ATTEMPTS + 1):
            try:
                response = self._session.get(
                    PLACE_DETAILS_URL.format(place_id=place_id),
                    headers={
                        "X-Goog-Api-Key": self._api_key,
                        "X-Goog-FieldMask": PLACE_DETAILS_FIELD_MASK,
                    },
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                break
            except requests.exceptions.RequestException:
                if attempt == REQUEST_MAX_ATTEMPTS:
                    return None
                time.sleep(REQUEST_RETRY_BACKOFF_SECONDS * attempt)

        data = response.json()
        photos = data.get("photos", [])
        return PlaceDetails(
            rating=data.get("rating"),
            phone=data.get("nationalPhoneNumber"),
            website=data.get("websiteUri"),
            photo_name=photos[0].get("name") if photos else None,
        )


class GooglePhotoDownloader:
    def __init__(self, api_key: str, session: Optional[requests.Session] = None):
        self._api_key = api_key
        self._session = session or requests.Session()

    def download(self, photo_name: str) -> Optional[bytes]:
        for attempt in range(1, REQUEST_MAX_ATTEMPTS + 1):
            try:
                response = self._session.get(
                    PHOTO_MEDIA_URL.format(photo_name=photo_name),
                    params={"maxWidthPx": PHOTO_MAX_WIDTH_PX, "key": self._api_key},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                return response.content
            except requests.exceptions.RequestException:
                if attempt == REQUEST_MAX_ATTEMPTS:
                    return None
                time.sleep(REQUEST_RETRY_BACKOFF_SECONDS * attempt)
        return None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Enrich saved spots with real Google Place data.")
    parser.add_argument("--db", default="travel.db", type=Path)
    parser.add_argument("--photos-dir", default=Path("app/static/spot_photos"), type=Path)
    args = parser.parse_args(argv)

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        print("GOOGLE_PLACES_API_KEY is not set.", file=sys.stderr)
        return 2

    details_fetcher = GooglePlaceDetailsFetcher(api_key)
    photo_downloader = GooglePhotoDownloader(api_key)

    summary = run_enrich(args.db, args.photos_dir, details_fetcher, photo_downloader)

    print(f"{args.db}: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

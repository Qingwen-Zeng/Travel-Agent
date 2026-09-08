import time
from datetime import datetime, timezone
from typing import Callable

CAPPED_MESSAGE = (
    "I've reached my message limit for now — feel free to keep browsing the saved city "
    "maps while you wait!"
)


class RateLimitExceeded(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class PerIPRateLimiter:
    """Fixed-window counter, keyed per caller (IP address)."""

    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.time):
        self._limit = limit
        self._window_seconds = window_seconds
        self._clock = clock
        self._counts: dict[str, tuple[int, float]] = {}

    def check(self, key: str) -> None:
        now = self._clock()
        count, window_start = self._counts.get(key, (0, now))

        if now - window_start >= self._window_seconds:
            count, window_start = 0, now

        count += 1
        self._counts[key] = (count, window_start)

        if count > self._limit:
            raise RateLimitExceeded(CAPPED_MESSAGE)


class DailyMessageCap:
    """Site-wide counter that resets at each new UTC calendar day."""

    def __init__(self, limit: int, clock: Callable[[], float] = time.time):
        self._limit = limit
        self._clock = clock
        self._count = 0
        self._day = None

    def check(self) -> None:
        today = datetime.fromtimestamp(self._clock(), tz=timezone.utc).date()

        if today != self._day:
            self._day = today
            self._count = 0

        self._count += 1

        if self._count > self._limit:
            raise RateLimitExceeded(CAPPED_MESSAGE)

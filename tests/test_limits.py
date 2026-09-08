from datetime import datetime, timedelta, timezone

import pytest

from app.limits import CAPPED_MESSAGE, DailyMessageCap, PerIPRateLimiter, RateLimitExceeded


class FakeClock:
    def __init__(self, start=0.0):
        self.now = start

    def __call__(self):
        return self.now


def test_per_ip_limiter_allows_requests_up_to_limit():
    clock = FakeClock()
    limiter = PerIPRateLimiter(limit=3, window_seconds=3600, clock=clock)

    for _ in range(3):
        limiter.check("1.2.3.4")  # should not raise


def test_per_ip_limiter_rejects_after_threshold():
    clock = FakeClock()
    limiter = PerIPRateLimiter(limit=2, window_seconds=3600, clock=clock)

    limiter.check("1.2.3.4")
    limiter.check("1.2.3.4")

    with pytest.raises(RateLimitExceeded) as exc_info:
        limiter.check("1.2.3.4")

    assert exc_info.value.message == CAPPED_MESSAGE


def test_per_ip_limiter_resets_after_window():
    clock = FakeClock()
    limiter = PerIPRateLimiter(limit=2, window_seconds=3600, clock=clock)

    limiter.check("1.2.3.4")
    limiter.check("1.2.3.4")
    with pytest.raises(RateLimitExceeded):
        limiter.check("1.2.3.4")

    clock.now += 3600.1

    limiter.check("1.2.3.4")  # should not raise, window reset


def test_per_ip_limiter_tracks_keys_independently():
    clock = FakeClock()
    limiter = PerIPRateLimiter(limit=1, window_seconds=3600, clock=clock)

    limiter.check("1.2.3.4")
    limiter.check("5.6.7.8")  # different IP, should not raise


def test_daily_cap_allows_requests_up_to_limit():
    clock = FakeClock()
    cap = DailyMessageCap(limit=3, clock=clock)

    for _ in range(3):
        cap.check()


def test_daily_cap_rejects_after_threshold():
    clock = FakeClock()
    cap = DailyMessageCap(limit=2, clock=clock)

    cap.check()
    cap.check()

    with pytest.raises(RateLimitExceeded) as exc_info:
        cap.check()

    assert exc_info.value.message == CAPPED_MESSAGE


def test_daily_cap_resets_on_new_calendar_day():
    start = datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)
    clock = FakeClock(start.timestamp())
    cap = DailyMessageCap(limit=1, clock=clock)

    cap.check()
    with pytest.raises(RateLimitExceeded):
        cap.check()

    next_day = start + timedelta(hours=2)  # crosses midnight UTC
    clock.now = next_day.timestamp()

    cap.check()  # should not raise, new calendar day

"""Tests for quota tracking."""

import os
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from youtube_mcp.utils.quota import QuotaExhaustedError, QuotaTracker


def _pacific_today() -> date:
    return datetime.now(ZoneInfo("America/Los_Angeles")).date()


def test_initial_state():
    tracker = QuotaTracker(daily_limit=10_000)
    assert tracker.used == 0
    assert tracker.remaining == 10_000


def test_consume_list():
    tracker = QuotaTracker()
    tracker.consume("list")
    assert tracker.used == 1


def test_consume_search():
    tracker = QuotaTracker()
    tracker.consume("search")
    assert tracker.used == 100


def test_consume_multiple():
    tracker = QuotaTracker()
    tracker.consume("list")
    tracker.consume("search")
    tracker.consume("list", count=3)
    assert tracker.used == 104  # 1 + 100 + 3


def test_exhaust_quota():
    tracker = QuotaTracker(daily_limit=50)
    tracker.consume("list", count=50)
    with pytest.raises(QuotaExhaustedError) as exc_info:
        tracker.consume("list")
    assert exc_info.value.used == 50
    assert exc_info.value.limit == 50


def test_exhaust_quota_search():
    tracker = QuotaTracker(daily_limit=150)
    tracker.consume("search")  # 100
    with pytest.raises(QuotaExhaustedError):
        tracker.consume("search")  # would be 200, over 150


def test_status():
    tracker = QuotaTracker(daily_limit=10_000)
    tracker.consume("search")
    status = tracker.status()
    assert status["used"] == 100
    assert status["remaining"] == 9_900
    assert status["limit"] == 10_000
    assert status["date"] == str(_pacific_today())


def test_resets_on_new_day():
    tracker = QuotaTracker(daily_limit=10_000)
    tracker.consume("search")
    assert tracker.used == 100

    # Simulate next day
    with patch("youtube_mcp.utils.quota._quota_day", return_value=date(2099, 1, 1)):
        assert tracker.used == 0
        assert tracker.remaining == 10_000


def test_unknown_operation_defaults_to_1():
    tracker = QuotaTracker()
    tracker.consume("some_unknown_op")
    assert tracker.used == 1


def test_caption_costs_match_google():
    """Regression (B7/B8): captions.list costs 50 units, captions.download 200."""
    tracker = QuotaTracker()
    tracker.consume("caption_list")
    assert tracker.used == 50
    tracker.consume("caption_download")
    assert tracker.used == 250


def _fake_clock(utc_instant):
    """A datetime subclass whose now(tz) returns a fixed UTC instant."""

    class _FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return utc_instant.astimezone(tz)

    return _FakeDatetime


def test_quota_day_follows_pacific_midnight():
    """Regression (B12): the quota day rolls over at midnight Pacific Time,
    not at the host's local midnight."""
    def clock(utc_instant):
        return patch("youtube_mcp.utils.quota.datetime", _fake_clock(utc_instant), create=True)

    # 2026-11-23 20:00 UTC = 12:00 PST on 11-23.
    with clock(datetime(2026, 11, 23, 20, 0, tzinfo=timezone.utc)):
        tracker = QuotaTracker(daily_limit=10_000)
        tracker.consume("search", count=90)
        assert tracker.status()["date"] == "2026-11-23"

    # 2026-11-24 00:30 UTC = 16:30 PST on 11-23: same Google quota day.
    with clock(datetime(2026, 11, 24, 0, 30, tzinfo=timezone.utc)):
        assert tracker.used == 9_000
        assert tracker.status()["date"] == "2026-11-23"
        with pytest.raises(QuotaExhaustedError):
            tracker.consume("search", count=11)

    # 2026-11-24 08:01 UTC = 00:01 PST on 11-24: Google has reset the quota.
    with clock(datetime(2026, 11, 24, 8, 1, tzinfo=timezone.utc)):
        assert tracker.used == 0
        assert tracker.status()["date"] == "2026-11-24"
        tracker.consume("search", count=11)
        assert tracker.used == 1_100


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="time.tzset() is POSIX-only")
def test_status_date_is_pacific_regardless_of_host_timezone():
    """Regression (B12): with the real clock, the tracker reports the Pacific
    quota day whatever the host's local time zone. At any instant at least one
    of UTC+14 / UTC-12 has a local date different from the Pacific date."""
    old_tz = os.environ.get("TZ")
    try:
        for host_tz in ("XXX-14", "YYY+12"):  # POSIX TZ strings: UTC+14, UTC-12
            os.environ["TZ"] = host_tz
            time.tzset()
            tracker = QuotaTracker()
            assert tracker.status()["date"] == str(_pacific_today()), host_tz
    finally:
        if old_tz is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = old_tz
        time.tzset()


def test_missing_tz_database_does_not_break_import():
    """B12 fix guard: without an IANA tz database (e.g. Windows without
    tzdata) the quota module must still import and compute a quota day."""
    code = (
        "import sys, zoneinfo\n"
        "zoneinfo.reset_tzpath(to=[])\n"
        "sys.modules['tzdata'] = None\n"
        "from datetime import date\n"
        "from youtube_mcp.utils import quota\n"
        "assert not isinstance(quota._PACIFIC, zoneinfo.ZoneInfo)\n"
        "assert isinstance(quota._quota_day(), date)\n"
        "t = quota.QuotaTracker()\n"
        "t.consume('search')\n"
        "assert t.used == 100\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"

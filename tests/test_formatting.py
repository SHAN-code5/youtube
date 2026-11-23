"""Tests for formatting utilities."""

from youtube_mcp.utils.formatting import (
    _is_likely_short,
    format_count,
    format_duration,
    format_video_summary,
)


class TestFormatDuration:
    def test_seconds_only(self):
        assert format_duration("PT30S") == "30s"

    def test_minutes_and_seconds(self):
        assert format_duration("PT5M30S") == "5m 30s"

    def test_hours_minutes_seconds(self):
        assert format_duration("PT1H2M3S") == "1h 2m 3s"

    def test_minutes_only(self):
        assert format_duration("PT10M") == "10m"

    def test_hours_only(self):
        assert format_duration("PT2H") == "2h"

    def test_zero(self):
        assert format_duration("PT0S") == "0s"

    def test_empty(self):
        assert format_duration("") == "unknown"

    def test_none(self):
        assert format_duration(None) == "unknown"

    def test_day_long_duration(self):
        # Videos >= 1 day use P#DT#H#M#S (P and T separated); used to raise ValueError.
        assert format_duration("P1DT2H3M4S") == "1d 2h 3m 4s"
        assert format_duration("P1DT0H12M3S") == "1d 12m 3s"
        assert format_duration("P2DT13M") == "2d 13m"
        assert format_duration("P1D") == "1d"

    def test_week_duration(self):
        assert format_duration("P3W3DT20H31M21S") == "24d 20h 31m 21s"

    def test_unparseable_does_not_raise(self):
        assert format_duration("PT1.5S") == "unknown"


class TestFormatCount:
    def test_small_number(self):
        assert format_count(42) == "42"

    def test_thousands(self):
        assert format_count(1500) == "1.5K"

    def test_millions(self):
        assert format_count(2_300_000) == "2.3M"

    def test_billions(self):
        assert format_count(1_000_000_000) == "1.0B"

    def test_string_input(self):
        assert format_count("12345") == "12.3K"

    def test_zero(self):
        assert format_count(0) == "0"


class TestIsLikelyShort:
    def test_short_video(self):
        assert _is_likely_short("PT30S") is True

    def test_exactly_60s(self):
        assert _is_likely_short("PT60S") is True
        assert _is_likely_short("PT1M") is True

    def test_over_60s(self):
        assert _is_likely_short("PT1M1S") is False
        assert _is_likely_short("PT2M") is False

    def test_long_video(self):
        assert _is_likely_short("PT1H") is False

    def test_empty(self):
        assert _is_likely_short("") is False

    def test_day_long_duration_is_not_short(self):
        # Used to raise ValueError ('P1DT5M') or return True ('P1D').
        assert _is_likely_short("P1DT5M") is False
        assert _is_likely_short("P2DT13M") is False
        assert _is_likely_short("P1DT2H3M4S") is False
        assert _is_likely_short("P1D") is False
        assert _is_likely_short("P3W3DT20H31M21S") is False

    def test_live_or_upcoming_zero_duration_is_not_short(self):
        # Live/upcoming broadcasts report duration P0D; a zero length is not a Short.
        assert _is_likely_short("P0D") is False
        assert _is_likely_short("PT0S") is False


class TestFormatVideoSummary:
    def test_full_video(self):
        video = {
            "id": "abc123",
            "snippet": {
                "title": "Test Video",
                "channelTitle": "Test Channel",
                "publishedAt": "2025-01-01T00:00:00Z",
                "description": "A test video",
                "tags": ["test", "video"],
                "thumbnails": {"high": {"url": "https://example.com/thumb.jpg"}},
            },
            "statistics": {
                "viewCount": "1000",
                "likeCount": "50",
                "commentCount": "10",
            },
            "contentDetails": {
                "duration": "PT5M30S",
            },
        }

        result = format_video_summary(video)
        assert result["id"] == "abc123"
        assert result["title"] == "Test Video"
        assert result["views"] == 1000
        assert result["likes"] == 50
        assert result["duration"] == "5m 30s"
        assert result["is_short"] is False

    def test_short_video(self):
        video = {
            "id": "short1",
            "snippet": {
                "title": "My Short",
                "channelTitle": "Ch",
                "publishedAt": "2025-06-01T00:00:00Z",
                "description": "",
                "thumbnails": {},
            },
            "statistics": {"viewCount": "50000", "likeCount": "500", "commentCount": "5"},
            "contentDetails": {"duration": "PT45S"},
        }

        result = format_video_summary(video)
        assert result["is_short"] is True
        assert result["duration"] == "45s"

    def test_missing_fields(self):
        video = {"id": "x", "snippet": {}, "statistics": {}, "contentDetails": {}}
        result = format_video_summary(video)
        assert result["id"] == "x"
        assert result["views"] == 0
        assert result["likes"] == 0
        assert result["title"] is None

    def test_day_long_video(self):
        video = {
            "id": "long1",
            "snippet": {"title": "24h stream archive"},
            "statistics": {},
            "contentDetails": {"duration": "P1DT0H12M3S"},
        }
        result = format_video_summary(video)
        assert result["duration"] == "1d 12m 3s"
        assert result["is_short"] is False

    def test_live_broadcast_not_short(self):
        for state in ("live", "upcoming"):
            video = {
                "id": "live1",
                "snippet": {"title": "Stream", "liveBroadcastContent": state},
                "statistics": {},
                "contentDetails": {"duration": "P0D"},
            }
            result = format_video_summary(video)
            assert result["is_short"] is False

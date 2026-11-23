"""Tests for tool functions with mocked YouTube API responses."""

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest


def _make_mock_youtube():
    """Create a mock YouTube Data API service."""
    return MagicMock()


def _make_video_resource(
    video_id="abc123",
    title="Test Video",
    views=1000,
    likes=50,
    comments=10,
    duration="PT5M30S",
):
    """Create a mock YouTube video resource."""
    return {
        "id": video_id,
        "snippet": {
            "title": title,
            "channelTitle": "Test Channel",
            "publishedAt": "2025-01-01T00:00:00Z",
            "description": "Test description",
            "tags": ["test"],
            "thumbnails": {"high": {"url": f"https://i.ytimg.com/vi/{video_id}/hq.jpg"}},
        },
        "statistics": {
            "viewCount": str(views),
            "likeCount": str(likes),
            "commentCount": str(comments),
        },
        "contentDetails": {"duration": duration},
        "status": {
            "privacyStatus": "public",
            "license": "youtube",
            "embeddable": True,
        },
        "topicDetails": {"topicCategories": []},
    }


class TestGetVideo:
    @patch("youtube_mcp.tools.channel.auth")
    @patch("youtube_mcp.tools.channel.quota")
    def test_get_video_found(self, mock_quota, mock_auth):
        from youtube_mcp.tools.channel import youtube_get_video

        mock_yt = _make_mock_youtube()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().list().execute.return_value = {
            "items": [_make_video_resource(video_id="xyz")]
        }

        result = youtube_get_video("xyz")
        assert result["id"] == "xyz"
        assert result["title"] == "Test Video"
        assert result["views"] == 1000
        assert result["privacy"] == "public"
        mock_quota.consume.assert_called_once_with("list")

    @patch("youtube_mcp.tools.channel.auth")
    @patch("youtube_mcp.tools.channel.quota")
    def test_get_video_not_found(self, mock_quota, mock_auth):
        from youtube_mcp.tools.channel import youtube_get_video

        mock_yt = _make_mock_youtube()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().list().execute.return_value = {"items": []}

        result = youtube_get_video("nonexistent")
        assert "error" in result


class TestGetChannel:
    @patch("youtube_mcp.tools.channel.auth")
    @patch("youtube_mcp.tools.channel.quota")
    def test_get_channel_by_handle(self, mock_quota, mock_auth):
        from youtube_mcp.tools.channel import youtube_get_channel

        mock_yt = _make_mock_youtube()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.channels().list().execute.return_value = {
            "items": [{
                "id": "UC123",
                "snippet": {
                    "title": "My Channel",
                    "customUrl": "@mychannel",
                    "description": "A channel",
                    "publishedAt": "2020-01-01T00:00:00Z",
                    "thumbnails": {"high": {"url": "https://example.com/thumb.jpg"}},
                },
                "statistics": {
                    "subscriberCount": "10000",
                    "viewCount": "500000",
                    "videoCount": "100",
                },
                "contentDetails": {
                    "relatedPlaylists": {"uploads": "UU123"},
                },
            }]
        }

        result = youtube_get_channel(handle="@mychannel")
        assert result["id"] == "UC123"
        assert result["subscribers"] == 10000
        assert result["uploads_playlist_id"] == "UU123"

    @patch("youtube_mcp.tools.channel.auth")
    @patch("youtube_mcp.tools.channel.quota")
    def test_get_channel_no_args(self, mock_quota, mock_auth):
        from youtube_mcp.tools.channel import youtube_get_channel

        result = youtube_get_channel()
        assert "error" in result


class TestSearch:
    @patch("youtube_mcp.tools.search.auth")
    @patch("youtube_mcp.tools.search.quota")
    def test_search_videos(self, mock_quota, mock_auth):
        from youtube_mcp.tools.search import youtube_search

        mock_yt = _make_mock_youtube()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.search().list().execute.return_value = {
            "items": [{
                "id": {"videoId": "vid1"},
                "snippet": {
                    "title": "Found Video",
                    "description": "A result",
                    "channelTitle": "Some Channel",
                    "publishedAt": "2025-06-01T00:00:00Z",
                    "thumbnails": {"high": {"url": "https://example.com/thumb.jpg"}},
                },
            }],
            "pageInfo": {"totalResults": 1},
        }

        result = youtube_search("test query")
        assert len(result["results"]) == 1
        assert result["results"][0]["video_id"] == "vid1"
        assert result["quota_cost"] == 100
        mock_quota.consume.assert_called_once_with("search")


class TestAnalytics:
    @patch("youtube_mcp.tools.analytics.auth")
    def test_analytics_overview(self, mock_auth):
        from youtube_mcp.tools.analytics import youtube_analytics_overview

        mock_analytics = MagicMock()
        mock_auth.build_youtube_analytics_service.return_value = mock_analytics
        mock_analytics.reports().query().execute.return_value = {
            "columnHeaders": [
                {"name": "views"},
                {"name": "estimatedMinutesWatched"},
            ],
            "rows": [[5000, 12000]],
        }

        result = youtube_analytics_overview()
        assert result["results"][0]["views"] == 5000
        assert result["results"][0]["estimatedMinutesWatched"] == 12000

    @patch("youtube_mcp.tools.analytics.auth")
    def test_analytics_top_shorts(self, mock_auth):
        from youtube_mcp.tools.analytics import youtube_analytics_top_shorts

        mock_analytics = MagicMock()
        mock_auth.build_youtube_analytics_service.return_value = mock_analytics
        mock_analytics.reports().query().execute.return_value = {
            "columnHeaders": [
                {"name": "video"},
                {"name": "views"},
            ],
            "rows": [
                ["short1", 10000],
                ["short2", 5000],
            ],
        }

        result = youtube_analytics_top_shorts()
        assert len(result["results"]) == 2
        assert result["results"][0]["video"] == "short1"
        assert result["results"][0]["views"] == 10000


class _FixedDate(date):
    """date subclass with a pinned today() so default ranges are deterministic."""

    @classmethod
    def today(cls):
        return cls(2026, 11, 23)


def _analytics_mock(mock_auth, response=None):
    """Wire a mock analytics service; return the reports().query mock."""
    mock_analytics = MagicMock()
    mock_auth.build_youtube_analytics_service.return_value = mock_analytics
    query = mock_analytics.reports.return_value.query
    query.return_value.execute.return_value = response or {
        "columnHeaders": [{"name": "views"}],
        "rows": [[1]],
    }
    return query


def _sent_ranges(query):
    return [(c.kwargs["startDate"], c.kwargs["endDate"]) for c in query.call_args_list]


class TestAnalyticsPartialDates:
    """A start_date or end_date given on its own must be kept (B4)."""

    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            ({"start_date": "2024-01-01"}, ("2024-01-01", "2026-11-23")),
            ({"end_date": "2024-06-30"}, ("2024-06-02", "2024-06-30")),
        ],
    )
    @patch("youtube_mcp.tools.analytics.date", _FixedDate)
    @patch("youtube_mcp.tools.analytics.auth")
    def test_overview_keeps_single_date(self, mock_auth, kwargs, expected):
        from youtube_mcp.tools.analytics import youtube_analytics_overview

        query = _analytics_mock(mock_auth)
        result = youtube_analytics_overview(**kwargs)

        assert _sent_ranges(query) == [expected]
        assert (result["start_date"], result["end_date"]) == expected

    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            ({"start_date": "2023-01-01"}, ("2023-01-01", "2026-11-23")),
            ({"end_date": "2024-06-30"}, ("2024-04-01", "2024-06-30")),
        ],
    )
    @patch("youtube_mcp.tools.analytics.date", _FixedDate)
    @patch("youtube_mcp.tools.analytics.auth")
    def test_day_of_week_keeps_single_date(self, mock_auth, kwargs, expected):
        from youtube_mcp.tools.analytics import youtube_analytics_day_of_week

        query = _analytics_mock(mock_auth, {"columnHeaders": [], "rows": []})
        result = youtube_analytics_day_of_week(**kwargs)

        assert _sent_ranges(query) == [expected]
        assert (result["start_date"], result["end_date"]) == expected

    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            ({"start_date": "2023-01-01"}, ("2023-01-01", "2026-11-23")),
            ({"end_date": "2025-03-31"}, ("2025-03-03", "2025-03-31")),
        ],
    )
    @patch("youtube_mcp.tools.analytics.date", _FixedDate)
    @patch("youtube_mcp.tools.analytics.auth")
    def test_content_type_breakdown_keeps_single_date(self, mock_auth, kwargs, expected):
        from youtube_mcp.tools.analytics import youtube_analytics_content_type_breakdown

        query = _analytics_mock(mock_auth)
        result = youtube_analytics_content_type_breakdown(**kwargs)

        assert _sent_ranges(query) == [expected] * 3
        assert (result["start_date"], result["end_date"]) == expected


def _http_error(status, message):
    from googleapiclient.errors import HttpError
    from httplib2 import Response

    content = json.dumps({"error": {"code": status, "message": message}}).encode()
    return HttpError(Response({"status": status}), content, uri="https://youtubeanalytics.googleapis.com/v2/reports")


class TestContentTypeBreakdownErrors:
    """Failures must not be reported as a successful 'not available' (B14)."""

    @patch("youtube_mcp.tools.analytics.auth")
    def test_auth_error_propagates(self, mock_auth):
        from youtube_mcp.auth import AuthError
        from youtube_mcp.tools.analytics import youtube_analytics_content_type_breakdown

        mock_auth.build_youtube_analytics_service.side_effect = AuthError(
            "client_secret.json not found"
        )

        with pytest.raises(AuthError, match="client_secret.json not found"):
            youtube_analytics_content_type_breakdown(
                start_date="2026-01-01", end_date="2026-01-28"
            )
        # The auth failure is not retried once per content type.
        assert mock_auth.build_youtube_analytics_service.call_count == 1

    @patch("youtube_mcp.tools.analytics.auth")
    def test_http_error_reports_cause_and_keeps_other_types(self, mock_auth):
        from youtube_mcp.tools.analytics import youtube_analytics_content_type_breakdown

        query = _analytics_mock(mock_auth)
        query.return_value.execute.side_effect = [
            _http_error(403, "Request had insufficient authentication scopes."),
            {"columnHeaders": [{"name": "views"}], "rows": [[42]]},
            {"columnHeaders": [{"name": "views"}]},
        ]

        result = youtube_analytics_content_type_breakdown(
            start_date="2026-01-01", end_date="2026-01-28"
        )
        breakdown = result["breakdown"]

        assert "insufficient authentication scopes" in breakdown["shorts"]["error"]
        assert breakdown["video_on_demand"] == {"views": 42}
        assert breakdown["live"] == {"views": 0, "estimatedMinutesWatched": 0}

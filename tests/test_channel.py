"""Tests for youtube_list_videos pagination and video-details batching."""

from unittest.mock import MagicMock, patch

import pytest


def _make_playlist_server(total, page_size_cap=50):
    """A fake playlistItems.list server that pages through `total` items,
    honoring whatever maxResults/pageToken the caller actually requests
    (unlike a naive mock that ignores maxResults).
    """
    state = {"cursor": 0}

    def side_effect(**kwargs):
        page_size = min(kwargs["maxResults"], page_size_cap)
        token = kwargs.get("pageToken")
        assert token is None or token == f"tok{state['cursor']}"
        start = state["cursor"]
        end = min(start + page_size, total)
        items = [
            {"id": f"pli_{i}", "contentDetails": {"videoId": f"vid_{i}"}}
            for i in range(start, end)
        ]
        state["cursor"] = end
        resp = {"items": items, "pageInfo": {"totalResults": total}}
        if end < total:
            resp["nextPageToken"] = f"tok{end}"
        return MagicMock(execute=MagicMock(return_value=resp))

    return side_effect


def _make_videos_details_side_effect():
    def side_effect(**kwargs):
        ids = kwargs["id"].split(",")
        return MagicMock(
            execute=MagicMock(
                return_value={
                    "items": [
                        {
                            "id": vid,
                            "snippet": {"title": f"Title {vid}", "channelTitle": "C"},
                            "statistics": {"viewCount": "1"},
                            "contentDetails": {"duration": "PT1M"},
                        }
                        for vid in ids
                    ]
                }
            )
        )

    return side_effect


class TestListVideosPagination:
    @patch("youtube_mcp.tools.channel.auth")
    @patch("youtube_mcp.tools.channel.quota")
    def test_under_one_page_returns_exact_count(self, mock_quota, mock_auth):
        from youtube_mcp.tools.channel import youtube_list_videos

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.playlistItems().list.side_effect = _make_playlist_server(total=200)
        mock_yt.videos().list.side_effect = _make_videos_details_side_effect()

        result = youtube_list_videos(playlist_id="PL1", max_results=20)

        assert len(result["videos"]) == 20
        assert result["total"] == 200
        assert mock_yt.videos().list.call_args.kwargs["id"].count(",") == 19

    @patch("youtube_mcp.tools.channel.auth")
    @patch("youtube_mcp.tools.channel.quota")
    def test_spans_multiple_playlist_pages_and_detail_batches(self, mock_quota, mock_auth):
        from youtube_mcp.tools.channel import youtube_list_videos

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.playlistItems().list.side_effect = _make_playlist_server(total=200)

        detail_call_sizes = []
        base_side_effect = _make_videos_details_side_effect()

        def tracking_side_effect(**kwargs):
            detail_call_sizes.append(len(kwargs["id"].split(",")))
            return base_side_effect(**kwargs)

        mock_yt.videos().list.side_effect = tracking_side_effect

        result = youtube_list_videos(playlist_id="PL1", max_results=120)

        assert len(result["videos"]) == 120
        assert result["total"] == 200
        # 120 items requires 3 playlistItems pages (50+50+20) and 3 videos.list
        # batches of at most 50 ids each (the API's per-call id limit).
        assert detail_call_sizes == [50, 50, 20]
        assert all(v["id"] == f"vid_{i}" for i, v in enumerate(result["videos"]))

    @patch("youtube_mcp.tools.channel.auth")
    @patch("youtube_mcp.tools.channel.quota")
    def test_max_results_zero_fetches_whole_playlist(self, mock_quota, mock_auth):
        from youtube_mcp.tools.channel import youtube_list_videos

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.playlistItems().list.side_effect = _make_playlist_server(total=130)
        mock_yt.videos().list.side_effect = _make_videos_details_side_effect()

        result = youtube_list_videos(playlist_id="PL1", max_results=0)

        assert len(result["videos"]) == 130
        assert result["total"] == 130

    @patch("youtube_mcp.tools.channel.auth")
    @patch("youtube_mcp.tools.channel.quota")
    def test_max_results_exceeds_playlist_size(self, mock_quota, mock_auth):
        from youtube_mcp.tools.channel import youtube_list_videos

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.playlistItems().list.side_effect = _make_playlist_server(total=30)
        mock_yt.videos().list.side_effect = _make_videos_details_side_effect()

        result = youtube_list_videos(playlist_id="PL1", max_results=500)

        assert len(result["videos"]) == 30
        assert result["total"] == 30

    @patch("youtube_mcp.tools.channel.auth")
    @patch("youtube_mcp.tools.channel.quota")
    def test_playlist_item_id_is_attached_to_each_video(self, mock_quota, mock_auth):
        from youtube_mcp.tools.channel import youtube_list_videos

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.playlistItems().list.side_effect = _make_playlist_server(total=5)
        mock_yt.videos().list.side_effect = _make_videos_details_side_effect()

        result = youtube_list_videos(playlist_id="PL1", max_results=5)

        for i, v in enumerate(result["videos"]):
            assert v["playlist_item_id"] == f"pli_{i}"

    @patch("youtube_mcp.tools.channel.auth")
    @patch("youtube_mcp.tools.channel.quota")
    def test_empty_playlist_returns_empty_list(self, mock_quota, mock_auth):
        from youtube_mcp.tools.channel import youtube_list_videos

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.playlistItems().list.side_effect = _make_playlist_server(total=0)

        result = youtube_list_videos(playlist_id="PL1", max_results=20)

        assert result == {"videos": [], "total": 0}
        mock_yt.videos().list.assert_not_called()

    @patch("youtube_mcp.tools.channel.auth")
    @patch("youtube_mcp.tools.channel.quota")
    def test_duplicate_video_in_playlist_does_not_crash(self, mock_quota, mock_auth):
        """A video can legitimately appear twice in the same playlist. The
        real videos.list API dedupes ids server-side, so the result has
        fewer entries than playlist items — this asserts the tool degrades
        gracefully (no crash, no duplicate entries) rather than a specific
        playlist_item_id winning, which is inherently ambiguous.
        """
        from youtube_mcp.tools.channel import youtube_list_videos

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.playlistItems().list.return_value.execute.return_value = {
            "items": [
                {"id": "pli_1", "contentDetails": {"videoId": "vid_A"}},
                {"id": "pli_2", "contentDetails": {"videoId": "vid_B"}},
                {"id": "pli_3", "contentDetails": {"videoId": "vid_A"}},
            ],
            "pageInfo": {"totalResults": 3},
        }
        mock_yt.videos().list.return_value.execute.return_value = {
            "items": [
                {"id": "vid_A", "snippet": {"title": "A"}, "statistics": {}, "contentDetails": {}},
                {"id": "vid_B", "snippet": {"title": "B"}, "statistics": {}, "contentDetails": {}},
            ]
        }

        result = youtube_list_videos(playlist_id="PL1", max_results=10)

        ids = [v["id"] for v in result["videos"]]
        assert ids == ["vid_A", "vid_B"]
        assert len(ids) == len(set(ids))


class TestQuotaNotChargedWithoutRequest:
    """Quota must only be charged for requests that are actually sent.

    Argument validation happens before the client is built, and the client is
    built before quota is charged, so neither a validation error nor an auth
    failure records phantom units.
    """

    @pytest.mark.parametrize(
        "kwargs",
        [{}, {"channel_id": "", "handle": ""}, {"channel_id": None, "handle": None, "mine": False}],
    )
    def test_get_channel_missing_identifier_charges_no_quota(self, kwargs):
        from youtube_mcp.tools.channel import youtube_get_channel
        from youtube_mcp.utils.quota import QuotaTracker

        tracker = QuotaTracker()
        mock_auth = MagicMock()
        with patch("youtube_mcp.tools.channel.quota", tracker), patch(
            "youtube_mcp.tools.channel.auth", mock_auth
        ):
            result = youtube_get_channel(**kwargs)

        assert result == {"error": "Provide channel_id, handle, or set mine=True"}
        assert tracker.used == 0
        mock_auth.build_youtube_service.assert_not_called()

    def test_get_channel_missing_identifier_returns_error_when_quota_exhausted(self):
        from youtube_mcp.tools.channel import youtube_get_channel
        from youtube_mcp.utils.quota import QuotaTracker

        tracker = QuotaTracker(daily_limit=0)
        with patch("youtube_mcp.tools.channel.quota", tracker), patch(
            "youtube_mcp.tools.channel.auth", MagicMock()
        ):
            result = youtube_get_channel()

        assert result == {"error": "Provide channel_id, handle, or set mine=True"}

    @pytest.mark.parametrize(
        "kwargs",
        [{}, {"channel_id": "", "playlist_id": ""}, {"channel_id": None, "mine": False}],
    )
    def test_list_videos_missing_identifier_charges_no_quota(self, kwargs):
        from youtube_mcp.tools.channel import youtube_list_videos
        from youtube_mcp.utils.quota import QuotaTracker

        tracker = QuotaTracker()
        mock_auth = MagicMock()
        with patch("youtube_mcp.tools.channel.quota", tracker), patch(
            "youtube_mcp.tools.channel.auth", mock_auth
        ):
            result = youtube_list_videos(**kwargs)

        assert result == {"error": "Provide channel_id, playlist_id, or set mine=True"}
        assert tracker.used == 0
        mock_auth.build_youtube_service.assert_not_called()

    def test_list_videos_missing_identifier_returns_error_when_quota_exhausted(self):
        from youtube_mcp.tools.channel import youtube_list_videos
        from youtube_mcp.utils.quota import QuotaTracker

        tracker = QuotaTracker(daily_limit=0)
        with patch("youtube_mcp.tools.channel.quota", tracker), patch(
            "youtube_mcp.tools.channel.auth", MagicMock()
        ):
            result = youtube_list_videos()

        assert result == {"error": "Provide channel_id, playlist_id, or set mine=True"}

    def test_list_videos_charges_only_requests_sent(self):
        from youtube_mcp.tools.channel import youtube_list_videos
        from youtube_mcp.utils.quota import QuotaTracker

        tracker = QuotaTracker()
        mock_auth = MagicMock()
        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.channels().list.return_value.execute.return_value = {
            "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]
        }
        mock_yt.playlistItems().list.side_effect = _make_playlist_server(total=3)
        mock_yt.videos().list.side_effect = _make_videos_details_side_effect()

        with patch("youtube_mcp.tools.channel.quota", tracker), patch(
            "youtube_mcp.tools.channel.auth", mock_auth
        ):
            assert "error" in youtube_list_videos()
            result = youtube_list_videos(channel_id="UC1", max_results=3)

        assert len(result["videos"]) == 3
        # Only the valid call's channels.list + playlistItems.list + videos.list
        assert tracker.used == 3
        assert mock_yt.channels().list.call_args.kwargs == {"part": "contentDetails", "id": "UC1"}

    @pytest.mark.parametrize(
        "call",
        [
            lambda m: m.youtube_get_channel(handle="@x"),
            lambda m: m.youtube_get_channel(mine=True),
            lambda m: m.youtube_get_video("vid"),
        ],
        ids=["get_channel_handle", "get_channel_mine", "get_video"],
    )
    def test_auth_failure_charges_no_quota(self, call):
        from youtube_mcp.auth import AuthError
        from youtube_mcp.tools import channel
        from youtube_mcp.utils.quota import QuotaTracker

        tracker = QuotaTracker()
        mock_auth = MagicMock()
        mock_auth.build_youtube_service.side_effect = AuthError("client_secret.json not found")
        with patch("youtube_mcp.tools.channel.quota", tracker), patch(
            "youtube_mcp.tools.channel.auth", mock_auth
        ):
            with pytest.raises(AuthError):
                call(channel)

        assert tracker.used == 0

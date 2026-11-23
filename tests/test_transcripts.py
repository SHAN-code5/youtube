"""Tests for transcript and caption tools."""

from unittest.mock import MagicMock, patch

import pytest

from youtube_mcp.auth import AuthError
from youtube_mcp.utils.quota import QuotaTracker


def _make_snippet(text, start, duration):
    snippet = MagicMock()
    snippet.text = text
    snippet.start = start
    snippet.duration = duration
    return snippet


class TestGetTranscriptScraping:
    def test_fetches_via_instance_list_and_fetch(self):
        """Regression: youtube-transcript-api >=1.0 replaced the old
        YouTubeTranscriptApi.list_transcripts() classmethod with an instance
        method YouTubeTranscriptApi().list(), and Transcript.fetch() now
        returns an iterable of snippet objects (text/start/duration
        attributes) rather than dicts. Calling the removed classmethod raises
        AttributeError for every video (issue #1).
        """
        from youtube_mcp.tools.transcripts import _get_transcript_scraping

        snippets = [
            _make_snippet("Hello", 0.0, 1.5),
            _make_snippet("world", 1.5, 1.2),
        ]
        mock_transcript = MagicMock()
        mock_transcript.language_code = "en"
        mock_transcript.is_generated = False
        mock_transcript.fetch.return_value = snippets

        mock_transcript_list = MagicMock()
        mock_transcript_list.find_transcript.return_value = mock_transcript

        mock_api_instance = MagicMock()
        mock_api_instance.list.return_value = mock_transcript_list

        with patch("youtube_transcript_api.YouTubeTranscriptApi", return_value=mock_api_instance) as mock_cls:
            result = _get_transcript_scraping("vid1", "en")

        mock_cls.assert_called_once_with()
        mock_api_instance.list.assert_called_once_with("vid1")
        mock_transcript_list.find_transcript.assert_called_once_with(["en"])

        assert "error" not in result
        assert result["video_id"] == "vid1"
        assert result["language"] == "en"
        assert result["is_generated"] is False
        assert result["full_text"] == "Hello world"
        assert result["segments"] == [
            {"text": "Hello", "start": 0.0, "duration": 1.5},
            {"text": "world", "start": 1.5, "duration": 1.2},
        ]

    def test_falls_back_to_any_transcript_when_language_not_found(self):
        from youtube_mcp.tools.transcripts import _get_transcript_scraping

        snippets = [_make_snippet("Bonjour", 0.0, 1.0)]
        mock_transcript = MagicMock()
        mock_transcript.language_code = "fr"
        mock_transcript.is_generated = True
        mock_transcript.fetch.return_value = snippets

        mock_transcript.translate.side_effect = Exception("not translatable")

        mock_transcript_list = MagicMock()
        mock_transcript_list.find_transcript.side_effect = Exception("not found")
        mock_transcript_list.__iter__.return_value = iter([mock_transcript])

        mock_api_instance = MagicMock()
        mock_api_instance.list.return_value = mock_transcript_list

        with patch("youtube_transcript_api.YouTubeTranscriptApi", return_value=mock_api_instance):
            result = _get_transcript_scraping("vid1", "en")

        assert "error" not in result
        assert result["language"] == "fr"
        assert result["full_text"] == "Bonjour"

    def test_api_error_is_returned_not_raised(self):
        from youtube_mcp.tools.transcripts import _get_transcript_scraping

        mock_api_instance = MagicMock()
        mock_api_instance.list.side_effect = Exception("Subtitles are disabled for this video")

        with patch("youtube_transcript_api.YouTubeTranscriptApi", return_value=mock_api_instance):
            result = _get_transcript_scraping("vid1", "en")

        assert result["video_id"] == "vid1"
        assert "error" in result
        assert result["source"] == "youtube-transcript-api"


def _mock_captions_service():
    youtube = MagicMock()
    youtube.captions().list().execute.return_value = {
        "items": [{"id": "cap1", "snippet": {"language": "en", "trackKind": "standard"}}]
    }
    youtube.captions().download().execute.return_value = b"1\n00:00:00,000 --> 00:00:01,000\nHi\n"
    return youtube


class TestCaptionQuota:
    """Regression (B7/B8): captions.list costs 50 units and captions.download 200."""

    @patch("youtube_mcp.tools.transcripts.auth")
    def test_list_captions_charges_caption_list_cost(self, mock_auth):
        from youtube_mcp.tools.transcripts import youtube_list_captions

        mock_auth.build_youtube_service.return_value = _mock_captions_service()
        tracker = QuotaTracker()
        with patch("youtube_mcp.tools.transcripts.quota", tracker):
            result = youtube_list_captions("vid1")

        assert result["tracks"][0]["id"] == "cap1"
        assert tracker.used == 50

    @patch("youtube_mcp.tools.transcripts.auth")
    def test_official_transcript_charges_list_and_download_costs(self, mock_auth):
        from youtube_mcp.tools.transcripts import youtube_get_transcript

        mock_auth.build_youtube_service.return_value = _mock_captions_service()
        tracker = QuotaTracker()
        with patch("youtube_mcp.tools.transcripts.quota", tracker):
            result = youtube_get_transcript("vid1", use_official_api=True)

        assert result["source"] == "official_api"
        assert "Hi" in result["full_text"]
        assert tracker.used == 250  # captions.list 50 + captions.download 200

    @patch("youtube_mcp.tools.transcripts.auth")
    def test_official_transcript_refuses_download_when_quota_short(self, mock_auth):
        from youtube_mcp.tools.transcripts import youtube_get_transcript
        from youtube_mcp.utils.quota import QuotaExhaustedError

        youtube = _mock_captions_service()
        mock_auth.build_youtube_service.return_value = youtube
        tracker = QuotaTracker(daily_limit=100)
        with patch("youtube_mcp.tools.transcripts.quota", tracker):
            with pytest.raises(QuotaExhaustedError):
                youtube_get_transcript("vid1", use_official_api=True)

        assert tracker.used == 50
        youtube.captions().download().execute.assert_not_called()


class TestQuotaNotChargedOnAuthFailure:
    """Regression (B17): no quota is charged when building the client fails,
    because no request reaches Google."""

    @patch("youtube_mcp.tools.transcripts.auth")
    def test_list_captions(self, mock_auth):
        from youtube_mcp.tools.transcripts import youtube_list_captions

        mock_auth.build_youtube_service.side_effect = AuthError("client_secret.json not found")
        tracker = QuotaTracker()
        with patch("youtube_mcp.tools.transcripts.quota", tracker):
            with pytest.raises(AuthError):
                youtube_list_captions("vid1")

        assert tracker.used == 0

    @patch("youtube_mcp.tools.transcripts.auth")
    def test_official_transcript(self, mock_auth):
        from youtube_mcp.tools.transcripts import youtube_get_transcript

        mock_auth.build_youtube_service.side_effect = AuthError("client_secret.json not found")
        tracker = QuotaTracker()
        with patch("youtube_mcp.tools.transcripts.quota", tracker):
            with pytest.raises(AuthError):
                youtube_get_transcript("vid1", use_official_api=True)

        assert tracker.used == 0

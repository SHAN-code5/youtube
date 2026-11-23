"""Tests for publishing tools with mocked YouTube API."""

from unittest.mock import MagicMock, patch

import pytest


class TestUploadVideo:
    @patch("youtube_mcp.tools.publishing.MediaFileUpload")
    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    @patch("os.path.exists", return_value=True)
    def test_upload_success(self, mock_exists, mock_quota, mock_auth, mock_media):
        from youtube_mcp.tools.publishing import youtube_upload_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().insert().execute.return_value = {
            "id": "new123",
            "snippet": {"title": "My Video"},
            "status": {"privacyStatus": "private"},
        }

        result = youtube_upload_video(
            file_path="/tmp/video.mp4",
            title="My Video",
            description="A test",
        )
        assert result["id"] == "new123"
        assert result["url"] == "https://www.youtube.com/watch?v=new123"
        assert result["quota_cost"] == 1600
        mock_quota.consume.assert_called_once_with("video_insert")

    @patch("youtube_mcp.tools.publishing.quota")
    def test_upload_file_not_found(self, mock_quota):
        from youtube_mcp.tools.publishing import youtube_upload_video

        result = youtube_upload_video(
            file_path="/nonexistent/video.mp4",
            title="Test",
        )
        assert "error" in result
        mock_quota.consume.assert_not_called()


class TestUpdateVideo:
    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_update_title(self, mock_quota, mock_auth):
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt

        # Mock the initial fetch
        mock_yt.videos().list().execute.return_value = {
            "items": [{
                "id": "vid1",
                "snippet": {
                    "title": "Old Title",
                    "description": "Desc",
                    "tags": ["tag1"],
                    "categoryId": "22",
                },
                "status": {"privacyStatus": "public"},
            }]
        }

        # Mock the update
        mock_yt.videos().update().execute.return_value = {
            "id": "vid1",
            "snippet": {"title": "New Title"},
            "status": {"privacyStatus": "public"},
        }

        result = youtube_update_video(video_id="vid1", title="New Title")
        assert result["title"] == "New Title"
        assert result["updated"] is True

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_update_not_found(self, mock_quota, mock_auth):
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().list().execute.return_value = {"items": []}

        result = youtube_update_video(video_id="nope", title="X")
        assert "error" in result

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")

    def test_update_schedule_on_private_video(self, mock_quota, mock_auth):
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().list().execute.return_value = {
            "items": [{
                "id": "vid1",
                "snippet": {"title": "T", "description": "D", "tags": [], "categoryId": "22"},
                "status": {"privacyStatus": "private"},
            }]
        }
        mock_yt.videos().update().execute.return_value = {
            "id": "vid1",
            "snippet": {"title": "T"},
            "status": {"privacyStatus": "private", "publishAt": "2026-05-01T16:00:00Z"},
        }

        result = youtube_update_video(video_id="vid1", publish_at="2026-05-01T16:00:00Z")
        assert result["publish_at"] == "2026-05-01T16:00:00Z"
        assert result["privacy"] == "private"

        # Verify the body sent to update() included status.publishAt
        call_kwargs = mock_yt.videos().update.call_args.kwargs
        assert call_kwargs["part"] == "snippet,status"
        assert call_kwargs["body"]["status"]["publishAt"] == "2026-05-01T16:00:00Z"
        assert call_kwargs["body"]["status"]["privacyStatus"] == "private"

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_update_made_for_kids(self, mock_quota, mock_auth):
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().list().execute.return_value = {
            "items": [{
                "id": "vid1",
                "snippet": {"title": "T", "description": "D", "tags": [], "categoryId": "22"},
                "status": {"privacyStatus": "private"},
            }]
        }
        mock_yt.videos().update().execute.return_value = {
            "id": "vid1",
            "snippet": {"title": "T"},
            "status": {"privacyStatus": "private"},
        }

        result = youtube_update_video(video_id="vid1", made_for_kids=False)
        assert result["updated"] is True

        call_kwargs = mock_yt.videos().update.call_args.kwargs
        assert call_kwargs["part"] == "snippet,status"
        assert call_kwargs["body"]["status"]["selfDeclaredMadeForKids"] is False
        assert call_kwargs["body"]["status"]["privacyStatus"] == "private"

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_update_schedule_rejects_public(self, mock_quota, mock_auth):
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().list().execute.return_value = {
            "items": [{
                "id": "vid1",
                "snippet": {"title": "T", "description": "D", "tags": [], "categoryId": "22"},
                "status": {"privacyStatus": "public"},
            }]
        }

        result = youtube_update_video(video_id="vid1", publish_at="2026-05-01T16:00:00Z")
        assert "error" in result
        mock_yt.videos().update.assert_not_called()

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_update_without_privacy_status_does_not_raise_keyerror(
        self, mock_quota, mock_auth
    ):
        """Regression: when privacy_status/publish_at/made_for_kids are all
        omitted, only part='snippet' is sent and the YouTube API response
        omits the 'status' field. The function must not raise KeyError.
        """
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt

        mock_yt.videos().list().execute.return_value = {
            "items": [{
                "id": "vid1",
                "snippet": {
                    "title": "Old Title",
                    "description": "Desc",
                    "tags": ["tag1"],
                    "categoryId": "22",
                },
                "status": {"privacyStatus": "public"},
            }]
        }

        mock_yt.videos().update().execute.return_value = {
            "kind": "youtube#video",
            "etag": "abc",
            "id": "vid1",
            "snippet": {"title": "New Title"},
        }

        result = youtube_update_video(video_id="vid1", title="New Title")
        assert result["id"] == "vid1"
        assert result["title"] == "New Title"
        assert result["updated"] is True
        assert result.get("privacy") is None
        assert result.get("publish_at") is None


class TestSetThumbnail:
    @patch("youtube_mcp.tools.publishing.MediaFileUpload")
    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    @patch("os.path.exists", return_value=True)
    def test_set_thumbnail(self, mock_exists, mock_quota, mock_auth, mock_media):
        from youtube_mcp.tools.publishing import youtube_set_thumbnail

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.thumbnails().set().execute.return_value = {
            "items": [{"default": {"url": "https://i.ytimg.com/thumb.jpg"}}]
        }

        result = youtube_set_thumbnail("vid1", "/tmp/thumb.jpg")
        assert result["updated"] is True
        mock_quota.consume.assert_called_once_with("thumbnail_set")


class TestDeleteVideo:
    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_delete(self, mock_quota, mock_auth):
        from youtube_mcp.tools.publishing import youtube_delete_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt

        result = youtube_delete_video("vid1")
        assert result["deleted"] is True
        mock_quota.consume.assert_called_once_with("delete")


SCHEDULED_STATUS = {
    "uploadStatus": "processed",
    "privacyStatus": "private",
    "publishAt": "2026-12-01T16:00:00Z",
    "license": "creativeCommon",
    "embeddable": False,
    "publicStatsViewable": False,
    "madeForKids": False,
    "selfDeclaredMadeForKids": False,
    "containsSyntheticMedia": True,
}


def _mock_update_service(mock_auth, status):
    mock_yt = MagicMock()
    mock_auth.build_youtube_service.return_value = mock_yt
    mock_yt.videos().list().execute.return_value = {
        "items": [{
            "id": "vid1",
            "snippet": {"title": "T", "description": "D", "tags": [], "categoryId": "22"},
            "status": dict(status),
        }]
    }
    mock_yt.videos().update().execute.return_value = {
        "id": "vid1",
        "snippet": {"title": "T"},
        "status": {"privacyStatus": status["privacyStatus"]},
    }
    return mock_yt


class TestUpdateVideoPreservesStatus:
    """Regression: videos.update resets any mutable status property left out
    of the body, so the tool must carry the current settings forward."""

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_made_for_kids_keeps_schedule_and_settings(self, mock_quota, mock_auth):
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = _mock_update_service(mock_auth, SCHEDULED_STATUS)

        youtube_update_video(video_id="vid1", made_for_kids=False)

        sent = mock_yt.videos().update.call_args.kwargs["body"]["status"]
        assert sent == {
            "privacyStatus": "private",
            "publishAt": "2026-12-01T16:00:00Z",
            "license": "creativeCommon",
            "embeddable": False,
            "publicStatsViewable": False,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        }

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_new_publish_at_keeps_other_settings(self, mock_quota, mock_auth):
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = _mock_update_service(mock_auth, SCHEDULED_STATUS)

        youtube_update_video(video_id="vid1", publish_at="2027-01-01T00:00:00Z")

        sent = mock_yt.videos().update.call_args.kwargs["body"]["status"]
        assert sent["publishAt"] == "2027-01-01T00:00:00Z"
        assert sent["license"] == "creativeCommon"
        assert sent["embeddable"] is False
        assert sent["publicStatsViewable"] is False
        assert sent["selfDeclaredMadeForKids"] is False
        assert sent["containsSyntheticMedia"] is True

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_privacy_change_keeps_settings_and_drops_publish_at(
        self, mock_quota, mock_auth
    ):
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = _mock_update_service(mock_auth, SCHEDULED_STATUS)

        youtube_update_video(video_id="vid1", privacy_status="unlisted")

        sent = mock_yt.videos().update.call_args.kwargs["body"]["status"]
        assert sent == {
            "privacyStatus": "unlisted",
            "license": "creativeCommon",
            "embeddable": False,
            "publicStatsViewable": False,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        }


class TestQuotaNotChargedWithoutRequest:
    """Regression: quota must not be charged when auth (or local media setup)
    fails and no request is ever sent to YouTube."""

    @patch("youtube_mcp.tools.publishing.MediaFileUpload")
    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    @patch("os.path.exists", return_value=True)
    def test_upload_auth_failure(self, mock_exists, mock_quota, mock_auth, mock_media):
        from youtube_mcp.auth import AuthError
        from youtube_mcp.tools.publishing import youtube_upload_video

        mock_auth.build_youtube_service.side_effect = AuthError("no client_secret.json")

        with pytest.raises(AuthError):
            youtube_upload_video(file_path="/tmp/video.mp4", title="T")
        mock_quota.consume.assert_not_called()

    @patch("youtube_mcp.tools.publishing.MediaFileUpload")
    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    @patch("os.path.exists", return_value=True)
    def test_upload_media_failure(self, mock_exists, mock_quota, mock_auth, mock_media):
        from youtube_mcp.tools.publishing import youtube_upload_video

        mock_auth.build_youtube_service.return_value = MagicMock()
        mock_media.side_effect = PermissionError("unreadable")

        with pytest.raises(PermissionError):
            youtube_upload_video(file_path="/tmp/video.mp4", title="T")
        mock_quota.consume.assert_not_called()

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_update_auth_failure(self, mock_quota, mock_auth):
        from youtube_mcp.auth import AuthError
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_auth.build_youtube_service.side_effect = AuthError("no client_secret.json")

        with pytest.raises(AuthError):
            youtube_update_video(video_id="vid1", title="X")
        mock_quota.consume.assert_not_called()

    @patch("youtube_mcp.tools.publishing.MediaFileUpload")
    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    @patch("os.path.exists", return_value=True)
    def test_thumbnail_auth_failure(self, mock_exists, mock_quota, mock_auth, mock_media):
        from youtube_mcp.auth import AuthError
        from youtube_mcp.tools.publishing import youtube_set_thumbnail

        mock_auth.build_youtube_service.side_effect = AuthError("no client_secret.json")

        with pytest.raises(AuthError):
            youtube_set_thumbnail("vid1", "/tmp/thumb.jpg")
        mock_quota.consume.assert_not_called()

    @patch("youtube_mcp.tools.publishing.MediaFileUpload")
    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    @patch("os.path.exists", return_value=True)
    def test_thumbnail_media_failure(self, mock_exists, mock_quota, mock_auth, mock_media):
        from youtube_mcp.tools.publishing import youtube_set_thumbnail

        mock_auth.build_youtube_service.return_value = MagicMock()
        mock_media.side_effect = PermissionError("unreadable")

        with pytest.raises(PermissionError):
            youtube_set_thumbnail("vid1", "/tmp/thumb.jpg")
        mock_quota.consume.assert_not_called()

    @patch("youtube_mcp.tools.publishing.MediaFileUpload")
    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    @patch("os.path.exists", return_value=True)
    def test_thumbnail_request_build_failure(self, mock_exists, mock_quota, mock_auth, mock_media):
        from googleapiclient.errors import MediaUploadSizeError

        from youtube_mcp.tools.publishing import youtube_set_thumbnail

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.thumbnails.return_value.set.side_effect = MediaUploadSizeError(
            "Media larger than: 52428800"
        )

        with pytest.raises(MediaUploadSizeError):
            youtube_set_thumbnail("vid1", "/tmp/thumb.png")
        mock_quota.consume.assert_not_called()

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_delete_auth_failure(self, mock_quota, mock_auth):
        from youtube_mcp.auth import AuthError
        from youtube_mcp.tools.publishing import youtube_delete_video

        mock_auth.build_youtube_service.side_effect = AuthError("no client_secret.json")

        with pytest.raises(AuthError):
            youtube_delete_video("vid1")
        mock_quota.consume.assert_not_called()

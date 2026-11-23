"""Tests for bulk reporting tools with mocked YouTube API."""

import urllib.request
from email.message import Message
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

REPORT_URL = (
    "https://youtubereporting.googleapis.com/v1/media/CHANNEL/UC1/jobs/j1/reports/r1?alt=media"
)


class TestListTypes:
    @patch("youtube_mcp.tools.reporting.auth")
    def test_list_types(self, mock_auth):
        from youtube_mcp.tools.reporting import youtube_reporting_list_types

        mock_reporting = MagicMock()
        mock_auth.build_youtube_reporting_service.return_value = mock_reporting
        mock_reporting.reportTypes().list().execute.return_value = {
            "reportTypes": [
                {"id": "channel_basic_a3", "name": "User activity"},
                {"id": "channel_demographics_a1", "name": "Demographics"},
            ]
        }

        result = youtube_reporting_list_types()
        assert result["total"] == 2
        assert result["report_types"][0]["id"] == "channel_basic_a3"


class TestCreateJob:
    @patch("youtube_mcp.tools.reporting.auth")
    def test_create(self, mock_auth):
        from youtube_mcp.tools.reporting import youtube_reporting_create_job

        mock_reporting = MagicMock()
        mock_auth.build_youtube_reporting_service.return_value = mock_reporting
        mock_reporting.jobs().create().execute.return_value = {
            "id": "job123",
            "reportTypeId": "channel_basic_a3",
            "name": "My Job",
            "createTime": "2026-01-01T00:00:00Z",
        }

        result = youtube_reporting_create_job("channel_basic_a3", name="My Job")
        assert result["job_id"] == "job123"
        assert result["report_type_id"] == "channel_basic_a3"


class TestListJobs:
    @patch("youtube_mcp.tools.reporting.auth")
    def test_list(self, mock_auth):
        from youtube_mcp.tools.reporting import youtube_reporting_list_jobs

        mock_reporting = MagicMock()
        mock_auth.build_youtube_reporting_service.return_value = mock_reporting
        mock_reporting.jobs().list().execute.return_value = {
            "jobs": [{
                "id": "job123",
                "reportTypeId": "channel_basic_a3",
                "name": "My Job",
                "createTime": "2026-01-01T00:00:00Z",
            }]
        }

        result = youtube_reporting_list_jobs()
        assert result["total"] == 1
        assert result["jobs"][0]["job_id"] == "job123"

    @patch("youtube_mcp.tools.reporting.auth")
    def test_list_empty(self, mock_auth):
        from youtube_mcp.tools.reporting import youtube_reporting_list_jobs

        mock_reporting = MagicMock()
        mock_auth.build_youtube_reporting_service.return_value = mock_reporting
        mock_reporting.jobs().list().execute.return_value = {"jobs": []}

        result = youtube_reporting_list_jobs()
        assert result["total"] == 0


class TestListReports:
    @patch("youtube_mcp.tools.reporting.auth")
    def test_list_reports(self, mock_auth):
        from youtube_mcp.tools.reporting import youtube_reporting_list_reports

        mock_reporting = MagicMock()
        mock_auth.build_youtube_reporting_service.return_value = mock_reporting
        mock_reporting.jobs().reports().list().execute.return_value = {
            "reports": [{
                "id": "report1",
                "startTime": "2026-01-01T00:00:00Z",
                "endTime": "2026-01-02T00:00:00Z",
                "createTime": "2026-01-03T00:00:00Z",
                "downloadUrl": "https://youtubereporting.googleapis.com/report.csv",
            }]
        }

        result = youtube_reporting_list_reports("job123")
        assert result["total"] == 1
        assert result["reports"][0]["report_id"] == "report1"


class TestDownload:
    @patch("youtube_mcp.tools.reporting.auth")
    @patch("youtube_mcp.tools.reporting.urllib.request.urlopen")
    def test_download(self, mock_urlopen, mock_auth):
        from youtube_mcp.tools.reporting import youtube_reporting_download

        mock_creds = MagicMock()
        mock_creds.token = "test-token"
        mock_auth.credentials = mock_creds

        mock_resp = MagicMock()
        csv_content = "date,views,watch_time\n2026-01-01,100,500\n2026-01-02,200,600\n"
        mock_resp.read.return_value = csv_content.encode("utf-8")
        mock_urlopen.return_value = mock_resp

        result = youtube_reporting_download(REPORT_URL)
        assert result["row_count"] == 2
        assert result["truncated"] is False
        assert "date,views,watch_time" in result["content"]

    @patch("youtube_mcp.tools.reporting.auth")
    @patch("youtube_mcp.tools.reporting.urllib.request.urlopen", side_effect=Exception("timeout"))
    def test_download_error(self, mock_urlopen, mock_auth):
        from youtube_mcp.tools.reporting import youtube_reporting_download

        mock_creds = MagicMock()
        mock_creds.token = "test-token"
        mock_auth.credentials = mock_creds

        result = youtube_reporting_download(REPORT_URL)
        assert "error" in result


class TestDownloadUrlSafety:
    """Regression tests: the OAuth bearer token must only go to the Reporting API host."""

    @pytest.mark.parametrize("url", [
        "http://youtubereporting.googleapis.com/v1/media/x?alt=media",
        "https://example.com/report.csv",
        "http://127.0.0.1:8080/x",
        "file:///etc/hostname",
        "ftp://youtubereporting.googleapis.com/x",
        "https://youtubereporting.googleapis.com.evil.example/x",
        "https://youtubereporting.googleapis.com@evil.example/x",
        "https://user:pw@youtubereporting.googleapis.com/x",
        "https://127.0.0.1:1\\@youtubereporting.googleapis.com/v1/media/x?alt=media",
        "https://youtubereporting.googleapis.com:8443/x",
        "https://youtubereporting.googleapis.com/v1/media/x\\y",
        "youtubereporting.googleapis.com/v1/media/x",
    ])
    @patch("youtube_mcp.tools.reporting.auth")
    @patch("youtube_mcp.tools.reporting.urllib.request.urlopen")
    def test_rejects_non_reporting_urls(self, mock_urlopen, mock_auth, url):
        from youtube_mcp.tools.reporting import youtube_reporting_download

        # Credentials must not even be read (that could start an OAuth flow).
        type(mock_auth).credentials = PropertyMock(
            side_effect=AssertionError("credentials accessed for rejected URL")
        )

        result = youtube_reporting_download(url)
        assert "error" in result
        assert "youtubereporting.googleapis.com" in result["error"]
        mock_urlopen.assert_not_called()

    @patch("youtube_mcp.tools.reporting.auth")
    def test_file_url_does_not_read_local_file(self, mock_auth, tmp_path):
        from youtube_mcp.tools.reporting import youtube_reporting_download

        mock_auth.credentials = MagicMock(token="test-token")
        secret = tmp_path / "token.json"
        secret.write_text('{"refresh_token": "1//SECRET-REFRESH"}')

        result = youtube_reporting_download(secret.as_uri())
        assert "error" in result
        assert "SECRET-REFRESH" not in str(result)

    @pytest.mark.parametrize("url", [
        REPORT_URL,
        "https://YouTubeReporting.GoogleAPIs.com/v1/media/x?alt=media",
        "https://youtubereporting.googleapis.com:443/v1/media/x?alt=media",
    ])
    @patch("youtube_mcp.tools.reporting.auth")
    @patch("youtube_mcp.tools.reporting.urllib.request.urlopen")
    def test_accepts_reporting_urls(self, mock_urlopen, mock_auth, url):
        from youtube_mcp.tools.reporting import youtube_reporting_download

        mock_auth.credentials = MagicMock(token="test-token")
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"date,views\n2026-01-01,1\n"
        mock_urlopen.return_value = mock_resp

        result = youtube_reporting_download(url)
        assert "error" not in result
        assert result["row_count"] == 1
        mock_urlopen.assert_called_once()

    @patch("youtube_mcp.tools.reporting.auth")
    @patch("youtube_mcp.tools.reporting.urllib.request.urlopen")
    def test_token_not_forwarded_on_redirect(self, mock_urlopen, mock_auth):
        from youtube_mcp.tools.reporting import youtube_reporting_download

        mock_auth.credentials = MagicMock(token="test-token")
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"date,views\n"
        mock_urlopen.return_value = mock_resp

        youtube_reporting_download(REPORT_URL)
        req = mock_urlopen.call_args[0][0]

        # Sent on the original request...
        assert req.get_header("Authorization") == "Bearer test-token"

        # ...but urllib's real redirect handler must not copy it to the next hop.
        redirected = urllib.request.HTTPRedirectHandler().redirect_request(
            req, None, 302, "Found", Message(), "https://evil.example/stolen"
        )
        assert redirected is not None
        assert redirected.get_header("Authorization") is None

    @patch("youtube_mcp.tools.reporting.auth")
    @patch("youtube_mcp.tools.reporting.urllib.request.urlopen")
    def test_sends_the_validated_url(self, mock_urlopen, mock_auth):
        from youtube_mcp.tools.reporting import youtube_reporting_download

        mock_auth.credentials = MagicMock(token="test-token")
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"date,views\n"
        mock_urlopen.return_value = mock_resp

        # urlsplit drops tabs before parsing; the request must go to the URL
        # that was actually validated, not the raw string.
        youtube_reporting_download(
            "https://youtubereporting.googleapis.co\tm/v1/media/x?alt=media"
        )
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "https://youtubereporting.googleapis.com/v1/media/x?alt=media"
        assert req.host == "youtubereporting.googleapis.com"

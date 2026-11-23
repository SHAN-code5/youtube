"""Tests for auth module."""

import json
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from youtube_mcp.auth import SCOPES, AuthError, YouTubeAuth


def test_default_config_dir():
    yt_auth = YouTubeAuth()
    assert yt_auth.config_dir == Path.home() / ".youtube-mcp"
    assert yt_auth.token_path == Path.home() / ".youtube-mcp" / "token.json"


def test_custom_config_dir(tmp_path):
    yt_auth = YouTubeAuth(config_dir=tmp_path)
    assert yt_auth.config_dir == tmp_path
    assert yt_auth.token_path == tmp_path / "token.json"


def test_client_secret_from_env(tmp_path, monkeypatch):
    secret_path = tmp_path / "my_secret.json"
    monkeypatch.setenv("YOUTUBE_MCP_CLIENT_SECRET", str(secret_path))
    yt_auth = YouTubeAuth()
    assert yt_auth.client_secret_path == secret_path


def test_client_secret_explicit_overrides_env(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_MCP_CLIENT_SECRET", "/env/path.json")
    explicit = tmp_path / "explicit.json"
    yt_auth = YouTubeAuth(client_secret_path=explicit)
    assert yt_auth.client_secret_path == explicit


def test_api_key_from_env(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-123")
    yt_auth = YouTubeAuth()
    assert yt_auth.api_key == "test-key-123"


def test_api_key_explicit_overrides_env(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "env-key")
    yt_auth = YouTubeAuth(api_key="explicit-key")
    assert yt_auth.api_key == "explicit-key"


def test_status_no_token(tmp_path):
    yt_auth = YouTubeAuth(config_dir=tmp_path)
    status = yt_auth.status()
    assert status["authenticated"] is False
    assert status["token_exists"] is False


def test_authenticate_missing_client_secret(tmp_path):
    yt_auth = YouTubeAuth(
        config_dir=tmp_path,
        client_secret_path=tmp_path / "nonexistent.json",
    )
    with pytest.raises(AuthError, match="client_secret.json not found"):
        yt_auth.authenticate()


def test_build_public_youtube_service_no_key(tmp_path):
    yt_auth = YouTubeAuth(config_dir=tmp_path, api_key=None)
    # Clear env var too
    with patch.dict("os.environ", {}, clear=True):
        yt_auth.api_key = None
        with pytest.raises(AuthError, match="No API key available"):
            yt_auth.build_public_youtube_service()


def test_load_and_save_token(tmp_path):
    yt_auth = YouTubeAuth(config_dir=tmp_path)

    # Create a mock credential
    mock_creds = MagicMock()
    mock_creds.to_json.return_value = json.dumps({
        "token": "test-token",
        "refresh_token": "test-refresh",
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
    })

    yt_auth._save_token(mock_creds)
    assert (tmp_path / "token.json").exists()


def _write_token(tmp_path, scopes, expiry="2099-01-01T00:00:00Z"):
    token_path = tmp_path / "token.json"
    token_path.write_text(json.dumps({
        "token": "fake-access-token",
        "refresh_token": "fake-refresh-token",
        "client_id": "fake-client-id",
        "client_secret": "fake-client-secret",
        "scopes": scopes,
        "expiry": expiry,
    }))
    return token_path


def test_scopes_include_force_ssl_for_comment_writes():
    """commentThreads.insert and comments.insert require youtube.force-ssl.
    Without this scope, write calls fail with 403 insufficientPermissions.
    """
    assert "https://www.googleapis.com/auth/youtube.force-ssl" in SCOPES


def test_load_token_reports_actual_scopes_from_disk(tmp_path):
    """Regression: from_authorized_user_file must not be passed a non-None
    `scopes` argument -- doing so makes it ignore the file's real "scopes"
    field and always report today's SCOPES constant instead, which silently
    defeats any scope-sufficiency check performed on the result.
    """
    old_scopes = [
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/youtube",
    ]
    _write_token(tmp_path, old_scopes)

    yt_auth = YouTubeAuth(config_dir=tmp_path)
    creds = yt_auth._load_token()

    assert creds.scopes == old_scopes
    assert "https://www.googleapis.com/auth/youtube.force-ssl" not in creds.scopes


class TestCachedTokenScopeValidation:
    """Regression: when SCOPES is expanded (e.g. adding youtube.force-ssl),
    existing cached tokens authorize only the old scope set but still report
    creds.valid == True. authenticate() must detect the scope shortfall,
    invalidate the stale token, and fall back to the interactive flow
    instead of returning stale credentials.

    These round-trip through the real Credentials.from_authorized_user_file
    (a real token.json on disk) rather than mocking google-auth's Credentials
    class directly, since mocking at that boundary is what let the original
    bug (scopes silently ignored by _load_token) go undetected.
    """

    def test_cached_token_missing_scopes_triggers_reauth_and_invalidation(
        self, tmp_path
    ):
        old_scopes = [
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/youtube",
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
            "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
        ]
        token_path = _write_token(tmp_path, old_scopes)

        yt_auth = YouTubeAuth(
            config_dir=tmp_path,
            client_secret_path=tmp_path / "nonexistent.json",
        )

        # With no client_secret available, a forced re-auth surfaces as
        # AuthError. That proves we did not silently return the stale creds.
        with pytest.raises(AuthError, match="client_secret.json not found"):
            yt_auth.authenticate()

        assert not token_path.exists()

    def test_cached_token_with_all_scopes_is_accepted(self, tmp_path):
        _write_token(tmp_path, list(SCOPES))

        yt_auth = YouTubeAuth(config_dir=tmp_path)
        result = yt_auth.authenticate()

        assert result.valid
        assert yt_auth._has_required_scopes(result)


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def _fake_creds(payload):
    creds = MagicMock()
    creds.to_json.return_value = json.dumps(payload)
    return creds


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
class TestTokenFilePermissions:
    """Regression: token.json holds the refresh token and client secret, but
    _save_token used mkdir()/write_text() defaults, so under umask 022 the
    file came out 0644 (world-readable) in a 0755 directory.
    """

    def test_new_token_and_dir_are_owner_only(self, tmp_path):
        config_dir = tmp_path / "cfg"
        yt_auth = YouTubeAuth(config_dir=config_dir)
        payload = {"token": "t", "refresh_token": "1//secret", "client_secret": "s"}

        old_umask = os.umask(0o022)
        try:
            yt_auth._save_token(_fake_creds(payload))
        finally:
            os.umask(old_umask)

        assert _mode(config_dir) == 0o700
        assert _mode(yt_auth.token_path) == 0o600
        assert json.loads(yt_auth.token_path.read_text()) == payload

    @pytest.mark.parametrize("has_fchmod", [True, False])
    def test_existing_world_readable_token_is_tightened(
        self, tmp_path, monkeypatch, has_fchmod
    ):
        # has_fchmod=False mimics Windows on Python < 3.13, where os.fchmod
        # does not exist; saving must still work there.
        if not has_fchmod:
            monkeypatch.delattr(os, "fchmod", raising=False)
        yt_auth = YouTubeAuth(config_dir=tmp_path)
        yt_auth.token_path.write_text("x" * 500)
        os.chmod(yt_auth.token_path, 0o644)
        payload = {"token": "t", "refresh_token": "1//secret"}

        yt_auth._save_token(_fake_creds(payload))

        assert _mode(yt_auth.token_path) == 0o600
        # The old, longer content is fully replaced (truncated), not merged.
        assert json.loads(yt_auth.token_path.read_text()) == payload


def test_oauth_flow_keeps_stdout_clean(tmp_path, capsys):
    """Regression: InstalledAppFlow.run_local_server print()s the consent URL
    to sys.stdout, which is the MCP stdio JSON-RPC stream. authenticate()
    must send that output to stderr instead.
    """
    client_secret = tmp_path / "client_secret.json"
    client_secret.write_text("{}")
    yt_auth = YouTubeAuth(config_dir=tmp_path, client_secret_path=client_secret)
    new_creds = _fake_creds({"token": "t", "scopes": list(SCOPES)})
    prompt = "Please visit this URL to authorize this application: https://x"

    def fake_run_local_server(**kwargs):
        # Same call google_auth_oauthlib makes for its default prompt.
        print(prompt)
        return new_creds

    flow = MagicMock()
    flow.run_local_server.side_effect = fake_run_local_server
    with patch(
        "youtube_mcp.auth.InstalledAppFlow.from_client_secrets_file",
        return_value=flow,
    ):
        result = yt_auth.authenticate()

    assert result is new_creds
    captured = capsys.readouterr()
    assert captured.out == ""
    assert prompt in captured.err


_MISSING_FORCE_SSL = [
    s for s in SCOPES if s != "https://www.googleapis.com/auth/youtube.force-ssl"
]


class TestStatusScopeValidation:
    """Regression: status() reported authenticated=True (or a refreshable
    expired token) for a cached token that authenticate() rejects and deletes
    because it lacks required scopes.
    """

    def test_valid_token_missing_scopes_is_not_authenticated(self, tmp_path):
        token_path = _write_token(tmp_path, _MISSING_FORCE_SSL)
        yt_auth = YouTubeAuth(config_dir=tmp_path)

        status = yt_auth.status()

        assert status["authenticated"] is False
        assert status["insufficient_scopes"] is True
        assert status["missing_scopes"] == [
            "https://www.googleapis.com/auth/youtube.force-ssl"
        ]
        # status() is read-only: it must not delete the token.
        assert token_path.exists()

    def test_expired_token_missing_scopes_is_not_reported_refreshable(
        self, tmp_path
    ):
        token_path = _write_token(
            tmp_path, _MISSING_FORCE_SSL, expiry="2000-01-01T00:00:00Z"
        )
        yt_auth = YouTubeAuth(config_dir=tmp_path)

        status = yt_auth.status()

        assert status["authenticated"] is False
        assert status["insufficient_scopes"] is True
        assert "has_refresh_token" not in status
        assert token_path.exists()

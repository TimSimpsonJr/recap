"""Tests for the OAuth HTTP endpoints."""

import pytest
import pytest_asyncio
from unittest.mock import MagicMock, patch

from recap.daemon.server import create_app

AUTH_TOKEN = "test-secret-token-abc123"


@pytest_asyncio.fixture
async def client(aiohttp_client):
    """Create a test client for the daemon app with OAuth routes."""
    app = create_app(auth_token=AUTH_TOKEN)
    return await aiohttp_client(app)


def _auth(token=AUTH_TOKEN):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
class TestOAuthStatusEndpoint:
    """GET /api/oauth/:provider/status"""

    async def test_returns_connected_false_when_no_credential(self, client):
        with patch("recap.daemon.credentials.has_credential", return_value=False):
            resp = await client.get(
                "/api/oauth/google/status", headers=_auth(),
            )
        assert resp.status == 200
        data = await resp.json()
        assert data["connected"] is False
        assert data["provider"] == "google"

    async def test_returns_connected_true_when_credential_exists(self, client):
        with patch("recap.daemon.credentials.has_credential", return_value=True):
            resp = await client.get(
                "/api/oauth/zoho/status", headers=_auth(),
            )
        assert resp.status == 200
        data = await resp.json()
        assert data["connected"] is True
        assert data["provider"] == "zoho"

    async def test_rejects_unknown_provider(self, client):
        resp = await client.get(
            "/api/oauth/outlook/status", headers=_auth(),
        )
        assert resp.status == 400

    async def test_requires_auth(self, client):
        resp = await client.get("/api/oauth/google/status")
        assert resp.status == 401


@pytest.mark.asyncio
class TestOAuthStartEndpoint:
    """POST /api/oauth/:provider/start"""

    async def test_returns_400_when_no_client_credentials(self, client):
        with patch("recap.daemon.credentials.get_credential", return_value=None):
            resp = await client.post(
                "/api/oauth/google/start",
                json={},
                headers=_auth(),
            )
        assert resp.status == 400
        data = await resp.json()
        assert "client_id" in data["error"]

    async def test_returns_authorize_url(self, client):
        def mock_get_cred(provider, key):
            return {"client_id": "cid", "client_secret": "csec"}.get(key)

        mock_mgr = MagicMock()
        mock_mgr.get_authorization_url.return_value = "https://accounts.google.com/auth?foo=bar"
        mock_mgr.start_callback_server = MagicMock()

        with (
            patch("recap.daemon.credentials.get_credential", side_effect=mock_get_cred),
            patch("recap.daemon.calendar.oauth.OAuthManager", return_value=mock_mgr) as mock_cls,
        ):
            resp = await client.post(
                "/api/oauth/google/start",
                json={},
                headers=_auth(),
            )

        assert resp.status == 200
        data = await resp.json()
        assert "authorize_url" in data
        assert "accounts.google.com" in data["authorize_url"]

    async def test_oauth_start_uses_fixed_port(self, client):
        """Bug 1: OAuth should use port 8399, not ephemeral port 0."""
        def mock_get_cred(provider, key):
            return {"client_id": "cid", "client_secret": "csec"}.get(key)

        mock_mgr = MagicMock()
        mock_mgr.get_authorization_url.return_value = "https://accounts.google.com/auth"
        mock_mgr.start_callback_server = MagicMock()

        with (
            patch("recap.daemon.credentials.get_credential", side_effect=mock_get_cred),
            patch("recap.daemon.calendar.oauth.OAuthManager", return_value=mock_mgr) as mock_cls,
        ):
            await client.post(
                "/api/oauth/google/start",
                json={},
                headers=_auth(),
            )
            # Verify OAuthManager was constructed with redirect_port=8399
            mock_cls.assert_called_once_with("google", "cid", "csec", redirect_port=8399)

    async def test_rejects_unknown_provider(self, client):
        resp = await client.post(
            "/api/oauth/outlook/start",
            json={},
            headers=_auth(),
        )
        assert resp.status == 400


@pytest.mark.asyncio
class TestOAuthDisconnectEndpoint:
    """DELETE /api/oauth/:provider"""

    async def test_disconnect_returns_200(self, client):
        with patch("recap.daemon.credentials.delete_credential") as mock_del:
            resp = await client.delete(
                "/api/oauth/google",
                headers=_auth(),
            )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "disconnected"
        assert data["provider"] == "google"
        # Should attempt to delete access_token, refresh_token, calendar_id
        assert mock_del.call_count == 3

    async def test_disconnect_rejects_unknown_provider(self, client):
        resp = await client.delete(
            "/api/oauth/outlook",
            headers=_auth(),
        )
        assert resp.status == 400

    async def test_disconnect_requires_auth(self, client):
        resp = await client.delete("/api/oauth/google")
        assert resp.status == 401


@pytest.mark.asyncio
class TestStatusIncludesCalendarSync:
    """GET /api/status includes last_calendar_sync from scheduler."""

    async def test_status_with_scheduler(self, aiohttp_client):
        from datetime import datetime

        mock_scheduler = MagicMock()
        mock_scheduler.last_sync = datetime(2026, 4, 14, 9, 0, 0)

        app = create_app(
            auth_token=AUTH_TOKEN,
            scheduler=mock_scheduler,
        )
        client = await aiohttp_client(app)

        resp = await client.get("/api/status", headers=_auth())
        assert resp.status == 200
        data = await resp.json()
        assert data["last_calendar_sync"] is not None
        assert "2026-04-14" in data["last_calendar_sync"]

    async def test_status_without_scheduler(self, client):
        resp = await client.get("/api/status", headers=_auth())
        assert resp.status == 200
        data = await resp.json()
        assert data["last_calendar_sync"] is None

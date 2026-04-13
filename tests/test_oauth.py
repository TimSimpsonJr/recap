"""Tests for OAuth flow management."""
import asyncio

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from recap.daemon.calendar.oauth import OAuthManager


class TestOAuthManagerConfig:
    def test_zoho_urls(self):
        manager = OAuthManager(provider="zoho", client_id="id", client_secret="secret")
        assert "accounts.zoho" in manager.authorize_url
        assert "accounts.zoho" in manager.token_url

    def test_google_urls(self):
        manager = OAuthManager(provider="google", client_id="id", client_secret="secret")
        assert "accounts.google" in manager.authorize_url
        assert "googleapis" in manager.token_url

    def test_redirect_uri_is_localhost(self):
        manager = OAuthManager(provider="zoho", client_id="id", client_secret="secret")
        assert "localhost" in manager.redirect_uri
        assert "8399" in manager.redirect_uri

    def test_custom_redirect_port(self):
        manager = OAuthManager(
            provider="zoho", client_id="id", client_secret="secret", redirect_port=9999
        )
        assert "9999" in manager.redirect_uri

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            OAuthManager(provider="unknown", client_id="id", client_secret="secret")

    def test_get_authorization_url(self):
        manager = OAuthManager(
            provider="zoho", client_id="test-id", client_secret="secret"
        )
        url = manager.get_authorization_url()
        assert "test-id" in url
        assert "localhost" in url
        assert "code" in url  # response_type=code

    def test_get_authorization_url_contains_scopes(self):
        manager = OAuthManager(
            provider="zoho", client_id="test-id", client_secret="secret"
        )
        url = manager.get_authorization_url()
        assert "ZohoCalendar" in url

    def test_google_authorization_url_contains_scopes(self):
        manager = OAuthManager(
            provider="google", client_id="test-id", client_secret="secret"
        )
        url = manager.get_authorization_url()
        assert "calendar.readonly" in url


class TestTokenExchange:
    @patch("recap.daemon.calendar.oauth.OAuth2Session")
    def test_exchange_code(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.fetch_token.return_value = {
            "access_token": "access-123",
            "refresh_token": "refresh-456",
            "expires_at": 9999999999,
        }
        mock_session_cls.return_value = mock_session

        manager = OAuthManager(provider="zoho", client_id="id", client_secret="secret")
        tokens = manager.exchange_code("auth-code-789")
        assert tokens["access_token"] == "access-123"
        assert tokens["refresh_token"] == "refresh-456"

    @patch("recap.daemon.calendar.oauth.OAuth2Session")
    def test_exchange_code_passes_correct_args(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.fetch_token.return_value = {
            "access_token": "a",
            "refresh_token": "r",
            "expires_at": 0,
        }
        mock_session_cls.return_value = mock_session

        manager = OAuthManager(provider="zoho", client_id="cid", client_secret="csec")
        manager.exchange_code("the-code")

        mock_session.fetch_token.assert_called_once()
        call_kwargs = mock_session.fetch_token.call_args
        assert call_kwargs[1]["code"] == "the-code" or call_kwargs[0] == ()

    @patch("recap.daemon.calendar.oauth.OAuth2Session")
    def test_refresh_token(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.refresh_token.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_at": 9999999999,
        }
        mock_session_cls.return_value = mock_session

        manager = OAuthManager(provider="zoho", client_id="id", client_secret="secret")
        tokens = manager.refresh_token("old-refresh-token")
        assert tokens["access_token"] == "new-access"


class TestCallbackServer:
    @pytest.mark.asyncio
    async def test_start_callback_server_returns_code(self):
        manager = OAuthManager(
            provider="zoho", client_id="id", client_secret="secret", redirect_port=0
        )

        async def simulate_callback():
            # Wait for server to start
            for _ in range(50):
                if manager._server_port is not None:
                    break
                await asyncio.sleep(0.05)

            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://localhost:{manager._server_port}/callback?code=test-auth-code"
                ) as resp:
                    assert resp.status == 200
                    text = await resp.text()
                    assert "close this window" in text.lower()

        code_task = asyncio.create_task(manager.start_callback_server())
        callback_task = asyncio.create_task(simulate_callback())

        await callback_task
        code = await code_task
        assert code == "test-auth-code"

    @pytest.mark.asyncio
    async def test_callback_server_missing_code_returns_error(self):
        manager = OAuthManager(
            provider="zoho", client_id="id", client_secret="secret", redirect_port=0
        )

        async def simulate_bad_callback():
            for _ in range(50):
                if manager._server_port is not None:
                    break
                await asyncio.sleep(0.05)

            import aiohttp

            async with aiohttp.ClientSession() as session:
                # Request without code param
                async with session.get(
                    f"http://localhost:{manager._server_port}/callback"
                ) as resp:
                    assert resp.status == 400

            # Now send a valid request so the server shuts down
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://localhost:{manager._server_port}/callback?code=ok"
                ) as resp:
                    pass

        code_task = asyncio.create_task(manager.start_callback_server())
        callback_task = asyncio.create_task(simulate_bad_callback())

        await callback_task
        code = await code_task
        assert code == "ok"

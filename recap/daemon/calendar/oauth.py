"""OAuth2 flow management for calendar providers using Authlib."""
from __future__ import annotations

import logging
from urllib.parse import urlencode

try:
    from aiohttp import web
except Exception:  # pragma: no cover - dependency-light test env
    web = None  # type: ignore[assignment]

try:
    from authlib.integrations.requests_client import OAuth2Session
except Exception:  # pragma: no cover - dependency-light test env
    OAuth2Session = None  # type: ignore[assignment]

logger = logging.getLogger("recap.calendar.oauth")


def _require_oauth_session():
    global OAuth2Session
    if OAuth2Session is None:
        try:
            from authlib.integrations.requests_client import OAuth2Session as imported
        except Exception as exc:  # pragma: no cover - depends on local env
            raise RuntimeError(
                "authlib is required for calendar OAuth flows. Install the daemon extras.",
            ) from exc
        OAuth2Session = imported
    return OAuth2Session


def _require_aiohttp_web():
    global web
    if web is None:
        try:
            from aiohttp import web as imported_web
        except Exception as exc:  # pragma: no cover - depends on local env
            raise RuntimeError(
                "aiohttp is required for the OAuth callback server. Install the dev or daemon extras.",
            ) from exc
        web = imported_web
    return web


class OAuthManager:
    """Manages OAuth2 flows for calendar providers using Authlib."""

    PROVIDERS = {
        "zoho": {
            "authorize_url": "https://accounts.zoho.com/oauth/v2/auth",
            "token_url": "https://accounts.zoho.com/oauth/v2/token",
            "scopes": "ZohoCalendar.calendar.ALL",
        },
        "google": {
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "scopes": "https://www.googleapis.com/auth/calendar.readonly",
        },
    }

    def __init__(
        self,
        provider: str,
        client_id: str,
        client_secret: str,
        redirect_port: int = 8399,
    ):
        if provider not in self.PROVIDERS:
            raise ValueError(f"Unknown provider: {provider!r}")

        self._provider = provider
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_port = redirect_port
        self._config = self.PROVIDERS[provider]
    @property
    def authorize_url(self) -> str:
        """Return the provider's authorization endpoint URL."""
        return self._config["authorize_url"]

    @property
    def token_url(self) -> str:
        """Return the provider's token endpoint URL."""
        return self._config["token_url"]

    @property
    def redirect_uri(self) -> str:
        """Return the local redirect URI for the OAuth callback.

        Always uses the configured redirect_port to ensure the URI in the
        authorization request matches the one used during token exchange.
        """
        return f"http://localhost:{self._redirect_port}/callback"

    def get_authorization_url(self) -> str:
        """Build the full OAuth authorization URL with all required parameters."""
        params = {
            "client_id": self._client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self._config["scopes"],
            "response_type": "code",
        }
        return f"{self.authorize_url}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        """Exchange an authorization code for tokens.

        Returns a token dict with access_token, refresh_token, and expires_at.
        """
        session_cls = _require_oauth_session()
        session = session_cls(
            client_id=self._client_id,
            client_secret=self._client_secret,
        )
        tokens = session.fetch_token(
            self.token_url,
            code=code,
            redirect_uri=self.redirect_uri,
        )
        return tokens

    def refresh_token(self, refresh_token: str) -> dict:
        """Refresh an expired access token.

        Returns a new token dict with access_token, refresh_token, and expires_at.
        """
        session_cls = _require_oauth_session()
        session = session_cls(
            client_id=self._client_id,
            client_secret=self._client_secret,
        )
        tokens = session.refresh_token(
            self.token_url,
            refresh_token=refresh_token,
        )
        return tokens

    async def start_callback_server(self) -> str:
        """Start a temporary HTTP server to catch the OAuth redirect.

        Listens on redirect_port (or an ephemeral port if 0), extracts the
        authorization code from the callback query string, shows a
        "you can close this window" page, then shuts down.

        Returns the authorization code.
        """
        aiohttp_web = _require_aiohttp_web()
        code_result: str | None = None

        async def handle_callback(request: aiohttp_web.Request) -> aiohttp_web.Response:
            nonlocal code_result
            auth_code = request.query.get("code")
            if not auth_code:
                return aiohttp_web.Response(
                    text="Missing 'code' parameter.",
                    status=400,
                    content_type="text/plain",
                )

            code_result = auth_code
            return aiohttp_web.Response(
                text=(
                    "<html><body>"
                    "<h1>Authorization successful</h1>"
                    "<p>You can close this window.</p>"
                    "</body></html>"
                ),
                content_type="text/html",
            )

        app = aiohttp_web.Application()
        app.router.add_get("/callback", handle_callback)

        runner = aiohttp_web.AppRunner(app)
        await runner.setup()
        site = aiohttp_web.TCPSite(runner, "localhost", self._redirect_port)
        await site.start()

        logger.info("OAuth callback server listening on port %d", self._redirect_port)

        try:
            # Poll until we receive the code
            import asyncio

            while code_result is None:
                await asyncio.sleep(0.05)
        finally:
            await runner.cleanup()

        return code_result

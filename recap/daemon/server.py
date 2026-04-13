"""HTTP server for the Recap daemon."""

import hmac

from aiohttp import web


async def _health(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "version": "0.2.0"})


async def _api_status(_request: web.Request) -> web.Response:
    return web.json_response(
        {
            "state": "idle",
            "recording": None,
            "daemon_uptime": 0,
            "last_calendar_sync": None,
            "errors": [],
        }
    )


def _auth_middleware(auth_token: str):
    """Return middleware that enforces Bearer token auth on /api/* routes."""

    @web.middleware
    async def middleware(request: web.Request, handler):
        if request.path.startswith("/api/"):
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return web.json_response(
                    {"error": "unauthorized"}, status=401
                )
            token = header[len("Bearer "):]
            if not hmac.compare_digest(token, auth_token):
                return web.json_response(
                    {"error": "unauthorized"}, status=401
                )
        return await handler(request)

    return middleware


def create_app(auth_token: str) -> web.Application:
    """Create and return the daemon aiohttp application."""
    app = web.Application(middlewares=[_auth_middleware(auth_token)])
    app.router.add_get("/health", _health)
    app.router.add_get("/api/status", _api_status)
    return app

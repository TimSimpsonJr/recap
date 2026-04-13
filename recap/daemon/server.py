"""HTTP server for the Recap daemon."""

from __future__ import annotations

import hmac
import json
import logging
from typing import TYPE_CHECKING

import aiohttp
from aiohttp import web

if TYPE_CHECKING:
    from recap.daemon.recorder.recorder import Recorder

logger = logging.getLogger("recap.daemon.server")

_WS_CLIENTS_KEY = web.AppKey("ws_clients", set)
_RECORDER_KEY = web.AppKey("recorder", object)


async def broadcast(app: web.Application, message: dict) -> None:
    """Send a JSON message to all connected WebSocket clients."""
    clients: set[web.WebSocketResponse] = app[_WS_CLIENTS_KEY]
    dead: list[web.WebSocketResponse] = []
    payload = json.dumps(message)

    for ws in clients:
        if ws.closed:
            dead.append(ws)
            continue
        try:
            await ws.send_str(payload)
        except (ConnectionResetError, ConnectionError):
            dead.append(ws)

    for ws in dead:
        clients.discard(ws)


async def _health(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "version": "0.2.0"})


async def _api_status(request: web.Request) -> web.Response:
    recorder: Recorder | None = request.app.get(_RECORDER_KEY)
    if recorder is None:
        return web.json_response(
            {
                "state": "idle",
                "recording": None,
                "daemon_uptime": 0,
                "last_calendar_sync": None,
                "errors": [],
            }
        )

    state = recorder.state_machine.state.value
    recording_info = None
    if recorder.is_recording and recorder.current_recording_path is not None:
        recording_info = {
            "path": str(recorder.current_recording_path),
            "org": recorder.state_machine.current_org or "",
        }

    return web.json_response(
        {
            "state": state,
            "recording": recording_info,
            "daemon_uptime": 0,
            "last_calendar_sync": None,
            "errors": [],
        }
    )


async def _record_start(request: web.Request) -> web.Response:
    recorder: Recorder | None = request.app.get(_RECORDER_KEY)
    if recorder is None:
        return web.json_response(
            {"error": "recorder not available"}, status=503
        )

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return web.json_response(
            {"error": "invalid JSON body"}, status=400
        )

    org = body.get("org")
    if not org:
        return web.json_response(
            {"error": "missing 'org' field"}, status=400
        )

    if recorder.is_recording:
        return web.json_response(
            {"error": "already recording"}, status=409
        )

    try:
        path = await recorder.start(org)
        return web.json_response({"recording_path": str(path)})
    except Exception as exc:
        logger.exception("Failed to start recording")
        return web.json_response(
            {"error": str(exc)}, status=500
        )


async def _record_stop(request: web.Request) -> web.Response:
    recorder: Recorder | None = request.app.get(_RECORDER_KEY)
    if recorder is None:
        return web.json_response(
            {"error": "recorder not available"}, status=503
        )

    if not recorder.is_recording:
        return web.json_response(
            {"error": "not recording"}, status=409
        )

    try:
        path = await recorder.stop()
        return web.json_response({"recording_path": str(path)})
    except Exception as exc:
        logger.exception("Failed to stop recording")
        return web.json_response(
            {"error": str(exc)}, status=500
        )


async def _websocket_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    clients: set[web.WebSocketResponse] = request.app[_WS_CLIENTS_KEY]
    clients.add(ws)
    logger.debug("WebSocket client connected (%d total)", len(clients))

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.ERROR:
                logger.warning(
                    "WebSocket error: %s", ws.exception()
                )
    finally:
        clients.discard(ws)
        logger.debug("WebSocket client disconnected (%d remaining)", len(clients))

    return ws


def _auth_middleware(auth_token: str):
    """Return middleware that enforces Bearer token auth on /api/* routes.

    WebSocket endpoint /api/ws is exempt from auth for now.
    """

    @web.middleware
    async def middleware(request: web.Request, handler):
        if request.path.startswith("/api/") and request.path != "/api/ws":
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


def create_app(
    auth_token: str,
    recorder: Recorder | None = None,
) -> web.Application:
    """Create and return the daemon aiohttp application."""
    app = web.Application(middlewares=[_auth_middleware(auth_token)])
    app[_WS_CLIENTS_KEY] = set()
    if recorder is not None:
        app[_RECORDER_KEY] = recorder

    app.router.add_get("/health", _health)
    app.router.add_get("/api/status", _api_status)
    app.router.add_post("/api/record/start", _record_start)
    app.router.add_post("/api/record/stop", _record_stop)
    app.router.add_get("/api/ws", _websocket_handler)
    return app

"""HTTP server for the Recap daemon."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Awaitable

import aiohttp
from aiohttp import web

if TYPE_CHECKING:
    from recap.daemon.calendar.scheduler import CalendarSyncScheduler
    from recap.daemon.config import DaemonConfig
    from recap.daemon.recorder.detector import MeetingDetector
    from recap.daemon.recorder.recorder import Recorder

logger = logging.getLogger("recap.daemon.server")

_WS_CLIENTS_KEY = web.AppKey("ws_clients", set)
_RECORDER_KEY = web.AppKey("recorder", object)
_DETECTOR_KEY = web.AppKey("detector", object)
_PIPELINE_TRIGGER_KEY = web.AppKey("pipeline_trigger", object)
_CONFIG_KEY = web.AppKey("config", object)
_SCHEDULER_KEY = web.AppKey("scheduler", object)


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


async def _meeting_detected(request: web.Request) -> web.Response:
    """POST /meeting-detected — browser extension signals a meeting URL was found."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return web.json_response({"error": "invalid JSON body"}, status=400)

    logger.info(
        "Meeting detected: platform=%s url=%s title=%s tabId=%s",
        body.get("platform"),
        body.get("url"),
        body.get("title"),
        body.get("tabId"),
    )
    # TODO: Forward this signal to the detector/recorder so it can trigger
    # automatic recording. Currently this endpoint only logs and acknowledges.
    # Wire to: recorder.on_meeting_detected(platform, url, title, tab_id)
    return web.json_response({"status": "acknowledged"})


async def _meeting_ended(request: web.Request) -> web.Response:
    """POST /meeting-ended — browser extension signals meeting page closed."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return web.json_response({"error": "invalid JSON body"}, status=400)

    logger.info("Meeting ended: tabId=%s", body.get("tabId"))
    # TODO: Forward this signal to the detector/recorder so it can trigger
    # automatic stop. Currently this endpoint only logs and acknowledges.
    # Wire to: recorder.on_meeting_ended(tab_id)
    return web.json_response({"status": "acknowledged"})


async def _api_status(request: web.Request) -> web.Response:
    recorder: Recorder | None = request.app.get(_RECORDER_KEY)
    scheduler: CalendarSyncScheduler | None = request.app.get(_SCHEDULER_KEY)

    last_sync = None
    if scheduler is not None and scheduler.last_sync is not None:
        last_sync = scheduler.last_sync.isoformat()

    if recorder is None:
        return web.json_response(
            {
                "state": "idle",
                "recording": None,
                "daemon_uptime": 0,
                "last_calendar_sync": last_sync,
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
            "last_calendar_sync": last_sync,
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


async def _reprocess(request: web.Request) -> web.Response:
    """POST /api/meetings/reprocess — re-run pipeline from a given stage."""
    trigger = request.app.get(_PIPELINE_TRIGGER_KEY)
    if trigger is None:
        return web.json_response(
            {"error": "pipeline not configured"}, status=503
        )

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return web.json_response({"error": "invalid JSON body"}, status=400)

    recording_path = body.get("recording_path")
    if not recording_path:
        return web.json_response(
            {"error": "missing 'recording_path' field"}, status=400
        )

    from_stage = body.get("from_stage")
    org = body.get("org", "")

    asyncio.create_task(trigger(Path(recording_path), org, from_stage))
    return web.json_response({"status": "processing"})


async def _speakers(request: web.Request) -> web.Response:
    """POST /api/meetings/speakers — save speaker mapping and reprocess from export."""
    trigger = request.app.get(_PIPELINE_TRIGGER_KEY)
    if trigger is None:
        return web.json_response(
            {"error": "pipeline not configured"}, status=503
        )

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return web.json_response({"error": "invalid JSON body"}, status=400)

    recording_path = body.get("recording_path")
    mapping = body.get("mapping")
    if not recording_path:
        return web.json_response(
            {"error": "missing 'recording_path' field"}, status=400
        )
    if not mapping or not isinstance(mapping, dict):
        return web.json_response(
            {"error": "missing or invalid 'mapping' field"}, status=400
        )

    # Save speaker mapping alongside the recording
    rec_path = Path(recording_path)
    speakers_file = rec_path.with_suffix(".speakers.json")
    speakers_file.write_text(json.dumps(mapping, indent=2))
    logger.info("Speaker mapping saved: %s", speakers_file)

    org = body.get("org", "")

    asyncio.create_task(trigger(rec_path, org, "analyze"))
    return web.json_response({"status": "processing"})


async def _arm(request: web.Request) -> web.Response:
    """POST /api/arm — arm the detector for an upcoming calendar event."""
    from datetime import datetime

    detector: MeetingDetector | None = request.app.get(_DETECTOR_KEY)
    if detector is None:
        return web.json_response(
            {"error": "detector not available"}, status=503
        )

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return web.json_response({"error": "invalid JSON body"}, status=400)

    event_id = body.get("event_id")
    start_time_str = body.get("start_time")
    org = body.get("org")
    if not event_id or not start_time_str or not org:
        return web.json_response(
            {"error": "missing required fields: event_id, start_time, org"},
            status=400,
        )

    try:
        start_time = datetime.fromisoformat(start_time_str)
    except (ValueError, TypeError):
        return web.json_response(
            {"error": "invalid start_time format"}, status=400
        )

    platform_hint = body.get("platform_hint")
    detector.arm_for_event(event_id, start_time, org, platform_hint)
    return web.json_response({"status": "armed"})


async def _disarm(request: web.Request) -> web.Response:
    """POST /api/disarm — disarm the detector."""
    detector: MeetingDetector | None = request.app.get(_DETECTOR_KEY)
    if detector is None:
        return web.json_response(
            {"error": "detector not available"}, status=503
        )

    detector.disarm()
    return web.json_response({"status": "disarmed"})


async def _autostart_status(_request: web.Request) -> web.Response:
    """GET /api/autostart — check if auto-start is enabled."""
    from recap.daemon.autostart import is_autostart_enabled

    return web.json_response({
        "enabled": is_autostart_enabled(),
        "implemented": False,
    })


async def _oauth_status(request: web.Request) -> web.Response:
    """GET /api/oauth/:provider/status — check if a provider is connected."""
    from recap.daemon.credentials import has_credential

    provider = request.match_info["provider"]
    if provider not in ("zoho", "google"):
        return web.json_response(
            {"error": f"unknown provider: {provider}"}, status=400,
        )

    connected = has_credential(provider, "access_token")
    return web.json_response({"connected": connected, "provider": provider})


async def _oauth_start(request: web.Request) -> web.Response:
    """POST /api/oauth/:provider/start — initiate OAuth flow."""
    from recap.daemon.calendar.oauth import OAuthManager
    from recap.daemon.credentials import get_credential, store_credential

    provider = request.match_info["provider"]
    if provider not in ("zoho", "google"):
        return web.json_response(
            {"error": f"unknown provider: {provider}"}, status=400,
        )

    client_id = get_credential(provider, "client_id")
    client_secret = get_credential(provider, "client_secret")

    if not client_id or not client_secret:
        return web.json_response(
            {"error": f"no client_id/client_secret configured for {provider}"},
            status=400,
        )

    mgr = OAuthManager(provider, client_id, client_secret, redirect_port=8399)
    authorize_url = mgr.get_authorization_url()

    # Start callback server in background — exchanges code and stores tokens
    async def _run_callback() -> None:
        try:
            code = await mgr.start_callback_server()
            tokens = mgr.exchange_code(code)
            store_credential(provider, "access_token", tokens["access_token"])
            if "refresh_token" in tokens:
                store_credential(provider, "refresh_token", tokens["refresh_token"])
            logger.info("OAuth flow complete for %s", provider)
        except Exception:
            logger.exception("OAuth callback failed for %s", provider)

    asyncio.create_task(_run_callback())

    # Return the URL immediately — the plugin opens it in a browser
    return web.json_response({"authorize_url": authorize_url})


async def _oauth_disconnect(request: web.Request) -> web.Response:
    """DELETE /api/oauth/:provider — disconnect a provider."""
    from recap.daemon.credentials import delete_credential

    provider = request.match_info["provider"]
    if provider not in ("zoho", "google"):
        return web.json_response(
            {"error": f"unknown provider: {provider}"}, status=400,
        )

    for key in ("access_token", "refresh_token", "calendar_id"):
        try:
            delete_credential(provider, key)
        except Exception:
            pass

    logger.info("Disconnected OAuth provider: %s", provider)
    return web.json_response({"status": "disconnected", "provider": provider})


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
    detector: MeetingDetector | None = None,
    pipeline_trigger: Callable[[Path, str, str | None], Awaitable[None]] | None = None,
    config: DaemonConfig | None = None,
    scheduler: CalendarSyncScheduler | None = None,
) -> web.Application:
    """Create and return the daemon aiohttp application."""
    app = web.Application(middlewares=[_auth_middleware(auth_token)])
    app[_WS_CLIENTS_KEY] = set()
    if recorder is not None:
        app[_RECORDER_KEY] = recorder
    if detector is not None:
        app[_DETECTOR_KEY] = detector
    if pipeline_trigger is not None:
        app[_PIPELINE_TRIGGER_KEY] = pipeline_trigger
    if config is not None:
        app[_CONFIG_KEY] = config
    if scheduler is not None:
        app[_SCHEDULER_KEY] = scheduler

    app.router.add_get("/health", _health)
    app.router.add_post("/meeting-detected", _meeting_detected)
    app.router.add_post("/meeting-ended", _meeting_ended)
    app.router.add_get("/api/status", _api_status)
    app.router.add_post("/api/record/start", _record_start)
    app.router.add_post("/api/record/stop", _record_stop)
    app.router.add_post("/api/arm", _arm)
    app.router.add_post("/api/disarm", _disarm)
    app.router.add_post("/api/meetings/reprocess", _reprocess)
    app.router.add_post("/api/meetings/speakers", _speakers)
    app.router.add_get("/api/autostart", _autostart_status)
    app.router.add_get("/api/oauth/{provider}/status", _oauth_status)
    app.router.add_post("/api/oauth/{provider}/start", _oauth_start)
    app.router.add_delete("/api/oauth/{provider}", _oauth_disconnect)
    app.router.add_get("/api/ws", _websocket_handler)
    return app

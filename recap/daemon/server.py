"""HTTP server for the Recap daemon."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import pathlib
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Awaitable

import aiohttp
from aiohttp import web

from recap.artifacts import transcript_path as artifact_transcript_path
from recap.daemon.api_config import (
    api_config_to_json_dict,
    apply_api_patch_to_yaml_doc,
    dump_yaml_doc,
    find_unknown_keys,
    load_yaml_doc,
    validate_yaml_doc,
    yaml_doc_to_api_config,
)

if TYPE_CHECKING:
    from recap.daemon.calendar.scheduler import CalendarSyncScheduler
    from recap.daemon.config import DaemonConfig
    from recap.daemon.recorder.detector import MeetingDetector
    from recap.daemon.recorder.recorder import Recorder
    from recap.daemon.service import Daemon

logger = logging.getLogger("recap.daemon.server")

_WS_CLIENTS_KEY = web.AppKey("ws_clients", set)
_RECORDER_KEY = web.AppKey("recorder", object)

# Analysis backends the daemon knows how to dispatch. Kept in sync with
# ``recap.analyze._BACKEND_LABELS`` and the signal-popup's hardcoded list
# in ``recap.daemon.__main__``. Exposed to the plugin via
# ``/api/config/orgs`` so the Start Recording modal can render a dropdown
# without hardcoding the set.
_SUPPORTED_BACKENDS: tuple[str, ...] = ("claude", "ollama")
_DETECTOR_KEY = web.AppKey("detector", object)
_PIPELINE_TRIGGER_KEY = web.AppKey("pipeline_trigger", object)
_CONFIG_KEY = web.AppKey("config", object)
_SCHEDULER_KEY = web.AppKey("scheduler", object)
_AUTH_TOKEN_KEY = web.AppKey("auth_token", str)

_MAX_EVENTS_LIMIT = 500
_DEFAULT_EVENTS_LIMIT = 100


async def broadcast(app: web.Application, message: dict) -> None:
    """Send a JSON message to all connected WebSocket clients."""
    clients: set[web.WebSocketResponse] = app[_WS_CLIENTS_KEY]
    dead: list[web.WebSocketResponse] = []
    payload = json.dumps(message)

    # Iterate over a snapshot so concurrent connect/disconnect during
    # an ``await send_str`` can't raise ``RuntimeError: Set changed
    # size during iteration`` and drop the broadcast.
    for ws in list(clients):
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
    scheduler: CalendarSyncScheduler | None = request.app.get(_SCHEDULER_KEY)
    daemon: Daemon | None = request.app.get("daemon")

    last_sync = None
    if scheduler is not None and scheduler.last_sync is not None:
        last_sync = scheduler.last_sync.isoformat()

    # Real uptime + recent errors, sourced from the Daemon if wired.
    uptime: float = 0.0
    recent_errors: list[dict[str, Any]] = []
    if daemon is not None:
        if daemon.started_at is not None:
            now = datetime.now(timezone.utc).astimezone()
            uptime = (now - daemon.started_at).total_seconds()
        if daemon.event_journal is not None:
            recent_errors = daemon.event_journal.tail(level="error", limit=10)

    if recorder is None:
        return web.json_response(
            {
                "state": "idle",
                "recording": None,
                "last_calendar_sync": last_sync,
                "uptime_seconds": uptime,
                "recent_errors": recent_errors,
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
            "last_calendar_sync": last_sync,
            "uptime_seconds": uptime,
            "recent_errors": recent_errors,
        }
    )


async def _api_events(request: web.Request) -> web.Response:
    """GET /api/events -- journal backfill for plugin notification history.

    Supports ``limit`` (clamped to [1, ``_MAX_EVENTS_LIMIT``], default
    ``_DEFAULT_EVENTS_LIMIT``) and ``since`` (RFC3339 timestamp; strict
    greater-than filter). Returns entries ascending by timestamp.

    Malformed query params return 400; out-of-range ``limit`` values are
    clamped. Missing/invalid Bearer is rejected by ``_auth_middleware``
    before reaching this handler.
    """
    daemon: Daemon = request.app["daemon"]

    limit_str = request.query.get("limit", str(_DEFAULT_EVENTS_LIMIT))
    try:
        limit = int(limit_str)
    except ValueError:
        return web.json_response({"error": "limit must be an integer"}, status=400)
    limit = max(1, min(_MAX_EVENTS_LIMIT, limit))

    since_str = request.query.get("since")
    since_dt = None
    if since_str is not None:
        try:
            since_dt = datetime.fromisoformat(since_str)
        except ValueError:
            return web.json_response(
                {"error": "since must be RFC3339 timestamp"}, status=400,
            )
        if since_dt.tzinfo is None:
            return web.json_response(
                {"error": "since must include a timezone offset"},
                status=400,
            )

    raw_entries = daemon.event_journal.tail(limit=_MAX_EVENTS_LIMIT)
    filtered = []
    for entry in raw_entries:
        ts_str = entry.get("ts")
        if not isinstance(ts_str, str):
            continue
        try:
            entry_dt = datetime.fromisoformat(ts_str)
        except ValueError:
            continue
        if entry_dt.tzinfo is None:
            continue  # defensive: skip legacy/manually-edited entries
        if since_dt is not None and entry_dt <= since_dt:
            continue
        filtered.append(entry)

    return web.json_response({"entries": filtered[-limit:]})


async def _api_config_get(request: web.Request) -> web.Response:
    """GET /api/config -- return the allowlisted, secret-free config DTO."""
    daemon: Daemon = request.app["daemon"]
    if daemon.config_path is None:
        return web.json_response(
            {"error": "config path not available"}, status=503,
        )
    try:
        doc = load_yaml_doc(daemon.config_path)
        api = yaml_doc_to_api_config(doc)
    except (OSError, ValueError) as e:
        return web.json_response({"error": str(e)}, status=500)
    return web.json_response(api_config_to_json_dict(api))


_STEM_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_CLIP_MIN_DURATION = 1
_CLIP_MAX_DURATION = 30
_CLIP_DEFAULT_DURATION = 5


def _run_ffmpeg_clip(cmd: list[str]) -> tuple[int, bytes]:
    """Run ffmpeg with list args (no shell). Returns ``(returncode, stderr)``.

    Split out as a module-level function so tests can mock
    ``asyncio.to_thread`` without having to reach into a closure.
    """
    result = subprocess.run(cmd, capture_output=True, check=False)
    return result.returncode, result.stderr


async def _api_recording_clip(request: web.Request) -> web.Response:
    """GET /api/recordings/<stem>/clip?speaker=SPEAKER_xx[&duration=N]

    Returns an MP3 clip of the first utterance attributed to the given
    speaker. Used by the plugin's speaker correction modal so users can
    hear who they're about to rename.

    Stem is regex-validated to block traversal. The clip is cached at
    ``<recordings_path>/<stem>.clips/<speaker>_<duration>s.mp3`` so
    repeat requests skip ffmpeg entirely. Any ffmpeg failure is
    journaled as ``clip_extraction_failed`` and returns 500.
    """
    daemon: Daemon = request.app["daemon"]
    stem = request.match_info["stem"]
    if not _STEM_RE.fullmatch(stem):
        return web.json_response({"error": "invalid stem"}, status=400)

    speaker = request.query.get("speaker")
    if not speaker:
        return web.json_response({"error": "speaker required"}, status=400)

    duration_str = request.query.get("duration", str(_CLIP_DEFAULT_DURATION))
    try:
        duration = int(duration_str)
    except ValueError:
        return web.json_response(
            {"error": "duration must be an integer"}, status=400,
        )
    if duration < _CLIP_MIN_DURATION or duration > _CLIP_MAX_DURATION:
        return web.json_response(
            {
                "error": f"duration must be in "
                         f"[{_CLIP_MIN_DURATION}, {_CLIP_MAX_DURATION}]",
            },
            status=400,
        )

    # Source recordings are FLAC, but the archive stage converts to
    # ``.m4a`` and can delete the source (``delete-source-after-archive``).
    # Prefer the FLAC if it's still on disk, else fall back to the
    # archived MP4/AAC — ffmpeg reads both.
    flac_path = daemon.config.recordings_path / f"{stem}.flac"
    m4a_path = daemon.config.recordings_path / f"{stem}.m4a"
    if flac_path.exists():
        audio_path = flac_path
    elif m4a_path.exists():
        audio_path = m4a_path
    else:
        return web.json_response({"error": "recording not found"}, status=404)

    # Transcript path is derived from whichever audio file we resolved;
    # ``with_suffix`` replaces the last extension so both FLAC and M4A
    # map to the same ``<stem>.transcript.json`` next to the source.
    transcript_file = artifact_transcript_path(audio_path)
    if not transcript_file.exists():
        return web.json_response(
            {"error": "transcript not found"}, status=404,
        )

    try:
        transcript_data = json.loads(
            transcript_file.read_text(encoding="utf-8"),
        )
    except (OSError, json.JSONDecodeError) as e:
        return web.json_response({"error": f"transcript read: {e}"}, status=500)

    utterances = transcript_data.get("utterances") or []
    match = next(
        (u for u in utterances if u.get("speaker") == speaker), None,
    )
    if match is None:
        return web.json_response(
            {"error": "speaker not found in transcript"}, status=404,
        )

    start = float(match["start"])
    end = float(match["end"])
    # Use the requested duration but never exceed the utterance length;
    # floor at 0.5s so very short first utterances still produce audio.
    clip_duration = min(float(duration), max(0.5, end - start))

    cache_dir = daemon.config.recordings_path / f"{stem}.clips"
    cache_file = cache_dir / f"{speaker}_{duration}s.mp3"
    if cache_file.exists():
        return web.FileResponse(
            cache_file, headers={"Content-Type": "audio/mpeg"},
        )

    cache_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-t", f"{clip_duration:.3f}",
        "-i", str(audio_path),
        "-acodec", "libmp3lame",
        "-b:a", "96k",
        "-ar", "22050",
        str(cache_file),
    ]
    returncode, stderr = await asyncio.to_thread(_run_ffmpeg_clip, cmd)
    if returncode != 0:
        daemon.emit_event(
            "error", "clip_extraction_failed",
            f"ffmpeg exit {returncode}",
            payload={
                "stem": stem,
                "speaker": speaker,
                "returncode": returncode,
                "stderr": stderr.decode("utf-8", errors="replace")[:500],
            },
        )
        if cache_file.exists():
            try:
                cache_file.unlink()
            except OSError:
                pass
        return web.json_response(
            {"error": "clip extraction failed"}, status=500,
        )

    return web.FileResponse(
        cache_file, headers={"Content-Type": "audio/mpeg"},
    )


async def _api_config_patch(request: web.Request) -> web.Response:
    """PATCH /api/config -- ruamel round-trip, strict key validation,
    atomic write, ``config_updated`` journal event.
    """
    daemon: Daemon = request.app["daemon"]
    if daemon.config_path is None:
        return web.json_response(
            {"error": "config path not available"}, status=503,
        )

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON"}, status=400)
    if not isinstance(body, dict):
        return web.json_response(
            {"error": "request body must be a JSON object"}, status=400,
        )

    unknown = find_unknown_keys(body)
    if unknown:
        return web.json_response(
            {"error": f"unknown or read-only fields: {unknown}"},
            status=400,
        )

    with daemon.config_lock:
        try:
            doc = load_yaml_doc(daemon.config_path)
            apply_api_patch_to_yaml_doc(doc, body)
            validate_yaml_doc(doc)
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except OSError as e:
            return web.json_response({"error": str(e)}, status=500)

        tmp_path = daemon.config_path.with_suffix(
            daemon.config_path.suffix + ".tmp",
        )
        try:
            with tmp_path.open("w", encoding="utf-8") as f:
                dump_yaml_doc(doc, f)
            os.replace(tmp_path, daemon.config_path)
        except OSError as e:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            return web.json_response({"error": str(e)}, status=500)

    daemon.emit_event(
        "info", "config_updated",
        f"Config updated (keys: {sorted(body.keys())})",
        payload={"changed_keys": sorted(body.keys())},
    )
    return web.json_response({"status": "ok", "restart_required": True})


async def _record_start(request: web.Request) -> web.Response:
    recorder: Recorder | None = request.app.get(_RECORDER_KEY)
    if recorder is None:
        return web.json_response(
            {"error": "recorder not available"}, status=503
        )

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response(
            {"error": "invalid JSON body"}, status=400
        )
    except Exception as e:
        logger.error("Unexpected error in _record_start: %s", e, exc_info=True)
        return web.json_response(
            {"error": "internal server error"}, status=500
        )

    if not isinstance(body, dict):
        return web.json_response(
            {"error": "request body must be a JSON object"}, status=400
        )

    org = body.get("org")
    if not org:
        return web.json_response(
            {"error": "missing 'org' field"}, status=400
        )

    # Optional analysis-backend override. Lets the plugin's Start
    # Recording modal pick Claude vs Ollama per-recording without going
    # through the Signal popup path (design: Scenario 2 backend choice).
    backend = body.get("backend")
    if backend is not None and backend not in _SUPPORTED_BACKENDS:
        return web.json_response(
            {"error": f"unknown backend: {backend}"}, status=400
        )

    if recorder.is_recording:
        return web.json_response(
            {"error": "already recording"}, status=409
        )

    try:
        path = await recorder.start(org, backend=backend)
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
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    except Exception as e:
        logger.error("Unexpected error in _reprocess: %s", e, exc_info=True)
        return web.json_response({"error": "internal server error"}, status=500)

    if not isinstance(body, dict):
        return web.json_response(
            {"error": "request body must be a JSON object"}, status=400
        )

    recording_path = body.get("recording_path")
    if not recording_path:
        return web.json_response(
            {"error": "missing 'recording_path' field"}, status=400
        )

    from_stage = body.get("from_stage")
    org = body.get("org", "")
    from recap.pipeline import validate_from_stage

    validation_error = validate_from_stage(Path(recording_path), from_stage)
    if validation_error is not None:
        return web.json_response({"error": validation_error}, status=400)

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
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    except Exception as e:
        logger.error("Unexpected error in _speakers: %s", e, exc_info=True)
        return web.json_response({"error": "internal server error"}, status=500)

    if not isinstance(body, dict):
        return web.json_response(
            {"error": "request body must be a JSON object"}, status=400
        )

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

    from recap.artifacts import speakers_path
    from recap.pipeline import validate_from_stage

    # Save speaker mapping alongside the recording
    rec_path = Path(recording_path)
    validation_error = validate_from_stage(rec_path, "analyze")
    if validation_error is not None:
        return web.json_response({"error": validation_error}, status=400)

    speakers_file = speakers_path(rec_path)
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
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    except Exception as e:
        logger.error("Unexpected error in _arm: %s", e, exc_info=True)
        return web.json_response({"error": "internal server error"}, status=500)

    if not isinstance(body, dict):
        return web.json_response(
            {"error": "request body must be a JSON object"}, status=400
        )

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


async def _config_orgs(request: web.Request) -> web.Response:
    """GET /api/config/orgs — return orgs (with per-org default backend)
    and the full list of supported analysis backends. The plugin's Start
    Recording modal uses this to render an org dropdown + backend dropdown
    where the backend defaults to the selected org's configured choice."""
    config: DaemonConfig | None = request.app.get(_CONFIG_KEY)
    if config is None:
        return web.json_response({
            "orgs": [{"name": "default", "default_backend": "claude"}],
            "backends": list(_SUPPORTED_BACKENDS),
        })

    orgs = [
        {
            "name": org.name,
            "default_backend": org.llm_backend or "claude",
        }
        for org in config.orgs
    ]
    if not orgs:
        orgs = [{"name": "default", "default_backend": "claude"}]
    return web.json_response({
        "orgs": orgs,
        "backends": list(_SUPPORTED_BACKENDS),
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

    oauth_manager = OAuthManager(provider, client_id, client_secret, redirect_port=8399)
    authorize_url = oauth_manager.get_authorization_url()
    # Log the scope(s) being requested so integration runs can prove
    # the running daemon picked up scope changes without having to
    # inspect the browser URL.
    logger.info(
        "OAuth authorize URL for %s requests scopes=%r",
        provider, OAuthManager.PROVIDERS[provider]["scopes"],
    )

    # Start callback server in background -- exchanges code and stores tokens,
    # then logs the scope the provider actually granted (may differ from
    # what we requested if the consent screen was narrowed).
    async def _run_callback() -> None:
        try:
            code = await oauth_manager.start_callback_server()
            tokens = oauth_manager.exchange_code(code)
            store_credential(provider, "access_token", tokens["access_token"])
            if "refresh_token" in tokens:
                store_credential(provider, "refresh_token", tokens["refresh_token"])
            granted_scope = tokens.get("scope", "<not returned>")
            logger.info(
                "OAuth flow complete for %s; granted scope=%r",
                provider, granted_scope,
            )
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
        except Exception as e:
            logger.warning("Failed to delete credential for %s: %s", provider, e)

    logger.info("Disconnected OAuth provider: %s", provider)
    return web.json_response({"status": "disconnected", "provider": provider})


async def _api_index_rename(request: web.Request) -> web.Response:
    """POST /api/index/rename — update EventIndex path for an event.

    Called by the Obsidian plugin's rename processor (Phase 4) when a
    calendar-seeded note is moved or renamed in the vault. The handler
    updates the vault-relative path in the EventIndex; ``org`` is
    preserved by :meth:`EventIndex.rename`. Missing entries are a no-op
    (matches index semantics) so a rename event for an unknown id just
    returns 200 with no side effects.

    Body: ``{"event_id": str, "new_path": str, "old_path"?: str}``. The
    ``old_path`` field is accepted for future debugging/telemetry but
    is not consulted by the handler.
    """
    daemon: Daemon | None = request.app.get("daemon")
    if daemon is None:
        return web.json_response({"error": "daemon not available"}, status=503)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    except Exception as e:
        logger.error("Unexpected error in _api_index_rename: %s", e, exc_info=True)
        return web.json_response({"error": "internal server error"}, status=500)

    if not isinstance(body, dict):
        return web.json_response(
            {"error": "request body must be a JSON object"}, status=400
        )

    event_id = body.get("event_id")
    new_path = body.get("new_path")
    if not event_id or not new_path:
        return web.json_response(
            {"error": "event_id and new_path required"}, status=400
        )
    if not isinstance(event_id, str) or not isinstance(new_path, str):
        return web.json_response(
            {"error": "event_id and new_path must be strings"},
            status=400,
        )

    # Reject absolute paths in either POSIX form (``/foo/bar``) or
    # Windows form (``C:/foo`` / ``C:\foo``). EventIndex stores paths
    # as ``PurePosixPath``; the plugin should always send vault-relative.
    if (
        pathlib.PurePosixPath(new_path).is_absolute()
        or pathlib.PureWindowsPath(new_path).is_absolute()
    ):
        return web.json_response(
            {"error": "new_path must be vault-relative"}, status=400
        )

    rel_path = pathlib.PurePosixPath(pathlib.Path(new_path).as_posix())
    # Check existence before rename so the journal reflects actual state
    # change: EventIndex.rename() silently no-ops on unknown event_id,
    # and observability should show "what the daemon actually did," not
    # "what the plugin claimed." The theoretical lookup/rename race is
    # harmless under the index lock.
    existed = daemon.event_index.lookup(event_id) is not None
    daemon.event_index.rename(event_id, rel_path)
    if existed:
        daemon.emit_event(
            "info",
            "index_rename",
            f"Renamed event-index entry {event_id} -> {rel_path}",
            payload={"event_id": event_id, "new_path": str(rel_path)},
        )
    return web.json_response({"status": "ok"})


async def _websocket_handler(request: web.Request) -> web.WebSocketResponse:
    # Validate token from query parameter
    token = request.query.get("token", "")
    expected = request.app.get(_AUTH_TOKEN_KEY, "")
    if not token or not hmac.compare_digest(token, expected):
        return web.json_response({"error": "unauthorized"}, status=401)

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    clients: set[web.WebSocketResponse] = request.app[_WS_CLIENTS_KEY]
    clients.add(ws)
    logger.debug("WebSocket client connected (%d total)", len(clients))

    # Subscribe to the journal so this client receives a ``journal_entry``
    # frame for every new entry. The subscriber fires on whatever thread
    # called EventJournal.append(), so we marshal to the running loop via
    # run_coroutine_threadsafe. run_coroutine_threadsafe failures (loop
    # closed, etc.) are logged and swallowed.
    daemon: Daemon | None = request.app.get("daemon")
    loop = asyncio.get_running_loop()
    unsubscribe: Callable[[], None] | None = None
    if daemon is not None and daemon.event_journal is not None:
        def _on_journal_entry(entry: dict[str, Any]) -> None:
            try:
                if ws.closed or loop.is_closed():
                    return
                asyncio.run_coroutine_threadsafe(
                    ws.send_json({"event": "journal_entry", "entry": entry}),
                    loop,
                )
            except Exception:
                logger.exception("Failed to marshal journal entry to WebSocket")

        unsubscribe = daemon.event_journal.subscribe(_on_journal_entry)

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.ERROR:
                logger.warning(
                    "WebSocket error: %s", ws.exception()
                )
    finally:
        if unsubscribe is not None:
            try:
                unsubscribe()
            except Exception:
                logger.exception("Failed to unsubscribe journal listener")
        clients.discard(ws)
        logger.debug("WebSocket client disconnected (%d remaining)", len(clients))

    return ws


def _extract_peer_ip(request: web.Request) -> str:
    """Return the peer IP aiohttp saw on this request, or ``""`` if unknown.

    Isolated so tests can monkey-patch it to simulate non-loopback
    callers. We intentionally trust only ``transport.get_extra_info``
    (the kernel-level peer) and never ``X-Forwarded-For``, since the
    daemon binds loopback-only and there is no legitimate proxy in
    front of it.
    """
    transport = request.transport
    if transport is None:
        return ""
    peername = transport.get_extra_info("peername")
    if not peername:
        return ""
    # peername is typically (host, port) for IPv4 or (host, port, ...) for IPv6.
    host = peername[0] if isinstance(peername, tuple) and peername else ""
    return host or ""


async def _bootstrap_token(request: web.Request) -> web.Response:
    """GET /bootstrap/token -- one-shot loopback pairing endpoint (design §0.5).

    Publicly routed (no Bearer required); the security gate is the
    ``PairingWindow.is_open`` flag plus a loopback-only peer check.

    - Window closed -> 404 (as if the route didn't exist).
    - Loopback peer, window open -> 200 with ``{"token": "<auth_token>"}``
      and the window closes for future requests.
    - Non-loopback peer -> 403; window stays open for the legitimate
      loopback caller.

    The token handed out is the full daemon ``auth_token`` so the
    extension can authenticate against the same Bearer middleware
    used by the Obsidian plugin. The middleware does constant-time
    compare against a single value, so scoped tokens would require
    middleware changes; see Phase 4+ work.
    """
    daemon: Daemon | None = request.app.get("daemon")
    if daemon is None or not daemon.pairing.is_open:
        return web.json_response({"error": "not found"}, status=404)

    peer_ip = _extract_peer_ip(request)
    try:
        # Return value (pairing_token) is discarded: we hand the
        # extension the daemon auth_token instead. Calling consume()
        # enforces the one-shot + loopback guarantees and journals
        # the appropriate events.
        daemon.pairing.consume(requester_ip=peer_ip)
    except PermissionError:
        return web.json_response({"error": "forbidden"}, status=403)
    except RuntimeError:
        # Lost race: another request consumed between is_open check
        # and consume(). Treat as if the window were closed.
        return web.json_response({"error": "not found"}, status=404)

    auth_token = request.app.get(_AUTH_TOKEN_KEY, "")
    return web.json_response({"token": auth_token})


async def _meeting_detected_api(request: web.Request) -> web.Response:
    """Browser-extension hook for auto-starting a recording."""
    detector: MeetingDetector | None = request.app.get(_DETECTOR_KEY)
    if detector is None:
        return web.json_response({"error": "detector not available"}, status=503)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    except Exception as e:
        logger.error("Unexpected error in _meeting_detected_api: %s", e, exc_info=True)
        return web.json_response({"error": "internal server error"}, status=500)

    if not isinstance(body, dict):
        return web.json_response(
            {"error": "request body must be a JSON object"}, status=400
        )

    platform = body.get("platform")
    url = body.get("url")
    if not platform or not url:
        return web.json_response(
            {"error": "missing required fields: platform, url"},
            status=400,
        )

    started = await detector.handle_extension_meeting_detected(
        platform=str(platform),
        url=str(url),
        title=str(body.get("title") or "Meeting"),
        tab_id=body.get("tabId"),
    )
    return web.json_response({
        "status": "recording_started" if started else "ignored",
    })


async def _meeting_ended_api(request: web.Request) -> web.Response:
    """Browser-extension hook for auto-stopping a recording."""
    detector: MeetingDetector | None = request.app.get(_DETECTOR_KEY)
    if detector is None:
        return web.json_response({"error": "detector not available"}, status=503)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    except Exception as e:
        logger.error("Unexpected error in _meeting_ended_api: %s", e, exc_info=True)
        return web.json_response({"error": "internal server error"}, status=500)

    if not isinstance(body, dict):
        return web.json_response(
            {"error": "request body must be a JSON object"}, status=400
        )

    stopped = await detector.handle_extension_meeting_ended(
        tab_id=body.get("tabId"),
    )
    return web.json_response({
        "status": "recording_stopped" if stopped else "ignored",
    })


@web.middleware
async def _cors_middleware(request: web.Request, handler):
    """Add CORS headers so the Obsidian plugin (``app://`` origin) can
    call ``/api/*`` from within an Electron/Chromium context.

    The daemon binds to loopback only and all ``/api/*`` mutations require
    a Bearer token, so ``Access-Control-Allow-Origin: *`` is acceptable —
    the real security boundary is auth, not origin. Without this
    middleware, Chromium's preflight OPTIONS for requests with an
    ``Authorization`` header is rejected (no OPTIONS handler + no allow
    headers), and the plugin sees ``Failed to fetch`` with no route
    actually reached.

    Must run BEFORE ``_auth_middleware`` (i.e. appear earlier in the
    middleware list) so OPTIONS preflight doesn't get 401'd.
    """
    if request.method == "OPTIONS":
        return web.Response(
            status=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": (
                    "GET, POST, PATCH, DELETE, OPTIONS"
                ),
                "Access-Control-Allow-Headers": "Authorization, Content-Type",
                "Access-Control-Max-Age": "600",
            },
        )
    response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


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
    app = web.Application(
        middlewares=[_cors_middleware, _auth_middleware(auth_token)],
    )
    app[_WS_CLIENTS_KEY] = set()
    app[_AUTH_TOKEN_KEY] = auth_token
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

    # Public (no auth) routes.
    app.router.add_get("/health", _health)
    # One-shot extension pairing endpoint (design §0.5). Security is
    # gated at request time by ``daemon.pairing.is_open`` + loopback
    # check; the route is always registered but 404s while closed.
    app.router.add_get("/bootstrap/token", _bootstrap_token)

    # Authenticated API routes (Bearer enforced by _auth_middleware for
    # every path starting with /api/, except /api/ws which gates via
    # its own query-token check).
    app.router.add_get("/api/status", _api_status)
    app.router.add_get("/api/events", _api_events)
    app.router.add_get("/api/config", _api_config_get)
    app.router.add_patch("/api/config", _api_config_patch)
    app.router.add_get(
        "/api/recordings/{stem}/clip", _api_recording_clip,
    )
    app.router.add_post("/api/record/start", _record_start)
    app.router.add_post("/api/record/stop", _record_stop)
    app.router.add_post("/api/arm", _arm)
    app.router.add_post("/api/disarm", _disarm)
    app.router.add_post("/api/meeting-detected", _meeting_detected_api)
    app.router.add_post("/api/meeting-ended", _meeting_ended_api)
    app.router.add_post("/api/meetings/reprocess", _reprocess)
    app.router.add_post("/api/meetings/speakers", _speakers)
    app.router.add_post("/api/index/rename", _api_index_rename)
    app.router.add_get("/api/config/orgs", _config_orgs)
    app.router.add_get("/api/oauth/{provider}/status", _oauth_status)
    app.router.add_post("/api/oauth/{provider}/start", _oauth_start)
    app.router.add_delete("/api/oauth/{provider}", _oauth_disconnect)
    app.router.add_get("/api/ws", _websocket_handler)
    return app

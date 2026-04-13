"""Entry point: python -m recap.daemon <config-path>"""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import signal
import sys
import threading

from aiohttp import web

from recap.daemon.auth import ensure_auth_token
from recap.daemon.config import load_daemon_config
from recap.daemon.logging_setup import setup_logging
from recap.daemon.notifications import notify
from recap.daemon.recorder.recorder import Recorder
from recap.daemon.recorder.recovery import find_orphaned_recordings
from recap.daemon.server import broadcast, create_app
from recap.daemon.startup import validate_startup
from recap.daemon.tray import RecapTray

logger = logging.getLogger("recap.daemon")


def main() -> None:
    # Parse config path from args
    if len(sys.argv) < 2:
        print("Usage: python -m recap.daemon <config-path>")
        sys.exit(1)

    config_path = pathlib.Path(sys.argv[1])
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        sys.exit(1)

    # Load config
    try:
        config = load_daemon_config(config_path)
    except (ValueError, FileNotFoundError) as e:
        print(f"Config error: {e}")
        sys.exit(1)

    # Setup logging
    log_path = config.vault_path / config.logging.path
    setup_logging(log_path, config.logging.retention_days)
    logger.info("Recap daemon starting")

    # Startup validation
    result = validate_startup(vault_path=config.vault_path, check_gpu=True)
    for check in result.warnings:
        logger.warning("Startup check: %s -- %s", check.name, check.message)
        notify("Recap", check.message)

    if not result.can_start:
        for check in result.checks:
            if check.fatal and not check.passed:
                logger.error(
                    "Fatal startup check: %s -- %s", check.name, check.message,
                )
                notify("Recap -- Cannot Start", check.message)
        sys.exit(1)

    logger.info("Startup validation passed")

    # Check for orphaned recordings
    orphans = find_orphaned_recordings(config.recordings_path)
    for path in orphans:
        logger.warning("Orphaned recording found: %s", path)
        notify("Recap", f"Incomplete recording found: {path.name}")

    # Auth token
    recap_dir = config.vault_path / "_Recap" / ".recap"
    recap_dir.mkdir(parents=True, exist_ok=True)
    auth_token_path = recap_dir / "auth-token"
    auth_token = ensure_auth_token(auth_token_path)
    logger.info("Auth token ready")

    # Create recorder
    recorder = Recorder(
        recordings_path=config.recordings_path,
        silence_timeout_minutes=config.recording.silence_timeout_minutes,
        max_duration_hours=config.recording.max_duration_hours,
    )

    # Wire silence/duration callbacks to notifications
    recorder.on_silence_detected = lambda: notify(
        "Recap", "No audio for 5 minutes. Still in a meeting?",
    )
    recorder.on_max_duration_warning = lambda: notify(
        "Recap", "Recording for 3+ hours. Still going?",
    )
    recorder.on_max_duration_reached = lambda: notify(
        "Recap", "Max recording duration reached. Stopping.",
    )

    # Create HTTP app (pass recorder so endpoints can use it)
    app = create_app(auth_token=auth_token, recorder=recorder)

    # Wire state changes to tray updates + WebSocket broadcasts
    def on_state_change(old, new):
        org = recorder.state_machine.current_org or ""
        tray.update_state(new.value, org)
        # Schedule broadcast on the event loop (state change may fire
        # from any thread, but broadcast is async)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    broadcast(app, {
                        "event": "state_change",
                        "state": new.value,
                        "org": org,
                    })
                )
        except RuntimeError:
            pass

    # Replace state machine with one that has our callback
    from recap.daemon.recorder.state_machine import RecorderStateMachine
    recorder.state_machine = RecorderStateMachine(on_state_change=on_state_change)

    # Setup tray — wire menu items to recorder
    org_names = [org.name for org in config.orgs]

    # The event loop is needed to call async recorder methods from the
    # synchronous tray callbacks.  We capture it after web.run_app starts,
    # but since the tray thread starts first we stash it in a mutable container.
    _loop_holder: list[asyncio.AbstractEventLoop | None] = [None]

    def _run_async(coro):
        """Schedule an async coroutine from the tray thread."""
        loop = _loop_holder[0]
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, loop)

    def on_start_recording(org: str) -> None:
        logger.info("Start recording requested for org: %s", org)
        _run_async(recorder.start(org))

    def on_stop_recording() -> None:
        logger.info("Stop recording requested")
        _run_async(recorder.stop())

    def on_quit() -> None:
        logger.info("Quit requested from tray")
        os.kill(os.getpid(), signal.SIGINT)

    tray = RecapTray(
        orgs=org_names,
        on_start_recording=on_start_recording,
        on_stop_recording=on_stop_recording,
        on_quit=on_quit,
    )

    # Start tray in background thread
    tray_thread = threading.Thread(target=tray.run, daemon=True, name="recap-tray")
    tray_thread.start()
    logger.info("System tray started")

    # Capture the event loop once the server starts so tray callbacks
    # can schedule async work on it.
    async def _on_startup(app_: web.Application) -> None:
        _loop_holder[0] = asyncio.get_event_loop()

    app.on_startup.append(_on_startup)

    # Run HTTP server (blocking)
    logger.info("Starting HTTP server on port %d", config.daemon_ports.plugin_port)
    web.run_app(
        app,
        host="127.0.0.1",
        port=config.daemon_ports.plugin_port,
        print=lambda msg: logger.info(msg),
    )


if __name__ == "__main__":
    main()

"""Entry point: python -m recap.daemon <config-path>"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import pathlib
import signal
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from recap.artifacts import RecordingMetadata, load_recording_metadata
from recap.daemon.auth import ensure_auth_token
from recap.daemon.calendar.scheduler import CalendarSyncScheduler
from recap.daemon.config import DaemonConfig, load_daemon_config
from recap.daemon.logging_setup import setup_logging
from recap.daemon.notifications import notify
from recap.daemon.recorder.detector import MeetingDetector
from recap.daemon.recorder.recorder import Recorder
from recap.daemon.recorder.recovery import find_orphaned_recordings
from recap.daemon.recorder.signal_popup import show_signal_popup
from recap.daemon.runtime_config import build_runtime_config
from recap.daemon.server import broadcast
from recap.daemon.service import Daemon
from recap.daemon.signal_metadata import build_signal_metadata
from recap.daemon.startup import validate_startup
from recap.daemon.tray import RecapTray
from recap.pipeline import run_pipeline

logger = logging.getLogger("recap.daemon")


# ----------------------------------------------------------------------
# Pipeline trigger factory (now closes over the Daemon instead of holders)
# ----------------------------------------------------------------------


def _make_process_recording(daemon: Daemon):
    """Create the async process_recording coroutine bound to a Daemon."""

    async def process_recording(
        flac_path: Path,
        org: str,
        from_stage: str | None = None,
    ) -> None:
        """Run the pipeline in a background task after recording stops."""
        config = daemon.config
        recorder = daemon.recorder
        try:
            org_config = next(
                (o for o in config.orgs if o.name == org),
                config.default_org,
            )
            if org_config is None:
                raise ValueError(f"No org config found for '{org}'")

            recording_metadata = load_recording_metadata(flac_path)
            if recording_metadata is None:
                recording_metadata = RecordingMetadata(
                    org=org,
                    note_path="",
                    title=flac_path.stem,
                    date=datetime.now().date().isoformat(),
                    participants=[],
                    platform="unknown",
                )
            metadata = recording_metadata.to_meeting_metadata()
            pipeline_config = build_runtime_config(config, org_config, recording_metadata)

            # Pass the streaming transcript (if available) so the pipeline
            # can skip batch transcription + diarization when streaming succeeded.
            streaming_transcript = recorder.streaming_result

            note_path = await asyncio.to_thread(
                run_pipeline,
                audio_path=flac_path,
                metadata=metadata,
                config=pipeline_config,
                org_slug=org_config.name,
                org_subfolder=org_config.subfolder,
                vault_path=config.vault_path,
                user_name=config.user_name,
                streaming_transcript=streaming_transcript,
                from_stage=from_stage,
                recording_metadata=recording_metadata,
                event_index=daemon.event_index,
            )
            recorder.state_machine.processing_complete()
            notify("Recap", f"Meeting processed: {note_path.stem}")
        except Exception as e:
            # Ensure state machine returns to idle even on failure
            try:
                recorder.state_machine.processing_complete()
            except Exception as reset_error:
                logger.error(
                    "Failed to reset state machine after pipeline failure: %s",
                    reset_error,
                )
            logger.error("Pipeline failed: %s", e)
            notify("Recap", f"Pipeline failed: {e}")
            await _broadcast_safe(daemon, {
                "event": "error",
                "scope": "pipeline",
                "message": str(e),
                "stage": from_stage or "full",
                "recording_path": str(flac_path),
            })

    return process_recording


# ----------------------------------------------------------------------
# Broadcast helpers (WebSocket frames out to plugin subscribers)
# ----------------------------------------------------------------------


async def _broadcast_safe(daemon: Daemon, message: dict) -> None:
    """Broadcast ``message`` to WebSocket subscribers if the app is up."""
    if daemon.app is not None:
        await broadcast(daemon.app, message)


def _schedule_async(daemon: Daemon, coro) -> None:
    """Schedule ``coro`` on the daemon's loop from any thread.

    Used by sync callbacks (recorder, tray, signal popup) that need to
    fire async work. Errors are logged + surfaced via ``error`` events.
    """
    if daemon.loop is None or not daemon.loop.is_running():
        # Loop not running yet (or already torn down) -- best-effort no-op.
        coro.close()
        return
    future = daemon.run_in_loop(coro)
    future.add_done_callback(lambda f: _handle_async_error(daemon, f))


def _handle_async_error(daemon: Daemon, future) -> None:
    try:
        future.result()
    except Exception as e:
        logger.error("Async callback failed: %s", e)
        notify("Recap Error", str(e))
        # Schedule the error broadcast separately so it doesn't recurse on
        # this failure path.
        if daemon.loop is not None and daemon.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                _broadcast_safe(daemon, {
                    "event": "error",
                    "scope": "async_callback",
                    "message": str(e),
                }),
                daemon.loop,
            )


# ----------------------------------------------------------------------
# Subservice construction + callback wiring (replaces the holder bag)
# ----------------------------------------------------------------------


def _build_subservices(daemon: Daemon, auth_token: str) -> dict[str, Any]:
    """Construct recorder / detector / scheduler and wire their callbacks.

    Callbacks close over ``daemon``; they only access ``daemon.loop`` /
    ``daemon.app`` when invoked, by which time ``Daemon.start()`` has
    populated those attributes. This replaces the old mutable-list closure
    bag pattern that ``__main__.py`` used pre-Phase-3.
    """
    config = daemon.config

    # Recorder.
    recorder = Recorder(
        recordings_path=config.recordings_path,
        silence_timeout_minutes=config.recording.silence_timeout_minutes,
        max_duration_hours=config.recording.max_duration_hours,
    )

    # Pipeline trigger -- reads daemon.recorder lazily at invocation, by
    # which time Daemon.start() has populated it from callbacks["recorder"].
    process_recording = _make_process_recording(daemon)

    # Recording-stopped callback: spawn the pipeline on the event loop.
    def _on_recording_stopped(flac_path: Path, org: str) -> None:
        if daemon.loop is None or not daemon.loop.is_running():
            logger.warning(
                "Event loop not available -- cannot trigger pipeline for %s",
                flac_path,
            )
            return
        asyncio.run_coroutine_threadsafe(
            process_recording(flac_path, org), daemon.loop,
        )

    recorder.on_recording_stopped = _on_recording_stopped

    # Streaming segment callback: bridge audio thread -> WebSocket broadcast.
    def _on_streaming_segment(segment: dict) -> None:
        if daemon.loop is None or not daemon.loop.is_running() or daemon.app is None:
            return
        asyncio.run_coroutine_threadsafe(
            broadcast(daemon.app, {
                "event": "transcript_segment",
                "speaker": segment.get("speaker", "UNKNOWN"),
                "text": segment.get("text", ""),
                "start": segment.get("start", 0),
                "end": segment.get("end", 0),
            }),
            daemon.loop,
        )

    recorder.on_streaming_segment = _on_streaming_segment

    # Silence + duration notifications.
    recorder.on_silence_detected = lambda: (
        notify("Recap", "No audio for 5 minutes. Still in a meeting?"),
        _schedule_async(daemon, _broadcast_safe(daemon, {
            "event": "silence_warning",
            "message": "No audio for 5 minutes. Still in a meeting?",
        })),
    )
    recorder.on_max_duration_warning = lambda: notify(
        "Recap", "Recording for 3+ hours. Still going?",
    )
    recorder.on_max_duration_reached = lambda: notify(
        "Recap", "Max recording duration reached. Stopping.",
    )

    # Signal popup callback -- runs when the detector sees a Signal call.
    def on_signal_detected(meeting_window, enriched_metadata):
        org_names = [org.name for org in config.orgs]
        signal_config = config.detection.signal
        defaults = {
            "org": signal_config.default_org,
            "backend": getattr(signal_config, "default_backend", "ollama"),
        }
        result = show_signal_popup(orgs=org_names, defaults=defaults)
        if result:
            logger.info(
                "Signal recording started: org=%s, backend=%s",
                result["org"], result["backend"],
            )
            if daemon.loop is None or not daemon.loop.is_running():
                logger.warning("Event loop not available -- cannot start Signal recording")
                return
            metadata = build_signal_metadata(result, meeting_window, enriched_metadata)
            asyncio.run_coroutine_threadsafe(
                recorder.start(result["org"], metadata=metadata, detected=True),
                daemon.loop,
            )
        else:
            logger.info("Signal recording declined")

    # Detector.
    detector = MeetingDetector(
        config=config,
        recorder=recorder,
        on_signal_detected=on_signal_detected,
        event_index=daemon.event_index,
    )

    # Scheduler -- needs an async on_rename_queued callback.
    async def _on_rename_queued(count: int) -> None:
        await _broadcast_safe(daemon, {
            "event": "rename_queued",
            "count": count,
        })

    scheduler = CalendarSyncScheduler(
        config=config,
        vault_path=config.vault_path,
        detector=detector,
        on_rename_queued=_on_rename_queued,
        event_index=daemon.event_index,
    )

    # Tray + state-change wiring (constructed after recorder so it closes
    # over recorder.state_machine).
    org_names = [org.name for org in config.orgs]

    def on_start_recording(org: str) -> None:
        logger.info("Start recording requested for org: %s", org)
        _schedule_async(daemon, recorder.start(org))

    def on_stop_recording() -> None:
        logger.info("Stop recording requested")
        _schedule_async(daemon, recorder.stop())

    def on_quit() -> None:
        logger.info("Quit requested from tray")
        os.kill(os.getpid(), signal.SIGINT)

    tray = RecapTray(
        orgs=org_names,
        on_start_recording=on_start_recording,
        on_stop_recording=on_stop_recording,
        on_quit=on_quit,
    )

    def on_state_change(old, new):
        org = recorder.state_machine.current_org or ""
        tray.update_state(new.value, org)
        _schedule_async(daemon, _broadcast_safe(daemon, {
            "event": "state_change",
            "state": new.value,
            "org": org,
        }))

    recorder.set_on_state_change(on_state_change)

    # Start tray in background thread (independent of Daemon lifecycle --
    # the tray thread is daemonized so it exits with the process).
    tray_thread = threading.Thread(target=tray.run, daemon=True, name="recap-tray")
    tray_thread.start()
    logger.info("System tray started")

    return {
        "auth_token": auth_token,
        "recorder": recorder,
        "detector": detector,
        "scheduler": scheduler,
        "pipeline_trigger": process_recording,
    }


# ----------------------------------------------------------------------
# Pre-flight (logging, validation, orphan scan, auth token)
# ----------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m recap.daemon",
        description="Run the Recap daemon.",
    )
    parser.add_argument("config", type=pathlib.Path, help="Path to daemon config YAML")
    return parser.parse_args(argv)


def _preflight(config: DaemonConfig) -> str:
    """Run startup validation, orphan scan, ensure auth token. Returns token.

    Raises ``SystemExit`` on fatal validation failures. Logging is already
    configured by the caller.
    """
    logger.info("Recap daemon starting")

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
        raise SystemExit(1)

    logger.info("Startup validation passed")

    # Check for orphaned recordings.
    status_dir = config.vault_path / "_Recap" / ".recap" / "status"
    orphans = find_orphaned_recordings(config.recordings_path, status_dir=status_dir)
    for path in orphans:
        logger.warning("Orphaned recording found: %s", path)
        notify("Recap", f"Incomplete recording found: {path.name}")

    # Auth token (must live in {vault}/_Recap/.recap/ for the plugin to find it).
    recap_dir = config.vault_path / "_Recap" / ".recap"
    recap_dir.mkdir(parents=True, exist_ok=True)
    auth_token = ensure_auth_token(recap_dir / "auth-token")
    logger.info("Auth token ready")

    return auth_token


# ----------------------------------------------------------------------
# Async lifecycle entry
# ----------------------------------------------------------------------


async def _run_daemon(daemon: Daemon, args: argparse.Namespace, auth_token: str) -> None:
    """Drive the daemon: build subservices, start, wait for shutdown, stop."""
    callbacks = _build_subservices(daemon, auth_token)

    # SIGINT handler that signals shutdown via the Daemon's stop_event.
    # On Windows asyncio doesn't support add_signal_handler for SIGINT, so
    # we use signal.signal + call_soon_threadsafe (Daemon.request_shutdown
    # handles the threadsafe hop internally).
    def _on_sigint(signum, frame):  # noqa: ARG001
        logger.info("SIGINT received -- shutting down")
        daemon.request_shutdown()

    previous_handler = None
    try:
        await daemon.start(args=args, callbacks=callbacks)
        # Install SIGINT handler only AFTER start() completes. If we installed
        # it earlier, a signal arriving during start() would hit
        # request_shutdown() before _stop_event/loop are populated and the
        # user's Ctrl-C would be silently dropped. Python's default SIGINT
        # handler raises KeyboardInterrupt during start(), which asyncio.run
        # propagates cleanly.
        previous_handler = signal.signal(signal.SIGINT, _on_sigint)
        await daemon.wait_for_shutdown()
    finally:
        if previous_handler is not None:
            signal.signal(signal.SIGINT, previous_handler)
        await daemon.stop()


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    if not args.config.exists():
        print(f"Config file not found: {args.config}")
        sys.exit(1)

    try:
        config = load_daemon_config(args.config)
    except (ValueError, FileNotFoundError) as e:
        print(f"Config error: {e}")
        sys.exit(1)

    log_path = config.vault_path / config.logging.path
    setup_logging(log_path, config.logging.retention_days)

    auth_token = _preflight(config)

    daemon = Daemon(config)
    try:
        asyncio.run(_run_daemon(daemon, args, auth_token))
    except KeyboardInterrupt:
        # Belt-and-suspenders: SIGINT handler should have triggered a clean
        # shutdown, but if asyncio.run still raises KeyboardInterrupt, we
        # exit cleanly here.
        logger.info("Daemon interrupted by user")


if __name__ == "__main__":
    main()

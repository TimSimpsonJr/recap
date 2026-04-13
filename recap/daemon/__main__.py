"""Entry point: python -m recap.daemon <config-path>"""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import signal
import sys
import threading
from datetime import date
from pathlib import Path

from aiohttp import web

from recap.daemon.auth import ensure_auth_token
from recap.daemon.calendar.scheduler import CalendarSyncScheduler
from recap.daemon.config import DaemonConfig, load_daemon_config
from recap.daemon.logging_setup import setup_logging
from recap.daemon.notifications import notify
from recap.daemon.recorder.detector import MeetingDetector
from recap.daemon.recorder.recorder import Recorder
from recap.daemon.recorder.recovery import find_orphaned_recordings
from recap.daemon.recorder.signal_popup import show_signal_popup
from recap.daemon.server import broadcast, create_app
from recap.daemon.startup import validate_startup
from recap.daemon.tray import RecapTray
from recap.models import MeetingMetadata
from recap.pipeline import PipelineConfig as PipelineCfg, run_pipeline

logger = logging.getLogger("recap.daemon")


def _build_pipeline_config(config: DaemonConfig, org_config) -> PipelineCfg:
    """Build a PipelineConfig from the daemon config and an org config."""
    return PipelineCfg(
        transcription_model=config.pipeline.transcription_model,
        diarization_model=config.pipeline.diarization_model,
        device="cuda",
        llm_backend=org_config.llm_backend,
        ollama_model="",
        archive_format=config.recording.archive_format,
        archive_bitrate="64k",
        delete_source_after_archive=config.recording.delete_source_after_archive,
        auto_retry=config.pipeline.auto_retry,
        max_retries=config.pipeline.max_retries,
        prompt_template_path=None,
        status_dir=config.vault_path / "_Recap" / ".recap" / "status",
    )


def _make_process_recording(config: DaemonConfig, recorder: Recorder):
    """Create the async process_recording coroutine bound to daemon state."""

    async def process_recording(
        flac_path: Path,
        org: str,
        from_stage: str | None = None,
    ) -> None:
        """Run the pipeline in a background task after recording stops."""
        try:
            org_config = next(
                (o for o in config.orgs if o.name == org),
                config.default_org,
            )
            if org_config is None:
                raise ValueError(f"No org config found for '{org}'")

            metadata = MeetingMetadata(
                title=flac_path.stem,
                date=date.today(),
                participants=[],
                platform="unknown",
            )
            pipeline_config = _build_pipeline_config(config, org_config)

            # Pass the streaming transcript (if available) so the pipeline
            # can skip batch transcription + diarization when streaming succeeded.
            streaming_transcript = recorder.streaming_result

            note_path = run_pipeline(
                audio_path=flac_path,
                metadata=metadata,
                config=pipeline_config,
                org_subfolder=org_config.subfolder,
                vault_path=config.vault_path,
                user_name=config.user_name,
                streaming_transcript=streaming_transcript,
                from_stage=from_stage,
            )
            recorder.state_machine.processing_complete()
            notify("Recap", f"Meeting processed: {note_path.stem}")
        except Exception as e:
            # Ensure state machine returns to idle even on failure
            try:
                recorder.state_machine.processing_complete()
            except Exception:
                pass
            logger.error("Pipeline failed: %s", e)
            notify("Recap", f"Pipeline failed: {e}")

    return process_recording


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

    # The event loop is needed to call async methods from synchronous
    # callbacks (tray, recorder).  We capture it after web.run_app starts,
    # but stash it in a mutable container so closures can reference it.
    _loop_holder: list[asyncio.AbstractEventLoop | None] = [None]

    # Create recorder
    recorder = Recorder(
        recordings_path=config.recordings_path,
        silence_timeout_minutes=config.recording.silence_timeout_minutes,
        max_duration_hours=config.recording.max_duration_hours,
    )

    # Build the pipeline trigger
    process_recording = _make_process_recording(config, recorder)

    # Wire recording-stopped callback: spawn pipeline in the event loop
    def _on_recording_stopped(flac_path: Path, org: str) -> None:
        loop = _loop_holder[0]
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(
                process_recording(flac_path, org), loop,
            )
        else:
            logger.warning(
                "Event loop not available — cannot trigger pipeline for %s",
                flac_path,
            )

    recorder.on_recording_stopped = _on_recording_stopped

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

    # Signal popup callback — runs when the detector sees a Signal call
    def on_signal_detected(meeting_window, enriched_metadata):
        """Show Signal call popup in a separate thread."""
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
            loop = _loop_holder[0]
            if loop is not None and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    recorder.start(result["org"]), loop,
                )
        else:
            logger.info("Signal recording declined")

    # Create meeting detector
    detector = MeetingDetector(
        config=config,
        recorder=recorder,
        on_signal_detected=on_signal_detected,
    )

    # Create calendar sync scheduler
    calendar_scheduler = CalendarSyncScheduler(
        config=config,
        vault_path=config.vault_path,
        detector=detector,
    )

    # Create HTTP app (pass recorder, detector, scheduler so endpoints can use them)
    app = create_app(
        auth_token=auth_token,
        recorder=recorder,
        detector=detector,
        pipeline_trigger=process_recording,
        config=config,
        scheduler=calendar_scheduler,
    )

    # Wire streaming segment callback: bridge from audio thread to async
    # event loop for WebSocket broadcast of live transcript segments.
    def _on_streaming_segment(segment: dict) -> None:
        loop = _loop_holder[0]
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(
                broadcast(app, {
                    "event": "transcript_segment",
                    "speaker": segment.get("speaker", "UNKNOWN"),
                    "text": segment.get("text", ""),
                    "start": segment.get("start", 0),
                    "end": segment.get("end", 0),
                }),
                loop,
            )

    recorder.on_streaming_segment = _on_streaming_segment

    # Helper to schedule async work from synchronous callbacks (tray, state machine)
    def _handle_async_error(future):
        try:
            future.result()
        except Exception as e:
            logger.error("Async callback failed: %s", e)
            notify("Recap Error", str(e))

    def _run_async(coro):
        """Schedule an async coroutine from any thread."""
        loop = _loop_holder[0]
        if loop is not None and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            future.add_done_callback(_handle_async_error)

    # Wire state changes to tray updates + WebSocket broadcasts
    def on_state_change(old, new):
        org = recorder.state_machine.current_org or ""
        tray.update_state(new.value, org)
        # Schedule broadcast on the event loop (state change may fire
        # from any thread, but broadcast is async)
        _run_async(
            broadcast(app, {
                "event": "state_change",
                "state": new.value,
                "org": org,
            })
        )

    # Replace state machine with one that has our callback
    from recap.daemon.recorder.state_machine import RecorderStateMachine
    recorder.state_machine = RecorderStateMachine(on_state_change=on_state_change)

    # Setup tray — wire menu items to recorder
    org_names = [org.name for org in config.orgs]

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
    # can schedule async work on it, and start meeting detection.
    async def _on_startup(app_: web.Application) -> None:
        _loop_holder[0] = asyncio.get_event_loop()
        detector.start()
        logger.info("Meeting detection started")
        await calendar_scheduler.start()
        logger.info("Calendar sync started")

    async def _on_cleanup(app_: web.Application) -> None:
        calendar_scheduler.stop()
        logger.info("Calendar sync stopped")
        detector.stop()
        logger.info("Meeting detection stopped")

    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)

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

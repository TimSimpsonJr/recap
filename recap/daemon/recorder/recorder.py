"""Recorder orchestrator tying together AudioCapture, SilenceDetector, and RecorderStateMachine.

Manages the full recording lifecycle: starting/stopping audio capture,
monitoring for silence timeouts, and enforcing maximum duration limits.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable

from recap.artifacts import RecordingMetadata, write_recording_metadata
from recap.daemon.recorder.audio import AudioCapture
from recap.daemon.recorder.silence import SilenceDetector
from recap.daemon.recorder.state_machine import RecorderState, RecorderStateMachine
from recap.daemon.streaming.diarizer import StreamingDiarizer
from recap.daemon.streaming.transcriber import StreamingTranscriber
from recap.models import TranscriptResult

logger = logging.getLogger(__name__)

# Minimum free disk space in bytes (1 GB)
_MIN_DISK_SPACE_BYTES = 1_073_741_824


class Recorder:
    """Orchestrates audio recording with silence detection and duration limits.

    Ties together AudioCapture, SilenceDetector, and RecorderStateMachine
    to provide a high-level recording interface with automatic monitoring.
    """

    def __init__(
        self,
        recordings_path: Path,
        sample_rate: int = 16000,
        channels: int = 2,
        silence_timeout_minutes: float = 5,
        max_duration_hours: float = 4,
        on_state_change: Callable | None = None,
    ) -> None:
        self._recordings_path = recordings_path
        self._sample_rate = sample_rate
        self._channels = channels
        self._silence_timeout_seconds = silence_timeout_minutes * 60
        self._max_duration_seconds = max_duration_hours * 3600

        self.state_machine = RecorderStateMachine(on_state_change=on_state_change)

        self._audio_capture: AudioCapture | None = None
        self._silence_detector: SilenceDetector | None = None
        self._current_path: Path | None = None
        self._current_metadata: RecordingMetadata | None = None

        # Async monitoring tasks
        self._silence_task: asyncio.Task | None = None
        self._duration_task: asyncio.Task | None = None
        self._capture_health_task: asyncio.Task | None = None

        # Streaming transcription/diarization (best-effort)
        self._transcriber: StreamingTranscriber | None = None
        self._diarizer: StreamingDiarizer | None = None
        self._streaming_result: TranscriptResult | None = None

        # Callbacks for external notification (e.g., tray icon)
        self.on_silence_detected: Callable | None = None
        self.on_max_duration_warning: Callable | None = None
        self.on_max_duration_reached: Callable | None = None
        self.on_recording_stopped: Callable[[Path, str], None] | None = None
        self.on_streaming_segment: Callable[[dict], None] | None = None

    @property
    def is_recording(self) -> bool:
        """True if audio capture is currently active."""
        if self._audio_capture is None:
            return False
        return self._audio_capture.is_recording

    @property
    def current_recording_path(self) -> Path | None:
        """Path to the current recording file, or None if not recording."""
        if not self.is_recording:
            return None
        return self._current_path

    @property
    def streaming_result(self) -> TranscriptResult | None:
        """Merged streaming transcript, or None if streaming failed or wasn't used."""
        return self._streaming_result

    def set_on_state_change(self, callback: Callable | None) -> None:
        """Update the recorder state callback without replacing the state machine."""
        self.state_machine.set_on_state_change(callback)

    def _default_recording_metadata(self, org: str, now: datetime) -> RecordingMetadata:
        title = f"Meeting {now.strftime('%Y-%m-%d %H:%M')}"
        return RecordingMetadata(
            org=org,
            note_path="",
            title=title,
            date=now.date().isoformat(),
            participants=[],
            platform="manual",
        )

    def _generate_recording_path(self, org: str) -> Path:
        """Generate a unique recording filename.

        Format: {recordings_path}/{YYYY-MM-DD}-{HHMMSS}-{org}.flac
        """
        now = datetime.now()
        filename = f"{now.strftime('%Y-%m-%d')}-{now.strftime('%H%M%S')}-{org}.flac"
        return self._recordings_path / filename

    def _check_disk_space(self) -> bool:
        """Check if there is sufficient disk space for recording.

        Returns:
            True if at least 1 GB is free on the recordings drive.
        """
        try:
            usage = shutil.disk_usage(self._recordings_path)
            if usage.free < _MIN_DISK_SPACE_BYTES:
                logger.warning(
                    "Low disk space: %.1f MB free on %s",
                    usage.free / (1024 * 1024),
                    self._recordings_path,
                )
                return False
            return True
        except OSError:
            logger.warning("Could not check disk space for %s", self._recordings_path)
            return False

    async def start(
        self,
        org: str,
        metadata: RecordingMetadata | None = None,
        *,
        detected: bool = False,
        backend: str | None = None,
    ) -> Path:
        """Start recording audio for the given org.

        Creates an AudioCapture instance, a SilenceDetector, transitions
        the state machine to RECORDING, and starts async monitoring tasks
        for silence and duration limits.

        ``backend`` is the optional analysis-backend override (e.g.
        ``"ollama"``) the plugin's Start Recording modal passes through.
        When provided, it overwrites ``metadata.llm_backend`` so the
        pipeline dispatches the chosen subprocess regardless of the org's
        configured default. When ``metadata`` is already supplied (Signal
        popup path) its ``llm_backend`` is preserved unless ``backend`` is
        also set explicitly.

        Returns:
            Path to the FLAC file being recorded.
        """
        self._recordings_path.mkdir(parents=True, exist_ok=True)

        if not self._check_disk_space():
            logger.warning("Low disk space — recording may fail")

        now = datetime.now()
        path = self._generate_recording_path(org)
        self._current_path = path
        self._current_metadata = metadata or self._default_recording_metadata(org, now)
        if backend is not None:
            # Manual override (e.g. plugin Start modal picks "ollama"):
            # always wins over the auto-generated or Signal-popup default.
            self._current_metadata.llm_backend = backend

        self._audio_capture = AudioCapture(
            output_path=path,
            sample_rate=self._sample_rate,
            channels=self._channels,
        )
        self._silence_detector = SilenceDetector(
            timeout_seconds=self._silence_timeout_seconds,
        )

        # Start streaming transcription and diarization (best-effort)
        self._streaming_result = None
        self._start_streaming()

        try:
            if detected and self.state_machine.state in {
                RecorderState.IDLE,
                RecorderState.ARMED,
            }:
                self.state_machine.detected(org)
            self.state_machine.start_recording(org)
            write_recording_metadata(path, self._current_metadata)
            self._audio_capture.start()
        except Exception:
            self._streaming_result = None
            self._current_path = None
            self._current_metadata = None
            self.state_machine.reset()
            raise

        # Start async monitoring tasks
        self._silence_task = asyncio.create_task(self._monitor_silence())
        self._duration_task = asyncio.create_task(self._monitor_duration())
        self._capture_health_task = asyncio.create_task(self._monitor_capture_health())

        logger.info("Recording started: %s", path)
        return path

    async def stop(self) -> Path:
        """Stop recording and return the FLAC file path.

        Cancels monitoring tasks, stops audio capture, resets silence
        detector, and transitions the state machine to PROCESSING.

        Returns:
            Path to the completed FLAC file.
        """
        # Cancel monitoring tasks
        if self._silence_task is not None:
            self._silence_task.cancel()
            try:
                await self._silence_task
            except asyncio.CancelledError:
                pass
            self._silence_task = None

        if self._duration_task is not None:
            self._duration_task.cancel()
            try:
                await self._duration_task
            except asyncio.CancelledError:
                pass
            self._duration_task = None

        # Cancel capture-health monitor. Ordering matters: clear the
        # attribute to None BEFORE cancelling so that if the monitor
        # itself is what called stop() (fatal-event path), its own
        # "await self.stop()" won't race to cancel itself.
        if self._capture_health_task is not None:
            task = self._capture_health_task
            self._capture_health_task = None
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Stop audio capture
        path = self._current_path
        if self._audio_capture is not None:
            self._audio_capture.stop()
            self._audio_capture = None

        # Stop streaming and merge results
        self._stop_streaming()

        # Reset silence detector
        if self._silence_detector is not None:
            self._silence_detector.reset()
            self._silence_detector = None

        # Capture org before state transition (stop_recording clears nothing,
        # but processing_complete will clear current_org later)
        org = self.state_machine.current_org or ""

        # Transition state machine
        self.state_machine.stop_recording()

        logger.info("Recording stopped: %s", path)
        self._current_path = None
        self._current_metadata = None

        # Notify listener (e.g., pipeline trigger in __main__.py)
        if self.on_recording_stopped is not None and path is not None:
            self.on_recording_stopped(path, org)
        else:
            # No pipeline configured — transition back to idle directly
            self.state_machine.processing_complete()

        return path

    def _start_streaming(self) -> None:
        """Create and start streaming transcriber and diarizer (best-effort).

        If either fails to start, recording continues without it.
        """
        self._transcriber = StreamingTranscriber()
        self._diarizer = StreamingDiarizer()

        try:
            self._transcriber.start()
        except Exception:
            logger.warning("Streaming transcriber failed to start", exc_info=True)

        # Wire the on_segment callback so external listeners (e.g. WebSocket
        # broadcast) receive live transcript segments.
        if self.on_streaming_segment is not None:
            self._transcriber.on_segment = self.on_streaming_segment

        try:
            self._diarizer.start()
        except Exception:
            logger.warning("Streaming diarizer failed to start", exc_info=True)

        # Subscribe to the public on_chunk callback so the streaming models
        # receive combined mono audio directly, without reaching into private
        # audio-capture state.
        if self._audio_capture is not None:
            self._audio_capture.on_chunk = self._feed_streaming_models

    def _feed_streaming_models(self, chunk: bytes, sample_rate: int) -> None:
        """Route a combined mono audio chunk to the streaming ASR + diarizer.

        Invoked by ``AudioCapture`` once per interleave cycle. Each model
        already handles its own error state internally (see
        ``StreamingTranscriber.feed_audio`` / ``StreamingDiarizer.feed_audio``).
        """
        if self._transcriber is not None:
            self._transcriber.feed_audio(chunk, sample_rate)
        if self._diarizer is not None:
            self._diarizer.feed_audio(chunk, sample_rate)

    def _stop_streaming(self) -> None:
        """Stop streaming models and merge results if both succeeded."""
        from recap.pipeline.diarize import assign_speakers

        # Detach the audio-capture callback first so any final drain chunks
        # fired during ``AudioCapture.stop()`` don't invoke a half-torn-down
        # streaming pipeline.
        if self._audio_capture is not None:
            self._audio_capture.on_chunk = None

        transcript_result: TranscriptResult | None = None
        diarizer_segments: list[dict] | None = None

        if self._transcriber is not None:
            transcript_result = self._transcriber.stop()
            self._transcriber = None

        if self._diarizer is not None:
            diarizer_segments = self._diarizer.stop()
            self._diarizer = None

        # Merge if both succeeded
        if transcript_result is not None and diarizer_segments is not None:
            try:
                self._streaming_result = assign_speakers(
                    transcript_result, diarizer_segments,
                )
                logger.info(
                    "Streaming transcript merged: %d utterances",
                    len(self._streaming_result.utterances),
                )
            except Exception:
                logger.warning("Failed to merge streaming results", exc_info=True)
                self._streaming_result = None
        else:
            self._streaming_result = None

    async def _monitor_capture_health(self) -> None:
        """Watch AudioCapture._fatal_event for both-sources-dead
        condition. When tripped, stop the recording cleanly and log
        the error so the user knows why it stopped. ``threading.Event``
        is not awaitable, so this polls at 500 ms.

        Re-entry safety: a manual ``Recorder.stop()`` racing with a
        fatal event can leave the state machine past RECORDING by the
        time this monitor observes the event. Only call ``stop()`` if
        the state machine still thinks we're recording; otherwise log
        the fatal cause and exit quietly (the user-initiated stop
        already did the teardown)."""
        try:
            while self._audio_capture is not None:
                cap = self._audio_capture
                fatal_event = getattr(cap, "_fatal_event", None)
                if fatal_event is not None and fatal_event.is_set():
                    err = getattr(cap, "_fatal_error", None)
                    logger.error("Capture fatal: %s", err)
                    if self.state_machine.state == RecorderState.RECORDING:
                        try:
                            await self.stop()
                        except Exception:
                            logger.exception(
                                "Recorder stop() during fatal capture handling raised",
                            )
                    # else: a concurrent manual stop already tore down
                    # the recorder; nothing left to do.
                    return
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise

    async def _monitor_silence(self) -> None:
        """Async task that periodically checks for silence timeout."""
        silence_already_notified = False
        try:
            while True:
                await asyncio.sleep(1.0)
                if self._audio_capture is None or self._silence_detector is None:
                    break

                rms = self._audio_capture.current_rms
                self._silence_detector.update(rms)

                if self._silence_detector.is_silent and not silence_already_notified:
                    silence_already_notified = True
                    logger.info(
                        "Silence detected for %.0f seconds",
                        self._silence_detector.silence_duration,
                    )
                    if self.on_silence_detected is not None:
                        self.on_silence_detected()

                # Reset notification flag when audio resumes
                if not self._silence_detector.is_silent:
                    silence_already_notified = False

        except asyncio.CancelledError:
            raise

    async def _monitor_duration(self) -> None:
        """Async task that enforces max recording duration."""
        # Only warn if max duration is longer than 1 hour; otherwise skip warning
        if self._max_duration_seconds > 3600:
            warning_threshold: float | None = self._max_duration_seconds - 3600
        else:
            warning_threshold = None
        warning_sent = False
        elapsed = 0.0

        try:
            while True:
                await asyncio.sleep(1.0)
                elapsed += 1.0

                # Warning at max_duration - 1 hour (skipped for short sessions)
                if (
                    warning_threshold is not None
                    and elapsed >= warning_threshold
                    and not warning_sent
                ):
                    warning_sent = True
                    logger.warning(
                        "Recording approaching max duration (%.0f hours remaining)",
                        (self._max_duration_seconds - elapsed) / 3600,
                    )
                    if self.on_max_duration_warning is not None:
                        self.on_max_duration_warning()

                # Auto-stop at max duration
                if elapsed >= self._max_duration_seconds:
                    logger.warning("Max recording duration reached — auto-stopping")
                    if self.on_max_duration_reached is not None:
                        self.on_max_duration_reached()
                    await self.stop()
                    break

        except asyncio.CancelledError:
            raise

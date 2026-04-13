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

from recap.daemon.recorder.audio import AudioCapture
from recap.daemon.recorder.silence import SilenceDetector
from recap.daemon.recorder.state_machine import RecorderStateMachine

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

        # Async monitoring tasks
        self._silence_task: asyncio.Task | None = None
        self._duration_task: asyncio.Task | None = None

        # Callbacks for external notification (e.g., tray icon)
        self.on_silence_detected: Callable | None = None
        self.on_max_duration_warning: Callable | None = None
        self.on_max_duration_reached: Callable | None = None
        self.on_recording_stopped: Callable[[Path, str], None] | None = None

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

    async def start(self, org: str) -> Path:
        """Start recording audio for the given org.

        Creates an AudioCapture instance, a SilenceDetector, transitions
        the state machine to RECORDING, and starts async monitoring tasks
        for silence and duration limits.

        Returns:
            Path to the FLAC file being recorded.
        """
        self._recordings_path.mkdir(parents=True, exist_ok=True)

        if not self._check_disk_space():
            logger.warning("Low disk space — recording may fail")

        path = self._generate_recording_path(org)
        self._current_path = path

        self._audio_capture = AudioCapture(
            output_path=path,
            sample_rate=self._sample_rate,
            channels=self._channels,
        )
        self._silence_detector = SilenceDetector(
            timeout_seconds=self._silence_timeout_seconds,
        )

        self.state_machine.start_recording(org)
        self._audio_capture.start()

        # Start async monitoring tasks
        self._silence_task = asyncio.create_task(self._monitor_silence())
        self._duration_task = asyncio.create_task(self._monitor_duration())

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

        # Stop audio capture
        path = self._current_path
        if self._audio_capture is not None:
            self._audio_capture.stop()
            self._audio_capture = None

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

        # Notify listener (e.g., pipeline trigger in __main__.py)
        if self.on_recording_stopped is not None and path is not None:
            self.on_recording_stopped(path, org)

        return path

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
        warning_threshold = self._max_duration_seconds - 3600  # 1 hour before max
        warning_sent = False
        elapsed = 0.0

        try:
            while True:
                await asyncio.sleep(1.0)
                elapsed += 1.0

                # Warning at max_duration - 1 hour
                if elapsed >= warning_threshold and not warning_sent:
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

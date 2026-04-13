"""Silence detection for audio streams.

Monitors RMS audio levels and detects when a meeting has gone quiet
for longer than a configurable timeout.
"""

import time


class SilenceDetector:
    """Detects sustained silence in an audio stream.

    Tracks whether the audio RMS level has remained below a dB threshold
    for longer than a specified timeout period.
    """

    def __init__(self, threshold_db: float = -40, timeout_seconds: float = 300) -> None:
        self._threshold_linear: float = 10 ** (threshold_db / 20)
        self._timeout_seconds: float = timeout_seconds
        self._silence_start: float | None = None

    def update(self, rms_level: float) -> None:
        """Feed an audio frame's RMS level into the detector.

        If the level is below the threshold, silence tracking begins
        (or continues). If above, silence tracking resets.
        """
        if rms_level < self._threshold_linear:
            if self._silence_start is None:
                self._silence_start = time.monotonic()
        else:
            self._silence_start = None

    @property
    def is_silent(self) -> bool:
        """True if continuous silence has exceeded the timeout."""
        if self._silence_start is None:
            return False
        return (time.monotonic() - self._silence_start) >= self._timeout_seconds

    @property
    def silence_duration(self) -> float:
        """Seconds of continuous silence, or 0.0 if not currently silent."""
        if self._silence_start is None:
            return 0.0
        elapsed = time.monotonic() - self._silence_start
        return elapsed if elapsed >= 0 else 0.0

    def reset(self) -> None:
        """Clear all silence tracking state."""
        self._silence_start = None

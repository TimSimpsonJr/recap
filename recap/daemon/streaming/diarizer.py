"""Streaming diarization module using NeMo Sortformer.

Runs NeMo's streaming Sortformer model in real-time during recording
to produce speaker segments. If VRAM is exceeded, fails gracefully
and defers to post-meeting batch diarization.
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)


class StreamingDiarizer:
    """Real-time speaker diarization using NeMo streaming Sortformer.

    Feeds audio chunks to the model during recording and accumulates
    speaker segments. On VRAM exhaustion or other model errors, sets
    ``had_errors`` and lets the caller fall back to batch diarization.

    Args:
        model_name: NeMo model identifier for streaming Sortformer.
        device: Torch device string (``"cuda"`` or ``"cpu"``).
    """

    def __init__(
        self,
        model_name: str = "nvidia/diar_streaming_sortformer_4spk-v2.1",
        device: str = "cuda",
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._model = None
        self._running = False
        self._had_errors = False
        self._segments: list[dict] = []
        self.on_speaker_segment: Callable[[dict], None] | None = None

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Whether the diarizer is actively processing audio."""
        return self._running

    @property
    def speaker_segments(self) -> list[dict]:
        """Accumulated speaker segments (live reference)."""
        return self._segments

    @property
    def had_errors(self) -> bool:
        """True if any errors occurred during model loading or inference."""
        return self._had_errors

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Load the streaming Sortformer model and begin processing.

        If model loading fails (e.g. VRAM exceeded), sets ``had_errors``
        and logs the error rather than raising.
        """
        try:
            self._load_model()
            self._running = True
            logger.info("Streaming diarizer started (%s)", self._model_name)
        except Exception as exc:
            self._on_error(exc)
            logger.error("Failed to start streaming diarizer: %s", exc)

    def feed_audio(self, audio_data: bytes, sample_rate: int = 16000) -> None:
        """Feed an audio chunk for diarization.

        Args:
            audio_data: Raw audio bytes (16-bit PCM).
            sample_rate: Sample rate in Hz (default 16 kHz).
        """
        if not self._running or self._had_errors:
            return
        try:
            self._process_audio(audio_data, sample_rate)
        except Exception as exc:
            self._on_error(exc)

    def stop(self) -> list[dict] | None:
        """Stop the diarizer, unload the model, and return results.

        Returns:
            Accumulated speaker segments on success, or ``None`` if
            errors occurred during the session.
        """
        self._running = False
        self._unload_model()
        if self._had_errors:
            return None
        return list(self._segments)

    def get_speaker_segments(self) -> list[dict]:
        """Return a copy of the current accumulated segments."""
        return list(self._segments)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_speaker_segment(self, segment: dict) -> None:
        """Append a segment and fire the callback if registered."""
        self._segments.append(segment)
        if self.on_speaker_segment is not None:
            self.on_speaker_segment(segment)

    def _on_error(self, error: Exception) -> None:
        """Record that an error occurred and log it."""
        self._had_errors = True
        logger.error("Streaming diarizer error: %s", error)

    def _load_model(self) -> None:
        """Lazy-import NeMo and load the streaming Sortformer model."""
        from nemo.collections.asr.models import SortformerEncLabelModel  # type: ignore[import-untyped]

        self._model = SortformerEncLabelModel.from_pretrained(self._model_name)
        # Set model to inference mode and move to target device
        self._model.eval()
        self._model = self._model.to(self._device)
        logger.info("Loaded streaming Sortformer model on %s", self._device)

    def _unload_model(self) -> None:
        """Release the model to free VRAM."""
        self._model = None

    def _process_audio(self, audio_data: bytes, sample_rate: int) -> None:
        """Feed audio to the model and emit any new speaker segments.

        Converts raw PCM bytes to a float32 numpy array, feeds the chunk
        to the NeMo streaming Sortformer model, and emits speaker segments
        for any detected speaker changes.
        """
        if self._model is None:
            return

        import numpy as np

        # Convert 16-bit PCM bytes to float32 in [-1.0, 1.0]
        audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

        # Feed to NeMo streaming interface; the model accumulates audio
        # internally and periodically emits speaker segments.
        results = self._model.process_chunk(audio_array)
        if results:
            for segment in results:
                self._on_speaker_segment({
                    "start": segment.start,
                    "end": segment.end,
                    "speaker": f"SPEAKER_{segment.speaker_id:02d}",
                })

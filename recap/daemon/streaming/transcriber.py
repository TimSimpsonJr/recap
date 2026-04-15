"""Streaming transcription using NVIDIA Parakeet models."""
from __future__ import annotations

import logging
from typing import Callable

from recap.models import TranscriptResult, Utterance

logger = logging.getLogger(__name__)


class StreamingTranscriber:
    """Real-time streaming transcriber using parakeet-stream.

    Feeds audio chunks in, receives transcript segments out.
    Handles model loading failures gracefully without crashing.
    """

    def __init__(
        self,
        model_name: str = "nvidia/parakeet-tdt-0.6b-v2",
        device: str = "cuda",
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._running = False
        self._segments: list[dict] = []
        self._had_errors = False
        self._model = None
        self.on_segment: Callable[[dict], None] | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def segments(self) -> list[dict]:
        return list(self._segments)

    @property
    def had_errors(self) -> bool:
        return self._had_errors

    def start(self) -> None:
        """Load the streaming model and prepare for receiving audio chunks.

        If the model fails to load, sets had_errors and returns without
        crashing.
        """
        try:
            self._load_model()
            self._running = True
        except Exception:
            logger.warning(
                "Failed to load streaming model %s", self._model_name, exc_info=True
            )
            self._had_errors = True

    def _load_model(self) -> None:
        """Load the parakeet-stream model. Lazy-imports the library."""
        # parakeet_stream is an optional streaming-ASR dependency; lazy import
        # avoids a hard requirement for environments that don't run streaming.
        import parakeet_stream  # type: ignore[import-not-found]

        self._model = parakeet_stream.load_model(
            self._model_name, device=self._device
        )

    def feed_audio(self, audio_data: bytes, sample_rate: int = 16000) -> None:
        """Feed a chunk of raw audio to the streaming model.

        Called from the audio capture thread. Silently returns if the
        transcriber is not running or has encountered errors.
        """
        if not self._running or self._had_errors:
            return

        try:
            results = self._model.transcribe_chunk(audio_data, sample_rate=sample_rate)
            if results:
                for segment in results:
                    self._on_segment(segment)
        except Exception as exc:
            self._on_error(exc)

    def stop(self) -> TranscriptResult | None:
        """Stop streaming, unload model, return TranscriptResult.

        Returns None if errors occurred during the session.
        """
        self._running = False

        # Unload model
        self._model = None

        if self._had_errors:
            return None

        return self.get_transcript_result()

    def get_transcript_result(self) -> TranscriptResult:
        """Convert accumulated segments to a TranscriptResult."""
        utterances = [
            Utterance(
                speaker=seg.get("speaker", "UNKNOWN"),
                start=seg.get("start", 0.0),
                end=seg.get("end", 0.0),
                text=seg.get("text", ""),
            )
            for seg in self._segments
        ]

        raw_text = " ".join(u.text for u in utterances)

        return TranscriptResult(
            utterances=utterances,
            raw_text=raw_text,
            language="en",
        )

    def _on_segment(self, segment: dict) -> None:
        """Append segment and fire callback."""
        self._segments.append(segment)
        if self.on_segment is not None:
            self.on_segment(segment)

    def _on_error(self, error: Exception) -> None:
        """Record error and log warning."""
        self._had_errors = True
        logger.warning("Streaming transcription error: %s", error, exc_info=True)

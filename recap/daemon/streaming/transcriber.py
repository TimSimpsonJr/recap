"""Streaming transcription — deferred to Phase 8.

Phase 7 stubs this subsystem because parakeet-stream 0.6 adopted an
audio-source-owned API that doesn't compose with our bytes-in recorder.
Public surface preserved; batch pipeline is the canonical transcription
path in Phase 7.
"""
from __future__ import annotations

import logging
from typing import Callable

from recap.models import TranscriptResult

logger = logging.getLogger(__name__)


class StreamingTranscriber:
    """No-op facade for live streaming transcription.

    Live streaming transcription is deferred to Phase 8 (see Phase 7
    design doc). Recorder and plugin wiring reference this class;
    start() logs deferral and sets had_errors=True so downstream code
    short-circuits. feed_audio() is a no-op.
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
        logger.info(
            "Live streaming transcription deferred; see Phase 7 plan for context."
        )
        self._had_errors = True

    def feed_audio(self, audio_data: bytes, sample_rate: int = 16000) -> None:
        return

    def stop(self) -> TranscriptResult | None:
        self._running = False
        return None

    def get_transcript_result(self) -> TranscriptResult:
        return TranscriptResult(utterances=[], raw_text="", language="en")

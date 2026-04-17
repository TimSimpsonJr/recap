"""Streaming diarization — deferred to Phase 8.

Phase 7 stubs this subsystem because live NeMo Sortformer streaming
diarization is being deferred alongside parakeet-stream. Public surface
preserved; batch diarization is the canonical diarization path in
Phase 7.
"""
from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)


class StreamingDiarizer:
    """No-op facade for live streaming diarization.

    Live streaming diarization is deferred to Phase 8 (see Phase 7
    design doc). Recorder and plugin wiring reference this class;
    start() logs deferral and sets had_errors=True so downstream code
    short-circuits. feed_audio() is a no-op.
    """

    def __init__(
        self,
        model_name: str = "nvidia/diar_streaming_sortformer_4spk-v2.1",
        device: str = "cuda",
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._running = False
        self._segments: list[dict] = []
        self._had_errors = False
        self.on_speaker_segment: Callable[[dict], None] | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def speaker_segments(self) -> list[dict]:
        return list(self._segments)

    @property
    def had_errors(self) -> bool:
        return self._had_errors

    def start(self) -> None:
        logger.info(
            "Live streaming diarization deferred; see Phase 7 plan for context."
        )
        self._had_errors = True

    def feed_audio(self, audio_data: bytes, sample_rate: int = 16000) -> None:
        return

    def stop(self) -> list[dict] | None:
        self._running = False
        return None

    def get_speaker_segments(self) -> list[dict]:
        return list(self._segments)

"""Tests for the Signal-popup -> RecordingMetadata backend plumbing.

Ensures the popup's backend choice actually reaches the metadata file;
guards against a regression Codex found in Phase 1 review where the
Signal callback constructed RecordingMetadata without passing
llm_backend through.
"""
from __future__ import annotations

from recap.daemon.signal_metadata import build_signal_metadata


class _StubWindow:
    title = "Signal"
    platform = "signal"


class TestSignalMetadataConstruction:
    def test_llm_backend_from_result_reaches_metadata(self):
        metadata = build_signal_metadata(
            result={"org": "personal", "backend": "ollama"},
            meeting_window=_StubWindow(),
            enriched_metadata={"title": "Call with Alice"},
        )
        assert metadata.llm_backend == "ollama"

    def test_claude_backend_from_result_reaches_metadata(self):
        metadata = build_signal_metadata(
            result={"org": "personal", "backend": "claude"},
            meeting_window=_StubWindow(),
            enriched_metadata={},
        )
        assert metadata.llm_backend == "claude"

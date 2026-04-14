"""Tests for recording sidecar artifacts."""
from __future__ import annotations

import pathlib

from recap.artifacts import RecordingMetadata, load_recording_metadata, write_recording_metadata
from recap.models import Participant


class TestRecordingMetadataLLMBackend:
    def test_default_llm_backend_is_none(self):
        metadata = RecordingMetadata(
            org="test",
            note_path="",
            title="t",
            date="2026-04-14",
            participants=[],
            platform="manual",
        )
        assert metadata.llm_backend is None

    def test_explicit_llm_backend_round_trips(self, tmp_path: pathlib.Path):
        audio_path = tmp_path / "recording.flac"
        audio_path.touch()
        original = RecordingMetadata(
            org="test",
            note_path="",
            title="t",
            date="2026-04-14",
            participants=[Participant(name="Alice")],
            platform="signal",
            llm_backend="ollama",
        )
        write_recording_metadata(audio_path, original)

        loaded = load_recording_metadata(audio_path)
        assert loaded is not None
        assert loaded.llm_backend == "ollama"

    def test_legacy_metadata_without_llm_backend_loads_as_none(self, tmp_path: pathlib.Path):
        import json

        audio_path = tmp_path / "legacy.flac"
        audio_path.touch()
        legacy_data = {
            "org": "test",
            "note_path": "",
            "title": "t",
            "date": "2026-04-14",
            "participants": [],
            "platform": "manual",
        }
        (audio_path.with_suffix(".metadata.json")).write_text(json.dumps(legacy_data))

        loaded = load_recording_metadata(audio_path)
        assert loaded is not None
        assert loaded.llm_backend is None

"""Tests for recording sidecar artifacts."""
from __future__ import annotations

import pathlib
from datetime import datetime, timezone

from recap.artifacts import (
    RecordingMetadata,
    load_recording_metadata,
    resolve_note_path,
    to_vault_relative,
    write_recording_metadata,
)
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


class TestResolveNotePath:
    def test_resolve_relative_path_joins_with_vault(self):
        vault = pathlib.Path("/v")
        result = resolve_note_path("Clients/D/Meetings/x.md", vault)
        assert result == vault / "Clients/D/Meetings/x.md"

    def test_resolve_absolute_path_returns_as_is(self, tmp_path):
        # Use a real absolute path to work cross-platform (Windows treats
        # "/foo" as non-absolute without a drive letter).
        absolute = tmp_path / "absolute" / "path" / "x.md"
        vault = tmp_path / "v"
        result = resolve_note_path(str(absolute), vault)
        assert result == absolute


class TestToVaultRelative:
    def test_relative_to_vault_returns_forward_slash_string(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        note = vault / "Clients/D/Meetings/x.md"
        result = to_vault_relative(note, vault)
        assert result == "Clients/D/Meetings/x.md"

    def test_outside_vault_returns_absolute_string_degraded(self, tmp_path):
        vault = tmp_path / "vault"
        outside = tmp_path / "outside" / "x.md"
        result = to_vault_relative(outside, vault)
        # Degraded mode: returns the absolute path as-is (str)
        assert result == str(outside)


class TestRecordingMetadataAudioWarnings:
    def test_defaults_to_empty_lists(self, tmp_path):
        m = RecordingMetadata(
            org="test",
            note_path="",
            title="T",
            date="2026-04-21",
            participants=[],
            platform="zoho_meet",
        )
        assert m.audio_warnings == []
        assert m.system_audio_devices_seen == []

    def test_roundtrip_preserves_warnings(self, tmp_path):
        audio_path = tmp_path / "rec.flac"
        audio_path.touch()
        m = RecordingMetadata(
            org="test",
            note_path="",
            title="T",
            date="2026-04-21",
            participants=[],
            platform="zoho_meet",
            audio_warnings=["no-system-audio-captured"],
            system_audio_devices_seen=["Laptop Speakers", "HDMI"],
        )
        write_recording_metadata(audio_path, m)
        loaded = load_recording_metadata(audio_path)
        assert loaded is not None
        assert loaded.audio_warnings == ["no-system-audio-captured"]
        assert loaded.system_audio_devices_seen == ["Laptop Speakers", "HDMI"]

    def test_loads_older_sidecar_without_fields(self, tmp_path):
        """Older sidecars without the new fields deserialize with empty defaults."""
        import json

        audio_path = tmp_path / "rec.flac"
        audio_path.touch()
        sidecar = audio_path.with_suffix(".metadata.json")
        sidecar.write_text(json.dumps({
            "org": "test",
            "note_path": "",
            "title": "T",
            "date": "2026-04-21",
            "participants": [],
            "platform": "zoho_meet",
        }))
        loaded = load_recording_metadata(audio_path)
        assert loaded is not None
        assert loaded.audio_warnings == []
        assert loaded.system_audio_devices_seen == []


def test_recording_metadata_has_recording_started_at_field():
    """New field persists through sidecar serialization round-trip."""
    ts = datetime(2026, 4, 22, 14, 30, 0, tzinfo=timezone.utc)
    metadata = RecordingMetadata(
        org="acme", note_path="Meetings/test.md", title="Test",
        date="2026-04-22", participants=[], platform="teams",
        recording_started_at=ts,
    )
    assert metadata.recording_started_at == ts

    roundtripped = RecordingMetadata.from_dict(metadata.to_dict())
    assert roundtripped.recording_started_at == ts


def test_recording_metadata_missing_recording_started_at_deserializes_to_none():
    """Pre-#27 sidecars without the field load cleanly with None."""
    legacy_sidecar = {
        "org": "acme", "note_path": "x.md", "title": "Test",
        "date": "2026-04-22", "participants": [], "platform": "teams",
        "calendar_source": None, "event_id": None, "meeting_link": "",
    }
    metadata = RecordingMetadata.from_dict(legacy_sidecar)
    assert metadata.recording_started_at is None


def test_recording_metadata_default_recording_started_at_is_none():
    """Default factory omits the field cleanly."""
    metadata = RecordingMetadata(
        org="acme", note_path="", title="Test", date="2026-04-22",
        participants=[], platform="teams",
    )
    assert metadata.recording_started_at is None

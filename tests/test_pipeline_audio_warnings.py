"""Tests for audio-warning rendering in note frontmatter + body."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from recap.artifacts import RecordingMetadata
from recap.models import AnalysisResult, MeetingMetadata
from recap.vault import build_canonical_frontmatter


# --- Fixture helpers -------------------------------------------------------

def _meeting_metadata() -> MeetingMetadata:
    return MeetingMetadata(
        title="Test Meeting",
        date=date(2026, 4, 21),
        participants=[],
        platform="zoho_meet",
    )


def _analysis_result() -> AnalysisResult:
    return AnalysisResult(
        speaker_mapping={},
        meeting_type="client-call",
        summary="s",
        key_points=[],
        decisions=[],
        action_items=[],
        follow_ups=[],
        relationship_notes=None,
        people=[],
        companies=[],
    )


def _recording_metadata(
    audio_warnings: list[str] | None = None,
    devices_seen: list[str] | None = None,
) -> RecordingMetadata:
    return RecordingMetadata(
        org="testorg",
        note_path="",
        title="Test",
        date="2026-04-21",
        participants=[],
        platform="zoho_meet",
        audio_warnings=(audio_warnings or []),
        system_audio_devices_seen=(devices_seen or []),
    )


# --- Tests -----------------------------------------------------------------

class TestFrontmatterAudioWarnings:
    def test_absent_when_empty(self, tmp_path: Path) -> None:
        fm = build_canonical_frontmatter(
            metadata=_meeting_metadata(),
            analysis=_analysis_result(),
            duration_seconds=120,
            recording_path=tmp_path / "r.flac",
            org="testorg",
            org_subfolder="TestOrg",
            recording_metadata=_recording_metadata(audio_warnings=[]),
        )
        assert "audio-warnings" not in fm

    def test_present_when_non_empty(self, tmp_path: Path) -> None:
        fm = build_canonical_frontmatter(
            metadata=_meeting_metadata(),
            analysis=_analysis_result(),
            duration_seconds=120,
            recording_path=tmp_path / "r.flac",
            org="testorg",
            org_subfolder="TestOrg",
            recording_metadata=_recording_metadata(
                audio_warnings=["no-system-audio-captured"],
            ),
        )
        assert fm["audio-warnings"] == ["no-system-audio-captured"]

    def test_frontmatter_copy_not_reference(self, tmp_path: Path) -> None:
        """Frontmatter dict must own its own list, not alias the dataclass field."""
        warnings = ["no-system-audio-captured"]
        rm = _recording_metadata(audio_warnings=warnings)
        fm = build_canonical_frontmatter(
            metadata=_meeting_metadata(),
            analysis=_analysis_result(),
            duration_seconds=120,
            recording_path=tmp_path / "r.flac",
            org="testorg",
            org_subfolder="TestOrg",
            recording_metadata=rm,
        )
        # Mutating the source list must not affect the frontmatter output.
        rm.audio_warnings.append("zombie-stream-detected")
        assert fm["audio-warnings"] == ["no-system-audio-captured"]

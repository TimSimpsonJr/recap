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


class TestBodyCallout:
    def test_no_callout_when_warnings_empty(self, tmp_path):
        from recap.vault import upsert_note
        note_path = tmp_path / "note.md"
        fm = {
            "pipeline-status": "complete",
            "title": "T",
            "date": "2026-04-21",
        }
        upsert_note(note_path, fm, body="## Summary\n\nHi.\n")
        content = note_path.read_text(encoding="utf-8")
        assert "[!warning]" not in content

    def test_no_system_audio_callout_wording(self, tmp_path):
        from recap.vault import upsert_note
        note_path = tmp_path / "note.md"
        fm = {
            "pipeline-status": "complete",
            "title": "T",
            "date": "2026-04-21",
            "audio-warnings": ["no-system-audio-captured"],
            "system-audio-devices-seen": ["Laptop Speakers", "HDMI Audio"],
        }
        upsert_note(note_path, fm, body="## Summary\n\nHi.\n")
        content = note_path.read_text(encoding="utf-8")
        assert "[!warning] System audio was not captured" in content
        assert "Laptop Speakers" in content
        assert "HDMI Audio" in content

    def test_interrupted_callout_wording(self, tmp_path):
        from recap.vault import upsert_note
        note_path = tmp_path / "note.md"
        fm = {
            "pipeline-status": "complete",
            "title": "T",
            "date": "2026-04-21",
            "audio-warnings": ["system-audio-interrupted"],
            "system-audio-devices-seen": ["AirPods"],
        }
        upsert_note(note_path, fm, body="## Summary\n\nHi.\n")
        content = note_path.read_text(encoding="utf-8")
        assert "[!warning] System audio dropped out" in content

    def test_upsert_preserves_warning_on_merge_path(self, tmp_path):
        """Existing note with calendar frontmatter + marker -> pipeline run
        with warnings. Callout must appear below the marker; frontmatter
        merged with new audio-warnings key."""
        from recap.vault import upsert_note, MEETING_RECORD_MARKER
        note_path = tmp_path / "note.md"
        existing = (
            "---\n"
            "date: '2026-04-21'\n"
            "title: T\n"
            "---\n"
            "\n"
            "User agenda\n"
            f"\n{MEETING_RECORD_MARKER}\n\n"
            "(old body)\n"
        )
        note_path.write_text(existing, encoding="utf-8")
        fm = {
            "pipeline-status": "complete",
            "title": "T",
            "date": "2026-04-21",
            "audio-warnings": ["no-system-audio-captured"],
            "system-audio-devices-seen": ["Laptop Speakers"],
        }
        upsert_note(note_path, fm, body="## Summary\n\nNew body.\n")
        content = note_path.read_text(encoding="utf-8")
        assert "User agenda" in content  # preserved above marker
        assert "[!warning]" in content  # callout in new body
        assert "audio-warnings:" in content  # frontmatter merged


class TestPipelineExportThreadsWarnings:
    def test_frontmatter_includes_devices_seen_when_non_empty(self, tmp_path):
        """build_canonical_frontmatter-level test: when system_audio_devices_seen
        is populated on the RecordingMetadata, the frontmatter dict carries it
        under the 'system-audio-devices-seen' key (so the callout renderer in
        upsert_note has device names available)."""
        from recap.vault import build_canonical_frontmatter
        fm = build_canonical_frontmatter(
            metadata=_meeting_metadata(),
            analysis=_analysis_result(),
            duration_seconds=120,
            recording_path=tmp_path / "r.flac",
            org="testorg",
            org_subfolder="TestOrg",
            recording_metadata=_recording_metadata(
                audio_warnings=["no-system-audio-captured"],
                devices_seen=["Laptop Speakers", "HDMI Audio"],
            ),
        )
        assert fm.get("system-audio-devices-seen") == ["Laptop Speakers", "HDMI Audio"]

    def test_frontmatter_omits_devices_seen_when_empty(self, tmp_path):
        from recap.vault import build_canonical_frontmatter
        fm = build_canonical_frontmatter(
            metadata=_meeting_metadata(),
            analysis=_analysis_result(),
            duration_seconds=120,
            recording_path=tmp_path / "r.flac",
            org="testorg",
            org_subfolder="TestOrg",
            recording_metadata=_recording_metadata(
                audio_warnings=[], devices_seen=[],
            ),
        )
        assert "system-audio-devices-seen" not in fm

"""End-to-end test: recorder sidecar -> pipeline export -> note on disk.

Validates that audio-warning codes survive the full chain without being
dropped or mangled at a seam. Each earlier test covers one piece; this
one covers the join between them so a regression in the threading
between artifacts / pipeline / vault surfaces here rather than in a
user's actual meeting note.
"""
from __future__ import annotations

from pathlib import Path

from recap.artifacts import RecordingMetadata, write_recording_metadata


def test_no_system_audio_code_flows_to_note(tmp_path: Path) -> None:
    # Arrange: write a sidecar with the warning code next to an audio file.
    audio_path = tmp_path / "rec.flac"
    audio_path.touch()
    sidecar = RecordingMetadata(
        org="testorg",
        note_path="",
        title="Test",
        date="2026-04-21",
        participants=[],
        platform="zoho_meet",
        audio_warnings=["no-system-audio-captured"],
        system_audio_devices_seen=["Laptop Speakers", "HDMI Audio"],
    )
    write_recording_metadata(audio_path, sidecar)

    # Act: drive the export stage.
    vault_root = tmp_path / "vault"
    (vault_root / "TestOrg" / "Meetings").mkdir(parents=True)
    note_path = vault_root / "TestOrg" / "Meetings" / "2026-04-21 - test.md"

    from recap.pipeline import run_export_for_test
    run_export_for_test(
        audio_path=audio_path,
        note_path=note_path,
        vault_root=vault_root,
    )

    # Assert: frontmatter + body callout both render the warning.
    content = note_path.read_text(encoding="utf-8")
    assert "audio-warnings:" in content
    assert "- no-system-audio-captured" in content
    assert "[!warning] System audio was not captured" in content
    assert "Laptop Speakers" in content
    assert "HDMI Audio" in content


def test_interrupted_code_flows_to_note(tmp_path: Path) -> None:
    audio_path = tmp_path / "rec.flac"
    audio_path.touch()
    sidecar = RecordingMetadata(
        org="testorg",
        note_path="",
        title="Test",
        date="2026-04-21",
        participants=[],
        platform="zoho_meet",
        audio_warnings=["system-audio-interrupted"],
        system_audio_devices_seen=["AirPods"],
    )
    write_recording_metadata(audio_path, sidecar)

    vault_root = tmp_path / "vault"
    (vault_root / "TestOrg" / "Meetings").mkdir(parents=True)
    note_path = vault_root / "TestOrg" / "Meetings" / "2026-04-21 - test.md"

    from recap.pipeline import run_export_for_test
    run_export_for_test(
        audio_path=audio_path,
        note_path=note_path,
        vault_root=vault_root,
    )

    content = note_path.read_text(encoding="utf-8")
    assert "[!warning] System audio dropped out" in content
    assert "AirPods" in content

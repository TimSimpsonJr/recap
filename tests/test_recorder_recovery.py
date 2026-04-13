"""Tests for orphaned recording recovery."""
import json
from recap.daemon.recorder.recovery import find_orphaned_recordings


class TestOrphanedRecoveryDetection:
    def test_finds_flac_without_status(self, tmp_path):
        (tmp_path / "2026-04-13-meeting.flac").write_bytes(b"fake flac data")
        orphans = find_orphaned_recordings(tmp_path)
        assert len(orphans) == 1
        assert orphans[0].name == "2026-04-13-meeting.flac"

    def test_ignores_flac_with_completed_status(self, tmp_path):
        (tmp_path / "2026-04-13-meeting.flac").write_bytes(b"fake")
        status_dir = tmp_path / ".recap" / "status"
        status_dir.mkdir(parents=True)
        (status_dir / "2026-04-13-meeting.json").write_text(
            json.dumps({"pipeline-status": "complete"})
        )
        orphans = find_orphaned_recordings(tmp_path, status_dir=status_dir)
        assert len(orphans) == 0

    def test_finds_flac_with_failed_status(self, tmp_path):
        (tmp_path / "2026-04-13-meeting.flac").write_bytes(b"fake")
        status_dir = tmp_path / ".recap" / "status"
        status_dir.mkdir(parents=True)
        (status_dir / "2026-04-13-meeting.json").write_text(
            json.dumps({"pipeline-status": "failed:transcribing"})
        )
        orphans = find_orphaned_recordings(tmp_path, status_dir=status_dir)
        assert len(orphans) == 1

    def test_returns_empty_for_clean_directory(self, tmp_path):
        orphans = find_orphaned_recordings(tmp_path)
        assert len(orphans) == 0

    def test_returns_empty_for_nonexistent_directory(self, tmp_path):
        orphans = find_orphaned_recordings(tmp_path / "nope")
        assert len(orphans) == 0

    def test_ignores_non_flac_files(self, tmp_path):
        (tmp_path / "notes.txt").write_text("not audio")
        (tmp_path / "recording.wav").write_bytes(b"wav data")
        orphans = find_orphaned_recordings(tmp_path)
        assert len(orphans) == 0

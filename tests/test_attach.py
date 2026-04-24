"""Tests for attach_event_to_recording orchestrator and helpers (#33 Task 4)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------
# Error type tests
# ---------------------------------------------------------------------


class TestErrorTypes:
    def test_attach_result_to_dict(self):
        from recap.daemon.recorder.attach import AttachResult
        r = AttachResult(status="ok", note_path="x/y.md")
        assert r.to_dict() == {
            "status": "ok", "note_path": "x/y.md",
            "noop": False, "cleanup_performed": False,
        }

    def test_attach_result_noop_cleanup(self):
        from recap.daemon.recorder.attach import AttachResult
        r = AttachResult(status="ok", note_path="x/y.md",
                         noop=True, cleanup_performed=True)
        assert r.to_dict()["noop"] is True
        assert r.to_dict()["cleanup_performed"] is True

    def test_already_bound_error_to_dict(self):
        from recap.daemon.recorder.attach import AttachAlreadyBoundError
        e = AttachAlreadyBoundError(
            current_event_id="E1",
            current_note_path="a/b.md",
        )
        d = e.to_dict()
        assert d["error"] == "already_bound_to_other_event"
        assert d["current_event_id"] == "E1"
        assert d["current_note_path"] == "a/b.md"

    def test_conflict_error_to_dict(self):
        from recap.daemon.recorder.attach import AttachConflictError
        e = AttachConflictError(existing_recording="rec1.flac", note_path="x.md")
        d = e.to_dict()
        assert d["error"] == "recording_conflict"
        assert d["existing_recording"] == "rec1.flac"
        assert d["note_path"] == "x.md"

    def test_not_found_error_to_dict(self):
        from recap.daemon.recorder.attach import AttachNotFoundError
        e = AttachNotFoundError(what="event not found")
        d = e.to_dict()
        assert d["error"] == "event not found"


# ---------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------


class TestClassifySidecar:
    def test_unscheduled_returns_normal(self):
        from recap.daemon.recorder.attach import _classify_sidecar
        sidecar = MagicMock()
        sidecar.event_id = "unscheduled:abc123"
        assert _classify_sidecar(sidecar, "E1") == "normal"

    def test_same_event_id_returns_noop_candidate(self):
        from recap.daemon.recorder.attach import _classify_sidecar
        sidecar = MagicMock()
        sidecar.event_id = "E1"
        assert _classify_sidecar(sidecar, "E1") == "noop_candidate"

    def test_different_real_event_raises(self):
        from recap.daemon.recorder.attach import (
            _classify_sidecar, AttachAlreadyBoundError,
        )
        sidecar = MagicMock()
        sidecar.event_id = "E2"
        sidecar.note_path = "x/y.md"
        with pytest.raises(AttachAlreadyBoundError) as exc_info:
            _classify_sidecar(sidecar, "E1")
        assert exc_info.value.current_event_id == "E2"
        assert exc_info.value.current_note_path == "x/y.md"


class TestMergeBodies:
    def test_empty_stub_no_pre_meeting_notes(self):
        from recap.daemon.recorder.attach import _merge_bodies
        result = _merge_bodies(stub_body="", source_body="# Summary\n\nDetails")
        assert "Pre-Meeting Notes" not in result
        assert result == "# Summary\n\nDetails"

    def test_agenda_heading_only_no_append(self):
        from recap.daemon.recorder.attach import _merge_bodies
        result = _merge_bodies(stub_body="## Agenda\n\n", source_body="# S")
        assert "Pre-Meeting Notes" not in result

    def test_agenda_with_content_appended(self):
        from recap.daemon.recorder.attach import _merge_bodies
        stub = "## Agenda\n\nPrep: talk about Q4"
        result = _merge_bodies(stub_body=stub, source_body="# Summary")
        assert "## Pre-Meeting Notes" in result
        assert "Prep: talk about Q4" in result
        assert result.startswith("# Summary")

    def test_unexpected_shape_fallback_preserves_whole(self):
        from recap.daemon.recorder.attach import _merge_bodies
        stub = "# Custom Heading\n\nUser rewrote the stub"
        result = _merge_bodies(stub_body=stub, source_body="# Summary")
        assert "## Pre-Meeting Notes" in result
        assert "# Custom Heading" in result
        assert "User rewrote the stub" in result

    def test_source_body_always_first(self):
        from recap.daemon.recorder.attach import _merge_bodies
        result = _merge_bodies(
            stub_body="## Agenda\n\nprep",
            source_body="# Final Summary\n\nBody",
        )
        assert result.index("Final Summary") < result.index("Pre-Meeting Notes")


class TestMergeFrontmatter:
    def _stub_fm(self) -> dict:
        return {
            "date": "2026-04-24",
            "time": "14:00-15:00",
            "title": "Sprint Planning",
            "event-id": "E1",
            "calendar-source": "google",
            "meeting-link": "https://meet.google.com/xyz",
            "org": "test",
            "org-subfolder": "Test",
            "pipeline-status": "pending",
            "participants": ["[[Stub Alice]]"],
        }

    def _source_fm(self) -> dict:
        return {
            "date": "2026-04-24",
            "time": "14:30-15:15",
            "title": "Teams call",
            "event-id": "unscheduled:abc123",
            "org": "test",
            "org-subfolder": "Test",
            "pipeline-status": "complete",
            "platform": "teams",
            "type": "discovery",
            "participants": ["[[Alice]]", "[[Bob]]"],
            "companies": ["[[Acme]]"],
            "duration": "45:00",
            "recording": "2026-04-24 1430 Teams call.flac",
            "tags": ["meeting/test", "unscheduled"],
        }

    def test_calendar_keys_from_stub(self):
        from recap.daemon.recorder.attach import _build_merged_frontmatter
        merged = _build_merged_frontmatter(self._stub_fm(), self._source_fm())
        assert merged["event-id"] == "E1"
        assert merged["calendar-source"] == "google"
        assert merged["meeting-link"] == "https://meet.google.com/xyz"
        assert merged["time"] == "14:00-15:00"
        assert merged["title"] == "Sprint Planning"

    def test_recording_metadata_from_source(self):
        from recap.daemon.recorder.attach import _build_merged_frontmatter
        merged = _build_merged_frontmatter(self._stub_fm(), self._source_fm())
        assert merged["recording"] == "2026-04-24 1430 Teams call.flac"
        assert merged["duration"] == "45:00"
        assert "[[Acme]]" in merged["companies"]

    def test_unscheduled_tag_removed(self):
        from recap.daemon.recorder.attach import _build_merged_frontmatter
        merged = _build_merged_frontmatter(self._stub_fm(), self._source_fm())
        assert "unscheduled" not in merged.get("tags", [])
        assert "meeting/test" in merged["tags"]

    def test_pipeline_status_from_source(self):
        from recap.daemon.recorder.attach import _build_merged_frontmatter
        stub = self._stub_fm()
        stub["pipeline-status"] = "complete"
        src = self._source_fm()
        src["pipeline-status"] = "partial"
        merged = _build_merged_frontmatter(stub, src)
        assert merged["pipeline-status"] == "partial"

    def test_participants_from_source_override_stub(self):
        from recap.daemon.recorder.attach import _build_merged_frontmatter
        merged = _build_merged_frontmatter(self._stub_fm(), self._source_fm())
        # Source's participants win; stub's "[[Stub Alice]]" absent.
        assert "[[Alice]]" in merged["participants"]
        assert "[[Bob]]" in merged["participants"]
        assert "[[Stub Alice]]" not in merged["participants"]

    def test_pipeline_owned_fields_preserved(self):
        # Regression guard: build_canonical_frontmatter writes platform + type.
        # Rebind must not silently drop them.
        from recap.daemon.recorder.attach import _build_merged_frontmatter
        merged = _build_merged_frontmatter(self._stub_fm(), self._source_fm())
        assert merged["platform"] == "teams"
        assert merged["type"] == "discovery"

    def test_stub_user_keys_preserved(self):
        # User edits on stub frontmatter (e.g. priority) survive rebind even
        # when the source note doesn't carry the key.
        from recap.daemon.recorder.attach import _build_merged_frontmatter
        stub = self._stub_fm()
        stub["priority"] = "high"
        merged = _build_merged_frontmatter(stub, self._source_fm())
        assert merged["priority"] == "high"


# ---------------------------------------------------------------------
# Orchestrator end-to-end tests (via real daemon setup)
# ---------------------------------------------------------------------


@pytest.fixture
def attach_daemon(tmp_path: Path):
    """Build a minimal real Daemon with recordings + vault + EventIndex."""
    import yaml
    from recap.daemon.calendar.index import EventIndex
    from recap.daemon.config import load_daemon_config
    from recap.daemon.service import Daemon

    vault = tmp_path / "vault"
    meetings = vault / "Test" / "Meetings"
    meetings.mkdir(parents=True)
    recordings = tmp_path / "recordings"
    recordings.mkdir()

    doc = {
        "config-version": 1,
        "vault-path": str(vault),
        "recordings-path": str(recordings),
        "user-name": "Tester",
        "default-org": "test",
        "orgs": {"test": {"subfolder": "Test"}},
        "detection": {},
        "calendar": {},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(doc))
    config = load_daemon_config(config_path)

    daemon = Daemon(config=config, config_path=config_path)
    daemon.event_index = EventIndex(vault / ".recap" / "event-index.json")
    return daemon


def _seed_unscheduled_recording(
    daemon, *, stem: str, event_id: str, note_path: str, body: str,
) -> Path:
    """Write an unscheduled recording setup: audio, sidecar, note."""
    from recap.artifacts import RecordingMetadata, write_recording_metadata
    from recap.models import Participant

    audio = daemon.config.recordings_path / f"{stem}.flac"
    audio.touch()
    md = RecordingMetadata(
        org="test", note_path=note_path, title="Teams call",
        date="2026-04-24", participants=[Participant(name="Alice")],
        platform="manual",
    )
    md.event_id = event_id
    write_recording_metadata(audio, md)

    vault = daemon.config.vault_path
    (vault / note_path).parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "date": "2026-04-24",
        "time": "14:30-15:15",
        "title": "Teams call",
        "event-id": event_id,
        "org": "test",
        "org-subfolder": "Test",
        "participants": ["[[Alice]]"],
        "companies": [],
        "duration": "45:00",
        "recording": f"{stem}.flac",
        "tags": ["meeting/test", "unscheduled"],
        "pipeline-status": "complete",
    }
    import yaml
    content = "---\n" + yaml.dump(fm, sort_keys=False) + "---\n\n" + body
    (vault / note_path).write_text(content, encoding="utf-8")
    daemon.event_index.add(
        event_id, Path(note_path), "test",
    )
    return audio


def _seed_calendar_stub(
    daemon, *, event_id: str, title: str, stub_body: str,
) -> Path:
    """Write a calendar stub note."""
    vault = daemon.config.vault_path
    stub_path = Path("Test/Meetings") / f"2026-04-24 - {title.lower().replace(' ', '-')}.md"
    full = vault / stub_path
    fm = {
        "date": "2026-04-24",
        "time": "14:00-15:00",
        "title": title,
        "event-id": event_id,
        "calendar-source": "google",
        "meeting-link": "https://meet.google.com/xyz",
        "org": "test",
        "org-subfolder": "Test",
        "participants": [],
        "pipeline-status": "pending",
    }
    import yaml
    content = "---\n" + yaml.dump(fm, sort_keys=False) + "---\n\n" + stub_body
    full.write_text(content, encoding="utf-8")
    daemon.event_index.add(event_id, stub_path, "test")
    return full


class TestAttachOrchestrationHappyPath:
    def test_binds_to_calendar_stub(self, attach_daemon):
        from recap.daemon.recorder.attach import attach_event_to_recording

        audio = _seed_unscheduled_recording(
            attach_daemon,
            stem="2026-04-24 1430 Teams call",
            event_id="unscheduled:abc",
            note_path="Test/Meetings/2026-04-24 1430 - Teams call.md",
            body="# Meeting Summary\n\nPipeline output.",
        )
        stub = _seed_calendar_stub(
            attach_daemon,
            event_id="E1",
            title="Sprint Planning",
            stub_body="## Agenda\n\n",
        )

        result = attach_event_to_recording(
            daemon=attach_daemon,
            stem="2026-04-24 1430 Teams call",
            event_id="E1",
        )

        assert result.status == "ok"
        assert result.noop is False
        # Merged note at stub path.
        merged = stub.read_text(encoding="utf-8")
        assert "Pipeline output" in merged
        assert "event-id: E1" in merged
        assert "unscheduled" not in merged.splitlines()[1:10]  # not in tags near top
        # Unscheduled note gone.
        unscheduled = attach_daemon.config.vault_path / "Test/Meetings/2026-04-24 1430 - Teams call.md"
        assert not unscheduled.exists()
        # EventIndex: synthetic removed.
        assert attach_daemon.event_index.lookup("unscheduled:abc") is None
        assert attach_daemon.event_index.lookup("E1") is not None
        # Sidecar rewritten.
        from recap.artifacts import load_recording_metadata
        loaded = load_recording_metadata(audio)
        assert loaded is not None
        assert loaded.event_id == "E1"
        assert loaded.calendar_source == "google"


class TestAttachOrchestrationNoOp:
    def test_sidecar_already_bound_paths_match(self, attach_daemon):
        """Sidecar + note both reference E1; return noop."""
        from recap.daemon.recorder.attach import attach_event_to_recording
        from recap.artifacts import (
            RecordingMetadata, load_recording_metadata, write_recording_metadata,
        )
        from recap.models import Participant

        stub = _seed_calendar_stub(
            attach_daemon, event_id="E1", title="Sprint Planning",
            stub_body="## Agenda\n\n",
        )
        # Sidecar already points at E1 + stub path.
        audio = attach_daemon.config.recordings_path / "rec.flac"
        audio.touch()
        md = RecordingMetadata(
            org="test", note_path="Test/Meetings/2026-04-24 - sprint-planning.md",
            title="Sprint Planning", date="2026-04-24",
            participants=[Participant(name="Alice")], platform="manual",
        )
        md.event_id = "E1"
        write_recording_metadata(audio, md)

        result = attach_event_to_recording(
            daemon=attach_daemon, stem="rec", event_id="E1",
        )
        assert result.noop is True

    def test_sidecar_bound_but_orphan_unscheduled_note_cleaned(self, attach_daemon):
        """Simulates partial crash: sidecar bound + synthetic index still present."""
        from recap.daemon.recorder.attach import attach_event_to_recording
        from recap.artifacts import RecordingMetadata, write_recording_metadata
        from recap.models import Participant
        import yaml

        stub = _seed_calendar_stub(
            attach_daemon, event_id="E1", title="Sprint Planning",
            stub_body="## Agenda\n\n",
        )
        # Simulated orphan state: sidecar is bound to E1,
        # synthetic EventIndex entry still present, unscheduled note file still present.
        audio = attach_daemon.config.recordings_path / "rec.flac"
        audio.touch()
        md = RecordingMetadata(
            org="test",
            note_path=str(Path(stub).relative_to(attach_daemon.config.vault_path)),
            title="Sprint Planning", date="2026-04-24",
            participants=[Participant(name="A")], platform="manual",
        )
        md.event_id = "E1"
        write_recording_metadata(audio, md)
        # Add synthetic entry + unscheduled file (orphans).
        attach_daemon.event_index.add("unscheduled:abc", Path("Test/Meetings/u.md"), "test")
        orphan = attach_daemon.config.vault_path / "Test/Meetings/u.md"
        orphan.write_text("---\n" + yaml.dump({
            "event-id": "unscheduled:abc", "org": "test",
            "org-subfolder": "Test", "date": "2026-04-24", "time": "14:30-15:15",
            "recording": "rec.flac",
        }) + "---\n\nOrphan body.", encoding="utf-8")
        # NOTE: The orphan note's frontmatter MUST carry `recording: rec.flac` so
        # _find_orphan_synthetic_for_recording keys it off the same filename as the
        # target stub's `recording` field. IMPORTANT: the stub from _seed_calendar_stub
        # does not yet have a `recording` field. For this test, manually add it to the
        # stub before calling the orchestrator so the discovery scan has something to
        # match against. Do this BEFORE the attach_event_to_recording call.
        import yaml as _yaml
        stub_content = stub.read_text(encoding="utf-8")
        # Re-write stub frontmatter with recording=rec.flac included:
        stub_fm = {
            "date": "2026-04-24", "time": "14:00-15:00", "title": "Sprint Planning",
            "event-id": "E1", "calendar-source": "google",
            "meeting-link": "https://meet.google.com/xyz", "org": "test",
            "org-subfolder": "Test", "participants": [], "pipeline-status": "pending",
            "recording": "rec.flac",
        }
        stub.write_text(
            "---\n" + _yaml.dump(stub_fm, sort_keys=False) + "---\n\n## Agenda\n\n",
            encoding="utf-8",
        )

        result = attach_event_to_recording(
            daemon=attach_daemon, stem="rec", event_id="E1",
        )
        assert result.noop is True
        assert result.cleanup_performed is True
        # Orphan note deleted, synthetic entry removed.
        assert not orphan.exists()
        assert attach_daemon.event_index.lookup("unscheduled:abc") is None

    def test_sidecar_bound_but_orphan_file_remains_after_index_cleanup(self, attach_daemon):
        """Crash AFTER index cleanup but BEFORE file delete: sidecar is bound,
        synthetic EventIndex entry is GONE, but the unscheduled note file
        still exists on disk. Retry must heal by deleting the orphan file --
        even though the index has nothing for the discovery to scan.
        """
        from recap.daemon.recorder.attach import attach_event_to_recording
        from recap.artifacts import RecordingMetadata, write_recording_metadata
        from recap.models import Participant
        import yaml as _yaml

        stub = _seed_calendar_stub(
            attach_daemon, event_id="E1", title="Sprint Planning",
            stub_body="## Agenda\n\n",
        )
        # Stub already carries `recording: rec.flac` (mid-crash state from a
        # prior bind that completed steps 6-9 but crashed during step 10/11).
        stub_fm = {
            "date": "2026-04-24", "time": "14:00-15:00", "title": "Sprint Planning",
            "event-id": "E1", "calendar-source": "google",
            "meeting-link": "https://meet.google.com/xyz", "org": "test",
            "org-subfolder": "Test", "participants": [], "pipeline-status": "pending",
            "recording": "rec.flac",
        }
        stub.write_text(
            "---\n" + _yaml.dump(stub_fm, sort_keys=False) + "---\n\n## Agenda\n\n",
            encoding="utf-8",
        )
        # Sidecar already rebound to E1 (step 9 ran successfully).
        audio = attach_daemon.config.recordings_path / "rec.flac"
        audio.touch()
        md = RecordingMetadata(
            org="test",
            note_path=str(stub.relative_to(attach_daemon.config.vault_path)).replace("\\", "/"),
            title="Sprint Planning", date="2026-04-24",
            participants=[Participant(name="A")], platform="manual",
        )
        md.event_id = "E1"
        write_recording_metadata(audio, md)
        # Orphan file remains. The synthetic EventIndex entry is GONE
        # (step 10 ran), but step 11 crashed before unlinking the file.
        orphan = attach_daemon.config.vault_path / "Test/Meetings/u.md"
        orphan.write_text("---\n" + _yaml.dump({
            "event-id": "unscheduled:abc", "org": "test",
            "org-subfolder": "Test", "date": "2026-04-24", "time": "14:30-15:15",
            "recording": "rec.flac",
        }) + "---\n\nOrphan body.", encoding="utf-8")
        # IMPORTANT: do NOT call attach_daemon.event_index.add for unscheduled:abc.
        # That's the whole point -- the index entry was already cleaned up.

        result = attach_event_to_recording(
            daemon=attach_daemon, stem="rec", event_id="E1",
        )
        assert result.noop is True
        assert result.cleanup_performed is True
        # Orphan file is gone (the heal worked).
        assert not orphan.exists()
        # Index still has nothing for unscheduled:abc.
        assert attach_daemon.event_index.lookup("unscheduled:abc") is None

    def test_normal_flow_with_matching_recording_is_noop(self, attach_daemon):
        """Sidecar still synthetic, but target stub already carries the same
        `recording` filename. Mid-crash retry should rebind the sidecar +
        fire cleanup, not redo the merge write.
        """
        from recap.daemon.recorder.attach import attach_event_to_recording
        from recap.artifacts import load_recording_metadata
        import yaml

        audio = _seed_unscheduled_recording(
            attach_daemon, stem="rec", event_id="unscheduled:abc",
            note_path="Test/Meetings/u.md", body="# Source body",
        )
        # Stub already carries `recording: rec.flac` (mid-crash state).
        vault = attach_daemon.config.vault_path
        stub_path = Path("Test/Meetings/2026-04-24 - sprint.md")
        fm = {
            "date": "2026-04-24", "time": "14:00-15:00", "title": "Sprint",
            "event-id": "E1", "calendar-source": "google",
            "meeting-link": "https://meet.google.com/x",
            "org": "test", "org-subfolder": "Test",
            "recording": "rec.flac",  # already merged from a prior crashed attempt
            "pipeline-status": "complete",
        }
        (vault / stub_path).write_text(
            "---\n" + yaml.dump(fm, sort_keys=False) + "---\n\n## Agenda\n\n",
            encoding="utf-8",
        )
        attach_daemon.event_index.add("E1", stub_path, "test")

        result = attach_event_to_recording(
            daemon=attach_daemon, stem="rec", event_id="E1",
        )
        assert result.noop is True
        assert result.cleanup_performed is True
        # Sidecar should now point at E1 (rebind ran).
        loaded = load_recording_metadata(audio)
        assert loaded is not None
        assert loaded.event_id == "E1"
        # Unscheduled note + synthetic index entry both cleaned up.
        assert not (vault / "Test/Meetings/u.md").exists()
        assert attach_daemon.event_index.lookup("unscheduled:abc") is None


class TestAttachOrchestrationErrors:
    def test_synthetic_event_id_raises(self, attach_daemon):
        from recap.daemon.recorder.attach import attach_event_to_recording
        with pytest.raises(ValueError, match="target_event_must_be_real_calendar_event"):
            attach_event_to_recording(
                daemon=attach_daemon, stem="rec", event_id="unscheduled:x",
            )

    def test_stem_not_found(self, attach_daemon):
        from recap.daemon.recorder.attach import (
            attach_event_to_recording, AttachNotFoundError,
        )
        with pytest.raises(AttachNotFoundError, match="recording not found"):
            attach_event_to_recording(
                daemon=attach_daemon, stem="ghost", event_id="E1",
            )

    def test_sidecar_missing(self, attach_daemon):
        from recap.daemon.recorder.attach import (
            attach_event_to_recording, AttachNotFoundError,
        )
        (attach_daemon.config.recordings_path / "rec.flac").touch()
        with pytest.raises(AttachNotFoundError, match="sidecar not found"):
            attach_event_to_recording(
                daemon=attach_daemon, stem="rec", event_id="E1",
            )

    def test_event_id_not_found(self, attach_daemon):
        from recap.daemon.recorder.attach import (
            attach_event_to_recording, AttachNotFoundError,
        )
        _seed_unscheduled_recording(
            attach_daemon, stem="rec", event_id="unscheduled:abc",
            note_path="Test/Meetings/u.md", body="body",
        )
        with pytest.raises(AttachNotFoundError, match="event not found"):
            attach_event_to_recording(
                daemon=attach_daemon, stem="rec", event_id="ghost",
            )

    def test_already_bound_to_other_event(self, attach_daemon):
        from recap.daemon.recorder.attach import (
            attach_event_to_recording, AttachAlreadyBoundError,
        )
        _seed_unscheduled_recording(
            attach_daemon, stem="rec", event_id="E2",
            note_path="Test/Meetings/u.md", body="body",
        )
        _seed_calendar_stub(
            attach_daemon, event_id="E1", title="Sprint",
            stub_body="## Agenda\n\n",
        )
        with pytest.raises(AttachAlreadyBoundError) as exc_info:
            attach_event_to_recording(
                daemon=attach_daemon, stem="rec", event_id="E1",
            )
        assert exc_info.value.current_event_id == "E2"

    def test_recording_conflict(self, attach_daemon):
        from recap.daemon.recorder.attach import (
            attach_event_to_recording, AttachConflictError,
        )
        _seed_unscheduled_recording(
            attach_daemon, stem="rec-new", event_id="unscheduled:abc",
            note_path="Test/Meetings/u.md", body="new body",
        )
        # Stub already has a different `recording` field (from a prior bind).
        vault = attach_daemon.config.vault_path
        stub_path = Path("Test/Meetings/2026-04-24 - sprint.md")
        import yaml
        fm = {
            "date": "2026-04-24", "time": "14:00-15:00", "title": "Sprint",
            "event-id": "E1", "calendar-source": "google",
            "meeting-link": "", "org": "test", "org-subfolder": "Test",
            "recording": "other-rec.flac",  # existing recording
            "pipeline-status": "complete",
        }
        (vault / stub_path).write_text(
            "---\n" + yaml.dump(fm, sort_keys=False) + "---\n\n## Agenda\n\n",
            encoding="utf-8",
        )
        attach_daemon.event_index.add("E1", stub_path, "test")

        with pytest.raises(AttachConflictError) as exc_info:
            attach_event_to_recording(
                daemon=attach_daemon, stem="rec-new", event_id="E1",
                replace=False,
            )
        assert exc_info.value.existing_recording == "other-rec.flac"

    def test_replace_skips_conflict(self, attach_daemon):
        """With replace=true, conflict is ignored and bind proceeds."""
        from recap.daemon.recorder.attach import attach_event_to_recording
        _seed_unscheduled_recording(
            attach_daemon, stem="rec-new", event_id="unscheduled:abc",
            note_path="Test/Meetings/u.md", body="new body",
        )
        vault = attach_daemon.config.vault_path
        stub_path = Path("Test/Meetings/2026-04-24 - sprint.md")
        import yaml
        fm = {
            "date": "2026-04-24", "time": "14:00-15:00", "title": "Sprint",
            "event-id": "E1", "calendar-source": "google",
            "meeting-link": "", "org": "test", "org-subfolder": "Test",
            "recording": "other-rec.flac",
            "pipeline-status": "complete",
        }
        (vault / stub_path).write_text(
            "---\n" + yaml.dump(fm, sort_keys=False) + "---\n\n## Agenda\n\n",
            encoding="utf-8",
        )
        attach_daemon.event_index.add("E1", stub_path, "test")

        result = attach_event_to_recording(
            daemon=attach_daemon, stem="rec-new", event_id="E1", replace=True,
        )
        assert result.status == "ok"
        assert result.noop is False
        # New recording field overwrote old.
        content = (vault / stub_path).read_text()
        assert "rec-new.flac" in content

    def test_cross_org_bind_refused(self, attach_daemon):
        """Orchestrator refuses to bind across orgs."""
        from recap.daemon.recorder.attach import attach_event_to_recording
        import yaml

        _seed_unscheduled_recording(
            attach_daemon, stem="rec", event_id="unscheduled:abc",
            note_path="Test/Meetings/u.md", body="body",
        )
        # Hand-rolled cross-org stub: org "other" in frontmatter, but path under
        # the test org's Meetings dir so find_note_by_event_id resolves it.
        vault = attach_daemon.config.vault_path
        stub_path = Path("Test/Meetings/2026-04-24 - cross.md")
        fm = {
            "date": "2026-04-24", "time": "14:00-15:00", "title": "Cross",
            "event-id": "E1", "calendar-source": "google",
            "meeting-link": "", "org": "other", "org-subfolder": "Other",
            "pipeline-status": "pending",
        }
        (vault / stub_path).write_text(
            "---\n" + yaml.dump(fm, sort_keys=False) + "---\n\n## Agenda\n\n",
            encoding="utf-8",
        )
        attach_daemon.event_index.add("E1", stub_path, "other")

        with pytest.raises(ValueError, match="cross_org_bind_refused"):
            attach_event_to_recording(
                daemon=attach_daemon, stem="rec", event_id="E1",
            )

    def test_date_out_of_window(self, attach_daemon):
        """Orchestrator refuses bind when source/target dates are >+/- 1 day apart."""
        from recap.daemon.recorder.attach import attach_event_to_recording
        import yaml

        _seed_unscheduled_recording(
            attach_daemon, stem="rec", event_id="unscheduled:abc",
            note_path="Test/Meetings/u.md", body="body",
        )
        vault = attach_daemon.config.vault_path
        stub_path = Path("Test/Meetings/2026-04-26 - far.md")
        fm = {
            "date": "2026-04-26",  # 2 days after source's 2026-04-24
            "time": "14:00-15:00", "title": "Far",
            "event-id": "E1", "calendar-source": "google",
            "meeting-link": "", "org": "test", "org-subfolder": "Test",
            "pipeline-status": "pending",
        }
        (vault / stub_path).write_text(
            "---\n" + yaml.dump(fm, sort_keys=False) + "---\n\n## Agenda\n\n",
            encoding="utf-8",
        )
        attach_daemon.event_index.add("E1", stub_path, "test")

        with pytest.raises(ValueError, match="date_out_of_window"):
            attach_event_to_recording(
                daemon=attach_daemon, stem="rec", event_id="E1",
            )

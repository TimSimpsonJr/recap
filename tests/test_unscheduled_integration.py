"""End-to-end test for unscheduled meeting synthesis (#27).

Covers: detector synthesis -> sidecar -> pipeline resolve -> vault upsert
-> EventIndex entry. All Parakeet/NeMo/Claude calls are stubbed; the
three layers of interest (detector, pipeline resolution, vault writer)
run their real code paths.
"""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import Mock

import yaml

from recap.artifacts import write_recording_metadata
from recap.daemon.calendar.index import EventIndex
from recap.daemon.recorder.detector import MeetingDetector
from recap.models import AnalysisResult, MeetingMetadata
from recap.vault import write_meeting_note


def _make_detector(vault_path):
    org_cfg = Mock()
    org_cfg.slug = "acme"
    org_cfg.resolve_subfolder = lambda v: v / "Acme"
    config = Mock()
    config.vault_path = str(vault_path)
    config.org_by_slug = lambda slug: org_cfg if slug == "acme" else None
    config.default_org = org_cfg
    return MeetingDetector(config=config, recorder=Mock())


def test_unscheduled_meeting_end_to_end(tmp_path, monkeypatch):
    """Teams auto-record with no calendar event produces a coherent
    note + EventIndex entry, via the real detector + vault code paths."""
    vault = tmp_path / "vault"
    (vault / "Acme" / "Meetings").mkdir(parents=True)

    # Freeze wall clock so filename/time are deterministic.
    import recap.daemon.recorder.detector as det_mod

    class _FakeDatetime:
        @staticmethod
        def now(tz=None):
            if tz is None:
                return datetime(2026, 4, 22, 14, 30, 0)
            return datetime(2026, 4, 22, 14, 30, 0, tzinfo=tz)
    monkeypatch.setattr(det_mod, "datetime", _FakeDatetime)

    # --- Detector synthesizes metadata. ---
    detector = _make_detector(vault)
    metadata = detector._build_recording_metadata(
        org="acme", title="Whatever Teams showed",
        platform="teams", participants=[], event_id=None,
    )
    assert metadata.event_id.startswith("unscheduled:")
    assert metadata.note_path == "Acme/Meetings/2026-04-22 1430 - Teams call.md"
    assert metadata.recording_started_at is not None

    # --- Recorder would write the sidecar; simulate. ---
    recording_dir = tmp_path / "recordings"
    recording_dir.mkdir()
    audio_path = recording_dir / "2026-04-22 1430 Teams.flac"
    audio_path.write_bytes(b"")
    write_recording_metadata(audio_path, metadata)

    # --- Vault write with stub analysis (no Claude/NeMo). ---
    analysis = AnalysisResult(
        speaker_mapping={"SPEAKER_00": "Unknown Speaker 1"},
        meeting_type="general", summary="stub",
        key_points=[], decisions=[], action_items=[],
        follow_ups=[], relationship_notes=None,
        people=[], companies=[],
    )
    event_index = EventIndex(vault / ".recap" / "event-index.json")

    meeting_meta = MeetingMetadata(
        title=metadata.title, date=date(2026, 4, 22),
        participants=[], platform="teams",
    )
    note_path = write_meeting_note(
        metadata=meeting_meta,
        analysis=analysis,
        duration_seconds=2712,
        recording_path=audio_path,
        meetings_dir=vault / "Acme" / "Meetings",
        org="acme", org_subfolder="Acme",
        note_path=vault / metadata.note_path,
        recording_metadata=metadata,
        event_index=event_index,
        vault_path=vault,
    )

    # --- Assert note shape. ---
    assert note_path == vault / "Acme/Meetings/2026-04-22 1430 - Teams call.md"
    assert note_path.exists()
    content = note_path.read_text(encoding="utf-8")
    parts = content.split("---\n")
    fm = yaml.safe_load(parts[1])

    assert fm["event-id"] == metadata.event_id
    assert fm["title"] == "Teams call"
    assert fm["platform"] == "teams"
    assert fm["org"] == "acme"
    assert fm["org-subfolder"] == "Acme"
    assert fm["time"] == "14:30-15:15"
    assert fm["type"] == "general"
    assert "meeting/general" in fm["tags"]
    assert "unscheduled" in fm["tags"]
    assert "calendar-source" not in fm
    assert "meeting-link" not in fm
    assert fm["recording"] == "2026-04-22 1430 Teams.flac"

    # --- Assert EventIndex carries the synthetic id. ---
    indexed = event_index.lookup(metadata.event_id)
    assert indexed is not None
    # Normalize separators across Windows/POSIX.
    indexed_str = str(indexed.path).replace("\\", "/")
    assert indexed_str.endswith("Acme/Meetings/2026-04-22 1430 - Teams call.md")

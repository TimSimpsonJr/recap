"""Phase 2 integration: calendar sync -> note -> pipeline -> index stays consistent."""
from __future__ import annotations

from datetime import date

import yaml

from recap.artifacts import (
    RecordingMetadata,
    save_analysis,
    save_transcript,
)
from recap.daemon.calendar.index import EventIndex
from recap.daemon.calendar.sync import CalendarEvent, write_calendar_note
from recap.daemon.config import OrgConfig
from recap.models import (
    AnalysisResult,
    MeetingMetadata,
    Participant,
    ProfileStub,
    TranscriptResult,
    Utterance,
)
from recap.pipeline import PipelineRuntimeConfig, run_pipeline


def test_calendar_event_flow_to_pipeline_with_index(tmp_path):
    """End-to-end: calendar sync -> note + index entry; recording with same
    event_id resolves to the SAME note via the index; pipeline backfills
    canonical frontmatter without creating a duplicate; index entry
    remains consistent.
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    index_path = vault / "_Recap" / ".recap" / "event-index.json"
    index = EventIndex(index_path)

    # Calendar sync creates the note and populates the index
    org = OrgConfig(name="disbursecloud", subfolder="Clients/Disbursecloud")
    event = CalendarEvent(
        event_id="evt-integration",
        title="Q2 Review",
        date="2026-04-14",
        time="14:00-15:00",
        participants=["Alice", "Bob"],
        calendar_source="google",
        org="disbursecloud",
        meeting_link="https://meet.google.com/abc",
        description="Q2 agenda",
    )
    calendar_note = write_calendar_note(event, vault, org, event_index=index)
    assert index.lookup("evt-integration") is not None

    # A recording attaches to the same calendar event via event_id
    audio_path = tmp_path / "2026-04-14-140000-disbursecloud.flac"
    audio_path.touch()
    save_transcript(
        audio_path,
        TranscriptResult(
            utterances=[Utterance(speaker_id="Alice", speaker="Alice", start=0, end=1, text="hi")],
            raw_text="hi",
            language="en",
        ),
    )
    save_analysis(
        audio_path,
        AnalysisResult(
            speaker_mapping={},
            meeting_type="quarterly_review",
            summary="Productive Q2 discussion.",
            key_points=[],
            decisions=[],
            action_items=[],
            follow_ups=[],
            relationship_notes=None,
            people=[],
            companies=[ProfileStub(name="Acme")],
        ),
    )
    recording_metadata = RecordingMetadata(
        org="disbursecloud",
        note_path="",  # empty -- resolver uses event_id + index
        title="Q2 Review",
        date="2026-04-14",
        participants=[Participant(name="Alice")],
        platform="google_meet",
        calendar_source="google",
        event_id="evt-integration",
        meeting_link="https://meet.google.com/abc",
    )

    metadata = MeetingMetadata(
        title="Q2 Review",
        date=date(2026, 4, 14),
        participants=[Participant(name="Alice")],
        platform="google_meet",
    )
    config = PipelineRuntimeConfig(archive_format="flac")

    run_pipeline(
        audio_path=audio_path,
        metadata=metadata,
        config=config,
        org_slug="disbursecloud",
        org_subfolder="Clients/Disbursecloud",
        vault_path=vault,
        user_name="Tim",
        from_stage="export",
        recording_metadata=recording_metadata,
        event_index=index,
    )

    # The pre-existing calendar note should be backfilled, not a duplicate created
    content = calendar_note.read_text(encoding="utf-8")
    _, fm_block, rest = content.split("---\n", 2)
    fm = yaml.safe_load(fm_block)

    # Calendar-owned keys preserved
    assert fm["time"] == "14:00-15:00"
    assert fm["calendar-source"] == "google"
    assert fm["event-id"] == "evt-integration"
    assert fm["meeting-link"] == "https://meet.google.com/abc"

    # Pipeline-owned keys backfilled
    assert fm["pipeline-status"] == "complete"
    assert fm["type"] == "quarterly_review"
    assert fm["recording"] == "2026-04-14-140000-disbursecloud.flac"
    assert fm["companies"] == ["[[Acme]]"]

    # Agenda preserved
    assert "Q2 agenda" in rest

    # Index still consistent -- entry.path is PurePosixPath, compare via str
    entry = index.lookup("evt-integration")
    assert entry is not None
    expected_rel = str(calendar_note.relative_to(vault)).replace("\\", "/")
    assert str(entry.path) == expected_rel

    # Confirm no duplicate note was created -- only one .md file in meetings dir
    meetings_dir = vault / "Clients" / "Disbursecloud" / "Meetings"
    md_files = list(meetings_dir.glob("*.md"))
    assert len(md_files) == 1
    assert md_files[0] == calendar_note

"""Tests for canonical frontmatter builder."""
from __future__ import annotations

import pathlib
from datetime import date

from recap.models import (
    AnalysisResult,
    MeetingMetadata,
    Participant,
    ProfileStub,
)
from recap.vault import build_canonical_frontmatter


def _make_analysis(meeting_type: str = "standup", companies: list[str] | None = None) -> AnalysisResult:
    return AnalysisResult(
        speaker_mapping={},
        meeting_type=meeting_type,
        summary="s",
        key_points=[],
        decisions=[],
        action_items=[],
        follow_ups=[],
        relationship_notes=None,
        people=[],
        companies=[ProfileStub(name=n) for n in (companies or [])],
    )


class TestCanonicalFrontmatter:
    def test_required_fields_populated(self):
        metadata = MeetingMetadata(
            title="Q2 Review",
            date=date(2026, 4, 14),
            participants=[Participant(name="Alice"), Participant(name="Bob")],
            platform="google_meet",
        )
        analysis = _make_analysis(meeting_type="quarterly_review", companies=["Acme"])

        fm = build_canonical_frontmatter(
            metadata=metadata,
            analysis=analysis,
            duration_seconds=4320.0,
            recording_path=pathlib.Path("2026-04-14-140000-disbursecloud.m4a"),
            org="disbursecloud",
            org_subfolder="Clients/Disbursecloud",
        )

        assert fm["date"] == "2026-04-14"
        assert fm["title"] == "Q2 Review"
        assert fm["org"] == "disbursecloud"
        assert fm["org-subfolder"] == "Clients/Disbursecloud"
        assert fm["platform"] == "google_meet"
        assert fm["participants"] == ["[[Alice]]", "[[Bob]]"]
        assert fm["companies"] == ["[[Acme]]"]
        assert fm["duration"] == "1h 12m"
        assert fm["type"] == "quarterly_review"
        assert fm["tags"] == ["meeting/quarterly_review"]
        assert fm["pipeline-status"] == "complete"
        assert fm["recording"] == "2026-04-14-140000-disbursecloud.m4a"

    def test_org_is_always_the_slug_not_the_subfolder(self):
        metadata = MeetingMetadata(
            title="t",
            date=date(2026, 4, 14),
            participants=[],
            platform="manual",
        )
        analysis = _make_analysis()
        fm = build_canonical_frontmatter(
            metadata=metadata,
            analysis=analysis,
            duration_seconds=60.0,
            recording_path=pathlib.Path("r.m4a"),
            org="disbursecloud",
            org_subfolder="Clients/Disbursecloud",
        )
        assert fm["org"] == "disbursecloud"
        assert "/" not in fm["org"]

    def test_recording_is_filename_not_path(self):
        metadata = MeetingMetadata(
            title="t", date=date(2026, 4, 14), participants=[], platform="manual",
        )
        fm = build_canonical_frontmatter(
            metadata=metadata,
            analysis=_make_analysis(),
            duration_seconds=60.0,
            recording_path=pathlib.Path("/abs/path/to/recording.m4a"),
            org="o",
            org_subfolder="O",
        )
        assert fm["recording"] == "recording.m4a"

    def test_includes_calendar_fields_when_recording_metadata_has_them(self):
        from recap.artifacts import RecordingMetadata

        metadata = MeetingMetadata(
            title="Q2 Review",
            date=date(2026, 4, 14),
            participants=[Participant(name="Alice")],
            platform="google_meet",
        )
        recording_metadata = RecordingMetadata(
            org="disbursecloud",
            note_path="",
            title="Q2 Review",
            date="2026-04-14",
            participants=[Participant(name="Alice")],
            platform="google_meet",
            calendar_source="google",
            event_id="evt-123",
            meeting_link="https://meet.google.com/abc",
        )

        fm = build_canonical_frontmatter(
            metadata=metadata,
            analysis=_make_analysis(),
            duration_seconds=60.0,
            recording_path=pathlib.Path("r.m4a"),
            org="disbursecloud",
            org_subfolder="Clients/Disbursecloud",
            recording_metadata=recording_metadata,
        )

        assert fm["calendar-source"] == "google"
        assert fm["event-id"] == "evt-123"
        assert fm["meeting-link"] == "https://meet.google.com/abc"

    def test_omits_calendar_fields_when_recording_metadata_is_none(self):
        metadata = MeetingMetadata(
            title="Ad hoc", date=date(2026, 4, 14), participants=[], platform="manual",
        )
        fm = build_canonical_frontmatter(
            metadata=metadata,
            analysis=_make_analysis(),
            duration_seconds=60.0,
            recording_path=pathlib.Path("r.m4a"),
            org="personal",
            org_subfolder="Personal",
            # recording_metadata omitted
        )
        assert "calendar-source" not in fm
        assert "event-id" not in fm
        assert "meeting-link" not in fm

    def test_omits_calendar_fields_when_metadata_values_are_empty(self):
        from recap.artifacts import RecordingMetadata

        recording_metadata = RecordingMetadata(
            org="personal", note_path="", title="Ad hoc",
            date="2026-04-14", participants=[], platform="manual",
            # calendar fields left as defaults (None, None, "")
        )

        metadata = MeetingMetadata(
            title="Ad hoc", date=date(2026, 4, 14), participants=[], platform="manual",
        )
        fm = build_canonical_frontmatter(
            metadata=metadata,
            analysis=_make_analysis(),
            duration_seconds=60.0,
            recording_path=pathlib.Path("r.m4a"),
            org="personal",
            org_subfolder="Personal",
            recording_metadata=recording_metadata,
        )
        assert "calendar-source" not in fm
        assert "event-id" not in fm
        assert "meeting-link" not in fm

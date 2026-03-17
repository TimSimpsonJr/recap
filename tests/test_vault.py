"""Tests for vault writing module."""
import pathlib
from datetime import date

import pytest
import yaml

from recap.models import (
    ActionItem,
    AnalysisResult,
    Decision,
    FollowUp,
    KeyPoint,
    MeetingMetadata,
    Participant,
    ProfileStub,
)
from recap.vault import (
    write_meeting_note,
    write_profile_stubs,
    find_previous_meeting,
    _generate_meeting_markdown,
    _format_duration,
    _slugify,
)
from recap.frames import FrameResult


@pytest.fixture
def sample_metadata() -> MeetingMetadata:
    return MeetingMetadata(
        title="Project Kickoff with Acme Corp",
        date=date(2026, 3, 16),
        participants=[
            Participant(name="Tim", email="tim@example.com"),
            Participant(name="Jane Smith", email="jane@acme.com"),
        ],
        platform="zoom",
    )


@pytest.fixture
def sample_analysis() -> AnalysisResult:
    return AnalysisResult(
        speaker_mapping={"SPEAKER_00": "Tim", "SPEAKER_01": "Jane Smith"},
        meeting_type="client-call",
        summary="Discussed project kickoff and timeline.",
        key_points=[
            KeyPoint(topic="Timeline", detail="Q3 delivery target"),
            KeyPoint(topic="Budget", detail="$50k approved"),
        ],
        decisions=[Decision(decision="Use vendor X", made_by="Jane Smith")],
        action_items=[
            ActionItem(assignee="Tim", description="Send proposal by Friday", due_date="2026-03-20", priority="high"),
            ActionItem(assignee="Jane Smith", description="Review budget numbers", due_date=None, priority="normal"),
        ],
        follow_ups=[FollowUp(item="Contract review", context="Legal team pending")],
        relationship_notes=None,
        people=[ProfileStub(name="Jane Smith", company="Acme Corp", role="VP Engineering")],
        companies=[ProfileStub(name="Acme Corp", industry="SaaS")],
    )


class TestSlugify:
    def test_basic(self):
        assert _slugify("Project Kickoff with Acme Corp") == "project-kickoff-with-acme-corp"

    def test_special_chars(self):
        assert _slugify("Q3 Review: Budget & Timeline") == "q3-review-budget-timeline"


class TestFormatDuration:
    def test_minutes_only(self):
        assert _format_duration(2700.0) == "45m"

    def test_hours_and_minutes(self):
        assert _format_duration(5400.0) == "1h 30m"

    def test_round_hour(self):
        assert _format_duration(3600.0) == "1h 0m"


class TestGenerateMeetingMarkdown:
    def test_includes_frontmatter(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/recap-data/recordings/2026-03-16-kickoff.mp4"),
        )
        # Parse frontmatter
        parts = md.split("---\n")
        assert len(parts) >= 3
        fm = yaml.safe_load(parts[1])
        assert fm["date"] == "2026-03-16"
        assert "[[Tim]]" in fm["participants"]
        assert "[[Acme Corp]]" in fm["companies"]
        assert fm["platform"] == "zoom"
        assert fm["type"] == "client-call"
        assert "meeting/client-call" in fm["tags"]

    def test_includes_summary(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
        )
        assert "## Summary" in md
        assert "Discussed project kickoff" in md

    def test_includes_key_points(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
        )
        assert "## Key Points" in md
        assert "Timeline" in md

    def test_includes_decisions_when_present(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
        )
        assert "## Decisions Made" in md
        assert "Use vendor X" in md

    def test_omits_decisions_when_empty(self, sample_metadata, sample_analysis):
        sample_analysis.decisions = []
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
        )
        assert "## Decisions Made" not in md

    def test_includes_action_items(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
        )
        assert "## Action Items" in md
        # Without user_name, all assignees get wikilinked, no #todoist tags
        assert "- [ ] [[Tim]]: Send proposal by Friday" in md
        assert "- [ ] [[Jane Smith]]: Review budget numbers" in md

    def test_omits_relationship_notes_when_null(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
        )
        assert "## Relationship Notes" not in md

    def test_includes_relationship_notes_when_present(self, sample_metadata, sample_analysis):
        sample_analysis.relationship_notes = "Jane prefers async communication."
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
        )
        assert "## Relationship Notes" in md
        assert "Jane prefers async" in md

    def test_includes_frames_when_present(self, sample_metadata, sample_analysis):
        frames = [
            FrameResult(path=pathlib.Path("frames/meeting-002.500.png"), timestamp=2.5),
            FrameResult(path=pathlib.Path("frames/meeting-010.000.png"), timestamp=10.0),
        ]
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
            frames=frames,
        )
        assert "## Screenshots" in md
        assert "![[meeting-002.500.png]]" in md
        assert "0:02" in md

    def test_user_action_items_tagged_todoist(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
            user_name="Tim",
        )
        assert "Send proposal by Friday #todoist" in md
        assert "#todoist" not in md.split("Jane Smith")[1].split("\n")[0]


class TestWriteMeetingNote:
    def test_writes_file(self, tmp_vault, sample_metadata, sample_analysis):
        note_path = write_meeting_note(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
            meetings_dir=tmp_vault / "Work" / "Meetings",
        )
        assert note_path.exists()
        assert note_path.name == "2026-03-16 - Project Kickoff with Acme Corp.md"

    def test_skips_if_exists(self, tmp_vault, sample_metadata, sample_analysis):
        meetings_dir = tmp_vault / "Work" / "Meetings"
        existing = meetings_dir / "2026-03-16 - Project Kickoff with Acme Corp.md"
        existing.write_text("existing content")

        note_path = write_meeting_note(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
            meetings_dir=meetings_dir,
        )
        assert note_path is None
        assert existing.read_text() == "existing content"


class TestWriteProfileStubs:
    def test_creates_person_stub(self, tmp_vault, sample_analysis):
        created = write_profile_stubs(
            analysis=sample_analysis,
            people_dir=tmp_vault / "Work" / "People",
            companies_dir=tmp_vault / "Work" / "Companies",
        )
        person_file = tmp_vault / "Work" / "People" / "Jane Smith.md"
        assert person_file.exists()
        content = person_file.read_text()
        assert "Acme Corp" in content
        assert "VP Engineering" in content
        assert "Jane Smith" in created

    def test_creates_company_stub(self, tmp_vault, sample_analysis):
        write_profile_stubs(
            analysis=sample_analysis,
            people_dir=tmp_vault / "Work" / "People",
            companies_dir=tmp_vault / "Work" / "Companies",
        )
        company_file = tmp_vault / "Work" / "Companies" / "Acme Corp.md"
        assert company_file.exists()
        content = company_file.read_text()
        assert "SaaS" in content

    def test_skips_existing_person(self, tmp_vault, sample_analysis):
        person_file = tmp_vault / "Work" / "People" / "Jane Smith.md"
        person_file.write_text("existing content")
        write_profile_stubs(
            analysis=sample_analysis,
            people_dir=tmp_vault / "Work" / "People",
            companies_dir=tmp_vault / "Work" / "Companies",
        )
        assert person_file.read_text() == "existing content"

    def test_skips_existing_company(self, tmp_vault, sample_analysis):
        company_file = tmp_vault / "Work" / "Companies" / "Acme Corp.md"
        company_file.write_text("existing content")
        write_profile_stubs(
            analysis=sample_analysis,
            people_dir=tmp_vault / "Work" / "People",
            companies_dir=tmp_vault / "Work" / "Companies",
        )
        assert company_file.read_text() == "existing content"


class TestFindPreviousMeeting:
    def test_finds_matching_meeting(self, tmp_vault):
        meetings_dir = tmp_vault / "Work" / "Meetings"
        old_note = meetings_dir / "2026-03-09 - Weekly Standup.md"
        old_note.write_text(
            "---\nparticipants:\n  - \"[[Tim]]\"\n  - \"[[Jane Smith]]\"\n---\nContent here"
        )
        result = find_previous_meeting(
            participant_names=["Tim", "Jane Smith"],
            meetings_dir=meetings_dir,
            exclude_filename="2026-03-16 - Weekly Standup.md",
        )
        assert result == "2026-03-09 - Weekly Standup"

    def test_returns_none_when_no_match(self, tmp_vault):
        meetings_dir = tmp_vault / "Work" / "Meetings"
        old_note = meetings_dir / "2026-03-09 - Other Meeting.md"
        old_note.write_text(
            "---\nparticipants:\n  - \"[[Bob]]\"\n  - \"[[Alice]]\"\n---\nContent"
        )
        result = find_previous_meeting(
            participant_names=["Tim", "Jane Smith"],
            meetings_dir=meetings_dir,
            exclude_filename="2026-03-16 - Standup.md",
        )
        assert result is None

    def test_returns_most_recent_match(self, tmp_vault):
        meetings_dir = tmp_vault / "Work" / "Meetings"
        (meetings_dir / "2026-03-02 - Sync.md").write_text(
            "---\nparticipants:\n  - \"[[Tim]]\"\n  - \"[[Jane Smith]]\"\n---\n"
        )
        (meetings_dir / "2026-03-09 - Sync.md").write_text(
            "---\nparticipants:\n  - \"[[Tim]]\"\n  - \"[[Jane Smith]]\"\n---\n"
        )
        result = find_previous_meeting(
            participant_names=["Tim", "Jane Smith"],
            meetings_dir=meetings_dir,
            exclude_filename="2026-03-16 - Sync.md",
        )
        assert result == "2026-03-09 - Sync"

    def test_partial_overlap_matches(self, tmp_vault):
        meetings_dir = tmp_vault / "Work" / "Meetings"
        (meetings_dir / "2026-03-09 - Team Sync.md").write_text(
            "---\nparticipants:\n  - \"[[Tim]]\"\n  - \"[[Jane Smith]]\"\n  - \"[[Bob]]\"\n---\n"
        )
        result = find_previous_meeting(
            participant_names=["Tim", "Jane Smith", "Alice"],
            meetings_dir=meetings_dir,
            exclude_filename="2026-03-16 - Team Sync.md",
            min_overlap=0.5,
        )
        # 2 of 3 current participants overlap = 0.67 > 0.5 threshold
        assert result == "2026-03-09 - Team Sync"

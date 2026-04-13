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
    MEETING_RECORD_MARKER,
    write_meeting_note,
    write_profile_stubs,
    find_previous_meeting,
    _generate_meeting_markdown,
    _generate_pipeline_content,
    _format_action_item,
    _format_duration,
    slugify,
)


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
        assert slugify("Project Kickoff with Acme Corp") == "project-kickoff-with-acme-corp"

    def test_special_chars(self):
        assert slugify("Q3 Review: Budget & Timeline") == "q3-review-budget-timeline"


class TestFormatDuration:
    def test_minutes_only(self):
        assert _format_duration(2700.0) == "45m"

    def test_hours_and_minutes(self):
        assert _format_duration(5400.0) == "1h 30m"

    def test_round_hour(self):
        assert _format_duration(3600.0) == "1h 0m"


class TestFormatActionItem:
    def test_high_priority_with_due_date_user_assignee(self):
        item = ActionItem(assignee="Tim", description="Send proposal", due_date="2026-04-18", priority="high")
        result = _format_action_item(item, user_name="Tim")
        assert result == "- [ ] Tim: Send proposal 📅 2026-04-18 ⏫"

    def test_normal_priority_other_assignee(self):
        item = ActionItem(assignee="Jane", description="Review budget", due_date="2026-04-21", priority="normal")
        result = _format_action_item(item, user_name="Tim")
        assert result == "- [ ] [[Jane]]: Review budget 📅 2026-04-21 🔼"

    def test_low_priority_no_emoji(self):
        item = ActionItem(assignee="Tim", description="Clean up docs", due_date=None, priority="low")
        result = _format_action_item(item, user_name="Tim")
        assert result == "- [ ] Tim: Clean up docs"
        assert "⏫" not in result
        assert "🔼" not in result

    def test_no_due_date(self):
        item = ActionItem(assignee="Jane", description="Do thing", due_date=None, priority="high")
        result = _format_action_item(item, user_name="Tim")
        assert result == "- [ ] [[Jane]]: Do thing ⏫"
        assert "📅" not in result

    def test_no_user_name_wikilinks_everyone(self):
        item = ActionItem(assignee="Tim", description="Task", due_date=None, priority="normal")
        result = _format_action_item(item, user_name=None)
        assert result == "- [ ] [[Tim]]: Task 🔼"


class TestGenerateMeetingMarkdown:
    def test_includes_frontmatter(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/recap-data/recordings/2026-03-16-kickoff.m4a"),
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

    def test_pipeline_status_in_frontmatter(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
        )
        parts = md.split("---\n")
        fm = yaml.safe_load(parts[1])
        assert fm["pipeline-status"] == "complete"

    def test_org_in_frontmatter(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
            org="disbursecloud",
        )
        parts = md.split("---\n")
        fm = yaml.safe_load(parts[1])
        assert fm["org"] == "disbursecloud"

    def test_org_omitted_when_none(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
        )
        parts = md.split("---\n")
        fm = yaml.safe_load(parts[1])
        assert "org" not in fm

    def test_includes_meeting_record_marker(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
        )
        assert MEETING_RECORD_MARKER in md

    def test_includes_summary(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
        )
        assert "## Summary" in md
        assert "Discussed project kickoff" in md

    def test_includes_key_points(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
        )
        assert "## Key Points" in md
        assert "Timeline" in md

    def test_includes_decisions_when_present(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
        )
        assert "## Decisions Made" in md
        assert "Use vendor X" in md

    def test_omits_decisions_when_empty(self, sample_metadata, sample_analysis):
        sample_analysis.decisions = []
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
        )
        assert "## Decisions Made" not in md

    def test_action_items_emoji_format(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
            user_name="Tim",
        )
        assert "## Action Items" in md
        # Tim is user: no wikilink, high priority, due date
        assert "- [ ] Tim: Send proposal by Friday 📅 2026-03-20 ⏫" in md
        # Jane is not user: wikilinked, normal priority, no due date
        assert "- [ ] [[Jane Smith]]: Review budget numbers 🔼" in md

    def test_action_items_no_user_name(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
        )
        # Without user_name, all assignees get wikilinked
        assert "[[Tim]]" in md
        assert "[[Jane Smith]]" in md

    def test_omits_relationship_notes_when_null(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
        )
        assert "## Relationship Notes" not in md

    def test_includes_relationship_notes_when_present(self, sample_metadata, sample_analysis):
        sample_analysis.relationship_notes = "Jane prefers async communication."
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
        )
        assert "## Relationship Notes" in md
        assert "Jane prefers async" in md

    def test_no_screenshots_section(self, sample_metadata, sample_analysis):
        """Screenshots/frames section should not exist."""
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
        )
        assert "## Screenshots" not in md

    def test_no_todoist_tags(self, sample_metadata, sample_analysis):
        """Todoist tags should not appear in output."""
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
            user_name="Tim",
        )
        assert "#todoist" not in md

    def test_recording_path_m4a(self, sample_metadata, sample_analysis):
        """Recording path should use .m4a extension."""
        rec = pathlib.Path("C:/recap-data/recordings/2026-03-16-kickoff.m4a")
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=rec,
        )
        parts = md.split("---\n")
        fm = yaml.safe_load(parts[1])
        assert fm["recording"].endswith(".m4a")


class TestWriteMeetingNote:
    def test_writes_file(self, tmp_vault, sample_metadata, sample_analysis):
        note_path = write_meeting_note(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
            meetings_dir=tmp_vault / "Work" / "Meetings",
        )
        assert note_path.exists()
        assert note_path.name == "2026-03-16 - Project Kickoff with Acme Corp.md"

    def test_new_note_has_marker(self, tmp_vault, sample_metadata, sample_analysis):
        note_path = write_meeting_note(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
            meetings_dir=tmp_vault / "Work" / "Meetings",
        )
        content = note_path.read_text(encoding="utf-8")
        assert MEETING_RECORD_MARKER in content

    def test_org_subfolder_routing(self, tmp_vault, sample_metadata, sample_analysis):
        """Meeting note goes to correct org subfolder path."""
        org_meetings = tmp_vault / "DisburseCloud" / "Meetings"
        org_meetings.mkdir(parents=True)
        note_path = write_meeting_note(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
            meetings_dir=org_meetings,
            org="disbursecloud",
        )
        assert note_path is not None
        assert "DisburseCloud" in str(note_path)
        # Verify org in frontmatter
        content = note_path.read_text(encoding="utf-8")
        parts = content.split("---\n")
        fm = yaml.safe_load(parts[1])
        assert fm["org"] == "disbursecloud"

    def test_append_below_marker_when_file_exists_without_marker(
        self, tmp_vault, sample_metadata, sample_analysis
    ):
        """If file exists but has no marker, append marker + pipeline content."""
        meetings_dir = tmp_vault / "Work" / "Meetings"
        existing = meetings_dir / "2026-03-16 - Project Kickoff with Acme Corp.md"
        existing.write_text("## Agenda\n\n- Item 1\n- Item 2", encoding="utf-8")

        note_path = write_meeting_note(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
            meetings_dir=meetings_dir,
        )
        assert note_path is not None
        content = note_path.read_text(encoding="utf-8")
        # Manual content preserved
        assert "## Agenda" in content
        assert "- Item 1" in content
        # Marker added
        assert MEETING_RECORD_MARKER in content
        # Pipeline content added below marker
        assert "## Summary" in content

    def test_reprocess_replaces_below_marker(
        self, tmp_vault, sample_metadata, sample_analysis
    ):
        """If marker exists, replace everything below it."""
        meetings_dir = tmp_vault / "Work" / "Meetings"
        existing = meetings_dir / "2026-03-16 - Project Kickoff with Acme Corp.md"
        existing.write_text(
            "## Agenda\n\n- Item 1\n\n"
            + MEETING_RECORD_MARKER
            + "\n\n## Summary\n\nOld summary that should be replaced.\n",
            encoding="utf-8",
        )

        note_path = write_meeting_note(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
            meetings_dir=meetings_dir,
        )
        assert note_path is not None
        content = note_path.read_text(encoding="utf-8")
        # Manual content preserved
        assert "## Agenda" in content
        assert "- Item 1" in content
        # Old summary replaced
        assert "Old summary that should be replaced" not in content
        # New pipeline content present
        assert "Discussed project kickoff" in content

    def test_reprocess_preserves_above_marker(
        self, tmp_vault, sample_metadata, sample_analysis
    ):
        """Content above marker is never touched during reprocess."""
        meetings_dir = tmp_vault / "Work" / "Meetings"
        existing = meetings_dir / "2026-03-16 - Project Kickoff with Acme Corp.md"
        above = "---\ntitle: My Manual Notes\n---\n\n## My Briefing\n\nImportant context here.\n\n"
        existing.write_text(
            above + MEETING_RECORD_MARKER + "\n\nOld content\n",
            encoding="utf-8",
        )

        write_meeting_note(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.m4a"),
            meetings_dir=meetings_dir,
        )
        content = existing.read_text(encoding="utf-8")
        assert "My Manual Notes" in content
        assert "My Briefing" in content
        assert "Important context here." in content


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

    def test_only_creates_when_not_exists(self, tmp_vault, sample_analysis):
        """Stubs are only created if the note doesn't already exist."""
        people_dir = tmp_vault / "Work" / "People"
        companies_dir = tmp_vault / "Work" / "Companies"

        # Pre-create one person and one company
        (people_dir / "Jane Smith.md").write_text("manual note about Jane")
        (companies_dir / "Acme Corp.md").write_text("manual note about Acme")

        created = write_profile_stubs(
            analysis=sample_analysis,
            people_dir=people_dir,
            companies_dir=companies_dir,
        )
        assert created == []
        # Originals untouched
        assert (people_dir / "Jane Smith.md").read_text() == "manual note about Jane"
        assert (companies_dir / "Acme Corp.md").read_text() == "manual note about Acme"


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

    def test_handles_crlf_line_endings(self, tmp_vault):
        """Ensure frontmatter parsing works with Windows-style CRLF endings."""
        meetings_dir = tmp_vault / "Work" / "Meetings"
        old_note = meetings_dir / "2026-03-09 - CRLF Meeting.md"
        # Write with CRLF line endings
        old_note.write_bytes(
            b"---\r\nparticipants:\r\n  - \"[[Tim]]\"\r\n  - \"[[Jane Smith]]\"\r\n---\r\nContent\r\n"
        )
        result = find_previous_meeting(
            participant_names=["Tim", "Jane Smith"],
            meetings_dir=meetings_dir,
            exclude_filename="2026-03-16 - Meeting.md",
        )
        assert result == "2026-03-09 - CRLF Meeting"

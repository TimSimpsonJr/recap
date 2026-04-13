"""Tests for calendar sync."""
import json
from recap.daemon.calendar.sync import (
    CalendarEvent,
    write_calendar_note,
    should_update_note,
    update_calendar_note,
    find_note_by_event_id,
)


class TestWriteCalendarNote:
    def test_creates_note_with_frontmatter(self, tmp_path):
        event = CalendarEvent(
            event_id="abc123",
            title="Sprint Planning",
            date="2026-04-14",
            time="14:00-15:00",
            participants=["Tim", "Jane Smith"],
            calendar_source="zoho",
            org="disbursecloud",
            meeting_link="https://teams.microsoft.com/...",
            description="Review sprint goals",
        )
        path = write_calendar_note(event, tmp_path)
        assert path.exists()
        content = path.read_text()
        assert "event-id:" in content
        assert "Sprint Planning" in content
        assert "[[Tim]]" in content
        assert "## Agenda" in content
        assert "Review sprint goals" in content

    def test_creates_directories(self, tmp_path):
        event = CalendarEvent(
            event_id="abc",
            title="Meeting",
            date="2026-04-14",
            time="10:00-11:00",
            participants=[],
            calendar_source="zoho",
            org="disbursecloud",
        )
        path = write_calendar_note(event, tmp_path)
        assert path.parent.exists()

    def test_pipeline_status_is_pending(self, tmp_path):
        event = CalendarEvent(
            event_id="abc",
            title="Meeting",
            date="2026-04-14",
            time="10:00-11:00",
            participants=[],
            calendar_source="zoho",
            org="disbursecloud",
        )
        path = write_calendar_note(event, tmp_path)
        content = path.read_text()
        assert "pipeline-status: pending" in content


class TestShouldUpdateNote:
    def test_new_event_returns_create(self, tmp_path):
        result = should_update_note(
            event_id="new-event",
            vault_path=tmp_path,
            org_subfolder="_Recap/Disbursecloud",
        )
        assert result == "create"

    def test_existing_unchanged_returns_skip(self, tmp_path):
        # Create a note with event-id
        meetings_dir = tmp_path / "_Recap" / "Disbursecloud" / "Meetings"
        meetings_dir.mkdir(parents=True)
        note = meetings_dir / "2026-04-14 - test.md"
        note.write_text('---\nevent-id: "abc"\ntime: "10:00-11:00"\nparticipants: []\n---\n')
        result = should_update_note(
            event_id="abc",
            vault_path=tmp_path,
            org_subfolder="_Recap/Disbursecloud",
            new_time="10:00-11:00",
        )
        assert result == "skip"

    def test_changed_time_returns_update(self, tmp_path):
        meetings_dir = tmp_path / "_Recap" / "Disbursecloud" / "Meetings"
        meetings_dir.mkdir(parents=True)
        note = meetings_dir / "2026-04-14 - test.md"
        note.write_text('---\nevent-id: "abc"\ntime: "10:00-11:00"\nparticipants: []\n---\n')
        result = should_update_note(
            event_id="abc",
            vault_path=tmp_path,
            org_subfolder="_Recap/Disbursecloud",
            new_time="14:00-15:00",
        )
        assert result == "update"


    def test_wikilink_participants_match_raw_names(self, tmp_path):
        """Bug 3: Notes store [[Name]] wikilinks but sync compares raw names."""
        meetings_dir = tmp_path / "_Recap" / "Disbursecloud" / "Meetings"
        meetings_dir.mkdir(parents=True)
        note = meetings_dir / "2026-04-14 - test.md"
        note.write_text(
            '---\nevent-id: "abc"\ntime: "10:00-11:00"\n'
            'participants:\n- "[[Alice]]"\n- "[[Bob]]"\n---\n'
        )
        result = should_update_note(
            event_id="abc",
            vault_path=tmp_path,
            org_subfolder="_Recap/Disbursecloud",
            new_time="10:00-11:00",
            new_participants=["Alice", "Bob"],
        )
        assert result == "skip"

    def test_wikilink_participants_detect_real_change(self, tmp_path):
        """Participants actually changed — should detect update."""
        meetings_dir = tmp_path / "_Recap" / "Disbursecloud" / "Meetings"
        meetings_dir.mkdir(parents=True)
        note = meetings_dir / "2026-04-14 - test.md"
        note.write_text(
            '---\nevent-id: "abc"\ntime: "10:00-11:00"\n'
            'participants:\n- "[[Alice]]"\n- "[[Bob]]"\n---\n'
        )
        result = should_update_note(
            event_id="abc",
            vault_path=tmp_path,
            org_subfolder="_Recap/Disbursecloud",
            new_time="10:00-11:00",
            new_participants=["Alice", "Charlie"],
        )
        assert result == "update"


class TestUpdateCalendarNote:
    def test_rename_queue_writes_json_array(self, tmp_path):
        """Bug 4: Rename queue should be a JSON array of {old_path, new_path}."""
        note = tmp_path / "2026-04-14 - test.md"
        note.write_text(
            '---\nevent-id: "abc"\ndate: "2026-04-14"\n'
            'time: "10:00-11:00"\nparticipants: []\n---\nBody\n'
        )
        queue_path = tmp_path / "rename-queue.json"

        update_calendar_note(
            note,
            new_time="2026-04-15 10:00-11:00",
            rename_queue_path=queue_path,
        )

        assert queue_path.exists()
        queue = json.loads(queue_path.read_text())
        assert isinstance(queue, list)
        assert len(queue) == 1
        assert "old_path" in queue[0]
        assert "new_path" in queue[0]
        assert "2026-04-14" in queue[0]["old_path"]
        assert "2026-04-15" in queue[0]["new_path"]

    def test_rename_queue_appends_to_existing(self, tmp_path):
        """Rename queue should append, not overwrite existing entries."""
        note = tmp_path / "2026-04-14 - test.md"
        note.write_text(
            '---\nevent-id: "abc"\ndate: "2026-04-14"\n'
            'time: "10:00-11:00"\nparticipants: []\n---\nBody\n'
        )
        queue_path = tmp_path / "rename-queue.json"
        # Pre-populate with an existing entry
        queue_path.write_text(
            json.dumps([{"old_path": "old.md", "new_path": "new.md"}])
        )

        update_calendar_note(
            note,
            new_time="2026-04-15 10:00-11:00",
            rename_queue_path=queue_path,
        )

        queue = json.loads(queue_path.read_text())
        assert len(queue) == 2


class TestFindNoteByEventId:
    def test_finds_note(self, tmp_path):
        note = tmp_path / "test.md"
        note.write_text('---\nevent-id: "abc123"\n---\nContent')
        result = find_note_by_event_id("abc123", tmp_path)
        assert result == note

    def test_returns_none_when_not_found(self, tmp_path):
        result = find_note_by_event_id("nonexistent", tmp_path)
        assert result is None

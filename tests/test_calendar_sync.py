"""Tests for calendar sync."""
import json
import pytest
from pathlib import Path
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


class TestFindNoteByEventId:
    def test_finds_note(self, tmp_path):
        note = tmp_path / "test.md"
        note.write_text('---\nevent-id: "abc123"\n---\nContent')
        result = find_note_by_event_id("abc123", tmp_path)
        assert result == note

    def test_returns_none_when_not_found(self, tmp_path):
        result = find_note_by_event_id("nonexistent", tmp_path)
        assert result is None

"""Tests for calendar sync."""
import json

import yaml

from recap.daemon.calendar.sync import (
    CalendarEvent,
    write_calendar_note,
    should_update_note,
    update_calendar_note,
    find_note_by_event_id,
)
from recap.daemon.config import OrgConfig


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
        org = OrgConfig(name="disbursecloud", subfolder="_Recap/Disbursecloud")
        path = write_calendar_note(event, tmp_path, org)
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
        org = OrgConfig(name="disbursecloud", subfolder="_Recap/Disbursecloud")
        path = write_calendar_note(event, tmp_path, org)
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
        org = OrgConfig(name="disbursecloud", subfolder="_Recap/Disbursecloud")
        path = write_calendar_note(event, tmp_path, org)
        content = path.read_text()
        assert "pipeline-status: pending" in content


def test_write_calendar_note_uses_configured_subfolder(tmp_path):
    from recap.daemon.calendar.sync import CalendarEvent, write_calendar_note
    from recap.daemon.config import OrgConfig

    org = OrgConfig(name="disbursecloud", subfolder="Clients/Disbursecloud")
    event = CalendarEvent(
        event_id="evt-1",
        title="Meeting",
        date="2026-04-14",
        time="14:00-15:00",
        participants=["Alice"],
        calendar_source="google",
        org="disbursecloud",  # still the slug — frontmatter identity
        meeting_link="https://meet.google.com/x",
        description="",
    )

    note_path = write_calendar_note(event, tmp_path, org)
    assert note_path == tmp_path / "Clients/Disbursecloud/Meetings/2026-04-14 - meeting.md"
    assert note_path.exists()


def test_write_calendar_note_frontmatter_org_is_slug_not_subfolder(tmp_path):
    import yaml
    from recap.daemon.calendar.sync import CalendarEvent, write_calendar_note
    from recap.daemon.config import OrgConfig

    org = OrgConfig(name="disbursecloud", subfolder="Clients/Disbursecloud")
    event = CalendarEvent(
        event_id="evt-1", title="X", date="2026-04-14", time="09:00-10:00",
        participants=[], calendar_source="google", org="disbursecloud",
        meeting_link="", description="",
    )
    note_path = write_calendar_note(event, tmp_path, org)
    content = note_path.read_text(encoding="utf-8")
    _, fm_block, _ = content.split("---\n", 2)
    fm = yaml.safe_load(fm_block)
    assert fm["org"] == "disbursecloud"  # slug, not the folder path
    assert fm["org-subfolder"] == "Clients/Disbursecloud"  # filesystem location


class TestShouldUpdateNote:
    def test_new_event_returns_create(self, tmp_path):
        org = OrgConfig(name="disbursecloud", subfolder="_Recap/Disbursecloud")
        result = should_update_note(
            event_id="new-event",
            vault_path=tmp_path,
            org_config=org,
        )
        assert result == "create"

    def test_existing_unchanged_returns_skip(self, tmp_path):
        # Create a note with event-id
        meetings_dir = tmp_path / "_Recap" / "Disbursecloud" / "Meetings"
        meetings_dir.mkdir(parents=True)
        note = meetings_dir / "2026-04-14 - test.md"
        note.write_text('---\nevent-id: "abc"\ntime: "10:00-11:00"\nparticipants: []\n---\n')
        org = OrgConfig(name="disbursecloud", subfolder="_Recap/Disbursecloud")
        result = should_update_note(
            event_id="abc",
            vault_path=tmp_path,
            org_config=org,
            new_time="10:00-11:00",
        )
        assert result == "skip"

    def test_changed_time_returns_update(self, tmp_path):
        meetings_dir = tmp_path / "_Recap" / "Disbursecloud" / "Meetings"
        meetings_dir.mkdir(parents=True)
        note = meetings_dir / "2026-04-14 - test.md"
        note.write_text('---\nevent-id: "abc"\ntime: "10:00-11:00"\nparticipants: []\n---\n')
        org = OrgConfig(name="disbursecloud", subfolder="_Recap/Disbursecloud")
        result = should_update_note(
            event_id="abc",
            vault_path=tmp_path,
            org_config=org,
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
        org = OrgConfig(name="disbursecloud", subfolder="_Recap/Disbursecloud")
        result = should_update_note(
            event_id="abc",
            vault_path=tmp_path,
            org_config=org,
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
        org = OrgConfig(name="disbursecloud", subfolder="_Recap/Disbursecloud")
        result = should_update_note(
            event_id="abc",
            vault_path=tmp_path,
            org_config=org,
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

    def test_backfills_org_subfolder_on_pre_canonical_note(self, tmp_path):
        """Notes written before the canonical shape get org-subfolder filled in on update."""
        note = tmp_path / "2026-04-14 - test.md"
        note.write_text(
            '---\nevent-id: "abc"\ndate: "2026-04-14"\n'
            'time: "10:00-11:00"\nparticipants: []\norg: "disbursecloud"\n---\nBody\n'
        )
        org = OrgConfig(name="disbursecloud", subfolder="Clients/Disbursecloud")

        update_calendar_note(note, new_time="10:00-11:30", org_config=org)

        _, fm_block, _ = note.read_text(encoding="utf-8").split("---\n", 2)
        fm = yaml.safe_load(fm_block)
        assert fm["org-subfolder"] == "Clients/Disbursecloud"

    def test_does_not_overwrite_existing_org_subfolder(self, tmp_path):
        """Backfill only fills missing keys; existing values stay intact."""
        note = tmp_path / "2026-04-14 - test.md"
        note.write_text(
            '---\nevent-id: "abc"\ndate: "2026-04-14"\n'
            'time: "10:00-11:00"\nparticipants: []\norg: "disbursecloud"\n'
            'org-subfolder: "legacy/path"\n---\nBody\n'
        )
        org = OrgConfig(name="disbursecloud", subfolder="Clients/Disbursecloud")

        update_calendar_note(note, new_time="10:00-11:30", org_config=org)

        _, fm_block, _ = note.read_text(encoding="utf-8").split("---\n", 2)
        fm = yaml.safe_load(fm_block)
        assert fm["org-subfolder"] == "legacy/path"


class TestFindNoteByEventId:
    def test_finds_note(self, tmp_path):
        note = tmp_path / "test.md"
        note.write_text('---\nevent-id: "abc123"\n---\nContent')
        result = find_note_by_event_id("abc123", tmp_path)
        assert result == note

    def test_returns_none_when_not_found(self, tmp_path):
        result = find_note_by_event_id("nonexistent", tmp_path)
        assert result is None


def test_write_calendar_note_adds_to_index_when_provided(tmp_path):
    from recap.daemon.calendar.index import EventIndex
    from recap.daemon.calendar.sync import CalendarEvent, write_calendar_note
    from recap.daemon.config import OrgConfig

    org = OrgConfig(name="d", subfolder="Clients/D")
    event = CalendarEvent(
        event_id="evt-1", title="M", date="2026-04-14", time="09:00-10:00",
        participants=[], calendar_source="google", org="d",
        meeting_link="", description="",
    )
    index = EventIndex(tmp_path / "_Recap" / ".recap" / "event-index.json")
    note_path = write_calendar_note(event, tmp_path, org, event_index=index)

    entry = index.lookup("evt-1")
    assert entry is not None
    # entry.path is PurePosixPath, note_path is concrete Path; compare via str:
    assert str(entry.path) == str(note_path.relative_to(tmp_path)).replace("\\", "/")


def test_find_note_by_event_id_uses_index_when_provided(tmp_path):
    from recap.daemon.calendar.index import EventIndex
    from recap.daemon.calendar.sync import find_note_by_event_id

    vault = tmp_path
    meetings = vault / "Clients/D/Meetings"
    meetings.mkdir(parents=True)
    note = meetings / "2026-04-14 - x.md"
    note.write_text("---\nevent-id: evt-1\n---\n\nbody\n", encoding="utf-8")

    index = EventIndex(vault / "_Recap" / ".recap" / "event-index.json")
    index.add("evt-1", note.relative_to(vault), "d")

    result = find_note_by_event_id("evt-1", meetings, vault_path=vault, event_index=index)
    assert result == note


def test_find_note_by_event_id_falls_back_to_scan_without_index(tmp_path):
    from recap.daemon.calendar.sync import find_note_by_event_id

    meetings = tmp_path / "Meetings"
    meetings.mkdir()
    note = meetings / "2026-04-14 - a.md"
    note.write_text("---\nevent-id: evt-1\n---\n\nbody\n", encoding="utf-8")

    # No index → falls back to O(n) scan
    result = find_note_by_event_id("evt-1", meetings)
    assert result == note


def test_should_update_note_uses_event_index_when_provided(tmp_path):
    """should_update_note's internal lookup uses the index for O(1).

    We put the note at a path that meetings_dir.glob("*.md") cannot find
    (a subdir inside Meetings) so only the index can resolve the event-id
    to the note. If should_update_note returns "skip" (matching state),
    that proves the index was what answered the lookup.
    """
    from recap.daemon.calendar.index import EventIndex
    from recap.daemon.calendar.sync import should_update_note
    from recap.daemon.config import OrgConfig

    org = OrgConfig(name="d", subfolder="Clients/D")
    vault = tmp_path
    meetings = vault / "Clients/D/Meetings"
    meetings.mkdir(parents=True)
    # Place note in a subdir so the top-level *.md scan cannot find it.
    subdir = meetings / "archive"
    subdir.mkdir()
    note = subdir / "2026-04-14 - x.md"
    note.write_text(
        "---\nevent-id: evt-1\ndate: 2026-04-14\ntime: 09:00-10:00\n"
        "participants: []\n---\n\nbody\n",
        encoding="utf-8",
    )

    index = EventIndex(vault / "_Recap" / ".recap" / "event-index.json")
    index.add("evt-1", note.relative_to(vault), "d")

    # Without the index, the scan would miss the note and return "create".
    # With the index, it resolves to the note and returns "skip" since the
    # time/participants match.
    action = should_update_note(
        "evt-1",
        vault,
        org,
        new_time="09:00-10:00",
        new_participants=[],
        event_index=index,
    )
    assert action == "skip"

    # Sanity: without the index, the same call returns "create"
    # because the scan cannot find the note in the subdir.
    action_no_index = should_update_note(
        "evt-1",
        vault,
        org,
        new_time="09:00-10:00",
        new_participants=[],
    )
    assert action_no_index == "create"


def test_find_note_by_event_id_logs_warning_on_stale_entry(tmp_path, caplog):
    import logging
    import pathlib
    from recap.daemon.calendar.index import EventIndex
    from recap.daemon.calendar.sync import find_note_by_event_id

    vault = tmp_path
    meetings = vault / "Clients/D/Meetings"
    meetings.mkdir(parents=True)
    # Index points at a note that never existed
    index = EventIndex(vault / "_Recap" / ".recap" / "event-index.json")
    index.add("evt-1", pathlib.Path("Clients/D/Meetings/gone.md"), "d")

    with caplog.at_level(logging.WARNING, logger="recap.daemon.calendar.sync"):
        result = find_note_by_event_id(
            "evt-1", meetings, vault_path=vault, event_index=index,
        )
    assert result is None
    assert any("Stale EventIndex entry" in rec.message for rec in caplog.records)


def test_find_note_by_event_id_heals_stale_entry_when_scan_finds(tmp_path):
    """Self-healing: stale index entry gets updated when scan finds the note."""
    from recap.daemon.calendar.index import EventIndex
    from recap.daemon.calendar.sync import find_note_by_event_id
    import pathlib

    vault = tmp_path
    meetings = vault / "Clients/D/Meetings"
    meetings.mkdir(parents=True)
    # Note exists at "moved.md", but index points to "stale.md"
    moved = meetings / "moved.md"
    moved.write_text("---\nevent-id: evt-1\n---\n\nbody\n", encoding="utf-8")

    index = EventIndex(vault / "_Recap" / ".recap" / "event-index.json")
    index.add("evt-1", pathlib.Path("Clients/D/Meetings/stale.md"), "d")

    result = find_note_by_event_id(
        "evt-1", meetings, vault_path=vault, event_index=index,
    )
    assert result == moved
    # Index should now point to moved.md, preserving org="d"
    entry = index.lookup("evt-1")
    assert entry is not None
    assert str(entry.path) == "Clients/D/Meetings/moved.md"
    assert entry.org == "d"


def test_find_note_by_event_id_removes_stale_entry_when_scan_misses(tmp_path):
    """Self-healing: stale index entry gets removed when scan also fails."""
    from recap.daemon.calendar.index import EventIndex
    from recap.daemon.calendar.sync import find_note_by_event_id
    import pathlib

    vault = tmp_path
    meetings = vault / "Clients/D/Meetings"
    meetings.mkdir(parents=True)
    # No notes on disk at all

    index = EventIndex(vault / "_Recap" / ".recap" / "event-index.json")
    index.add("evt-1", pathlib.Path("Clients/D/Meetings/gone.md"), "d")

    result = find_note_by_event_id(
        "evt-1", meetings, vault_path=vault, event_index=index,
    )
    assert result is None
    # Stale entry should be evicted
    assert index.lookup("evt-1") is None

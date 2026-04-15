"""Tests for the event-id index."""
from __future__ import annotations

import json
import pathlib

from recap.daemon.calendar.index import EventIndex


def _make_index(tmp_path: pathlib.Path) -> EventIndex:
    return EventIndex(tmp_path / "_Recap" / ".recap" / "event-index.json")


class TestEventIndexAddLookup:
    def test_add_then_lookup_returns_stored_entry(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.add("evt-1", pathlib.Path("Clients/Disbursecloud/Meetings/2026-04-14 - q2.md"), "disbursecloud")
        entry = idx.lookup("evt-1")
        assert entry is not None
        assert entry.path == pathlib.PurePosixPath("Clients/Disbursecloud/Meetings/2026-04-14 - q2.md")
        assert entry.org == "disbursecloud"

    def test_lookup_missing_returns_none(self, tmp_path):
        idx = _make_index(tmp_path)
        assert idx.lookup("nope") is None

    def test_add_overwrites_existing_entry(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.add("evt-1", pathlib.Path("old.md"), "o")
        idx.add("evt-1", pathlib.Path("new.md"), "o")
        assert idx.lookup("evt-1").path == pathlib.PurePosixPath("new.md")


class TestEventIndexRemoveRename:
    def test_remove_deletes_entry(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.add("evt-1", pathlib.Path("x.md"), "o")
        idx.remove("evt-1")
        assert idx.lookup("evt-1") is None

    def test_remove_nonexistent_is_noop(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.remove("evt-1")  # must not raise

    def test_rename_updates_path(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.add("evt-1", pathlib.Path("old.md"), "o")
        idx.rename("evt-1", pathlib.Path("new.md"))
        assert idx.lookup("evt-1").path == pathlib.PurePosixPath("new.md")

    def test_rename_nonexistent_is_noop(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.rename("evt-1", pathlib.Path("x.md"))  # must not raise
        assert idx.lookup("evt-1") is None


class TestEventIndexPersistence:
    def test_add_persists_to_disk(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.add("evt-1", pathlib.Path("x.md"), "o")
        index_file = tmp_path / "_Recap" / ".recap" / "event-index.json"
        assert index_file.exists()
        data = json.loads(index_file.read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert "evt-1" in data["entries"]
        assert data["entries"]["evt-1"]["path"] == "x.md"
        assert data["entries"]["evt-1"]["org"] == "o"
        assert "mtime" in data["entries"]["evt-1"]

    def test_new_instance_reads_persisted_index(self, tmp_path):
        idx1 = _make_index(tmp_path)
        idx1.add("evt-1", pathlib.Path("x.md"), "o")
        # Fresh instance pointed at the same file
        idx2 = _make_index(tmp_path)
        assert idx2.lookup("evt-1") is not None

    def test_persisted_path_uses_forward_slashes_on_disk(self, tmp_path):
        """Persisted paths use forward slashes regardless of input separator."""
        idx = _make_index(tmp_path)
        # Pass a Path that on Windows might use backslashes internally
        idx.add("evt-1", pathlib.Path("Clients/D/Meetings/2026-04-14 - q.md"), "d")
        index_file = tmp_path / "_Recap" / ".recap" / "event-index.json"
        data = json.loads(index_file.read_text(encoding="utf-8"))
        assert data["entries"]["evt-1"]["path"] == "Clients/D/Meetings/2026-04-14 - q.md"

    def test_path_round_trips_as_forward_slash_after_reload(self, tmp_path):
        """Regression: persisted paths must reload as forward-slash form on every OS."""
        idx1 = _make_index(tmp_path)
        idx1.add("evt-1", pathlib.Path("Clients/D/Meetings/2026-04-14 - q.md"), "d")
        # Fresh instance reads from disk
        idx2 = _make_index(tmp_path)
        entry = idx2.lookup("evt-1")
        assert entry is not None
        assert str(entry.path) == "Clients/D/Meetings/2026-04-14 - q.md"


class TestEventIndexRebuild:
    def test_rebuild_scans_vault_and_populates_entries(self, tmp_path):
        # Arrange: calendar-seeded notes on disk
        meetings = tmp_path / "Clients/Disbursecloud/Meetings"
        meetings.mkdir(parents=True)
        (meetings / "2026-04-14 - a.md").write_text(
            "---\nevent-id: evt-a\norg: disbursecloud\n---\n\n## Agenda\n", encoding="utf-8"
        )
        (meetings / "2026-04-15 - b.md").write_text(
            "---\nevent-id: evt-b\norg: disbursecloud\n---\n\n## Agenda\n", encoding="utf-8"
        )
        # A note without event-id — should be skipped
        (meetings / "2026-04-16 - adhoc.md").write_text(
            "---\ntitle: adhoc\n---\n\nbody\n", encoding="utf-8"
        )

        idx = _make_index(tmp_path)
        idx.rebuild(tmp_path)

        assert idx.lookup("evt-a") is not None
        assert idx.lookup("evt-a").path == pathlib.PurePosixPath("Clients/Disbursecloud/Meetings/2026-04-14 - a.md")
        assert idx.lookup("evt-b") is not None
        # Note without event-id is not indexed
        assert len([e for e in idx.all_entries() if e.event_id == "adhoc"]) == 0

    def test_rebuild_replaces_stale_entries(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.add("evt-stale", pathlib.Path("nonexistent.md"), "o")
        # No notes on disk → rebuild should drop the stale entry
        idx.rebuild(tmp_path)
        assert idx.lookup("evt-stale") is None

    def test_all_entries_returns_list(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.add("evt-1", pathlib.Path("a.md"), "o")
        idx.add("evt-2", pathlib.Path("b.md"), "o")
        entries = idx.all_entries()
        assert {e.event_id for e in entries} == {"evt-1", "evt-2"}


class TestEventIndexLoadResilience:
    def test_load_with_unknown_schema_version_is_empty_with_warning(self, tmp_path, caplog):
        import logging
        idx_path = tmp_path / "_Recap" / ".recap" / "event-index.json"
        idx_path.parent.mkdir(parents=True)
        idx_path.write_text(
            json.dumps({"version": 99, "entries": {"e": {"path": "x.md", "org": "o", "mtime": ""}}}),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="recap.daemon.calendar.index"):
            idx = EventIndex(idx_path)
        assert idx.all_entries() == []
        assert any("schema version" in rec.message.lower() for rec in caplog.records)

    def test_load_with_corrupt_json_is_empty_with_warning(self, tmp_path, caplog):
        import logging
        idx_path = tmp_path / "_Recap" / ".recap" / "event-index.json"
        idx_path.parent.mkdir(parents=True)
        idx_path.write_text("not json{{", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="recap.daemon.calendar.index"):
            idx = EventIndex(idx_path)
        assert idx.all_entries() == []
        assert any("could not load" in rec.message.lower() for rec in caplog.records)


class TestEdgeCases:
    """Phase 6: corruption recovery and concurrent-modification safety."""

    def test_corrupt_file_then_rebuild_recovers(self, tmp_path):
        """A corrupt on-disk index can be rebuilt from the vault."""
        index_path = tmp_path / "_Recap" / ".recap" / "event-index.json"
        index_path.parent.mkdir(parents=True)
        index_path.write_text("{this is not valid json", encoding="utf-8")

        idx = EventIndex(index_path)
        assert idx.all_entries() == []  # corrupt load -> empty start

        # Seed a vault note with a known event_id frontmatter.
        vault = tmp_path / "vault"
        meetings = vault / "Clients" / "Alpha" / "Meetings"
        meetings.mkdir(parents=True)
        note = meetings / "2026-04-15-test.md"
        note.write_text(
            "---\n"
            "event-id: evt-rebuild-1\n"
            "org: alpha\n"
            "title: Rebuild test\n"
            "---\n",
            encoding="utf-8",
        )

        idx.rebuild(vault)
        entries = idx.all_entries()
        assert len(entries) == 1
        assert entries[0].event_id == "evt-rebuild-1"
        # The rebuild must have refreshed the persisted file too,
        # with the correct path and org from the note frontmatter.
        from_disk = EventIndex(index_path)
        assert len(from_disk.all_entries()) == 1
        reloaded = from_disk.lookup("evt-rebuild-1")
        assert reloaded is not None
        assert str(reloaded.path) == "Clients/Alpha/Meetings/2026-04-15-test.md"
        assert reloaded.org == "alpha"

    def test_concurrent_add_and_remove_eventually_consistent(self, tmp_path):
        """Two EventIndex instances mutating the same file end in a
        consistent state after both call _persist_locked in sequence.

        Not a true concurrency test (no threads); documents that a second
        instance auto-loads the first's snapshot on construction, so its
        subsequent write preserves the earlier entry (last-writer-wins
        with full-state persistence).
        """
        index_path = tmp_path / "_Recap" / ".recap" / "event-index.json"

        a = EventIndex(index_path)
        a.add("evt-A", pathlib.Path("Clients/Alpha/Meetings/a.md"), "alpha")

        # A second instance auto-loads on construction, so it observes
        # evt-A before adding its own entry.
        b = EventIndex(index_path)
        b.add("evt-B", pathlib.Path("Clients/Alpha/Meetings/b.md"), "alpha")

        # Reload from disk: b's persist wrote both entries because b
        # read a's snapshot on construction.
        c = EventIndex(index_path)
        assert c.lookup("evt-B") is not None
        assert c.lookup("evt-B").path == pathlib.PurePosixPath("Clients/Alpha/Meetings/b.md")
        # Document actual behavior: full-state persistence preserves evt-A
        # because instance b loaded it before its own add().
        assert c.lookup("evt-A") is not None

    def test_empty_file_loads_as_empty_index(self, tmp_path):
        """An empty (zero-byte) index file is treated as a fresh start."""
        index_path = tmp_path / "_Recap" / ".recap" / "event-index.json"
        index_path.parent.mkdir(parents=True)
        index_path.write_text("", encoding="utf-8")

        idx = EventIndex(index_path)
        assert idx.all_entries() == []

    def test_partial_write_truncated_json_recovers(self, tmp_path):
        """A truncated write (e.g. crash mid-_save) doesn't crash the loader."""
        index_path = tmp_path / "_Recap" / ".recap" / "event-index.json"
        # First write a valid index.
        idx = EventIndex(index_path)
        idx.add("evt-1", pathlib.Path("Clients/Alpha/Meetings/one.md"), "alpha")
        idx.add("evt-2", pathlib.Path("Clients/Alpha/Meetings/two.md"), "alpha")

        # Truncate to half its bytes to simulate a partial fsync.
        contents = index_path.read_bytes()
        index_path.write_bytes(contents[: len(contents) // 2])

        # New instance loads: corrupt -> empty per existing
        # warn-and-continue policy.
        recovered = EventIndex(index_path)
        assert recovered.all_entries() == []

    def test_rebuild_is_idempotent(self, tmp_path):
        """Calling rebuild twice in a row produces the same entries."""
        vault = tmp_path / "vault"
        meetings = vault / "Clients" / "Alpha" / "Meetings"
        meetings.mkdir(parents=True)
        (meetings / "n.md").write_text(
            "---\nevent-id: evt-1\norg: alpha\n---\n", encoding="utf-8",
        )

        idx = EventIndex(tmp_path / "_Recap" / ".recap" / "event-index.json")
        idx.rebuild(vault)
        first = idx.all_entries()
        idx.rebuild(vault)
        second = idx.all_entries()
        # Compare by (event_id, path, org) since mtime is a wall-clock
        # string captured from the file's stat at scan time.
        first_keys = {(e.event_id, str(e.path), e.org) for e in first}
        second_keys = {(e.event_id, str(e.path), e.org) for e in second}
        assert first_keys == second_keys

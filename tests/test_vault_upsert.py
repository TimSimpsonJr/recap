"""Tests for upsert_note across the four cases from design doc §0.1."""
from __future__ import annotations

import pathlib

import yaml

from recap.vault import MEETING_RECORD_MARKER, upsert_note


class TestUpsertCase1NewNote:
    def test_creates_note_with_frontmatter_marker_and_body(self, tmp_path: pathlib.Path):
        note_path = tmp_path / "new.md"
        frontmatter = {
            "date": "2026-04-14",
            "title": "New Meeting",
            "org": "test",
            "pipeline-status": "complete",
        }
        body = "## Summary\n\nIt went well.\n"

        upsert_note(note_path, frontmatter, body)

        assert note_path.exists()
        content = note_path.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        _, fm_block, rest = content.split("---\n", 2)
        fm = yaml.safe_load(fm_block)
        assert fm["title"] == "New Meeting"
        assert fm["pipeline-status"] == "complete"
        assert MEETING_RECORD_MARKER in rest
        assert "It went well." in rest


class TestUpsertCase2BareExistingNote:
    def test_prepends_frontmatter_and_appends_marker_plus_body(self, tmp_path: pathlib.Path):
        note_path = tmp_path / "bare.md"
        note_path.write_text("Some pre-existing notes\nwritten by the user.\n", encoding="utf-8")

        frontmatter = {"date": "2026-04-14", "title": "Bare", "org": "test", "pipeline-status": "complete"}
        body = "## Summary\n\nAnalysis output.\n"

        upsert_note(note_path, frontmatter, body)

        content = note_path.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        _, fm_block, rest = content.split("---\n", 2)
        fm = yaml.safe_load(fm_block)
        assert fm["title"] == "Bare"

        # Original user content preserved above the marker
        assert "Some pre-existing notes" in rest
        assert "written by the user." in rest

        # Marker + body present
        assert MEETING_RECORD_MARKER in rest
        marker_idx = rest.index(MEETING_RECORD_MARKER)
        assert "Some pre-existing notes" in rest[:marker_idx]
        assert "Analysis output." in rest[marker_idx:]


class TestUpsertCase3CalendarSeeded:
    def test_merges_frontmatter_preserving_calendar_keys_and_appends_marker(self, tmp_path: pathlib.Path):
        note_path = tmp_path / "calendar.md"
        # Simulate what calendar sync writes
        calendar_content = (
            "---\n"
            "date: 2026-04-14\n"
            "time: 14:00-15:00\n"
            "title: Q2 Review\n"
            "participants:\n"
            "- '[[Alice]]'\n"
            "- '[[Bob]]'\n"
            "calendar-source: google\n"
            "org: disbursecloud\n"
            "meeting-link: https://meet.google.com/abc\n"
            "event-id: evt-123\n"
            "pipeline-status: pending\n"
            "---\n"
            "\n"
            "## Agenda\n\nDiscuss Q2 targets.\n"
        )
        note_path.write_text(calendar_content, encoding="utf-8")

        canonical = {
            "date": "2026-04-14",
            "title": "Q2 Review",
            "org": "disbursecloud",
            "org-subfolder": "Clients/Disbursecloud",
            "platform": "google_meet",
            "participants": ["[[Alice]]", "[[Bob]]"],
            "companies": ["[[Acme]]"],
            "duration": "1h 12m",
            "type": "quarterly_review",
            "tags": ["meeting/quarterly_review"],
            "pipeline-status": "complete",
            "recording": "2026-04-14-140000-disbursecloud.m4a",
        }
        body = "## Summary\n\nGreat meeting.\n"

        upsert_note(note_path, canonical, body)

        content = note_path.read_text(encoding="utf-8")
        _, fm_block, rest = content.split("---\n", 2)
        fm = yaml.safe_load(fm_block)

        # Calendar keys preserved
        assert fm["time"] == "14:00-15:00"
        assert fm["calendar-source"] == "google"
        assert fm["meeting-link"] == "https://meet.google.com/abc"
        assert fm["event-id"] == "evt-123"

        # Pipeline keys authoritative
        assert fm["pipeline-status"] == "complete"
        assert fm["duration"] == "1h 12m"
        assert fm["type"] == "quarterly_review"
        assert fm["tags"] == ["meeting/quarterly_review"]
        assert fm["companies"] == ["[[Acme]]"]
        assert fm["recording"] == "2026-04-14-140000-disbursecloud.m4a"

        # Shared keys from canonical (slug, not path)
        assert fm["org"] == "disbursecloud"
        assert fm["org-subfolder"] == "Clients/Disbursecloud"
        assert fm["platform"] == "google_meet"

        # Agenda preserved above marker, body below
        assert "## Agenda" in rest
        assert "Discuss Q2 targets." in rest
        marker_idx = rest.index(MEETING_RECORD_MARKER)
        assert "## Agenda" in rest[:marker_idx]
        assert "Great meeting." in rest[marker_idx:]

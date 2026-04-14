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

"""Tests for Teams metadata enrichment."""
from unittest.mock import patch
from recap.daemon.config import KnownContact
from recap.daemon.recorder.enrichment import (
    match_known_contacts,
    enrich_meeting_metadata,
)


class TestKnownContactMatching:
    def test_matches_exact_display_name(self):
        contacts = [
            KnownContact(name="Jane Smith", display_name="Jane Smith"),
            KnownContact(name="Bob Lee", display_name="Bob L."),
        ]
        result = match_known_contacts(["Jane Smith", "Bob L."], contacts)
        assert result == ["Jane Smith", "Bob Lee"]

    def test_returns_original_for_no_match(self):
        contacts = [
            KnownContact(name="Jane Smith", display_name="Jane Smith"),
        ]
        result = match_known_contacts(["Unknown Person"], contacts)
        assert result == ["Unknown Person"]

    def test_empty_contacts_returns_originals(self):
        result = match_known_contacts(["Alice", "Bob"], [])
        assert result == ["Alice", "Bob"]

    def test_case_insensitive(self):
        contacts = [KnownContact(name="Jane Smith", display_name="jane smith")]
        result = match_known_contacts(["Jane Smith"], contacts)
        assert result == ["Jane Smith"]  # returns canonical name

    def test_empty_display_names(self):
        contacts = [KnownContact(name="Jane", display_name="Jane")]
        result = match_known_contacts([], contacts)
        assert result == []


class TestEnrichMeetingMetadata:
    def test_teams_fallback_on_uia_failure(self):
        with patch("recap.daemon.recorder.enrichment.extract_teams_participants", return_value=None):
            result = enrich_meeting_metadata(
                hwnd=12345,
                title="Sprint Planning | Microsoft Teams",
                platform="teams",
                known_contacts=[],
            )
        assert result["title"] == "Sprint Planning"
        assert result["participants"] == []
        assert result["platform"] == "teams"

    def test_teams_with_uia_success(self):
        with patch("recap.daemon.recorder.enrichment.extract_teams_participants", return_value=["Jane Smith", "Bob L."]):
            result = enrich_meeting_metadata(
                hwnd=12345,
                title="Sprint Planning | Microsoft Teams",
                platform="teams",
                known_contacts=[KnownContact(name="Bob Lee", display_name="Bob L.")],
            )
        assert result["title"] == "Sprint Planning"
        assert "Jane Smith" in result["participants"]
        assert "Bob Lee" in result["participants"]  # matched from known contacts

    def test_zoom_parses_title(self):
        result = enrich_meeting_metadata(
            hwnd=1,
            title="Zoom Meeting",
            platform="zoom",
            known_contacts=[],
        )
        assert result["platform"] == "zoom"
        assert result["title"] == "Zoom Meeting"

    def test_signal_parses_title(self):
        result = enrich_meeting_metadata(
            hwnd=1,
            title="Signal",
            platform="signal",
            known_contacts=[],
        )
        assert result["platform"] == "signal"

    def test_teams_title_parsing_strips_suffix(self):
        with patch("recap.daemon.recorder.enrichment.extract_teams_participants", return_value=None):
            result = enrich_meeting_metadata(
                hwnd=1,
                title="Call with Jane | Microsoft Teams",
                platform="teams",
                known_contacts=[],
            )
        assert result["title"] == "Call with Jane"

"""Tests for Teams metadata enrichment."""
from unittest.mock import patch
from recap.daemon.config import KnownContact
from recap.daemon.recorder.enrichment import (
    match_known_contacts,
    enrich_meeting_metadata,
)
from recap.models import Participant


class TestKnownContactMatching:
    def test_matches_exact_display_name(self):
        contacts = [
            KnownContact(name="Jane Smith", display_name="Jane Smith"),
            KnownContact(name="Bob Lee", display_name="Bob L."),
        ]
        observed = [Participant(name="Jane Smith"), Participant(name="Bob L.")]
        result = match_known_contacts(observed, contacts)
        assert [p.name for p in result] == ["Jane Smith", "Bob Lee"]

    def test_returns_original_for_no_match(self):
        contacts = [
            KnownContact(name="Jane Smith", display_name="Jane Smith"),
        ]
        result = match_known_contacts([Participant(name="Unknown Person")], contacts)
        assert [p.name for p in result] == ["Unknown Person"]

    def test_empty_contacts_returns_originals(self):
        observed = [Participant(name="Alice"), Participant(name="Bob")]
        result = match_known_contacts(observed, [])
        assert [p.name for p in result] == ["Alice", "Bob"]

    def test_case_insensitive(self):
        contacts = [KnownContact(name="Jane Smith", display_name="jane smith")]
        result = match_known_contacts([Participant(name="Jane Smith")], contacts)
        assert [p.name for p in result] == ["Jane Smith"]  # returns canonical name

    def test_empty_display_names(self):
        contacts = [KnownContact(name="Jane", display_name="Jane")]
        result = match_known_contacts([], contacts)
        assert result == []


class TestMatchKnownContactsEmailFirst:
    def test_email_match_wins_over_name(self):
        contacts = [
            KnownContact(name="Alice Smith", display_name="Alice Smith",
                         email="alice@x.com"),
            KnownContact(name="Bob", display_name="Bob"),
        ]
        observed = [Participant(name="Bob", email="alice@x.com")]
        result = match_known_contacts(observed, contacts)
        assert result[0].name == "Alice Smith"

    def test_case_insensitive_email_match(self):
        contacts = [KnownContact(name="Alice", display_name="Alice",
                                 email="ALICE@X.COM")]
        observed = [Participant(name="nobody", email="alice@x.com")]
        result = match_known_contacts(observed, contacts)
        assert result[0].name == "Alice"


class TestMatchKnownContactsAliases:
    def test_alias_match_returns_canonical_name(self):
        contacts = [KnownContact(
            name="Sean Mooney", display_name="Sean Mooney",
            aliases=["Sean M.", "Sean"],
        )]
        observed = [Participant(name="Sean M.", email=None)]
        result = match_known_contacts(observed, contacts)
        assert result[0].name == "Sean Mooney"

    def test_normalized_alias_match(self):
        """Alias matching uses _normalize (casefold + strip + collapse)."""
        contacts = [KnownContact(
            name="Sean Mooney", display_name="Sean Mooney",
            aliases=["Sean M."],
        )]
        observed = [Participant(name="sean m", email=None)]  # no period, lowercase
        result = match_known_contacts(observed, contacts)
        assert result[0].name == "Sean Mooney"

    def test_empty_alias_does_not_match_empty_input(self):
        """Empty fields must be skipped when building the lookup index."""
        contacts = [KnownContact(
            name="Alice", display_name="Alice",
            aliases=["", "   "],  # garbage entries
        )]
        observed = [Participant(name="", email=None)]
        result = match_known_contacts(observed, contacts)
        # No false match on empty string.
        assert result[0].name == ""


class TestMatchKnownContactsPassthrough:
    def test_no_match_returns_unchanged(self):
        observed = [Participant(name="Unknown", email=None)]
        result = match_known_contacts(observed, [])
        assert result[0].name == "Unknown"

    def test_preserves_email_from_observed_when_match_has_none(self):
        contacts = [KnownContact(name="Alice", display_name="Alice")]
        observed = [Participant(name="Alice", email="alice@x.com")]
        result = match_known_contacts(observed, contacts)
        assert result[0].email == "alice@x.com"

    def test_preserves_email_from_contact_when_observed_has_none(self):
        contacts = [KnownContact(name="Alice", display_name="Alice", email="alice@x.com")]
        observed = [Participant(name="Alice", email=None)]
        result = match_known_contacts(observed, contacts)
        assert result[0].email == "alice@x.com"


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

"""Tests for shared identity helpers used by first-pass relabel,
reprocess participant union, and correction eligibility."""
from __future__ import annotations

import pytest

from recap.identity import _is_eligible_person_label, _normalize


class TestNormalize:
    def test_casefold(self):
        assert _normalize("Alice") == "alice"

    def test_strip_whitespace(self):
        assert _normalize("  Alice  ") == "alice"

    def test_collapse_internal_whitespace(self):
        assert _normalize("Sean  Mooney") == "sean mooney"

    def test_strip_periods_and_commas(self):
        assert _normalize("Sean M.") == "sean m"
        assert _normalize("Smith, John") == "smith john"
        assert _normalize("J.D.") == "jd"

    def test_empty_input_returns_empty(self):
        assert _normalize("") == ""
        assert _normalize("   ") == ""


class TestIsEligiblePersonLabel:
    def test_plain_name_eligible(self):
        assert _is_eligible_person_label("Sean Mooney") is True

    def test_speaker_xx_ineligible(self):
        assert _is_eligible_person_label("SPEAKER_00") is False
        assert _is_eligible_person_label("SPEAKER_12") is False

    def test_unknown_ineligible(self):
        assert _is_eligible_person_label("UNKNOWN") is False
        assert _is_eligible_person_label("Unknown Speaker 1") is False
        assert _is_eligible_person_label("unknown speaker 3") is False

    def test_parenthetical_ineligible(self):
        assert _is_eligible_person_label("Sean (development team)") is False

    def test_empty_ineligible(self):
        assert _is_eligible_person_label("") is False
        assert _is_eligible_person_label("   ") is False

    def test_initials_eligible(self):
        assert _is_eligible_person_label("Sean M.") is True

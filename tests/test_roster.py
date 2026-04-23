"""Tests for ParticipantRoster accumulator."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from recap.daemon.recorder.roster import ParticipantRoster


def _now_tz() -> datetime:
    return datetime.now(timezone.utc)


class TestMerge:
    def test_empty_merge_returns_false(self):
        r = ParticipantRoster()
        assert r.merge("src", [], _now_tz()) is False
        assert r.current() == []

    def test_first_merge_returns_true_and_preserves_order(self):
        r = ParticipantRoster()
        assert r.merge("src", ["Alice", "Bob", "Carol"], _now_tz()) is True
        assert r.current() == ["Alice", "Bob", "Carol"]

    def test_same_names_same_case_returns_false(self):
        r = ParticipantRoster()
        r.merge("src", ["Alice", "Bob"], _now_tz())
        assert r.merge("src", ["Alice", "Bob"], _now_tz()) is False
        assert r.current() == ["Alice", "Bob"]

    def test_same_names_different_case_returns_true_and_upgrades_display(self):
        r = ParticipantRoster()
        r.merge("src", ["alice"], _now_tz())
        assert r.merge("src", ["Alice"], _now_tz()) is True
        assert r.current() == ["Alice"]

    def test_new_names_appended_in_order(self):
        r = ParticipantRoster()
        r.merge("src", ["Alice"], _now_tz())
        assert r.merge("src", ["Bob"], _now_tz()) is True
        assert r.current() == ["Alice", "Bob"]

    def test_whitespace_only_names_skipped(self):
        r = ParticipantRoster()
        assert r.merge("src", ["", "   ", "\t", "Alice"], _now_tz()) is True
        assert r.current() == ["Alice"]

    def test_whitespace_stripped_on_valid_names(self):
        r = ParticipantRoster()
        r.merge("src", ["  Alice  "], _now_tz())
        assert r.current() == ["Alice"]

    def test_naive_datetime_raises_value_error(self):
        r = ParticipantRoster()
        with pytest.raises(ValueError, match="timezone-aware"):
            r.merge("src", ["Alice"], datetime(2026, 1, 1, 12, 0, 0))

    def test_last_merge_per_source_updated(self):
        r = ParticipantRoster()
        t1 = _now_tz()
        r.merge("teams_uia_detection", ["Alice"], t1)
        assert r._last_merge_per_source["teams_uia_detection"] == t1

    def test_multi_source_interleaving_preserves_first_seen_order(self):
        r = ParticipantRoster()
        r.merge("teams", ["Alice"], _now_tz())
        r.merge("zoom", ["Bob"], _now_tz())
        r.merge("teams", ["Carol"], _now_tz())
        assert r.current() == ["Alice", "Bob", "Carol"]


class TestReadSurface:
    def test_current_equals_finalize_in_v1(self):
        r = ParticipantRoster()
        r.merge("src", ["Alice", "Bob"], _now_tz())
        assert r.current() == r.finalize()

    def test_current_safe_to_call_on_empty_roster(self):
        assert ParticipantRoster().current() == []

    def test_finalize_safe_to_call_on_empty_roster(self):
        assert ParticipantRoster().finalize() == []

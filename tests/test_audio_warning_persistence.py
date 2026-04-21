"""Tests for audio-warning persistence to journal + sidecar."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from recap.daemon.recorder.audio import AudioCapture, _LoopbackEntry
from recap.daemon.recorder.audio_events import (
    EVT_AUDIO_NO_LOOPBACK_AT_START,
    EVT_AUDIO_NO_SYSTEM_AUDIO,
    EVT_AUDIO_ALL_LOOPBACKS_LOST,
    WARN_NO_SYSTEM_AUDIO_CAPTURED,
    WARN_SYSTEM_AUDIO_INTERRUPTED,
)


def _event_type_called(journal_mock, event_type: str) -> bool:
    return any(
        call.kwargs.get("event_type") == event_type
        for call in journal_mock.record.call_args_list
    )


def _make_entry(state: str, device_name: str = "Dev") -> _LoopbackEntry:
    s = MagicMock()
    s.is_terminal = False
    return _LoopbackEntry(
        stream=s, state=state, opened_at=0.0,
        last_active_at=(5.0 if state == "active" else None),
        device_name=device_name, missing_since=None,
    )


class TestScenarioAZeroEndpoints:
    def test_scenario_a_emits_journal_and_sidecar_warning(self, tmp_path):
        cap = AudioCapture(output_path=tmp_path / "test.flac")
        journal = MagicMock()
        cap._event_journal = journal

        cap._note_scenario_no_loopback_at_start()

        journal.record.assert_called_once()
        assert _event_type_called(journal, EVT_AUDIO_NO_LOOPBACK_AT_START)
        assert WARN_NO_SYSTEM_AUDIO_CAPTURED in cap._audio_warnings


class TestScenarioBNoActiveEverPromoted:
    def test_scenario_b_fires_once_when_last_probation_evicts(self, tmp_path):
        cap = AudioCapture(output_path=tmp_path / "test.flac")
        journal = MagicMock()
        cap._event_journal = journal
        cap._loopback_sources = {}
        cap._any_active_ever = False

        cap._note_scenario_no_system_audio_if_applicable()

        journal.record.assert_called_once()
        assert _event_type_called(journal, EVT_AUDIO_NO_SYSTEM_AUDIO)
        assert WARN_NO_SYSTEM_AUDIO_CAPTURED in cap._audio_warnings

    def test_scenario_b_does_not_fire_twice(self, tmp_path):
        cap = AudioCapture(output_path=tmp_path / "test.flac")
        journal = MagicMock()
        cap._event_journal = journal
        cap._loopback_sources = {}
        cap._any_active_ever = False

        cap._note_scenario_no_system_audio_if_applicable()
        cap._note_scenario_no_system_audio_if_applicable()

        assert journal.record.call_count == 1
        assert cap._audio_warnings.count(WARN_NO_SYSTEM_AUDIO_CAPTURED) == 1

    def test_scenario_b_does_not_fire_if_any_active_ever(self, tmp_path):
        cap = AudioCapture(output_path=tmp_path / "test.flac")
        journal = MagicMock()
        cap._event_journal = journal
        cap._loopback_sources = {}
        cap._any_active_ever = True

        cap._note_scenario_no_system_audio_if_applicable()

        journal.record.assert_not_called()
        assert WARN_NO_SYSTEM_AUDIO_CAPTURED not in cap._audio_warnings


class TestScenarioCAllLoopbacksLost:
    def test_scenario_c_fires_on_active_to_zero_transition(self, tmp_path):
        cap = AudioCapture(output_path=tmp_path / "test.flac")
        journal = MagicMock()
        cap._event_journal = journal
        cap._loopback_sources = {}  # just dropped from 1 to 0
        cap._any_active_ever = True
        cap._active_count_was_nonzero = True

        cap._note_scenario_all_loopbacks_lost_if_applicable()

        journal.record.assert_called_once()
        assert _event_type_called(journal, EVT_AUDIO_ALL_LOOPBACKS_LOST)
        assert WARN_SYSTEM_AUDIO_INTERRUPTED in cap._audio_warnings

    def test_scenario_c_does_not_duplicate_code_on_repeat_loss(self, tmp_path):
        cap = AudioCapture(output_path=tmp_path / "test.flac")
        journal = MagicMock()
        cap._event_journal = journal
        cap._any_active_ever = True
        cap._active_count_was_nonzero = True

        cap._note_scenario_all_loopbacks_lost_if_applicable()
        cap._note_scenario_all_loopbacks_lost_if_applicable()

        assert cap._audio_warnings.count(WARN_SYSTEM_AUDIO_INTERRUPTED) == 1

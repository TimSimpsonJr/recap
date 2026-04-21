"""Tests for _LoopbackEntry state machine (probation -> active -> removed)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from recap.daemon.recorder.audio import _LoopbackEntry


def _make_entry(opened_at: float = 0.0, device_name: str = "Test Device") -> _LoopbackEntry:
    stream = MagicMock()
    stream.is_terminal = False
    return _LoopbackEntry(
        stream=stream,
        state="probation",
        opened_at=opened_at,
        last_active_at=None,
        device_name=device_name,
        missing_since=None,
    )


class TestLoopbackEntryConstruction:
    def test_default_state_is_probation(self):
        e = _make_entry()
        assert e.state == "probation"
        assert e.last_active_at is None
        assert e.missing_since is None

    def test_device_name_stored(self):
        e = _make_entry(device_name="AirPods")
        assert e.device_name == "AirPods"

    def test_opened_at_stored(self):
        e = _make_entry(opened_at=123.45)
        assert e.opened_at == 123.45

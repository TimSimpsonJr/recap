"""Tests for _LoopbackEntry state machine (probation -> active -> removed)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from recap.daemon.recorder.audio import (
    AudioCapture,
    _LOOPBACK_DEVICE_GRACE_S,
    _LOOPBACK_PROBATION_S,
    _LoopbackEntry,
)


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


@pytest.fixture
def capture(tmp_path):
    return AudioCapture(output_path=tmp_path / "test.flac")


def _fake_enumerator(devices: list[tuple]):
    """Returns a function that mimics _enumerate_loopback_endpoints's contract:
    yields (stable_key, info_dict) pairs."""
    def _enum():
        for key, info in devices:
            yield key, info
    return _enum


class TestTickMembershipAdd:
    def test_new_endpoint_opens_as_probation(self, capture, monkeypatch):
        """Enumeration returns a new device -> new _LoopbackEntry with PROBATION."""
        captured_streams: list[tuple] = []

        def _fake_open_stream(bind_to, device_name):
            s = MagicMock()
            s.is_terminal = False
            captured_streams.append((bind_to, device_name))
            return s

        monkeypatch.setattr(
            capture, "_enumerate_loopback_endpoints",
            _fake_enumerator([
                (("airpods-guid",), {"name": "AirPods", "index": 3,
                                     "defaultSampleRate": 48000.0}),
            ]),
        )
        monkeypatch.setattr(capture, "_open_loopback_stream", _fake_open_stream)

        capture._tick_membership(now=10.0)

        assert ("airpods-guid",) in capture._loopback_sources
        entry = capture._loopback_sources[("airpods-guid",)]
        assert entry.state == "probation"
        assert entry.opened_at == 10.0
        assert entry.device_name == "AirPods"
        assert captured_streams == [(("airpods-guid",), "AirPods")]


class TestTickMembershipProbationExpiry:
    def test_probation_expiry_evicts(self, capture, monkeypatch):
        """A PROBATION entry past _LOOPBACK_PROBATION_S with no signal is evicted."""
        stream = MagicMock()
        stream.is_terminal = False
        capture._loopback_sources = {
            ("dev1",): _LoopbackEntry(
                stream=stream, state="probation", opened_at=0.0,
                last_active_at=None, device_name="Dev1", missing_since=None,
            ),
        }
        monkeypatch.setattr(
            capture, "_enumerate_loopback_endpoints",
            _fake_enumerator([
                (("dev1",), {"name": "Dev1", "index": 1, "defaultSampleRate": 48000.0}),
            ]),
        )

        capture._tick_membership(now=_LOOPBACK_PROBATION_S + 1.0)

        assert ("dev1",) not in capture._loopback_sources
        stream.stop.assert_called_once()

    def test_active_entry_survives_probation_window(self, capture, monkeypatch):
        """An ACTIVE entry past the probation window is NOT evicted by expiry."""
        stream = MagicMock()
        stream.is_terminal = False
        capture._loopback_sources = {
            ("dev1",): _LoopbackEntry(
                stream=stream, state="active", opened_at=0.0,
                last_active_at=5.0, device_name="Dev1", missing_since=None,
            ),
        }
        monkeypatch.setattr(
            capture, "_enumerate_loopback_endpoints",
            _fake_enumerator([
                (("dev1",), {"name": "Dev1", "index": 1, "defaultSampleRate": 48000.0}),
            ]),
        )

        capture._tick_membership(now=_LOOPBACK_PROBATION_S + 1.0)

        assert ("dev1",) in capture._loopback_sources
        stream.stop.assert_not_called()


class TestTickMembershipDebouncedRemove:
    def test_single_missed_enumeration_does_not_evict(self, capture, monkeypatch):
        stream = MagicMock()
        stream.is_terminal = False
        entry = _LoopbackEntry(
            stream=stream, state="active", opened_at=0.0,
            last_active_at=5.0, device_name="AirPods", missing_since=None,
        )
        capture._loopback_sources = {("airpods",): entry}
        monkeypatch.setattr(
            capture, "_enumerate_loopback_endpoints", _fake_enumerator([]),
        )

        capture._tick_membership(now=10.0)

        assert ("airpods",) in capture._loopback_sources
        assert entry.missing_since == 10.0
        stream.stop.assert_not_called()

    def test_sustained_absence_past_grace_evicts(self, capture, monkeypatch):
        stream = MagicMock()
        stream.is_terminal = False
        entry = _LoopbackEntry(
            stream=stream, state="active", opened_at=0.0,
            last_active_at=5.0, device_name="AirPods",
            missing_since=10.0,
        )
        capture._loopback_sources = {("airpods",): entry}
        monkeypatch.setattr(
            capture, "_enumerate_loopback_endpoints", _fake_enumerator([]),
        )

        capture._tick_membership(now=10.0 + _LOOPBACK_DEVICE_GRACE_S + 1.0)

        assert ("airpods",) not in capture._loopback_sources
        stream.stop.assert_called_once()

    def test_reappearance_clears_missing_since(self, capture, monkeypatch):
        stream = MagicMock()
        stream.is_terminal = False
        entry = _LoopbackEntry(
            stream=stream, state="active", opened_at=0.0,
            last_active_at=5.0, device_name="AirPods",
            missing_since=10.0,
        )
        capture._loopback_sources = {("airpods",): entry}
        monkeypatch.setattr(
            capture, "_enumerate_loopback_endpoints",
            _fake_enumerator([
                (("airpods",), {"name": "AirPods", "index": 3,
                                "defaultSampleRate": 48000.0}),
            ]),
        )

        capture._tick_membership(now=12.0)

        assert ("airpods",) in capture._loopback_sources
        assert entry.missing_since is None


class TestTickMembershipTerminalStream:
    def test_terminal_stream_is_evicted(self, capture, monkeypatch):
        stream = MagicMock()
        stream.is_terminal = True
        capture._loopback_sources = {
            ("dev1",): _LoopbackEntry(
                stream=stream, state="active", opened_at=0.0,
                last_active_at=5.0, device_name="Dev1", missing_since=None,
            ),
        }
        monkeypatch.setattr(
            capture, "_enumerate_loopback_endpoints",
            _fake_enumerator([
                (("dev1",), {"name": "Dev1", "index": 1, "defaultSampleRate": 48000.0}),
            ]),
        )

        capture._tick_membership(now=10.0)

        assert ("dev1",) not in capture._loopback_sources
        stream.stop.assert_called_once()


class TestTickMembershipEnumerationFailure:
    def test_enumeration_exception_skips_tick_without_evicting(self, capture, monkeypatch):
        stream = MagicMock()
        stream.is_terminal = False
        entry = _LoopbackEntry(
            stream=stream, state="active", opened_at=0.0,
            last_active_at=5.0, device_name="Dev1", missing_since=None,
        )
        capture._loopback_sources = {("dev1",): entry}

        def _raises():
            raise RuntimeError("transient WASAPI error")
            yield  # pragma: no cover - unreachable, keeps type a generator

        monkeypatch.setattr(capture, "_enumerate_loopback_endpoints", _raises)

        capture._tick_membership(now=10.0)  # must not raise

        assert ("dev1",) in capture._loopback_sources
        stream.stop.assert_not_called()

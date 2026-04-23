"""End-to-end integration tests for #29 non-Teams participant enrichment.

Combines three layers:
- MeetingDetector orchestration (session lifecycle, Zoom UIA periodic
  refresh, browser HTTP handler)
- Recorder stop-seam (on_before_finalize populates metadata.participants,
  on_after_stop clears session state)
- Sidecar roundtrip (write_recording_metadata at start time, rewrite at
  stop with finalized roster)

Strategy: real Recorder + real MeetingDetector, MagicMock for audio_capture,
no real UIA or real HTTP. Assertions on the loaded sidecar after stop().
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from recap.artifacts import (
    RecordingMetadata,
    load_recording_metadata,
    write_recording_metadata,
)
from recap.daemon.recorder.detection import MeetingWindow
from recap.daemon.recorder.detector import MeetingDetector
from recap.daemon.recorder.recorder import Recorder
from recap.models import Participant


def _make_mock_config():
    config = MagicMock()
    config.detection.teams.enabled = True
    config.detection.teams.behavior = "auto-record"
    config.detection.teams.default_org = "disbursecloud"
    config.detection.zoom.enabled = True
    config.detection.zoom.behavior = "auto-record"
    config.detection.zoom.default_org = "disbursecloud"
    config.detection.signal.enabled = True
    config.detection.signal.behavior = "prompt"
    config.detection.signal.default_org = "personal"
    config.known_contacts = []
    return config


def _setup_real_recorder_at_recording_state(
    tmp_path,
    *,
    initial_participants: list[str] | None = None,
) -> tuple[Recorder, MagicMock]:
    """Build a real Recorder with MagicMock audio_capture, already in
    RECORDING state, with an initial sidecar written. Mirrors
    tests/test_recorder_finalize.py::_make_recorder_ready_to_stop."""
    recorder = Recorder(recordings_path=tmp_path)

    fake_capture = MagicMock()
    fake_capture._audio_warnings = []
    fake_capture._system_audio_devices_seen = []
    fake_capture.stop = MagicMock()

    audio_path = tmp_path / "test.flac"
    audio_path.touch()
    initial_metadata = RecordingMetadata(
        org="testorg",
        note_path="",
        title="Test",
        date="2026-04-23",
        participants=[Participant(name=n) for n in (initial_participants or [])],
        platform="manual",
    )
    write_recording_metadata(audio_path, initial_metadata)

    recorder._audio_capture = fake_capture
    recorder._current_path = audio_path
    recorder._current_metadata = initial_metadata
    recorder.state_machine.detected("testorg")
    recorder.state_machine.start_recording("testorg")

    return recorder, fake_capture


@pytest.mark.asyncio
async def test_spontaneous_zoom_populates_participants_from_uia(tmp_path):
    """Zoom auto-record: periodic UIA refresh populates roster, stop()
    writes participants into the sidecar."""
    config = _make_mock_config()
    recorder, fake_capture = _setup_real_recorder_at_recording_state(
        tmp_path, initial_participants=[],
    )
    # Make recorder look "is_recording" to detector. Recorder.is_recording
    # is a property derived from state_machine state; since we're in
    # RECORDING state, it's already True.
    assert recorder.is_recording

    detector = MeetingDetector(config=config, recorder=recorder)
    hwnd = 500
    detector._tracked_meetings[hwnd] = MeetingWindow(
        hwnd=hwnd, title="Zoom Meeting", platform="zoom",
    )
    detector._recording_hwnd = hwnd
    detector._begin_roster_session()  # empty — Zoom has no calendar seed

    # Run 10 polls, patching detection + UIA.
    with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[]):
        with patch(
            "recap.daemon.recorder.detector.extract_zoom_participants",
            return_value=["Dana", "Eve"],
        ):
            with patch("recap.daemon.recorder.detector.is_window_alive", return_value=True):
                for _ in range(10):
                    await detector._poll_once()

    assert detector._active_roster.current() == ["Dana", "Eve"]

    # Now stop the recording; the on_before_finalize hook fires and
    # rewrites the sidecar.
    await recorder.stop()

    loaded = load_recording_metadata(tmp_path / "test.flac")
    assert loaded is not None
    names = [p.name for p in loaded.participants]
    assert "Dana" in names
    assert "Eve" in names


@pytest.mark.asyncio
async def test_spontaneous_meet_populates_from_endpoint(tmp_path):
    """Meet browser path: HTTP handler merges roster, stop() writes
    participants into sidecar."""
    config = _make_mock_config()
    recorder, _ = _setup_real_recorder_at_recording_state(
        tmp_path, initial_participants=[],
    )
    detector = MeetingDetector(config=config, recorder=recorder)

    # Simulate post-start state for a browser-detected meeting.
    tab_id = 77
    detector._begin_roster_session(tab_id=tab_id, browser_platform="google_meet")

    # Simulate two HTTP pushes (first and late-joiner).
    await detector.handle_extension_participants_updated(
        tab_id=tab_id, participants=["Fiona"],
    )
    await detector.handle_extension_participants_updated(
        tab_id=tab_id, participants=["Fiona", "Greg"],
    )
    assert detector._active_roster.current() == ["Fiona", "Greg"]

    await recorder.stop()

    loaded = load_recording_metadata(tmp_path / "test.flac")
    assert loaded is not None
    names = [p.name for p in loaded.participants]
    assert names == ["Fiona", "Greg"]


@pytest.mark.asyncio
async def test_spontaneous_zoho_tranzpay_populates_from_endpoint(tmp_path):
    """Zoho (tranzpay variant) browser path: source tag uses
    browser_dom_zoho_meet. Stop writes participants."""
    config = _make_mock_config()
    recorder, _ = _setup_real_recorder_at_recording_state(
        tmp_path, initial_participants=[],
    )
    detector = MeetingDetector(config=config, recorder=recorder)

    tab_id = 88
    detector._begin_roster_session(tab_id=tab_id, browser_platform="zoho_meet")
    await detector.handle_extension_participants_updated(
        tab_id=tab_id, participants=["Henry", "Ivy"],
    )

    # Source tag should reflect the platform.
    assert "browser_dom_zoho_meet" in detector._active_roster._last_merge_per_source

    await recorder.stop()
    loaded = load_recording_metadata(tmp_path / "test.flac")
    names = [p.name for p in loaded.participants]
    assert names == ["Henry", "Ivy"]


@pytest.mark.asyncio
async def test_teams_one_shot_preserves_initial_sidecar(tmp_path):
    """Teams regression: initial sidecar seeded with Teams UIA names,
    roster primed with same, finalize() returns same list, no rewrite.
    Verifies the issue's 'Teams no regression' acceptance criterion."""
    config = _make_mock_config()
    initial = ["Alice", "Bob"]
    recorder, _ = _setup_real_recorder_at_recording_state(
        tmp_path, initial_participants=initial,
    )
    detector = MeetingDetector(config=config, recorder=recorder)
    hwnd = 100
    detector._tracked_meetings[hwnd] = MeetingWindow(
        hwnd=hwnd, title="Standup | Microsoft Teams", platform="teams",
    )
    detector._recording_hwnd = hwnd
    # Seed roster with the same Teams one-shot names that went into initial metadata.
    detector._begin_roster_session(
        initial_names=initial,
        initial_source="teams_uia_detection",
    )

    # Even if polls run, Teams is deliberately skipped by _refresh_roster_uia.
    with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[]):
        with patch("recap.daemon.recorder.detector.is_window_alive", return_value=True):
            for _ in range(10):
                await detector._poll_once()

    # Roster still just the seeded two.
    assert detector._active_roster.current() == initial

    await recorder.stop()

    loaded = load_recording_metadata(tmp_path / "test.flac")
    assert loaded is not None
    names = [p.name for p in loaded.participants]
    # Teams initial is preserved (no regression from #29).
    assert names == initial

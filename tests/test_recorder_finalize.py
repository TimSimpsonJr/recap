"""Tests for Recorder on_before_finalize / on_after_stop hooks (#29).

Harness pattern mirrors tests/test_recorder_orchestrator.py —
inject MagicMock for audio_capture, seed sidecar + state machine,
call stop(), assert on the loaded sidecar.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from recap.artifacts import (
    RecordingMetadata,
    load_recording_metadata,
    write_recording_metadata,
)
from recap.daemon.recorder.recorder import Recorder
from recap.models import Participant


def _make_recorder_ready_to_stop(
    tmp_path,
    *,
    initial_participants: list[str] | None = None,
    audio_warnings: list[str] | None = None,
) -> tuple[Recorder, MagicMock]:
    """Build a Recorder with a fake audio_capture in RECORDING state,
    ready for stop(). Returns (recorder, fake_capture)."""
    recorder = Recorder(recordings_path=tmp_path)

    fake_capture = MagicMock()
    fake_capture._audio_warnings = list(audio_warnings or [])
    fake_capture._system_audio_devices_seen = []
    fake_capture.stop = MagicMock()

    audio_path = tmp_path / "test.flac"
    audio_path.touch()
    # RecordingMetadata.participants is list[Participant]; ParticipantRoster
    # hooks work in list[str]. Convert incoming string names to Participant
    # objects here so the sidecar JSON round-trip works.
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


def _names(metadata: RecordingMetadata | None) -> list[str]:
    """Extract the participant-name list from a loaded sidecar."""
    if metadata is None:
        return []
    return [p.name for p in metadata.participants]


@pytest.mark.asyncio
async def test_on_before_finalize_called_during_stop(tmp_path):
    recorder, _ = _make_recorder_ready_to_stop(tmp_path)
    called: list[str] = []

    def finalizer() -> list[str]:
        called.append("before")
        return []

    recorder.on_before_finalize = finalizer
    await recorder.stop()
    assert called == ["before"]


@pytest.mark.asyncio
async def test_on_after_stop_called_after_before_finalize(tmp_path):
    recorder, _ = _make_recorder_ready_to_stop(tmp_path)
    order: list[str] = []
    recorder.on_before_finalize = lambda: (order.append("before"), [])[1]
    recorder.on_after_stop = lambda: order.append("after")
    await recorder.stop()
    assert order == ["before", "after"]


@pytest.mark.asyncio
async def test_finalize_raising_does_not_abort_stop(tmp_path, caplog):
    recorder, _ = _make_recorder_ready_to_stop(tmp_path)

    def boom() -> list[str]:
        raise RuntimeError("finalize boom")

    after_called: list[int] = []
    recorder.on_before_finalize = boom
    recorder.on_after_stop = lambda: after_called.append(1)

    path = await recorder.stop()
    assert path is not None  # stop completed
    assert after_called == [1]
    assert "Participant finalizer failed" in caplog.text


@pytest.mark.asyncio
async def test_after_stop_raising_does_not_abort_stop(tmp_path, caplog):
    recorder, _ = _make_recorder_ready_to_stop(tmp_path)

    def boom() -> None:
        raise RuntimeError("after boom")

    recorder.on_after_stop = boom
    path = await recorder.stop()
    assert path is not None
    assert "on_after_stop hook failed" in caplog.text


@pytest.mark.asyncio
async def test_finalize_empty_list_does_not_rewrite(tmp_path):
    """Empty finalize output with no audio warnings → no rewrite.
    Sidecar retains the initial (empty) participants."""
    recorder, _ = _make_recorder_ready_to_stop(
        tmp_path, initial_participants=[],
    )
    recorder.on_before_finalize = lambda: []
    await recorder.stop()

    loaded = load_recording_metadata(recorder._current_path or tmp_path / "test.flac")
    # If no rewrite happens, the sidecar still has the initial empty list.
    assert loaded is not None
    assert _names(loaded) == []


@pytest.mark.asyncio
async def test_finalize_same_as_initial_does_not_rewrite(tmp_path):
    """Finalized list identical to initial → no rewrite. Teams one-shot
    path relies on this to avoid redundant sidecar writes."""
    initial = ["Alice", "Bob"]
    recorder, _ = _make_recorder_ready_to_stop(
        tmp_path, initial_participants=initial,
    )
    recorder.on_before_finalize = lambda: list(initial)
    await recorder.stop()

    loaded = load_recording_metadata(tmp_path / "test.flac")
    assert loaded is not None
    assert _names(loaded) == initial


@pytest.mark.asyncio
async def test_finalize_new_list_rewrites_sidecar(tmp_path):
    """Finalized list differs from initial → sidecar rewritten with new list."""
    recorder, _ = _make_recorder_ready_to_stop(
        tmp_path, initial_participants=[],
    )
    recorder.on_before_finalize = lambda: ["Alice", "Bob"]
    await recorder.stop()

    loaded = load_recording_metadata(tmp_path / "test.flac")
    assert loaded is not None
    assert _names(loaded) == ["Alice", "Bob"]


@pytest.mark.asyncio
async def test_audio_warnings_and_participants_single_rewrite(tmp_path):
    """Both audio_warnings AND new participants → single combined rewrite."""
    recorder, fake_capture = _make_recorder_ready_to_stop(
        tmp_path,
        initial_participants=[],
        audio_warnings=["test_warning"],
    )
    recorder.on_before_finalize = lambda: ["Alice"]
    await recorder.stop()

    loaded = load_recording_metadata(tmp_path / "test.flac")
    assert loaded is not None
    assert _names(loaded) == ["Alice"]
    assert "test_warning" in loaded.audio_warnings


@pytest.mark.asyncio
async def test_no_hooks_registered_leaves_initial_behavior_intact(tmp_path):
    """No hooks → stop() behaves exactly as pre-#29 (audio_warnings path only)."""
    recorder, _ = _make_recorder_ready_to_stop(
        tmp_path,
        initial_participants=["Pre29"],
        audio_warnings=["legacy_warning"],
    )
    # on_before_finalize and on_after_stop both None.
    await recorder.stop()

    loaded = load_recording_metadata(tmp_path / "test.flac")
    assert loaded is not None
    assert _names(loaded) == ["Pre29"]
    assert "legacy_warning" in loaded.audio_warnings


@pytest.mark.asyncio
async def test_finalize_case_upgrade_preserves_existing_participant_fields(tmp_path):
    """When the roster finalizes with an upgraded display form for an
    existing participant (same casefold key), the Participant's email
    and other fields must be preserved; only the display name updates.

    Example: calendar-synced meeting has Participant(name="alice smith",
    email="alice@x.com"); Teams/Zoom/browser UIA later contributes the
    same person with display form "Alice Smith". The rewrite must
    keep the email and update the visible name.
    """
    recorder = Recorder(recordings_path=tmp_path)

    fake_capture = MagicMock()
    fake_capture._audio_warnings = []
    fake_capture._system_audio_devices_seen = []
    fake_capture.stop = MagicMock()

    audio_path = tmp_path / "test.flac"
    audio_path.touch()
    initial_participant = Participant(name="alice smith", email="alice@x.com")
    initial_metadata = RecordingMetadata(
        org="testorg",
        note_path="",
        title="Test",
        date="2026-04-23",
        participants=[initial_participant],
        platform="manual",
    )
    write_recording_metadata(audio_path, initial_metadata)

    recorder._audio_capture = fake_capture
    recorder._current_path = audio_path
    recorder._current_metadata = initial_metadata
    recorder.state_machine.detected("testorg")
    recorder.state_machine.start_recording("testorg")

    recorder.on_before_finalize = lambda: ["Alice Smith"]
    await recorder.stop()

    loaded = load_recording_metadata(audio_path)
    assert loaded is not None
    assert len(loaded.participants) == 1
    assert loaded.participants[0].name == "Alice Smith"
    assert loaded.participants[0].email == "alice@x.com"

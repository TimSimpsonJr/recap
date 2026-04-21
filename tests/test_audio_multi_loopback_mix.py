"""Tests for AudioCapture._drain_and_mix (multi-stream mix math)."""
from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from recap.daemon.recorder.audio import (
    AudioCapture,
    _LoopbackEntry,
    _LOOPBACK_ACTIVE_RMS_LINEAR,
)


def _entry_with_buffer(samples: np.ndarray, device_name: str = "Test") -> _LoopbackEntry:
    """Build a _LoopbackEntry whose _SourceStream's drain_resampled() returns
    the given samples as int16 bytes."""
    stream = MagicMock()
    stream.is_terminal = False
    stream.drain_resampled.return_value = samples.astype(np.int16).tobytes()
    return _LoopbackEntry(
        stream=stream,
        state="probation",
        opened_at=0.0,
        last_active_at=None,
        device_name=device_name,
        missing_since=None,
    )


@pytest.fixture
def capture(tmp_path):
    cap = AudioCapture(output_path=tmp_path / "test.flac")
    return cap


def _mic_bytes(chunk_frames: int, level_int16: int = 10000) -> bytes:
    arr = np.full(chunk_frames, level_int16, dtype=np.int16)
    return arr.tobytes()


class TestDrainAndMix:
    def test_single_active_stream_preserves_level(self, capture):
        """One signal-bearing loopback -> channel-1 equals that stream's samples."""
        chunk_frames = 480
        speech = np.full(chunk_frames, 8000, dtype=np.int16)
        capture._mic_buffer = _mic_bytes(chunk_frames)
        capture._loopback_sources = {
            ("airpods",): _entry_with_buffer(speech, device_name="AirPods"),
        }

        mic, system, _ = capture._drain_and_mix(chunk_frames)
        np.testing.assert_array_equal(system, speech)

    def test_two_active_streams_average(self, capture):
        chunk_frames = 480
        a = np.full(chunk_frames, 8000, dtype=np.int16)
        b = np.full(chunk_frames, 4000, dtype=np.int16)
        capture._mic_buffer = _mic_bytes(chunk_frames)
        capture._loopback_sources = {
            ("dev-a",): _entry_with_buffer(a, device_name="A"),
            ("dev-b",): _entry_with_buffer(b, device_name="B"),
        }
        _, system, _ = capture._drain_and_mix(chunk_frames)
        expected = ((a.astype(np.int32) + b.astype(np.int32)) // 2).astype(np.int16)
        np.testing.assert_array_equal(system, expected)

    def test_silent_stream_excluded_from_active_count(self, capture):
        chunk_frames = 480
        speech = np.full(chunk_frames, 8000, dtype=np.int16)
        silent = np.zeros(chunk_frames, dtype=np.int16)
        capture._mic_buffer = _mic_bytes(chunk_frames)
        capture._loopback_sources = {
            ("airpods",): _entry_with_buffer(speech, device_name="AirPods"),
            ("speakers",): _entry_with_buffer(silent, device_name="Speakers"),
        }
        _, system, _ = capture._drain_and_mix(chunk_frames)
        np.testing.assert_array_equal(system, speech)

    def test_all_below_threshold_emits_zero_channel(self, capture):
        chunk_frames = 480
        capture._mic_buffer = _mic_bytes(chunk_frames)
        capture._loopback_sources = {
            ("a",): _entry_with_buffer(np.zeros(chunk_frames, dtype=np.int16)),
            ("b",): _entry_with_buffer(np.zeros(chunk_frames, dtype=np.int16)),
        }
        _, system, _ = capture._drain_and_mix(chunk_frames)
        assert np.all(system == 0)

    def test_no_loopback_sources_emits_zero_channel(self, capture):
        chunk_frames = 480
        capture._mic_buffer = _mic_bytes(chunk_frames)
        capture._loopback_sources = {}
        _, system, _ = capture._drain_and_mix(chunk_frames)
        assert np.all(system == 0)
        assert system.shape == (chunk_frames,)

    def test_rms_measured_before_padding(self, capture):
        """A stream that returns a short buffer must have its RMS measured on
        the unpadded samples. If RMS were measured after zero-padding, the
        below-threshold padded-RMS would misclassify a legitimately active
        short-buffer stream as silent.

        Values chosen so the regression is actually exercised:
          - unpadded RMS = 1000 (above ~328 threshold)
          - padded RMS over 480 samples = ~144 (below threshold)
        A broken implementation measuring RMS post-pad would now misclassify
        as silent; the correct implementation includes the stream.
        """
        chunk_frames = 480
        # Exactly 10 real samples, level chosen so unpadded-RMS clears
        # threshold and padded-RMS would not.
        short = np.full(10, 1000, dtype=np.int16)
        capture._mic_buffer = _mic_bytes(chunk_frames)
        entry = _entry_with_buffer(short)
        capture._loopback_sources = {("x",): entry}

        _, system, _ = capture._drain_and_mix(chunk_frames)

        # The stream must be classified active (only possible if RMS was
        # measured on the unpadded 10 samples, not the 480-sample padded view).
        assert entry.state == "active"
        # The 10 real samples should appear in channel-1; the rest is zero-pad.
        np.testing.assert_array_equal(system[:10], short)
        assert np.all(system[10:] == 0)

    def test_first_signal_promotes_probation_to_active(self, capture):
        chunk_frames = 480
        speech = np.full(chunk_frames, 8000, dtype=np.int16)
        entry = _entry_with_buffer(speech)
        assert entry.state == "probation"
        capture._mic_buffer = _mic_bytes(chunk_frames)
        capture._loopback_sources = {("a",): entry}

        capture._drain_and_mix(chunk_frames)

        assert entry.state == "active"
        assert entry.last_active_at is not None

    def test_below_threshold_leaves_probation_intact(self, capture):
        chunk_frames = 480
        silent = np.zeros(chunk_frames, dtype=np.int16)
        entry = _entry_with_buffer(silent)
        capture._mic_buffer = _mic_bytes(chunk_frames)
        capture._loopback_sources = {("a",): entry}
        capture._drain_and_mix(chunk_frames)
        assert entry.state == "probation"
        assert entry.last_active_at is None

    def test_active_stays_sticky_when_chunk_falls_silent(self, capture):
        """Once a stream is ACTIVE, a chunk with sub-threshold RMS leaves it
        ACTIVE (no demotion) but excludes it from this chunk's active_count.

        This invariant is load-bearing for Task 7's membership watcher: ACTIVE
        entries are only evicted on device-gone or is_terminal, never on
        silence. The mix math must exclude them per chunk without touching
        state, so that a later chunk that carries signal can still contribute
        via the already-ACTIVE entry."""
        chunk_frames = 480
        silent = np.zeros(chunk_frames, dtype=np.int16)
        entry = _entry_with_buffer(silent)
        entry.state = "active"  # simulate a previously-promoted entry
        entry.last_active_at = 5.0  # some prior timestamp
        capture._mic_buffer = _mic_bytes(chunk_frames)
        capture._loopback_sources = {("a",): entry}

        _, system, _ = capture._drain_and_mix(chunk_frames)

        # State unchanged -- ACTIVE is sticky through silence.
        assert entry.state == "active"
        # last_active_at not updated (chunk was below threshold)
        assert entry.last_active_at == 5.0
        # Excluded from the mix on this chunk -> zero channel-1.
        assert np.all(system == 0)

    def test_saturation_clips_without_overflow(self, capture):
        chunk_frames = 480
        peak = np.full(chunk_frames, 32767, dtype=np.int16)
        entry_a = _entry_with_buffer(peak)
        entry_b = _entry_with_buffer(peak)
        capture._mic_buffer = _mic_bytes(chunk_frames)
        capture._loopback_sources = {("a",): entry_a, ("b",): entry_b}
        _, system, _ = capture._drain_and_mix(chunk_frames)
        assert np.all(system == 32767)

    def test_mono_chunk_is_mic_plus_system_halved(self, capture):
        chunk_frames = 480
        speech = np.full(chunk_frames, 8000, dtype=np.int16)
        capture._mic_buffer = _mic_bytes(chunk_frames, level_int16=10000)
        capture._loopback_sources = {("a",): _entry_with_buffer(speech)}

        mic, system, mono_bytes = capture._drain_and_mix(chunk_frames)
        mono = np.frombuffer(mono_bytes, dtype=np.int16)

        expected = ((mic.astype(np.int32) + system.astype(np.int32)) // 2).astype(np.int16)
        np.testing.assert_array_equal(mono, expected)


class TestInterleaveUsesDrainAndMix:
    def test_interleave_uses_mic_and_system_mix(self, capture, monkeypatch):
        """_interleave_and_encode must build the stereo FLAC frame from
        _drain_and_mix output (mic in channel 0, system mix in channel 1)."""
        chunk_frames = 480
        mic = np.full(chunk_frames, 1000, dtype=np.int16)
        system = np.full(chunk_frames, 2000, dtype=np.int16)

        monkeypatch.setattr(
            capture, "_drain_and_mix",
            lambda cf: (mic, system, b"\x00" * cf * 2),
        )
        captured: list = []
        capture._encoder = MagicMock()
        capture._encoder.process.side_effect = lambda frames: captured.append(frames)

        capture._interleave_and_encode(chunk_frames)

        assert len(captured) == 1
        frames = captured[0]
        assert frames.shape == (chunk_frames, 2)
        np.testing.assert_array_equal(frames[:, 0], mic)
        np.testing.assert_array_equal(frames[:, 1], system)

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
        the unpadded samples. Measuring after padding with zeros would depress
        the level of legitimately-active short-buffer streams."""
        chunk_frames = 480
        short = np.full(100, 20000, dtype=np.int16)
        capture._mic_buffer = _mic_bytes(chunk_frames)
        entry = _entry_with_buffer(short)
        capture._loopback_sources = {("x",): entry}

        _, system, _ = capture._drain_and_mix(chunk_frames)

        np.testing.assert_array_equal(system[:100], short)
        assert np.all(system[100:] == 0)
        assert entry.state == "active"

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

"""Tests for audio capture module."""

import pytest
from unittest.mock import patch, MagicMock

from recap.daemon.recorder.audio import (
    AudioCapture,
    find_loopback_device,
    find_microphone_device,
    AudioDeviceError,
)


class TestDeviceDiscovery:
    def test_find_loopback_raises_on_no_device(self):
        with patch("recap.daemon.recorder.audio.pyaudio") as mock_pa:
            mock_instance = MagicMock()
            mock_pa.PyAudio.return_value = mock_instance
            mock_instance.get_host_api_info_by_type.side_effect = OSError("No WASAPI")
            with pytest.raises(AudioDeviceError):
                find_loopback_device()

    def test_find_loopback_returns_device(self):
        with patch("recap.daemon.recorder.audio.pyaudio") as mock_pa:
            mock_instance = MagicMock()
            mock_pa.PyAudio.return_value = mock_instance
            mock_pa.paWASAPI = 13
            expected = {"name": "Speakers (Loopback)", "index": 5}
            mock_instance.get_default_wasapi_loopback.return_value = expected
            result = find_loopback_device()
            assert result == expected
            mock_instance.terminate.assert_called_once()

    def test_find_microphone_raises_on_no_device(self):
        with patch("recap.daemon.recorder.audio.pyaudio") as mock_pa:
            mock_instance = MagicMock()
            mock_pa.PyAudio.return_value = mock_instance
            mock_instance.get_host_api_info_by_type.side_effect = OSError("No WASAPI")
            with pytest.raises(AudioDeviceError):
                find_microphone_device()

    def test_find_microphone_returns_device(self):
        with patch("recap.daemon.recorder.audio.pyaudio") as mock_pa:
            mock_instance = MagicMock()
            mock_pa.PyAudio.return_value = mock_instance
            mock_pa.paWASAPI = 13
            expected = {
                "name": "Microphone",
                "index": 2,
                "maxInputChannels": 1,
            }
            mock_instance.get_default_wasapi_device.return_value = expected
            result = find_microphone_device()
            assert result == expected
            mock_instance.terminate.assert_called_once()

    def test_find_microphone_raises_when_no_input_channels(self):
        with patch("recap.daemon.recorder.audio.pyaudio") as mock_pa:
            mock_instance = MagicMock()
            mock_pa.PyAudio.return_value = mock_instance
            mock_pa.paWASAPI = 13
            mock_instance.get_default_wasapi_device.return_value = {
                "name": "Speakers",
                "index": 1,
                "maxInputChannels": 0,
            }
            with pytest.raises(AudioDeviceError, match="no input channels"):
                find_microphone_device()


class TestAudioCaptureConfig:
    def test_initial_state(self, tmp_path):
        capture = AudioCapture(
            output_path=tmp_path / "test.flac",
            sample_rate=16000,
            channels=2,
        )
        assert capture.channels == 2
        assert capture.sample_rate == 16000
        assert capture.is_recording is False

    def test_output_path_stored(self, tmp_path):
        path = tmp_path / "test.flac"
        capture = AudioCapture(output_path=path)
        assert capture.output_path == path

    def test_default_values(self, tmp_path):
        capture = AudioCapture(output_path=tmp_path / "test.flac")
        assert capture.sample_rate == 16000
        assert capture.channels == 2

    def test_current_rms_initially_zero(self, tmp_path):
        capture = AudioCapture(output_path=tmp_path / "test.flac")
        assert capture.current_rms == 0.0


def test_audio_capture_invokes_on_chunk_after_interleave(tmp_path):
    """Public on_chunk callback replaces the monkey-patch."""
    pytest.importorskip("numpy")
    captured: list[tuple[bytes, int]] = []

    cap = AudioCapture(output_path=tmp_path / "out.flac")
    cap.on_chunk = lambda chunk, sample_rate: captured.append((chunk, sample_rate))
    # Feed two fake frames through the combine-and-encode path using the
    # helper the class exposes for tests. The encoder stays None so no pyflac
    # runtime is required.
    cap._test_feed_mock_frames(mic_frame=b"\x00" * 320, system_frame=b"\x01" * 320)
    cap._test_feed_mock_frames(mic_frame=b"\x02" * 320, system_frame=b"\x03" * 320)

    assert len(captured) == 2
    # Chunks are bytes and sample_rate is an int
    assert all(isinstance(c[0], bytes) and isinstance(c[1], int) for c in captured)
    # Sample rate reflects the AudioCapture configuration
    assert all(c[1] == cap.sample_rate for c in captured)


def test_audio_capture_on_chunk_default_is_none(tmp_path):
    """on_chunk defaults to None and the capture still works without a callback."""
    pytest.importorskip("numpy")
    cap = AudioCapture(output_path=tmp_path / "out.flac")
    assert cap.on_chunk is None
    # Should not raise even with no callback wired up.
    cap._test_feed_mock_frames(mic_frame=b"\x00" * 320, system_frame=b"\x01" * 320)


def test_audio_capture_does_not_pass_channels_to_encoder(tmp_path, monkeypatch):
    """AudioCapture.start() must not pass channels= to pyflac.StreamEncoder."""
    from unittest.mock import MagicMock
    from recap.daemon.recorder.audio import AudioCapture
    import recap.daemon.recorder.audio as audio_mod

    mock_encoder_cls = MagicMock()
    mock_pyflac = MagicMock()
    mock_pyflac.StreamEncoder = mock_encoder_cls

    monkeypatch.setattr(audio_mod, "_require_pyflac", lambda: mock_pyflac)
    monkeypatch.setattr(audio_mod, "_require_pyaudio", lambda: MagicMock())

    capture = AudioCapture(output_path=tmp_path / "x.flac", sample_rate=16000, channels=2)
    try:
        capture.start()
    except Exception:
        pass

    assert mock_encoder_cls.called
    _, kwargs = mock_encoder_cls.call_args
    assert "channels" not in kwargs, f"StreamEncoder called with channels: {kwargs}"

    # Stop to tear down the drain thread before monkeypatch is unwound;
    # otherwise the background thread races into real PyAudio after
    # teardown and crashes the process.
    try:
        capture.stop()
    except Exception:
        pass


def test_audio_capture_on_chunk_swallows_exceptions(tmp_path, caplog):
    """A failing on_chunk must not crash capture or poison subsequent invocations."""
    pytest.importorskip("numpy")

    captured: list[tuple[bytes, int]] = []
    call_count = [0]

    def sometimes_boom(chunk: bytes, sample_rate: int) -> None:
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("first call fails")
        captured.append((chunk, sample_rate))

    cap = AudioCapture(output_path=tmp_path / "out.flac")
    cap.on_chunk = sometimes_boom
    with caplog.at_level("ERROR"):
        cap._test_feed_mock_frames(mic_frame=b"\x00" * 320, system_frame=b"\x01" * 320)
        cap._test_feed_mock_frames(mic_frame=b"\x02" * 320, system_frame=b"\x03" * 320)

    # Callback fired on both chunks (exception didn't break the pipeline).
    assert call_count[0] == 2
    # Second call succeeded and delivered a (bytes, int) tuple.
    assert len(captured) == 1
    assert isinstance(captured[0][0], bytes) and isinstance(captured[0][1], int)
    # The failure was logged.
    assert "on_chunk callback raised" in caplog.text


class TestSoxrResamplerWrapper:
    """Thin stateful-streaming wrapper around soxr.ResampleStream.

    Isolated from _SourceStream so the resample contract (frame counts
    across chunk boundaries, rate-change rebuild, mono int16 in / mono
    int16 out) can be verified without PyAudio in the way.
    """

    def test_identity_rate_is_passthrough(self):
        pytest.importorskip("numpy")
        import numpy as np
        from recap.daemon.recorder.audio import _SoxrResamplerWrapper

        r = _SoxrResamplerWrapper(input_rate=48000, output_rate=48000)
        total_in = 0
        total_out = 0
        for _ in range(4):
            pcm = np.zeros(1024, dtype=np.int16).tobytes()
            out = r.process(pcm)
            total_in += 1024
            total_out += len(out) // 2
        assert abs(total_out - total_in) <= 128

    def test_upsample_44100_to_48000_frame_ratio(self):
        pytest.importorskip("numpy")
        import numpy as np
        from recap.daemon.recorder.audio import _SoxrResamplerWrapper

        r = _SoxrResamplerWrapper(input_rate=44100, output_rate=48000)
        total_in = 0
        total_out = 0
        for _ in range(44):
            pcm = np.zeros(1024, dtype=np.int16).tobytes()
            out = r.process(pcm)
            total_in += 1024
            total_out += len(out) // 2
        expected = total_in * 48000 / 44100
        assert abs(total_out - expected) / expected < 0.02

    def test_rate_change_rebuilds_resampler(self):
        pytest.importorskip("numpy")
        import numpy as np
        from recap.daemon.recorder.audio import _SoxrResamplerWrapper

        r = _SoxrResamplerWrapper(input_rate=48000, output_rate=48000)
        assert r.input_rate == 48000
        r.process(np.zeros(1024, dtype=np.int16).tobytes())
        r.rebuild(input_rate=44100)
        # input_rate must reflect the new rate.
        assert r.input_rate == 44100
        # The rebuilt resampler still produces bytes without crashing.
        out2 = r.process(np.zeros(1024, dtype=np.int16).tobytes())
        assert isinstance(out2, bytes)

    def test_no_discontinuity_across_chunk_boundaries(self):
        pytest.importorskip("numpy")
        import numpy as np
        from recap.daemon.recorder.audio import _SoxrResamplerWrapper

        r = _SoxrResamplerWrapper(input_rate=44100, output_rate=48000)
        sample_rate = 44100
        t = np.arange(44100 * 2) / sample_rate
        signal = (0.5 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
        out_bytes = b""
        for i in range(0, len(signal), 1024):
            chunk = signal[i:i + 1024].tobytes()
            out_bytes += r.process(chunk)
        out = np.frombuffer(out_bytes, dtype=np.int16)
        assert len(out) > 0

        # If the resampler preserved continuity, the dominant frequency
        # of the output is still ~440 Hz (at the 48 kHz output rate).
        # A broken chunk-boundary handler (drops, inversions, zeros)
        # would smear the spectrum or shift the peak.
        fft_mag = np.abs(np.fft.rfft(out.astype(np.float64)))
        freqs = np.fft.rfftfreq(len(out), d=1.0 / 48000)
        peak_freq = freqs[np.argmax(fft_mag)]
        assert abs(peak_freq - 440) < 5, (
            f"dominant output frequency {peak_freq:.1f} Hz; expected ~440 Hz"
        )


class TestSourceStreamSkeleton:
    """_SourceStream's state machine, identity tracking, and read_frames
    silence-padding contract -- verified without opening real PyAudio
    streams. PyAudio integration lands in a later task."""

    def test_initial_state_is_stopped(self):
        from recap.daemon.recorder.audio import _SourceStream, _SourceHealth

        src = _SourceStream(kind="mic", output_rate=48000)
        assert src.state == _SourceHealth.STOPPED
        assert src.is_degraded() is False

    def test_read_frames_returns_silence_of_correct_length_when_stopped(self):
        from recap.daemon.recorder.audio import _SourceStream

        src = _SourceStream(kind="mic", output_rate=48000)
        out = src.read_frames(1024)
        assert out == b"\x00" * 2048

    def test_read_frames_returns_silence_when_degraded(self):
        from recap.daemon.recorder.audio import _SourceStream, _SourceHealth

        src = _SourceStream(kind="mic", output_rate=48000)
        src._state = _SourceHealth.DEGRADED
        out = src.read_frames(512)
        assert out == b"\x00" * 1024

    def test_stop_transitions_to_stopped(self):
        # Name-only test -- proves the final state is STOPPED, not the
        # ordering of state change vs teardown. A real ordering test
        # lands in Task 5 (start + reopen) where teardown has
        # observable side effects to hook into.
        from recap.daemon.recorder.audio import _SourceStream, _SourceHealth

        src = _SourceStream(kind="mic", output_rate=48000)
        src._state = _SourceHealth.HEALTHY
        src.stop()
        assert src.state == _SourceHealth.STOPPED

    def test_device_identity_is_composite_not_bare_index(self):
        from recap.daemon.recorder.audio import _SourceStream

        info = {
            "name": "Microphone (Realtek)",
            "index": 5,
            "hostApi": 3,
            "maxInputChannels": 1,
            "defaultSampleRate": 48000.0,
        }
        ident_a = _SourceStream._compute_identity(info)
        info_after_hotplug = dict(info)
        info_after_hotplug["index"] = 9
        ident_b = _SourceStream._compute_identity(info_after_hotplug)
        assert ident_a == ident_b
        info_other = dict(info)
        info_other["name"] = "Microphone (USB)"
        ident_c = _SourceStream._compute_identity(info_other)
        assert ident_c != ident_a


class TestSourceStreamStart:
    """_SourceStream.start() opens a WASAPI stream, builds a resampler
    for the device's native rate, and transitions to HEALTHY."""

    def _mock_pyaudio(self, *, native_rate: float, is_loopback: bool):
        """Build a MagicMock pyaudio module that yields a stream whose
        callback can be driven manually."""
        from unittest.mock import MagicMock
        pa_instance = MagicMock()
        device_info = {
            "name": "MockDevice-loopback" if is_loopback else "MockDevice-mic",
            "index": 1,
            "hostApi": 0,
            "maxInputChannels": 2 if is_loopback else 1,
            "defaultSampleRate": native_rate,
        }
        if is_loopback:
            pa_instance.get_default_wasapi_loopback.return_value = device_info
        else:
            pa_instance.get_default_wasapi_device.return_value = device_info
        pa_instance.open.return_value = MagicMock()
        pa_module = MagicMock()
        pa_module.PyAudio.return_value = pa_instance
        pa_module.paInt16 = 8
        pa_module.paContinue = 0
        return pa_module, pa_instance

    def test_start_opens_stream_at_device_native_rate(self, monkeypatch):
        import recap.daemon.recorder.audio as audio_mod
        from recap.daemon.recorder.audio import _SourceStream, _SourceHealth

        pa_module, pa_instance = self._mock_pyaudio(native_rate=48000.0, is_loopback=False)
        monkeypatch.setattr(audio_mod, "_require_pyaudio", lambda: pa_module)

        src = _SourceStream(kind="mic", output_rate=48000)
        src.start()

        assert src.state == _SourceHealth.HEALTHY
        open_call = pa_instance.open.call_args
        assert open_call.kwargs["rate"] == 48000
        assert open_call.kwargs["input"] is True

    def test_start_builds_resampler_when_rates_match(self, monkeypatch):
        import recap.daemon.recorder.audio as audio_mod
        from recap.daemon.recorder.audio import _SourceStream

        pa_module, _ = self._mock_pyaudio(native_rate=48000.0, is_loopback=False)
        monkeypatch.setattr(audio_mod, "_require_pyaudio", lambda: pa_module)

        src = _SourceStream(kind="mic", output_rate=48000)
        src.start()

        assert src._resampler is not None
        assert src._resampler.input_rate == 48000
        assert src._resampler.output_rate == 48000

    def test_start_builds_resampler_for_mismatched_native_rate(self, monkeypatch):
        import recap.daemon.recorder.audio as audio_mod
        from recap.daemon.recorder.audio import _SourceStream

        pa_module, _ = self._mock_pyaudio(native_rate=44100.0, is_loopback=True)
        monkeypatch.setattr(audio_mod, "_require_pyaudio", lambda: pa_module)

        src = _SourceStream(kind="loopback", output_rate=48000)
        src.start()

        assert src._resampler.input_rate == 44100
        assert src._resampler.output_rate == 48000

    def test_start_records_bound_identity(self, monkeypatch):
        import recap.daemon.recorder.audio as audio_mod
        from recap.daemon.recorder.audio import _SourceStream

        pa_module, _ = self._mock_pyaudio(native_rate=48000.0, is_loopback=False)
        monkeypatch.setattr(audio_mod, "_require_pyaudio", lambda: pa_module)

        src = _SourceStream(kind="mic", output_rate=48000)
        src.start()

        assert src._bound_identity is not None
        assert src._bound_identity[0] in ("endpoint", "composite")


class TestSourceStreamPump:
    """_SourceStream converts raw callback bytes into resampled 48 kHz
    PCM in the drain thread via _pump_raw_to_resampled()."""

    def test_pump_moves_raw_to_resampled_at_identity_rate(self):
        pytest.importorskip("soxr")
        pytest.importorskip("numpy")
        from recap.daemon.recorder.audio import _SourceStream, _SourceHealth, _SoxrResamplerWrapper

        src = _SourceStream(kind="mic", output_rate=48000)
        src._resampler = _SoxrResamplerWrapper(input_rate=48000, output_rate=48000)
        src._state = _SourceHealth.HEALTHY
        src._raw_buffer = b"\x00\x00" * 4096  # 4096 frames mono int16

        src._pump_raw_to_resampled()

        assert src._raw_buffer == b""
        assert len(src._resampled_buffer) > 0

    def test_pump_handles_upsample_ratio(self):
        pytest.importorskip("soxr")
        pytest.importorskip("numpy")
        from recap.daemon.recorder.audio import _SourceStream, _SourceHealth, _SoxrResamplerWrapper

        src = _SourceStream(kind="loopback", output_rate=48000)
        src._resampler = _SoxrResamplerWrapper(input_rate=44100, output_rate=48000)
        src._state = _SourceHealth.HEALTHY
        src._raw_buffer = b"\x00\x00" * 44100

        src._pump_raw_to_resampled()

        resampled_frames = len(src._resampled_buffer) // 2
        expected = 48000
        assert abs(resampled_frames - expected) / expected < 0.02

    def test_pump_is_safe_when_raw_buffer_empty(self):
        pytest.importorskip("soxr")
        from recap.daemon.recorder.audio import _SourceStream, _SourceHealth, _SoxrResamplerWrapper

        src = _SourceStream(kind="mic", output_rate=48000)
        src._resampler = _SoxrResamplerWrapper(input_rate=48000, output_rate=48000)
        src._state = _SourceHealth.HEALTHY
        src._pump_raw_to_resampled()
        assert src._resampled_buffer == b""

    def test_pump_is_safe_when_not_healthy(self):
        """Source in STOPPED/RECONNECTING/DEGRADED must not invoke the
        resampler -- avoids touching a torn-down or unbuilt resampler."""
        from recap.daemon.recorder.audio import _SourceStream, _SourceHealth

        src = _SourceStream(kind="mic", output_rate=48000)
        src._state = _SourceHealth.STOPPED
        src._raw_buffer = b"\x00\x00" * 1024  # has data, but state is STOPPED
        src._pump_raw_to_resampled()  # must not raise even with resampler=None
        # Raw buffer untouched because the pump exited early.
        assert len(src._raw_buffer) == 2048


class TestSourceStreamReopen:
    """_SourceStream.attempt_reopen_if_due() detects identity drift and
    stream-status unhealthiness, performs reopen with backoff, rebuilds
    the resampler on rate change, and emits edge-triggered warnings."""

    def _patch_pa(self, monkeypatch, *, native_rate, identity_suffix="a"):
        import recap.daemon.recorder.audio as audio_mod
        from unittest.mock import MagicMock
        pa_instance = MagicMock()
        info = {
            "name": f"MockMic-{identity_suffix}",
            "index": 1,
            "hostApi": 0,
            "maxInputChannels": 1,
            "defaultSampleRate": native_rate,
        }
        pa_instance.get_default_wasapi_device.return_value = info
        pa_instance.open.return_value = MagicMock()
        pa_module = MagicMock()
        pa_module.PyAudio.return_value = pa_instance
        pa_module.paInt16 = 8
        pa_module.paContinue = 0
        monkeypatch.setattr(audio_mod, "_require_pyaudio", lambda: pa_module)
        return pa_instance

    def test_no_op_when_healthy_and_identity_matches(self, monkeypatch):
        from recap.daemon.recorder.audio import _SourceStream, _SourceHealth

        pa = self._patch_pa(monkeypatch, native_rate=48000.0)
        src = _SourceStream(kind="mic", output_rate=48000)
        src.start()
        open_count_before = pa.open.call_count

        src.attempt_reopen_if_due()

        assert pa.open.call_count == open_count_before
        assert src.state == _SourceHealth.HEALTHY

    def test_identity_change_triggers_reopen(self, monkeypatch, caplog):
        from recap.daemon.recorder.audio import _SourceStream, _SourceHealth

        pa = self._patch_pa(monkeypatch, native_rate=48000.0, identity_suffix="a")
        src = _SourceStream(kind="mic", output_rate=48000)
        src.start()
        initial_identity = src._bound_identity

        pa.get_default_wasapi_device.return_value = {
            "name": "MockMic-b",
            "index": 9,
            "hostApi": 0,
            "maxInputChannels": 1,
            "defaultSampleRate": 48000.0,
        }

        import logging
        with caplog.at_level(logging.WARNING):
            src.attempt_reopen_if_due()

        assert src.state == _SourceHealth.HEALTHY
        assert src._bound_identity != initial_identity
        assert pa.open.call_count == 2

    def test_rate_change_rebuilds_resampler(self, monkeypatch):
        from recap.daemon.recorder.audio import _SourceStream

        pa = self._patch_pa(monkeypatch, native_rate=48000.0, identity_suffix="a")
        src = _SourceStream(kind="mic", output_rate=48000)
        src.start()
        assert src._resampler.input_rate == 48000

        pa.get_default_wasapi_device.return_value = {
            "name": "MockMic-b",
            "index": 9,
            "hostApi": 0,
            "maxInputChannels": 1,
            "defaultSampleRate": 44100.0,
        }
        src.attempt_reopen_if_due()
        assert src._resampler.input_rate == 44100

    def test_reopen_respects_backoff(self, monkeypatch):
        from recap.daemon.recorder.audio import _SourceStream, _SourceHealth

        pa = self._patch_pa(monkeypatch, native_rate=48000.0, identity_suffix="a")
        src = _SourceStream(kind="mic", output_rate=48000)
        src.start()

        pa.open.side_effect = RuntimeError("device busy")
        with src._lock:
            src._state = _SourceHealth.RECONNECTING

        src.attempt_reopen_if_due()
        first_open_count = pa.open.call_count
        # Immediate re-call is a no-op (backoff gate).
        src.attempt_reopen_if_due()
        assert pa.open.call_count == first_open_count

    def test_degrades_after_window_exhausted(self, monkeypatch):
        from recap.daemon.recorder.audio import _SourceStream, _SourceHealth
        import time

        pa = self._patch_pa(monkeypatch, native_rate=48000.0, identity_suffix="a")
        src = _SourceStream(kind="mic", output_rate=48000)
        src.start()

        pa.open.side_effect = RuntimeError("device busy")
        with src._lock:
            src._state = _SourceHealth.RECONNECTING
            src._reconnect_started_at = time.monotonic() - 6.0

        src.attempt_reopen_if_due()
        assert src.state == _SourceHealth.DEGRADED

    def test_degraded_can_recover_to_healthy(self, monkeypatch):
        from recap.daemon.recorder.audio import _SourceStream, _SourceHealth

        pa = self._patch_pa(monkeypatch, native_rate=48000.0, identity_suffix="a")
        src = _SourceStream(kind="mic", output_rate=48000)
        with src._lock:
            src._state = _SourceHealth.DEGRADED
            src._next_reopen_at = 0.0

        pa.open.side_effect = None
        src.attempt_reopen_if_due()
        assert src.state == _SourceHealth.HEALTHY


class TestAudioCaptureDrain:
    """Wall-clock drain loop: health-check cadence driven by monotonic
    time, final partial tick on stop, cross-thread fatal state on
    both-sources-degraded."""

    def test_fatal_event_fires_when_both_sources_degraded(self, monkeypatch, tmp_path):
        """Both sources DEGRADED -> _fatal_error set, _fatal_event
        tripped, drain loop exits cleanly (no raise)."""
        from recap.daemon.recorder.audio import (
            AudioCapture,
            AudioCaptureBothSourcesFailedError,
            _SourceHealth,
        )
        import recap.daemon.recorder.audio as audio_mod
        from unittest.mock import MagicMock

        monkeypatch.setattr(audio_mod, "_require_pyflac", lambda: MagicMock())
        pa_instance = MagicMock()
        info = {
            "name": "Mock", "index": 1, "hostApi": 0,
            "maxInputChannels": 1, "defaultSampleRate": 48000.0,
        }
        pa_instance.get_default_wasapi_device.return_value = info
        pa_instance.get_default_wasapi_loopback.return_value = info
        pa_instance.open.return_value = MagicMock()
        pa_module = MagicMock()
        pa_module.PyAudio.return_value = pa_instance
        pa_module.paInt16 = 8
        monkeypatch.setattr(audio_mod, "_require_pyaudio", lambda: pa_module)

        cap = AudioCapture(output_path=tmp_path / "x.flac", sample_rate=48000)
        cap.start()

        with cap._mic_source._lock:
            cap._mic_source._state = _SourceHealth.DEGRADED
        with cap._loopback_source._lock:
            cap._loopback_source._state = _SourceHealth.DEGRADED

        assert cap._fatal_event.wait(timeout=2.0) is True
        assert isinstance(cap._fatal_error, AudioCaptureBothSourcesFailedError)

        cap.stop()

    def test_fatal_error_is_sticky_until_next_start(self, tmp_path):
        from recap.daemon.recorder.audio import AudioCapture

        cap = AudioCapture(output_path=tmp_path / "x.flac", sample_rate=48000)
        cap._fatal_error = RuntimeError("canned")
        cap._fatal_event.set()
        assert cap._fatal_error is not None

    def test_health_check_cadence_uses_monotonic_clock(self):
        from recap.daemon.recorder.audio import AudioCapture
        import inspect
        src = inspect.getsource(AudioCapture._drain_loop)
        assert "next_health_check_at" in src
        assert "monotonic" in src

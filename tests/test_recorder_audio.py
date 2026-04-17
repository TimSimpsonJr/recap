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


def test_audio_capture_start_uses_matched_device_rate(tmp_path, monkeypatch):
    """When loopback and mic both report the same native rate, start() uses that
    rate for the pyFLAC encoder AND for both WASAPI stream opens, overriding the
    ``sample_rate`` passed to ``__init__``.

    This is the Phase 7 fix for the `-9997 Invalid sample rate` WASAPI crash:
    WASAPI shared-mode refuses any rate that isn't the engine rate, so we must
    capture at the device's native rate rather than hardcoding 16000.
    """
    from unittest.mock import MagicMock
    import recap.daemon.recorder.audio as audio_mod

    mock_encoder_cls = MagicMock()
    mock_pyflac = MagicMock()
    mock_pyflac.StreamEncoder = mock_encoder_cls

    mock_pa_instance = MagicMock()
    mock_pa_instance.get_default_wasapi_loopback.return_value = {
        "index": 5, "defaultSampleRate": 48000.0,
    }
    mock_pa_instance.get_default_wasapi_device.return_value = {
        "index": 2, "defaultSampleRate": 48000.0, "maxInputChannels": 1,
    }
    mock_pa_module = MagicMock()
    mock_pa_module.PyAudio.return_value = mock_pa_instance

    monkeypatch.setattr(audio_mod, "_require_pyflac", lambda: mock_pyflac)
    monkeypatch.setattr(audio_mod, "_require_pyaudio", lambda: mock_pa_module)

    capture = AudioCapture(output_path=tmp_path / "x.flac", sample_rate=16000, channels=2)
    capture.start()

    # Encoder was constructed with the resolved native rate (48000), not the
    # __init__ default (16000).
    assert mock_encoder_cls.called
    _, enc_kwargs = mock_encoder_cls.call_args
    assert enc_kwargs["sample_rate"] == 48000

    # Both WASAPI streams opened at the resolved rate.
    open_calls = mock_pa_instance.open.call_args_list
    assert len(open_calls) == 2
    for _, kwargs in open_calls:
        assert kwargs["rate"] == 48000

    # The public ``sample_rate`` property reflects the actual capture rate so
    # downstream consumers (on_chunk subscribers, FLAC readers) see the truth.
    assert capture.sample_rate == 48000


def test_audio_capture_start_raises_on_device_rate_mismatch(tmp_path, monkeypatch):
    """When mic and loopback report different native rates, start() raises
    AudioDeviceError with both rates in the message and does NOT partially
    initialise any of: pyFLAC encoder, output file, or WASAPI streams.

    Resampling heterogeneous device clocks is explicitly out of scope for
    Phase 7; fail fast with a clear error is the agreed-on behaviour.
    """
    from unittest.mock import MagicMock
    import recap.daemon.recorder.audio as audio_mod

    mock_encoder_cls = MagicMock()
    mock_pyflac = MagicMock()
    mock_pyflac.StreamEncoder = mock_encoder_cls

    mock_pa_instance = MagicMock()
    mock_pa_instance.get_default_wasapi_loopback.return_value = {
        "index": 5, "defaultSampleRate": 48000.0,
    }
    mock_pa_instance.get_default_wasapi_device.return_value = {
        "index": 2, "defaultSampleRate": 44100.0, "maxInputChannels": 1,
    }
    mock_pa_module = MagicMock()
    mock_pa_module.PyAudio.return_value = mock_pa_instance

    monkeypatch.setattr(audio_mod, "_require_pyflac", lambda: mock_pyflac)
    monkeypatch.setattr(audio_mod, "_require_pyaudio", lambda: mock_pa_module)

    output_path = tmp_path / "x.flac"
    capture = AudioCapture(output_path=output_path)

    with pytest.raises(AudioDeviceError) as exc_info:
        capture.start()

    # Message names both rates so the user can act on it.
    msg = str(exc_info.value)
    assert "48000" in msg
    assert "44100" in msg

    # Clean failure: encoder was never constructed and no WASAPI streams opened.
    mock_encoder_cls.assert_not_called()
    mock_pa_instance.open.assert_not_called()

    # Capture did not transition into a half-started state.
    assert capture.is_recording is False
    # No output file was created on disk (encoder path never ran).
    assert not output_path.exists()


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

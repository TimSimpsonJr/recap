"""Tests for audio capture module."""

import pytest
from pathlib import Path
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

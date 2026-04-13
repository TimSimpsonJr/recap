"""Tests for silence detection."""
import time
from recap.daemon.recorder.silence import SilenceDetector


class TestSilenceDetector:
    def test_not_silent_initially(self):
        detector = SilenceDetector(threshold_db=-40, timeout_seconds=5)
        assert detector.is_silent is False
        assert detector.silence_duration == 0.0

    def test_becomes_silent_after_timeout(self):
        detector = SilenceDetector(threshold_db=-40, timeout_seconds=0.1)
        for _ in range(20):
            detector.update(rms_level=0.0001)  # well below -40dB
            time.sleep(0.01)
        assert detector.is_silent is True

    def test_resets_on_audio(self):
        detector = SilenceDetector(threshold_db=-40, timeout_seconds=0.1)
        for _ in range(20):
            detector.update(rms_level=0.0001)
            time.sleep(0.01)
        assert detector.is_silent is True
        detector.update(rms_level=0.5)  # loud audio
        assert detector.is_silent is False
        assert detector.silence_duration == 0.0

    def test_silence_duration_tracks_seconds(self):
        detector = SilenceDetector(threshold_db=-40, timeout_seconds=300)
        detector.update(rms_level=0.0001)
        time.sleep(0.05)
        detector.update(rms_level=0.0001)
        assert 0.04 < detector.silence_duration < 0.5

    def test_reset_clears_state(self):
        detector = SilenceDetector(threshold_db=-40, timeout_seconds=0.1)
        for _ in range(20):
            detector.update(rms_level=0.0001)
            time.sleep(0.01)
        assert detector.is_silent is True
        detector.reset()
        assert detector.is_silent is False
        assert detector.silence_duration == 0.0

    def test_threshold_conversion(self):
        # -40 dB should be 0.01 in linear
        detector = SilenceDetector(threshold_db=-40, timeout_seconds=5)
        assert abs(detector._threshold_linear - 0.01) < 0.001

    def test_audio_above_threshold_not_silent(self):
        detector = SilenceDetector(threshold_db=-40, timeout_seconds=0.01)
        for _ in range(20):
            detector.update(rms_level=0.1)  # well above -40dB
            time.sleep(0.01)
        assert detector.is_silent is False

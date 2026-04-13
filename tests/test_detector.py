"""Tests for detection polling loop."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from recap.daemon.recorder.detector import MeetingDetector
from recap.daemon.recorder.detection import MeetingWindow


class TestMeetingDetector:
    @pytest.fixture
    def mock_config(self):
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

    def test_enabled_platforms(self, mock_config):
        detector = MeetingDetector(config=mock_config, recorder=MagicMock())
        assert "teams" in detector.enabled_platforms
        assert "zoom" in detector.enabled_platforms
        assert "signal" in detector.enabled_platforms

    def test_disabled_platform_excluded(self, mock_config):
        mock_config.detection.teams.enabled = False
        detector = MeetingDetector(config=mock_config, recorder=MagicMock())
        assert "teams" not in detector.enabled_platforms

    def test_get_behavior(self, mock_config):
        detector = MeetingDetector(config=mock_config, recorder=MagicMock())
        assert detector.get_behavior("teams") == "auto-record"
        assert detector.get_behavior("signal") == "prompt"

    def test_get_default_org(self, mock_config):
        detector = MeetingDetector(config=mock_config, recorder=MagicMock())
        assert detector.get_default_org("teams") == "disbursecloud"
        assert detector.get_default_org("signal") == "personal"

    def test_auto_record_starts_recorder(self, mock_config):
        mock_recorder = MagicMock()
        mock_recorder.is_recording = False
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)

        meeting = MeetingWindow(hwnd=1, title="Sprint | Microsoft Teams", platform="teams")
        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[meeting]):
            with patch("recap.daemon.recorder.detector.enrich_meeting_metadata", return_value={"title": "Sprint", "participants": [], "platform": "teams"}):
                detector._poll_once()

        mock_recorder.start.assert_called_once_with("disbursecloud")

    def test_prompt_behavior_calls_callback(self, mock_config):
        mock_recorder = MagicMock()
        mock_recorder.is_recording = False
        on_signal = MagicMock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder, on_signal_detected=on_signal)

        meeting = MeetingWindow(hwnd=1, title="Signal", platform="signal")
        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[meeting]):
            with patch("recap.daemon.recorder.detector.enrich_meeting_metadata", return_value={"title": "Signal Call", "participants": [], "platform": "signal"}):
                detector._poll_once()

        on_signal.assert_called_once()
        mock_recorder.start.assert_not_called()

    def test_does_not_retrigger_same_meeting(self, mock_config):
        mock_recorder = MagicMock()
        mock_recorder.is_recording = False
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)

        meeting = MeetingWindow(hwnd=1, title="Sprint | Microsoft Teams", platform="teams")
        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[meeting]):
            with patch("recap.daemon.recorder.detector.enrich_meeting_metadata", return_value={"title": "Sprint", "participants": [], "platform": "teams"}):
                detector._poll_once()
                mock_recorder.start.reset_mock()
                # Second poll with same meeting
                mock_recorder.is_recording = True  # now recording
                detector._poll_once()

        mock_recorder.start.assert_not_called()  # should not trigger again

    def test_does_not_start_when_already_recording(self, mock_config):
        mock_recorder = MagicMock()
        mock_recorder.is_recording = True  # already recording
        detector = MeetingDetector(config=mock_config, recorder=MagicMock())

        meeting = MeetingWindow(hwnd=1, title="Sprint | Microsoft Teams", platform="teams")
        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[meeting]):
            with patch("recap.daemon.recorder.detector.enrich_meeting_metadata", return_value={"title": "Sprint", "participants": [], "platform": "teams"}):
                detector._poll_once()

        mock_recorder.start.assert_not_called()

    def test_cleans_up_closed_windows(self, mock_config):
        mock_recorder = MagicMock()
        mock_recorder.is_recording = False
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)

        meeting = MeetingWindow(hwnd=1, title="Sprint | Microsoft Teams", platform="teams")
        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[meeting]):
            with patch("recap.daemon.recorder.detector.enrich_meeting_metadata", return_value={"title": "Sprint", "participants": [], "platform": "teams"}):
                detector._poll_once()

        assert 1 in detector._tracked_meetings

        # Second poll: window is gone
        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[]):
            detector._poll_once()

        assert 1 not in detector._tracked_meetings

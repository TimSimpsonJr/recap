"""Tests for meeting window detection."""
import pytest
from unittest.mock import patch
from recap.daemon.recorder.detection import (
    MeetingWindow,
    detect_meeting_windows,
    MEETING_PATTERNS,
)


class TestMeetingPatterns:
    def test_teams_call_matches(self):
        assert MEETING_PATTERNS["teams"].search("Call with Bob | Microsoft Teams")

    def test_teams_meeting_matches(self):
        assert MEETING_PATTERNS["teams"].search("Sprint Planning | Microsoft Teams")

    def test_teams_main_window_does_not_match(self):
        # The main Teams window (no active call) should NOT match
        assert not MEETING_PATTERNS["teams"].search("Microsoft Teams")

    def test_zoom_meeting_matches(self):
        assert MEETING_PATTERNS["zoom"].search("Zoom Meeting")

    def test_zoom_webinar_matches(self):
        assert MEETING_PATTERNS["zoom"].search("Zoom Webinar")

    def test_signal_matches(self):
        assert MEETING_PATTERNS["signal"].search("Signal")

    def test_notepad_does_not_match(self):
        for pattern in MEETING_PATTERNS.values():
            assert not pattern.search("Notepad")


class TestDetectMeetingWindows:
    def test_returns_meeting_windows(self):
        mock_windows = [
            (12345, "Sprint Planning | Microsoft Teams"),
        ]
        with patch("recap.daemon.recorder.detection._enumerate_windows", return_value=mock_windows):
            meetings = detect_meeting_windows()
        assert len(meetings) == 1
        assert meetings[0].platform == "teams"
        assert meetings[0].hwnd == 12345

    def test_ignores_non_meeting_windows(self):
        mock_windows = [
            (1, "Notepad"),
            (2, "Chrome - Google"),
        ]
        with patch("recap.daemon.recorder.detection._enumerate_windows", return_value=mock_windows):
            meetings = detect_meeting_windows()
        assert len(meetings) == 0

    def test_detects_multiple_platforms(self):
        mock_windows = [
            (1, "Meeting with Jane | Microsoft Teams"),
            (2, "Zoom Meeting"),
        ]
        with patch("recap.daemon.recorder.detection._enumerate_windows", return_value=mock_windows):
            meetings = detect_meeting_windows()
        platforms = {m.platform for m in meetings}
        assert "teams" in platforms
        assert "zoom" in platforms

    def test_respects_enabled_platforms(self):
        mock_windows = [
            (1, "Meeting | Microsoft Teams"),
            (2, "Zoom Meeting"),
        ]
        with patch("recap.daemon.recorder.detection._enumerate_windows", return_value=mock_windows):
            meetings = detect_meeting_windows(enabled_platforms={"zoom"})
        assert len(meetings) == 1
        assert meetings[0].platform == "zoom"

    def test_empty_windows(self):
        with patch("recap.daemon.recorder.detection._enumerate_windows", return_value=[]):
            meetings = detect_meeting_windows()
        assert len(meetings) == 0

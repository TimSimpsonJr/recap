"""Tests for meeting window detection."""
from unittest.mock import patch
from recap.daemon.recorder.detection import (
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


def test_is_window_alive_returns_false_for_closed_hwnd(monkeypatch):
    import recap.daemon.recorder.detection as det
    monkeypatch.setattr(det.win32gui, "IsWindow", lambda h: False)
    assert det.is_window_alive(999) is False


def test_detect_meeting_windows_excludes_unconfirmed_candidates(monkeypatch):
    import recap.daemon.recorder.detection as det
    monkeypatch.setattr(det, "_enumerate_windows", lambda: [(42, "Standup | Microsoft Teams")])
    monkeypatch.setattr(det.call_state, "is_call_active", lambda h, p: False)
    result = det.detect_meeting_windows({"teams"})
    assert result == []


def test_excluded_hwnds_do_not_match_any_platform(monkeypatch):
    import recap.daemon.recorder.detection as det
    monkeypatch.setattr(det, "_enumerate_windows", lambda: [(42, "Signal call detected")])
    det.exclude_hwnd(42)
    try:
        result = det.detect_meeting_windows({"signal"})
    finally:
        det.include_hwnd(42)
    assert result == []


def test_exclude_include_are_symmetric():
    import recap.daemon.recorder.detection as det
    det.exclude_hwnd(123)
    assert 123 in det._EXCLUDED_HWNDS
    det.include_hwnd(123)
    assert 123 not in det._EXCLUDED_HWNDS


class TestEnumerationInstrumentation:
    """Pre-regex diagnostic logging for issue #30.

    Surfaces Teams-substring windows that didn't match the platform regex.
    Without these, a regex-is-the-broken-gate failure is invisible in logs.
    """

    def test_logs_enumeration_summary_each_poll(self, monkeypatch, caplog):
        import logging
        import recap.daemon.recorder.detection as det
        mock_windows = [
            (1, "Notepad"),
            (2, "Microsoft Teams"),
            (3, "Standup | Microsoft Teams"),
            (4, "Chrome - Google"),
        ]
        monkeypatch.setattr(det, "_enumerate_windows", lambda: mock_windows)
        monkeypatch.setattr(det.call_state, "is_call_active", lambda h, p: True)

        with caplog.at_level(logging.DEBUG, logger="recap.daemon.recorder.detection"):
            det.detect_meeting_windows({"teams"})

        summary_lines = [
            r.getMessage() for r in caplog.records
            if "window_enumeration" in r.getMessage()
        ]
        assert len(summary_lines) == 1, f"expected 1 summary line, got {summary_lines}"
        line = summary_lines[0]
        assert "total=4" in line
        assert "teams_substring_count=2" in line
        assert "teams_regex_matched_count=1" in line

    def test_logs_teams_candidate_when_substring_matches_but_regex_does_not(
        self, monkeypatch, caplog,
    ):
        import logging
        import recap.daemon.recorder.detection as det
        mock_windows = [
            (1, "Microsoft Teams"),            # idle main window, substring hit, regex miss
            (2, "Chat | Microsoft Teams"),     # regex hit
            (3, "Notepad"),                    # unrelated
        ]
        monkeypatch.setattr(det, "_enumerate_windows", lambda: mock_windows)
        monkeypatch.setattr(det.call_state, "is_call_active", lambda h, p: True)

        with caplog.at_level(logging.DEBUG, logger="recap.daemon.recorder.detection"):
            det.detect_meeting_windows({"teams"})

        candidate_lines = [
            r.getMessage() for r in caplog.records
            if "enumerated_teams_candidate" in r.getMessage()
        ]
        # Only hwnd=1: substring yes, regex no.
        assert len(candidate_lines) == 1, f"expected 1 candidate line, got {candidate_lines}"
        line = candidate_lines[0]
        assert "hwnd=1" in line
        assert "regex_matched=false" in line
        # Title is rendered via %r so it's single-line and unambiguous.
        assert "title='Microsoft Teams'" in line

    def test_substring_check_is_case_insensitive(self, monkeypatch, caplog):
        """New Teams variants with lowercase branding still surface as candidates."""
        import logging
        import recap.daemon.recorder.detection as det
        mock_windows = [(1, "microsoft teams (dev)")]
        monkeypatch.setattr(det, "_enumerate_windows", lambda: mock_windows)
        monkeypatch.setattr(det.call_state, "is_call_active", lambda h, p: True)

        with caplog.at_level(logging.DEBUG, logger="recap.daemon.recorder.detection"):
            det.detect_meeting_windows({"teams"})

        messages = [r.getMessage() for r in caplog.records]
        summary = next(m for m in messages if "window_enumeration" in m)
        assert "teams_substring_count=1" in summary
        assert "teams_regex_matched_count=0" in summary
        candidates = [m for m in messages if "enumerated_teams_candidate" in m]
        assert len(candidates) == 1


class TestDetectionGateInstrumentation:
    """detection_gate log lines for each regex-matched window, recording
    whether both gates passed (outcome=detected) or the call-state gate
    filtered the window (outcome=filtered, reason=call_state_inactive).
    """

    def test_logs_detection_gate_outcome_detected(self, monkeypatch, caplog):
        import logging
        import recap.daemon.recorder.detection as det
        monkeypatch.setattr(
            det, "_enumerate_windows",
            lambda: [(42, "Standup | Microsoft Teams")],
        )
        monkeypatch.setattr(det.call_state, "is_call_active", lambda h, p: True)

        with caplog.at_level(logging.DEBUG, logger="recap.daemon.recorder.detection"):
            result = det.detect_meeting_windows({"teams"})

        assert len(result) == 1
        gate_lines = [
            r.getMessage() for r in caplog.records
            if "detection_gate" in r.getMessage()
        ]
        assert len(gate_lines) == 1
        line = gate_lines[0]
        assert "platform=teams" in line
        assert "hwnd=42" in line
        assert "title_matched=true" in line
        assert "call_state_active=true" in line
        assert "outcome=detected" in line
        assert "title='Standup | Microsoft Teams'" in line

    def test_logs_detection_gate_outcome_filtered_by_call_state(
        self, monkeypatch, caplog,
    ):
        import logging
        import recap.daemon.recorder.detection as det
        monkeypatch.setattr(
            det, "_enumerate_windows",
            lambda: [(99, "Sprint Planning | Microsoft Teams")],
        )
        monkeypatch.setattr(det.call_state, "is_call_active", lambda h, p: False)

        with caplog.at_level(logging.DEBUG, logger="recap.daemon.recorder.detection"):
            result = det.detect_meeting_windows({"teams"})

        assert result == []
        gate_lines = [
            r.getMessage() for r in caplog.records
            if "detection_gate" in r.getMessage()
        ]
        assert len(gate_lines) == 1
        line = gate_lines[0]
        assert "platform=teams" in line
        assert "hwnd=99" in line
        assert "title_matched=true" in line
        assert "call_state_active=false" in line
        assert "outcome=filtered" in line
        assert "reason=call_state_inactive" in line

    def test_no_gate_line_for_non_matching_window(self, monkeypatch, caplog):
        """Windows that fail the regex do not generate detection_gate lines
        (they may still generate enumerated_teams_candidate for diagnostic)."""
        import logging
        import recap.daemon.recorder.detection as det
        monkeypatch.setattr(
            det, "_enumerate_windows",
            lambda: [(1, "Notepad"), (2, "Microsoft Teams")],
        )
        monkeypatch.setattr(det.call_state, "is_call_active", lambda h, p: True)

        with caplog.at_level(logging.DEBUG, logger="recap.daemon.recorder.detection"):
            det.detect_meeting_windows({"teams"})

        gate_lines = [
            r.getMessage() for r in caplog.records
            if "detection_gate" in r.getMessage()
        ]
        assert gate_lines == []

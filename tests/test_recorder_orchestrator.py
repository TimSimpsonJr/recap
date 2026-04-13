"""Tests for recorder orchestrator."""
import pathlib
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from recap.daemon.recorder.recorder import Recorder
from recap.daemon.recorder.state_machine import RecorderState


class TestRecorder:
    @pytest.fixture
    def recorder(self, tmp_path):
        return Recorder(
            recordings_path=tmp_path,
            sample_rate=16000,
            channels=2,
            silence_timeout_minutes=5,
            max_duration_hours=4,
        )

    def test_generates_unique_filename(self, recorder):
        path = recorder._generate_recording_path("disbursecloud")
        assert path.suffix == ".flac"
        assert "disbursecloud" in path.stem

    def test_filename_includes_date(self, recorder):
        path = recorder._generate_recording_path("personal")
        import re
        assert re.search(r"\d{4}-\d{2}-\d{2}", path.stem)

    def test_is_recording_false_initially(self, recorder):
        assert recorder.is_recording is False

    def test_current_recording_path_none_when_idle(self, recorder):
        assert recorder.current_recording_path is None

    def test_state_is_idle_initially(self, recorder):
        assert recorder.state_machine.state == RecorderState.IDLE

    def test_disk_space_check(self, recorder):
        # Should return True on most dev machines (>1GB free)
        assert recorder._check_disk_space() is True

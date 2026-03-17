"""Tests for frame extraction module."""
import pathlib
import json
from unittest.mock import patch, MagicMock

import pytest

from recap.frames import extract_frames, _parse_scene_timestamps, FrameResult


class TestParseSceneTimestamps:
    def test_parse_ffprobe_output(self):
        ffprobe_output = "0.000000\n5.234000\n12.567000\n"
        timestamps = _parse_scene_timestamps(ffprobe_output)
        assert timestamps == [0.0, 5.234, 12.567]

    def test_parse_empty_output(self):
        timestamps = _parse_scene_timestamps("")
        assert timestamps == []

    def test_parse_with_trailing_newlines(self):
        timestamps = _parse_scene_timestamps("1.5\n\n\n")
        assert timestamps == [1.5]


class TestExtractFrames:
    @patch("recap.frames.subprocess")
    def test_extract_returns_frame_results(self, mock_sub, tmp_path: pathlib.Path):
        video_file = tmp_path / "meeting.mp4"
        video_file.write_bytes(b"fake video")
        out_dir = tmp_path / "frames"
        out_dir.mkdir()

        # Mock ffprobe for scene detection
        mock_probe = MagicMock()
        mock_probe.stdout = "2.5\n10.0\n"
        mock_probe.returncode = 0

        # Mock ffmpeg for frame extraction
        mock_extract = MagicMock()
        mock_extract.returncode = 0

        mock_sub.run.side_effect = [mock_probe, mock_extract, mock_extract]

        # Create the frames that ffmpeg would create
        (out_dir / "meeting-002.500.png").write_bytes(b"fake png")
        (out_dir / "meeting-010.000.png").write_bytes(b"fake png")

        results = extract_frames(video_file, out_dir)
        assert len(results) == 2
        assert results[0].timestamp == 2.5
        assert results[1].timestamp == 10.0

    @patch("recap.frames.subprocess")
    def test_extract_audio_only_returns_empty(self, mock_sub, tmp_path: pathlib.Path):
        audio_file = tmp_path / "meeting.wav"
        audio_file.write_bytes(b"fake audio")
        out_dir = tmp_path / "frames"
        out_dir.mkdir()

        mock_probe = MagicMock()
        mock_probe.stdout = ""
        mock_probe.returncode = 1

        mock_sub.run.return_value = mock_probe

        results = extract_frames(audio_file, out_dir)
        assert results == []

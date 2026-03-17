"""Tests for CLI test harness."""
import json
import pathlib
from unittest.mock import patch, MagicMock

import pytest

from recap.cli import main, _parse_args


class TestParseArgs:
    def test_process_command(self):
        args = _parse_args(["process", "meeting.mp4", "meeting.json", "--config", "config.yaml"])
        assert args.command == "process"
        assert args.audio == "meeting.mp4"
        assert args.metadata == "meeting.json"
        assert args.config == "config.yaml"

    def test_retry_todoist_command(self):
        args = _parse_args(["retry-todoist", "--config", "config.yaml"])
        assert args.command == "retry-todoist"


class TestMain:
    @patch("recap.cli.run_pipeline")
    @patch("recap.cli.load_config")
    def test_process_calls_pipeline(self, mock_load_config, mock_run, tmp_path):
        config = MagicMock()
        mock_load_config.return_value = config
        mock_run.return_value = {
            "meeting_note": tmp_path / "note.md",
            "todoist_tasks": ["1"],
            "profiles_created": [],
            "frames": [],
        }

        audio = tmp_path / "meeting.mp4"
        audio.write_bytes(b"fake")
        meta = tmp_path / "meeting.json"
        meta.write_text('{"title":"test","date":"2026-03-16","participants":[],"platform":"zoom"}')
        config_file = tmp_path / "config.yaml"
        config_file.write_text("vault_path: test")

        with patch("sys.argv", ["recap", "process", str(audio), str(meta), "--config", str(config_file)]):
            main()

        mock_run.assert_called_once()

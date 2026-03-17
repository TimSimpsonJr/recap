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

    @patch("recap.todoist.TodoistAPI")
    @patch("recap.cli.load_config")
    def test_retry_todoist_calls_create_tasks(self, mock_load_config, mock_api_cls, tmp_path):
        """Test that retry-todoist actually calls create_tasks with retry items."""
        config = MagicMock()
        config.user_name = "Tim"
        config.todoist.api_token = "test_token"
        config.todoist.default_project = "Recap"
        config.vault_path.name = "TestVault"
        retry_path = tmp_path / "todoist-retry.json"
        config.retry_path = retry_path

        # Write retry items
        retry_items = [
            {
                "description": "Send proposal",
                "due_date": "2026-03-20",
                "priority": "high",
                "project": "Client Work",
                "note_path": "Work/Meetings/2026-03-16 - Kickoff.md",
            }
        ]
        retry_path.write_text(json.dumps(retry_items))

        mock_load_config.return_value = config

        # Mock the Todoist API
        mock_api = MagicMock()
        mock_api_cls.return_value = mock_api
        mock_task = MagicMock()
        mock_task.id = "456"
        mock_api.add_task.return_value = mock_task
        mock_api.get_projects.return_value = []
        mock_api.get_tasks.return_value = []

        config_file = tmp_path / "config.yaml"
        config_file.write_text("vault_path: test")

        main(["retry-todoist", "--config", str(config_file)])

        # Verify create_tasks was called (via the API)
        mock_api.add_task.assert_called_once()
        # Verify retry file was cleared
        assert not retry_path.exists()

    @patch("recap.cli.load_config")
    def test_retry_todoist_no_pending(self, mock_load_config, tmp_path):
        """Test retry-todoist with no pending items exits cleanly."""
        config = MagicMock()
        retry_path = tmp_path / "todoist-retry.json"
        config.retry_path = retry_path
        mock_load_config.return_value = config

        config_file = tmp_path / "config.yaml"
        config_file.write_text("vault_path: test")

        # Should not raise
        main(["retry-todoist", "--config", str(config_file)])

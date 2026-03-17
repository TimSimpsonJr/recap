"""Tests for Todoist integration."""
import json
import pathlib
from unittest.mock import MagicMock, patch

import pytest

from recap.models import ActionItem, AnalysisResult, KeyPoint, ProfileStub
from recap.todoist import (
    create_tasks,
    _filter_user_items,
    _build_obsidian_uri,
    save_retry_file,
    load_retry_file,
)


@pytest.fixture
def action_items() -> list[ActionItem]:
    return [
        ActionItem(assignee="Tim", description="Send proposal", due_date="2026-03-20", priority="high"),
        ActionItem(assignee="Jane Smith", description="Review budget", due_date=None, priority="normal"),
        ActionItem(assignee="Tim", description="Book room", due_date="next Monday", priority="low"),
    ]


class TestFilterUserItems:
    def test_filters_to_user_only(self, action_items):
        filtered = _filter_user_items(action_items, "Tim")
        assert len(filtered) == 2
        assert all(item.assignee == "Tim" for item in filtered)

    def test_case_insensitive(self, action_items):
        filtered = _filter_user_items(action_items, "tim")
        assert len(filtered) == 2


class TestBuildObsidianUri:
    def test_builds_uri(self):
        uri = _build_obsidian_uri(
            vault_name="Tim's Vault",
            note_path="Work/Meetings/2026-03-16 - Kickoff.md",
        )
        assert "obsidian://open" in uri
        assert "Tim's%20Vault" in uri or "Tim%27s%20Vault" in uri
        assert "Kickoff" in uri


class TestCreateTasks:
    @patch("recap.todoist.TodoistAPI")
    def test_creates_tasks_for_user_items(self, mock_api_cls, action_items):
        mock_api = MagicMock()
        mock_api_cls.return_value = mock_api
        mock_task = MagicMock()
        mock_task.id = "123"
        mock_api.add_task.return_value = mock_task

        # Mock get_projects for project lookup
        mock_project = MagicMock()
        mock_project.id = "proj_1"
        mock_project.name = "Client Work"
        mock_api.get_projects.return_value = [mock_project]

        task_ids = create_tasks(
            action_items=action_items,
            user_name="Tim",
            api_token="test_token",
            project_name="Client Work",
            vault_name="Tim's Vault",
            note_path="Work/Meetings/2026-03-16 - Kickoff.md",
        )

        assert len(task_ids) == 2
        assert mock_api.add_task.call_count == 2

    @patch("recap.todoist.TodoistAPI")
    def test_skips_when_no_user_items(self, mock_api_cls, action_items):
        mock_api = MagicMock()
        mock_api_cls.return_value = mock_api

        task_ids = create_tasks(
            action_items=action_items,
            user_name="Bob",
            api_token="test_token",
            project_name="Recap",
            vault_name="Vault",
            note_path="note.md",
        )

        assert task_ids == []
        mock_api.add_task.assert_not_called()


class TestRetryFile:
    def test_save_and_load(self, tmp_path):
        retry_path = tmp_path / "retry.json"
        items = [
            {"description": "Send proposal", "project": "Client Work", "note_path": "test.md"},
        ]
        save_retry_file(items, retry_path)
        assert retry_path.exists()

        loaded = load_retry_file(retry_path)
        assert len(loaded) == 1
        assert loaded[0]["description"] == "Send proposal"

    def test_load_missing_file_returns_empty(self, tmp_path):
        loaded = load_retry_file(tmp_path / "nonexistent.json")
        assert loaded == []

    def test_save_appends(self, tmp_path):
        retry_path = tmp_path / "retry.json"
        save_retry_file([{"a": 1}], retry_path)
        save_retry_file([{"b": 2}], retry_path)
        loaded = load_retry_file(retry_path)
        assert len(loaded) == 2

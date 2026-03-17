"""Todoist task creation from meeting action items."""
from __future__ import annotations

import json
import logging
import pathlib
from urllib.parse import quote

from recap.models import ActionItem

logger = logging.getLogger(__name__)

try:
    from todoist_api_python.api import TodoistAPI
except ImportError:
    TodoistAPI = None  # type: ignore[assignment, misc]


def _filter_user_items(items: list[ActionItem], user_name: str) -> list[ActionItem]:
    return [item for item in items if item.assignee.lower() == user_name.lower()]


def _build_obsidian_uri(vault_name: str, note_path: str) -> str:
    encoded_vault = quote(vault_name)
    encoded_path = quote(note_path)
    return f"obsidian://open?vault={encoded_vault}&file={encoded_path}"


def create_tasks(
    action_items: list[ActionItem],
    user_name: str,
    api_token: str,
    project_name: str,
    vault_name: str,
    note_path: str,
) -> list[str]:
    user_items = _filter_user_items(action_items, user_name)
    if not user_items:
        logger.info("No action items assigned to %s", user_name)
        return []

    if TodoistAPI is None:
        raise ImportError(
            "todoist-api-python is not installed. Install with: uv sync --extra todoist"
        )

    api = TodoistAPI(api_token)
    obsidian_link = _build_obsidian_uri(vault_name, note_path)

    # Find project ID
    project_id = None
    try:
        projects = api.get_projects()
        for proj in projects:
            if proj.name == project_name:
                project_id = proj.id
                break
    except Exception as e:
        logger.warning("Failed to fetch projects, using default: %s", e)

    task_ids = []
    for item in user_items:
        try:
            kwargs = {
                "content": item.description,
                "description": f"From meeting: {obsidian_link}",
                "labels": ["recap"],
            }
            if project_id:
                kwargs["project_id"] = project_id
            if item.due_date:
                kwargs["due_string"] = item.due_date
            if item.priority == "high":
                kwargs["priority"] = 4
            elif item.priority == "low":
                kwargs["priority"] = 2
            else:
                kwargs["priority"] = 3

            task = api.add_task(**kwargs)
            task_ids.append(task.id)
            logger.info("Created Todoist task: %s (id=%s)", item.description, task.id)
        except Exception as e:
            logger.error("Failed to create task '%s': %s", item.description, e)

    return task_ids


def save_retry_file(items: list[dict], path: pathlib.Path) -> None:
    existing = load_retry_file(path)
    existing.extend(items)
    path.write_text(json.dumps(existing, indent=2))
    logger.info("Saved %d items to retry file: %s", len(items), path)


def load_retry_file(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []

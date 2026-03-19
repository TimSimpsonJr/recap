"""Todoist task creation from meeting action items."""
from __future__ import annotations

import json
import logging
import pathlib
from datetime import datetime, timezone
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


def _save_task_mapping(meeting_dir: pathlib.Path, tasks: list[dict]) -> None:
    """Save Todoist task ID mapping for completion sync."""
    path = meeting_dir / "todoist_tasks.json"
    existing = []
    if path.exists():
        try:
            data = json.loads(path.read_text())
            existing = data.get("tasks", [])
        except (json.JSONDecodeError, KeyError):
            pass

    data = {
        "tasks": existing + tasks,
        "last_synced": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(data, indent=2))
    logger.info("Saved %d task mappings to %s", len(tasks), path)


def _resolve_project(
    api: "TodoistAPI",
    grouping: str,
    default_project_name: str,
    company_name: str | None,
    meeting_title: str,
) -> str | None:
    """Resolve the Todoist project ID based on grouping strategy."""
    if grouping == "company" and company_name:
        project_name = f"Recap: {company_name}"
    elif grouping == "meeting":
        project_name = f"Recap: {meeting_title}"
    else:
        project_name = default_project_name

    # Look up or create project
    try:
        projects = api.get_projects()
        for proj in projects:
            if proj.name == project_name:
                return proj.id
    except Exception as e:
        logger.warning("Failed to fetch projects: %s", e)
        return None

    try:
        new_proj = api.add_project(name=project_name)
        return new_proj.id
    except Exception as e:
        logger.warning("Failed to create project '%s': %s", project_name, e)
        return None


def create_tasks(
    action_items: list[ActionItem],
    user_name: str,
    api_token: str,
    project_name: str,
    vault_name: str,
    note_path: str,
    meeting_dir: pathlib.Path | None = None,
    grouping: str = "single",
    company_name: str | None = None,
    meeting_title: str = "",
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

    # Resolve project ID based on grouping strategy
    project_id = _resolve_project(
        api, grouping, project_name, company_name, meeting_title
    )

    # Fetch existing tasks for idempotency check
    existing_contents: set[str] = set()
    try:
        existing_tasks = api.get_tasks(label="recap")
        existing_contents = {t.content for t in existing_tasks}
    except Exception as e:
        logger.warning("Failed to fetch existing tasks for idempotency check: %s", e)

    task_ids = []
    task_records = []
    errors = []
    for item in user_items:
        # Idempotency: skip if a task with the same content already exists
        if item.description in existing_contents:
            logger.info("Skipping duplicate task: %s", item.description)
            continue

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
            task_records.append({
                "todoist_id": task.id,
                "description": item.description,
                "project_id": project_id or "",
            })
            logger.info("Created Todoist task: %s (id=%s)", item.description, task.id)
        except Exception as e:
            logger.error("Failed to create task '%s': %s", item.description, e)
            errors.append((item.description, str(e)))

    if task_records and meeting_dir:
        _save_task_mapping(meeting_dir, task_records)

    if errors:
        failed_descriptions = [desc for desc, _ in errors]
        logger.warning(
            "Failed to create %d task(s): %s", len(errors), ", ".join(failed_descriptions)
        )

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

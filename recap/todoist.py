"""Todoist task creation and completion sync from meeting action items."""
from __future__ import annotations

import json
import logging
import pathlib
import time
from datetime import datetime, timezone
from urllib.parse import quote

from recap.models import ActionItem

logger = logging.getLogger(__name__)

try:
    from todoist_api_python.api import TodoistAPI
except ImportError:
    TodoistAPI = None  # type: ignore[assignment, misc]


class RateLimiter:
    """Simple rate limiter for API calls."""

    def __init__(self, calls_per_second: float = 8):
        self.min_interval = 1.0 / calls_per_second
        self.last_call = 0.0

    def wait(self):
        elapsed = time.monotonic() - self.last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call = time.monotonic()


def _update_vault_checkbox(
    note_path: pathlib.Path,
    description: str,
    checked: bool = False,
    strikethrough: bool = False,
) -> None:
    """Update a checkbox in a vault note for a matching action item."""
    content = note_path.read_text(encoding="utf-8")

    if checked:
        new_mark = "- [x]"
    elif strikethrough:
        new_mark = "- [~]"
    else:
        return

    lines = content.split("\n")
    for i, line in enumerate(lines):
        if description in line and line.strip().startswith("- [ ]"):
            lines[i] = line.replace("- [ ]", new_mark, 1)
            break

    note_path.write_text("\n".join(lines), encoding="utf-8")


def sync_completions(
    meeting_dir: pathlib.Path | None = None,
    vault_note_path: pathlib.Path | None = None,
    api_token: str = "",
    *,
    tasks_path: pathlib.Path | None = None,
) -> dict:
    """Sync Todoist task completion status back to vault note.

    Either provide meeting_dir (looks for todoist_tasks.json inside it)
    or tasks_path (direct path to the tasks JSON file).
    """
    if tasks_path is None:
        if meeting_dir is None:
            return {"synced": 0, "note_missing": False}
        tasks_path = meeting_dir / "todoist_tasks.json"
    if not tasks_path.exists():
        return {"synced": 0, "note_missing": False}
    if vault_note_path is None:
        return {"synced": 0, "note_missing": True}

    data = json.loads(tasks_path.read_text())
    tasks = data.get("tasks", [])

    if not tasks:
        return {"synced": 0, "note_missing": False}

    if not vault_note_path.exists():
        return {"synced": 0, "note_missing": True, "expected_path": str(vault_note_path)}

    if TodoistAPI is None:
        raise ImportError("todoist-api-python is not installed")

    api = TodoistAPI(api_token)
    rate_limiter = RateLimiter()
    synced_count = 0

    for task_record in tasks:
        if task_record.get("completed_at") or task_record.get("deleted_at"):
            continue  # Already synced

        todoist_id = task_record["todoist_id"]
        try:
            rate_limiter.wait()
            task = api.get_task(todoist_id)
            if task.is_completed:
                _update_vault_checkbox(vault_note_path, task_record["description"], checked=True)
                task_record["completed_at"] = datetime.now(timezone.utc).isoformat()
                synced_count += 1
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                # Task was deleted in Todoist
                _update_vault_checkbox(vault_note_path, task_record["description"], strikethrough=True)
                task_record["deleted_at"] = datetime.now(timezone.utc).isoformat()
                synced_count += 1
            else:
                logger.warning("Failed to check task %s: %s", todoist_id, e)

    # Save updated task records
    data["tasks"] = tasks
    data["last_synced"] = datetime.now(timezone.utc).isoformat()
    tasks_path.write_text(json.dumps(data, indent=2))

    return {"synced": synced_count, "note_missing": False}


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

"""Calendar sync — write and update calendar event vault notes."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from recap.daemon.config import OrgConfig

logger = logging.getLogger(__name__)


@dataclass
class CalendarEvent:
    event_id: str
    title: str
    date: str  # "2026-04-14"
    time: str  # "14:00-15:00"
    participants: list[str]
    calendar_source: str  # "zoho" or "google"
    org: str  # "disbursecloud"
    meeting_link: str = ""
    description: str = ""


def _slugify(text: str) -> str:
    """Lowercase, dashes, strip special chars."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    return slug.strip("-")


def _parse_frontmatter(content: str) -> dict | None:
    """Parse YAML frontmatter from a markdown file's content."""
    content = content.replace("\r\n", "\n")
    parts = content.split("---\n", 2)
    if len(parts) < 3:
        return None
    try:
        return yaml.safe_load(parts[1])
    except yaml.YAMLError as e:
        logger.warning("Failed to parse frontmatter: %s", e)
        return None


def _to_vault_relative(path: Path, vault_path: Path | None) -> str:
    if vault_path is None:
        return str(path)
    try:
        return path.relative_to(vault_path).as_posix()
    except ValueError:
        return str(path)


def write_calendar_note(
    event: CalendarEvent, vault_path: Path, org_config: OrgConfig,
) -> Path:
    """Write a calendar event as a vault note. Returns the note path."""
    meetings_dir = org_config.resolve_subfolder(vault_path) / "Meetings"
    meetings_dir.mkdir(parents=True, exist_ok=True)

    slug = _slugify(event.title)
    filename = f"{event.date} - {slug}.md"
    note_path = meetings_dir / filename

    # Build frontmatter
    fm = {
        "date": event.date,
        "time": event.time,
        "title": event.title,
        "participants": [f"[[{p}]]" for p in event.participants],
        "calendar-source": event.calendar_source,
        "org": event.org,
        "org-subfolder": org_config.subfolder,
        "meeting-link": event.meeting_link,
        "event-id": event.event_id,
        "pipeline-status": "pending",
    }

    lines = ["---"]
    lines.append(yaml.dump(fm, default_flow_style=False, sort_keys=False).strip())
    lines.append("---")
    lines.append("")

    # Agenda section
    lines.append("## Agenda")
    lines.append("")
    if event.description:
        lines.append(event.description)
        lines.append("")

    note_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote calendar note: %s", note_path)
    return note_path


def find_note_by_event_id(event_id: str, search_path: Path) -> Path | None:
    """Scan markdown files in search_path for matching event-id in frontmatter."""
    if not search_path.exists():
        return None
    for md_file in search_path.glob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        fm = _parse_frontmatter(content)
        if fm and fm.get("event-id") == event_id:
            return md_file
    return None


def should_update_note(
    event_id: str,
    vault_path: Path,
    org_config: OrgConfig,
    new_time: str | None = None,
    new_participants: list[str] | None = None,
) -> str:
    """Check whether a note needs creating, updating, or skipping.

    Returns "create", "update", or "skip".
    """
    meetings_dir = org_config.resolve_subfolder(vault_path) / "Meetings"
    note = find_note_by_event_id(event_id, meetings_dir)

    if note is None:
        return "create"

    content = note.read_text(encoding="utf-8")
    fm = _parse_frontmatter(content)
    if fm is None:
        return "update"

    changed = False
    if new_time is not None and fm.get("time") != new_time:
        changed = True
    if new_participants is not None:
        existing = fm.get("participants", [])
        # Strip wikilink brackets for comparison — notes store [[Name]]
        # but incoming participants are raw names
        normalized_existing = sorted(
            p.replace("[[", "").replace("]]", "") for p in existing
        )
        normalized_new = sorted(new_participants)
        if normalized_existing != normalized_new:
            changed = True

    return "update" if changed else "skip"


def update_calendar_note(
    note_path: Path,
    new_time: str | None = None,
    new_participants: list[str] | None = None,
    rename_queue_path: Path | None = None,
    vault_path: Path | None = None,
    org_config: OrgConfig | None = None,
) -> int:
    """Update time and/or participants in frontmatter only.

    If the date portion of time changed, updates the frontmatter date and
    queues a file rename as JSON to rename_queue_path.

    If ``org_config`` is supplied, backfills ``org-subfolder`` into any
    pre-canonical frontmatter that lacks it. Notes written before the
    canonical shape landed will thus self-heal on their next scheduler pass.
    """
    content = note_path.read_text(encoding="utf-8")
    normalized = content.replace("\r\n", "\n")
    parts = normalized.split("---\n", 2)
    if len(parts) < 3:
        return 0

    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError as e:
        logger.warning("Failed to parse frontmatter: %s", e)
        return 0

    if fm is None:
        return 0

    if org_config is not None:
        fm.setdefault("org-subfolder", org_config.subfolder)

    old_date = fm.get("date", "")
    queued_renames = 0

    if new_time is not None:
        fm["time"] = new_time
        # Check if date changed (time string contains a date like "2026-04-15 14:00-15:00")
        # For simple time ranges, extract date from the time if it differs
        # The date change detection: if new_time starts with a date pattern
        date_match = re.match(r"^(\d{4}-\d{2}-\d{2})\s", new_time)
        if date_match:
            new_date = date_match.group(1)
            if new_date != old_date:
                fm["date"] = new_date
                if rename_queue_path is not None:
                    old_name = note_path.name
                    new_name = old_name.replace(old_date, new_date, 1)
                    new_path = note_path.parent / new_name
                    # Read existing queue entries and append
                    queue: list[dict] = []
                    if rename_queue_path.exists():
                        try:
                            queue = json.loads(
                                rename_queue_path.read_text(encoding="utf-8")
                            )
                        except (json.JSONDecodeError, ValueError) as e:
                            logger.warning("Could not parse rename queue %s: %s", rename_queue_path, e)
                            queue = []
                    queue.append(
                        {
                            "old_path": _to_vault_relative(note_path, vault_path),
                            "new_path": _to_vault_relative(new_path, vault_path),
                        }
                    )
                    rename_queue_path.parent.mkdir(parents=True, exist_ok=True)
                    rename_queue_path.write_text(
                        json.dumps(queue, indent=2),
                        encoding="utf-8",
                    )
                    queued_renames += 1

    if new_participants is not None:
        fm["participants"] = [f"[[{name}]]" for name in new_participants]

    # Reconstruct file: frontmatter + body below
    body = parts[2]
    new_fm = yaml.dump(fm, default_flow_style=False, sort_keys=False).strip()
    new_content = f"---\n{new_fm}\n---\n{body}"
    note_path.write_text(new_content, encoding="utf-8")
    logger.info("Updated calendar note: %s", note_path)
    return queued_renames

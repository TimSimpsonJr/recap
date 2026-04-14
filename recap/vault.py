"""Obsidian vault writing — meeting notes, profile stubs, previous meeting search."""
from __future__ import annotations

import logging
import pathlib
import re
from datetime import date

import yaml

from recap.artifacts import safe_note_title
from recap.models import (
    AnalysisResult,
    MeetingMetadata,
    ProfileStub,
)

logger = logging.getLogger(__name__)

MEETING_RECORD_MARKER = "## Meeting Record"

# Field ownership for canonical merge (design doc §0.1)
_CALENDAR_OWNED_KEYS = {"time", "event-id", "meeting-link", "calendar-source"}


def slugify(text: str) -> str:
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    return slug.strip("-")


def _format_duration(seconds: float) -> str:
    total_minutes = int(seconds // 60)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def build_canonical_frontmatter(
    metadata: MeetingMetadata,
    analysis: AnalysisResult,
    duration_seconds: float,
    recording_path: pathlib.Path,
    org: str,
    org_subfolder: str,
) -> dict:
    """Build the canonical frontmatter dict for a completed meeting note.

    Per docs/plans/2026-04-14-fix-everything-design.md §0.1. The `org` arg is
    always the slug; `org_subfolder` is the filesystem path. Both go into the
    frontmatter under their respective keys.
    """
    return {
        "date": metadata.date.isoformat(),
        "title": metadata.title,
        "org": org,
        "org-subfolder": org_subfolder,
        "platform": metadata.platform,
        "participants": [f"[[{p.name}]]" for p in metadata.participants],
        "companies": [f"[[{c.name}]]" for c in analysis.companies],
        "duration": _format_duration(duration_seconds),
        "type": analysis.meeting_type,
        "tags": [f"meeting/{analysis.meeting_type}"],
        "pipeline-status": "complete",
        "recording": recording_path.name,
    }


def upsert_note(
    note_path: pathlib.Path,
    frontmatter: dict,
    body: str,
) -> None:
    """Upsert a meeting note with canonical frontmatter + body below the marker.

    Four cases (design doc §0.1):
    1. Note does not exist — create with frontmatter + marker + body.
    2. Existing note, no frontmatter, no marker — add both.
    3. Existing note with calendar frontmatter, no marker — field-level merge
       of frontmatter (calendar keys preserved), append marker + body.
    4. Existing note with marker — field-level merge of frontmatter (pipeline
       authoritative for pipeline-owned keys), replace everything below marker.

    This function is the sole writer of canonical notes. All callers
    (calendar sync, pipeline export, manual tooling) route through here.
    """
    note_path.parent.mkdir(parents=True, exist_ok=True)

    if not note_path.exists():
        _write_new_note(note_path, frontmatter, body)
        return

    existing = note_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    has_frontmatter = existing.startswith("---\n") and existing.count("---\n") >= 2
    has_marker = MEETING_RECORD_MARKER in existing

    if not has_frontmatter and not has_marker:
        _prepend_fm_and_append_body(note_path, existing, frontmatter, body)
        return

    if has_frontmatter and not has_marker:
        _merge_fm_and_append_body(note_path, existing, frontmatter, body)
        return

    _merge_fm_and_replace_below_marker(note_path, existing, frontmatter, body)


def _merge_fm_and_replace_below_marker(
    note_path: pathlib.Path, existing: str, canonical: dict, body: str,
) -> None:
    """Case 4: existing frontmatter + marker. Merge FM, replace below marker."""
    _, fm_block, remainder = existing.split("---\n", 2)
    try:
        existing_fm = yaml.safe_load(fm_block) or {}
    except yaml.YAMLError:
        existing_fm = {}

    merged = _merge_frontmatter(existing_fm, canonical)

    # Drop pipeline-error if pipeline-status no longer starts with "failed:"
    if not str(merged.get("pipeline-status", "")).startswith("failed:"):
        merged.pop("pipeline-error", None)

    marker_idx = remainder.index(MEETING_RECORD_MARKER)
    above = remainder[:marker_idx]
    fm_out = yaml.dump(merged, default_flow_style=False, sort_keys=False).strip()
    new_content = (
        f"---\n{fm_out}\n---\n"
        f"{above.rstrip()}\n\n"
        f"{MEETING_RECORD_MARKER}\n\n"
        f"{body.lstrip()}"
    )
    note_path.write_text(new_content, encoding="utf-8")


def _write_new_note(note_path: pathlib.Path, frontmatter: dict, body: str) -> None:
    fm_block = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).strip()
    content = f"---\n{fm_block}\n---\n\n{MEETING_RECORD_MARKER}\n\n{body.lstrip()}"
    note_path.write_text(content, encoding="utf-8")


def _prepend_fm_and_append_body(
    note_path: pathlib.Path, existing: str, frontmatter: dict, body: str,
) -> None:
    fm_block = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).strip()
    new_content = (
        f"---\n{fm_block}\n---\n\n"
        f"{existing.rstrip()}\n\n"
        f"{MEETING_RECORD_MARKER}\n\n"
        f"{body.lstrip()}"
    )
    note_path.write_text(new_content, encoding="utf-8")


def _merge_fm_and_append_body(
    note_path: pathlib.Path, existing: str, canonical: dict, body: str,
) -> None:
    """Case 3: existing frontmatter + agenda, no marker. Merge + append."""
    _, fm_block, remainder = existing.split("---\n", 2)
    try:
        existing_fm = yaml.safe_load(fm_block) or {}
    except yaml.YAMLError:
        existing_fm = {}

    merged = _merge_frontmatter(existing_fm, canonical)
    fm_out = yaml.dump(merged, default_flow_style=False, sort_keys=False).strip()
    new_content = (
        f"---\n{fm_out}\n---\n"
        f"{remainder.rstrip()}\n\n"
        f"{MEETING_RECORD_MARKER}\n\n"
        f"{body.lstrip()}"
    )
    note_path.write_text(new_content, encoding="utf-8")


def _merge_frontmatter(existing: dict, canonical: dict) -> dict:
    """Field-level merge: calendar-owned keys preserve existing; canonical wins elsewhere."""
    merged = dict(existing)
    for key, value in canonical.items():
        if key in _CALENDAR_OWNED_KEYS and key in existing:
            continue  # preserve calendar-written value
        merged[key] = value
    return merged


def _format_action_item(
    item,
    user_name: str | None = None,
) -> str:
    """Format an action item in Obsidian Tasks emoji format."""
    is_user = user_name and item.assignee.lower() == user_name.lower()
    assignee = item.assignee if is_user else f"[[{item.assignee}]]"

    line = f"- [ ] {assignee}: {item.description}"

    # Due date
    if item.due_date:
        line += f" 📅 {item.due_date}"

    # Priority emoji
    if item.priority == "high":
        line += " ⏫"
    elif item.priority == "normal":
        line += " 🔼"
    # low priority: no emoji

    return line


def _generate_pipeline_content(
    metadata: MeetingMetadata,
    analysis: AnalysisResult,
    duration_seconds: float,
    recording_path: pathlib.Path,
    previous_meeting: str | None = None,
    user_name: str | None = None,
) -> str:
    """Generate the pipeline content that goes below the Meeting Record marker."""
    lines = []

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(analysis.summary)
    lines.append("")

    # Key Points
    if analysis.key_points:
        lines.append("## Key Points")
        lines.append("")
        for kp in analysis.key_points:
            lines.append(f"### {kp.topic}")
            lines.append("")
            lines.append(kp.detail)
            lines.append("")

    # Decisions (conditional)
    if analysis.decisions:
        lines.append("## Decisions Made")
        lines.append("")
        for d in analysis.decisions:
            lines.append(f"- **{d.decision}** (decided by {d.made_by})")
        lines.append("")

    # Action Items
    if analysis.action_items:
        lines.append("## Action Items")
        lines.append("")
        for item in analysis.action_items:
            lines.append(_format_action_item(item, user_name=user_name))
        lines.append("")

    # Follow-ups (conditional)
    if analysis.follow_ups:
        lines.append("## Follow-up Required")
        lines.append("")
        for fu in analysis.follow_ups:
            lines.append(f"- **{fu.item}** — {fu.context}")
        lines.append("")

    # Relationship Notes (conditional)
    if analysis.relationship_notes:
        lines.append("## Relationship Notes")
        lines.append("")
        lines.append(analysis.relationship_notes)
        lines.append("")

    # Previous Meeting (conditional)
    if previous_meeting:
        lines.append("## Previous Meeting")
        lines.append("")
        lines.append(f"[[{previous_meeting}]]")
        lines.append("")

    return "\n".join(lines)


def _generate_meeting_markdown(
    metadata: MeetingMetadata,
    analysis: AnalysisResult,
    duration_seconds: float,
    recording_path: pathlib.Path,
    org: str | None = None,
    previous_meeting: str | None = None,
    user_name: str | None = None,
) -> str:
    """Generate a complete meeting note with frontmatter, marker, and pipeline content."""
    # Frontmatter
    fm: dict = {
        "date": metadata.date.isoformat(),
        "participants": [f"[[{p.name}]]" for p in metadata.participants],
        "companies": [f"[[{c.name}]]" for c in analysis.companies],
        "platform": metadata.platform,
        "duration": _format_duration(duration_seconds),
        "recording": str(recording_path),
        "type": analysis.meeting_type,
        "tags": [f"meeting/{analysis.meeting_type}"],
        "pipeline-status": "complete",
    }
    if org:
        fm["org"] = org

    lines = ["---"]
    lines.append(yaml.dump(fm, default_flow_style=False, sort_keys=False).strip())
    lines.append("---")
    lines.append("")

    # Meeting Record marker
    lines.append(MEETING_RECORD_MARKER)
    lines.append("")

    # Pipeline content
    pipeline_content = _generate_pipeline_content(
        metadata=metadata,
        analysis=analysis,
        duration_seconds=duration_seconds,
        recording_path=recording_path,
        previous_meeting=previous_meeting,
        user_name=user_name,
    )
    lines.append(pipeline_content)

    return "\n".join(lines)


def write_meeting_note(
    metadata: MeetingMetadata,
    analysis: AnalysisResult,
    duration_seconds: float,
    recording_path: pathlib.Path,
    meetings_dir: pathlib.Path,
    org: str | None = None,
    previous_meeting: str | None = None,
    user_name: str | None = None,
    note_path: pathlib.Path | None = None,
) -> pathlib.Path | None:
    if note_path is None:
        filename = f"{metadata.date.isoformat()} - {safe_note_title(metadata.title)}.md"
        note_path = meetings_dir / filename
    else:
        note_path.parent.mkdir(parents=True, exist_ok=True)

    if note_path.exists():
        content = note_path.read_text(encoding="utf-8")
        if MEETING_RECORD_MARKER in content:
            # Reprocess: replace everything below the marker
            marker_idx = content.index(MEETING_RECORD_MARKER)
            above_marker = content[:marker_idx]
            pipeline_content = _generate_pipeline_content(
                metadata=metadata,
                analysis=analysis,
                duration_seconds=duration_seconds,
                recording_path=recording_path,
                previous_meeting=previous_meeting,
                user_name=user_name,
            )
            new_content = above_marker + MEETING_RECORD_MARKER + "\n\n" + pipeline_content
            note_path.write_text(new_content, encoding="utf-8")
            logger.info("Reprocessed meeting note (replaced below marker): %s", note_path)
            return note_path
        else:
            # Marker doesn't exist: append marker + content
            pipeline_content = _generate_pipeline_content(
                metadata=metadata,
                analysis=analysis,
                duration_seconds=duration_seconds,
                recording_path=recording_path,
                previous_meeting=previous_meeting,
                user_name=user_name,
            )
            new_content = content.rstrip("\n") + "\n\n" + MEETING_RECORD_MARKER + "\n\n" + pipeline_content
            note_path.write_text(new_content, encoding="utf-8")
            logger.info("Appended meeting record to existing note: %s", note_path)
            return note_path

    md = _generate_meeting_markdown(
        metadata=metadata,
        analysis=analysis,
        duration_seconds=duration_seconds,
        recording_path=recording_path,
        org=org,
        previous_meeting=previous_meeting,
        user_name=user_name,
    )

    note_path.write_text(md, encoding="utf-8")
    logger.info("Wrote meeting note: %s", note_path)
    return note_path


def _generate_person_stub(stub: ProfileStub) -> str:
    fm = {}
    if stub.company:
        fm["company"] = f"[[{stub.company}]]"
    if stub.role:
        fm["role"] = stub.role

    lines = ["---"]
    if fm:
        lines.append(yaml.dump(fm, default_flow_style=False, sort_keys=False).strip())
    lines.append("---")
    lines.append("")
    lines.append("## Key Topics")
    lines.append("")
    lines.append("## Meeting History")
    lines.append("")
    lines.append("[Automatic via Obsidian backlinks]")
    lines.append("")
    return "\n".join(lines)


def _generate_company_stub(stub: ProfileStub) -> str:
    fm = {}
    if stub.industry:
        fm["industry"] = stub.industry

    lines = ["---"]
    if fm:
        lines.append(yaml.dump(fm, default_flow_style=False, sort_keys=False).strip())
    lines.append("---")
    lines.append("")
    lines.append("## Ongoing Themes")
    lines.append("")
    lines.append("## Key Contacts")
    lines.append("")
    lines.append("[Automatic via Obsidian backlinks]")
    lines.append("")
    return "\n".join(lines)


def write_profile_stubs(
    analysis: AnalysisResult,
    people_dir: pathlib.Path,
    companies_dir: pathlib.Path,
) -> list[str]:
    created = []

    for person in analysis.people:
        path = people_dir / f"{safe_note_title(person.name)}.md"
        if path.exists():
            logger.debug("Person profile exists, skipping: %s", person.name)
            continue
        path.write_text(_generate_person_stub(person), encoding="utf-8")
        logger.info("Created person profile: %s", person.name)
        created.append(person.name)

    for company in analysis.companies:
        path = companies_dir / f"{safe_note_title(company.name)}.md"
        if path.exists():
            logger.debug("Company profile exists, skipping: %s", company.name)
            continue
        path.write_text(_generate_company_stub(company), encoding="utf-8")
        logger.info("Created company profile: %s", company.name)
        created.append(company.name)

    return created


def _parse_participants_from_frontmatter(content: str) -> list[str]:
    # Normalize CRLF to LF for consistent frontmatter splitting
    content = content.replace("\r\n", "\n")
    parts = content.split("---\n")
    if len(parts) < 3:
        return []
    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError as e:
        logger.warning("Failed to parse frontmatter for participant extraction: %s", e)
        return []
    if not fm or "participants" not in fm:
        return []
    names = []
    for p in fm["participants"]:
        # Extract name from "[[Name]]" format
        match = re.search(r"\[\[(.+?)]]", str(p))
        if match:
            names.append(match.group(1))
    return names


def find_previous_meeting(
    participant_names: list[str],
    meetings_dir: pathlib.Path,
    exclude_filename: str,
    min_overlap: float = 0.5,
) -> str | None:
    current_set = set(n.lower() for n in participant_names)
    if not current_set:
        return None

    candidates = []
    for note_path in sorted(meetings_dir.glob("*.md"), reverse=True):
        if note_path.name == exclude_filename:
            continue
        content = note_path.read_text(encoding="utf-8")
        note_participants = _parse_participants_from_frontmatter(content)
        note_set = set(n.lower() for n in note_participants)

        if not note_set:
            continue

        overlap = len(current_set & note_set) / len(current_set)
        if overlap >= min_overlap:
            candidates.append(note_path.stem)
            break  # sorted reverse = most recent first

    return candidates[0] if candidates else None

"""Obsidian vault writing — meeting notes, profile stubs, previous meeting search."""
from __future__ import annotations

import logging
import os
import pathlib
import re
from datetime import date, timedelta
from typing import TYPE_CHECKING

import yaml

from recap.artifacts import RecordingMetadata, safe_note_title
from recap.models import (
    AnalysisResult,
    MeetingMetadata,
    ProfileStub,
)

if TYPE_CHECKING:
    from recap.daemon.calendar.index import EventIndex

logger = logging.getLogger(__name__)

MEETING_RECORD_MARKER = "## Meeting Record"

# Field ownership for canonical merge (design doc §0.1)
_CALENDAR_OWNED_KEYS = {"time", "event-id", "meeting-link", "calendar-source"}


_AUDIO_WARNING_BANNERS = {
    "no-system-audio-captured": (
        "> [!warning] System audio was not captured during this recording.\n"
        "> Only the microphone channel has speech. If you expected other "
        "participants' voices, verify the meeting app's output device is "
        "one that was active on this machine.\n"
        "> Active outputs seen during recording: {devices}."
    ),
    "system-audio-interrupted": (
        "> [!warning] System audio dropped out during this recording.\n"
        "> Some portions of the transcript may be one-sided.\n"
        "> Active outputs seen during recording: {devices}."
    ),
}


def _render_audio_warning_callout(
    warnings: list[str], devices_seen: list[str],
) -> str:
    """Render the body callout for audio warnings. Empty warnings -> empty string.

    Each warning code in ``warnings`` that has a banner template in
    ``_AUDIO_WARNING_BANNERS`` produces one callout block. Blocks are joined
    with blank lines. The result ends with two newlines for clean placement
    above the body.
    """
    if not warnings:
        return ""
    devices = ", ".join(devices_seen) if devices_seen else "(none recorded)"
    blocks = []
    for code in warnings:
        template = _AUDIO_WARNING_BANNERS.get(code)
        if template is None:
            continue
        blocks.append(template.format(devices=devices))
    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n\n"


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
    recording_metadata: RecordingMetadata | None = None,
) -> dict:
    """Build the canonical frontmatter dict for a completed meeting note.

    Per docs/plans/2026-04-14-fix-everything-design.md §0.1. The `org` arg is
    always the slug; `org_subfolder` is the filesystem path. Both go into the
    frontmatter under their respective keys.

    When *recording_metadata* is supplied, truthy calendar-owned fields
    (`calendar-source`, `event-id`, `meeting-link`) are included so brand-new
    notes (cases 1 and 5 in `upsert_note`) record what we know about the
    meeting. Falsy values are omitted so the merge path (cases 3, 4) still
    treats those keys as "preserved from existing" rather than overwritten.
    """
    fm: dict = {
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

    if recording_metadata is not None:
        if recording_metadata.calendar_source:
            fm["calendar-source"] = recording_metadata.calendar_source
        if recording_metadata.event_id:
            fm["event-id"] = recording_metadata.event_id
        if recording_metadata.meeting_link:
            fm["meeting-link"] = recording_metadata.meeting_link
        if recording_metadata.audio_warnings:
            fm["audio-warnings"] = list(recording_metadata.audio_warnings)
        if recording_metadata.system_audio_devices_seen:
            fm["system-audio-devices-seen"] = list(
                recording_metadata.system_audio_devices_seen,
            )

    # Time range for notes whose start is known (typically unscheduled
    # synthesis via #27). Scheduled notes derive 'time' from calendar
    # sync; it's a calendar-owned field preserved via _merge_frontmatter
    # when upserting, so we don't block setting it here either.
    if (
        recording_metadata is not None
        and recording_metadata.recording_started_at is not None
    ):
        started = recording_metadata.recording_started_at
        end = started + timedelta(seconds=int(duration_seconds))
        fm["time"] = f"{started:%H:%M}-{end:%H:%M}"

    # Tag augmentation for unscheduled meetings (#27). Keep the canonical
    # meeting/<type> tag (analyzed type stays authoritative) and append
    # 'unscheduled' so Dataview queries can surface them.
    event_id = fm.get("event-id", "")
    if isinstance(event_id, str) and event_id.startswith("unscheduled:"):
        fm["tags"] = list(fm["tags"]) + ["unscheduled"]

    return fm


def upsert_note(
    note_path: pathlib.Path,
    frontmatter: dict,
    body: str,
    *,
    event_index: "EventIndex | None" = None,
    vault_path: pathlib.Path | None = None,
) -> None:
    """Upsert a meeting note with canonical frontmatter + body below the marker.

    Five cases (design doc §0.1):
    1. Note does not exist — create with frontmatter + marker + body.
    2. Existing note, no frontmatter, no marker — add both.
    3. Existing note with calendar frontmatter, no marker — field-level merge
       of frontmatter (calendar keys preserved), append marker + body.
    4. Existing note with frontmatter and marker — field-level merge of
       frontmatter (pipeline authoritative for pipeline-owned keys), replace
       everything below marker.
    5. Existing note with marker but no frontmatter — prepend canonical
       frontmatter, preserve content above marker, replace content below.

    This function is the sole writer of canonical notes. All callers
    (calendar sync, pipeline export, manual tooling) route through here.

    When *event_index* and *vault_path* are both supplied and the frontmatter
    carries an ``event-id``, the index is updated with the vault-relative
    path so subsequent lookups avoid scanning the filesystem.
    """
    note_path.parent.mkdir(parents=True, exist_ok=True)

    # Prepend the audio-warning callout (if any) to the body so all five
    # upsert branches write the banner consistently.
    callout = _render_audio_warning_callout(
        warnings=frontmatter.get("audio-warnings", []),
        devices_seen=frontmatter.get("system-audio-devices-seen", []),
    )
    body_with_callout = callout + body

    if not note_path.exists():
        _write_new_note(note_path, frontmatter, body_with_callout)
    else:
        existing = note_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        has_frontmatter = existing.startswith("---\n") and existing.count("---\n") >= 2
        has_marker = MEETING_RECORD_MARKER in existing

        if not has_frontmatter and not has_marker:
            _prepend_fm_and_append_body(note_path, existing, frontmatter, body_with_callout)
        elif has_frontmatter and not has_marker:
            _merge_fm_and_append_body(note_path, existing, frontmatter, body_with_callout)
        elif has_marker and not has_frontmatter:
            _prepend_fm_and_replace_below_marker(note_path, existing, frontmatter, body_with_callout)
        else:
            _merge_fm_and_replace_below_marker(note_path, existing, frontmatter, body_with_callout)

    _update_index_if_applicable(note_path, frontmatter, event_index, vault_path)


def _update_index_if_applicable(
    note_path: pathlib.Path,
    frontmatter: dict,
    event_index: "EventIndex | None",
    vault_path: pathlib.Path | None,
) -> None:
    """Add or refresh the EventIndex entry for a just-written note.

    No-op when any of these hold:
    - Both ``event_index`` and ``vault_path`` are ``None`` (caller didn't
      wire the index in — expected, silent).
    - ``frontmatter`` has no truthy ``event-id`` (nothing to key on —
      expected for non-calendar notes, silent).
    - Exactly one of ``event_index`` or ``vault_path`` is provided
      (misconfigured caller — logs a ``debug`` to aid diagnosis).
    - ``note_path`` is outside the vault root (degraded mode — logs a
      ``debug`` so stale-lookup bugs are traceable).
    """
    if event_index is None and vault_path is None:
        return
    if event_index is None or vault_path is None:
        logger.debug(
            "Skipping EventIndex update: missing %s",
            "event_index" if event_index is None else "vault_path",
        )
        return
    event_id = frontmatter.get("event-id")
    if not event_id:
        return
    try:
        rel_path = note_path.relative_to(vault_path)
    except ValueError:
        logger.debug(
            "Skipping EventIndex update: note_path %s outside vault %s",
            note_path, vault_path,
        )
        return
    event_index.add(str(event_id), rel_path, str(frontmatter.get("org", "")))


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


def _prepend_fm_and_replace_below_marker(
    note_path: pathlib.Path, existing: str, frontmatter: dict, body: str,
) -> None:
    """Case 5: marker present but no frontmatter. Prepend FM, preserve above-marker content, replace below."""
    marker_idx = existing.index(MEETING_RECORD_MARKER)
    above = existing[:marker_idx].rstrip()
    fm_block = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).strip()

    if above:
        new_content = (
            f"---\n{fm_block}\n---\n\n"
            f"{above}\n\n"
            f"{MEETING_RECORD_MARKER}\n\n"
            f"{body.lstrip()}"
        )
    else:
        new_content = (
            f"---\n{fm_block}\n---\n\n"
            f"{MEETING_RECORD_MARKER}\n\n"
            f"{body.lstrip()}"
        )
    note_path.write_text(new_content, encoding="utf-8")


def _write_new_note(note_path: pathlib.Path, frontmatter: dict, body: str) -> None:
    fm_block = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).strip()
    content = f"---\n{fm_block}\n---\n\n{MEETING_RECORD_MARKER}\n\n{body.lstrip()}"
    note_path.write_text(content, encoding="utf-8")


def _atomic_write_note(path: pathlib.Path, content: str) -> None:
    """Write a note atomically via temp-file + os.replace.

    Used by the retroactive-bind flow (#33) where a half-written merged
    note would corrupt the calendar stub on crash. Existing writers in
    this module write directly; this helper is opt-in and used where
    crash safety matters.
    """
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, path)
    except OSError:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


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


def write_meeting_note(
    metadata: MeetingMetadata,
    analysis: AnalysisResult,
    duration_seconds: float,
    recording_path: pathlib.Path,
    meetings_dir: pathlib.Path,
    org: str | None = None,
    org_subfolder: str | None = None,
    previous_meeting: str | None = None,
    user_name: str | None = None,
    note_path: pathlib.Path | None = None,
    recording_metadata: RecordingMetadata | None = None,
    *,
    event_index: "EventIndex | None" = None,
    vault_path: pathlib.Path | None = None,
) -> pathlib.Path:
    """Upsert a canonical meeting note.

    Delegates to `upsert_note` — handles new notes, bare notes, calendar-seeded
    notes, and fully-processed notes via field-level frontmatter merge.

    When *recording_metadata* is supplied, its truthy calendar fields
    (`calendar_source`, `event_id`, `meeting_link`) flow into the emitted
    frontmatter so brand-new notes (cases 1 and 5) carry the calendar
    provenance instead of silently dropping it.

    When *event_index* and *vault_path* are both supplied, the event-id
    index is updated with the note's vault-relative path so subsequent
    lookups avoid scanning the filesystem.
    """
    if note_path is None:
        filename = f"{metadata.date.isoformat()} - {safe_note_title(metadata.title)}.md"
        note_path = meetings_dir / filename

    frontmatter = build_canonical_frontmatter(
        metadata=metadata,
        analysis=analysis,
        duration_seconds=duration_seconds,
        recording_path=recording_path,
        org=org or "",
        org_subfolder=org_subfolder or (org or ""),
        recording_metadata=recording_metadata,
    )

    body = _generate_pipeline_content(
        metadata=metadata,
        analysis=analysis,
        duration_seconds=duration_seconds,
        recording_path=recording_path,
        previous_meeting=previous_meeting,
        user_name=user_name,
    )

    upsert_note(note_path, frontmatter, body, event_index=event_index, vault_path=vault_path)
    logger.info("Upserted meeting note: %s", note_path)
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

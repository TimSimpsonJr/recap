"""Obsidian vault writing — meeting notes, profile stubs, previous meeting search."""
from __future__ import annotations

import logging
import pathlib
import re
from datetime import date

import yaml

from recap.frames import FrameResult
from recap.models import (
    AnalysisResult,
    MeetingMetadata,
    ProfileStub,
)

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
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


def _format_timestamp(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


def _generate_meeting_markdown(
    metadata: MeetingMetadata,
    analysis: AnalysisResult,
    duration_seconds: float,
    recording_path: pathlib.Path,
    frames: list[FrameResult] | None = None,
    previous_meeting: str | None = None,
    user_name: str | None = None,
) -> str:
    # Frontmatter
    fm = {
        "date": metadata.date.isoformat(),
        "participants": [f"[[{p.name}]]" for p in metadata.participants],
        "companies": [f"[[{c.name}]]" for c in analysis.companies],
        "platform": metadata.platform,
        "duration": _format_duration(duration_seconds),
        "recording": str(recording_path),
        "type": analysis.meeting_type,
        "tags": [f"meeting/{analysis.meeting_type}"],
    }
    lines = ["---"]
    lines.append(yaml.dump(fm, default_flow_style=False, sort_keys=False).strip())
    lines.append("---")
    lines.append("")

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
            # Wikilink assignees other than the user
            is_user = user_name and item.assignee.lower() == user_name.lower()
            assignee = item.assignee if is_user else f"[[{item.assignee}]]"
            todoist_tag = " #todoist" if is_user else ""
            lines.append(f"- [ ] {assignee}: {item.description}{todoist_tag}")
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

    # Screenshots (conditional)
    if frames:
        lines.append("## Screenshots")
        lines.append("")
        for frame in frames:
            ts = _format_timestamp(frame.timestamp)
            lines.append(f"![[{frame.path.name}]]")
            lines.append(f"*Frame at {ts}*")
            lines.append("")

    return "\n".join(lines)


def write_meeting_note(
    metadata: MeetingMetadata,
    analysis: AnalysisResult,
    duration_seconds: float,
    recording_path: pathlib.Path,
    meetings_dir: pathlib.Path,
    frames: list[FrameResult] | None = None,
    previous_meeting: str | None = None,
    user_name: str | None = None,
) -> pathlib.Path | None:
    filename = f"{metadata.date.isoformat()} - {metadata.title}.md"
    note_path = meetings_dir / filename

    if note_path.exists():
        logger.warning("Meeting note already exists, skipping: %s", note_path)
        return None

    md = _generate_meeting_markdown(
        metadata=metadata,
        analysis=analysis,
        duration_seconds=duration_seconds,
        recording_path=recording_path,
        frames=frames,
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
        path = people_dir / f"{person.name}.md"
        if path.exists():
            logger.debug("Person profile exists, skipping: %s", person.name)
            continue
        path.write_text(_generate_person_stub(person), encoding="utf-8")
        logger.info("Created person profile: %s", person.name)
        created.append(person.name)

    for company in analysis.companies:
        path = companies_dir / f"{company.name}.md"
        if path.exists():
            logger.debug("Company profile exists, skipping: %s", company.name)
            continue
        path.write_text(_generate_company_stub(company), encoding="utf-8")
        logger.info("Created company profile: %s", company.name)
        created.append(company.name)

    return created


def _parse_participants_from_frontmatter(content: str) -> list[str]:
    parts = content.split("---\n")
    if len(parts) < 3:
        return []
    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError:
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

"""Retroactive calendar-bind orchestration (#33).

Single-entry-point: attach_event_to_recording(). See the companion
design doc section 2 for the step-by-step orchestration and retry
semantics.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import TYPE_CHECKING

from recap.daemon.calendar.sync import _parse_frontmatter

if TYPE_CHECKING:
    from recap.daemon.service import Daemon

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Result + error types
# ---------------------------------------------------------------------


@dataclass
class AttachResult:
    status: str
    note_path: str
    noop: bool = False
    cleanup_performed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class AttachAlreadyBoundError(Exception):
    """400: sidecar event_id is a different real event id."""
    def __init__(self, current_event_id: str, current_note_path: str | None = None):
        self.current_event_id = current_event_id
        self.current_note_path = current_note_path
        super().__init__(f"already bound to {current_event_id}")

    def to_dict(self) -> dict:
        d: dict = {
            "error": "already_bound_to_other_event",
            "current_event_id": self.current_event_id,
        }
        if self.current_note_path is not None:
            d["current_note_path"] = self.current_note_path
        return d


class AttachConflictError(Exception):
    """409: target stub already has a different recording."""
    def __init__(self, existing_recording: str, note_path: str):
        self.existing_recording = existing_recording
        self.note_path = note_path
        super().__init__(f"recording conflict: {existing_recording}")

    def to_dict(self) -> dict:
        return {
            "error": "recording_conflict",
            "existing_recording": self.existing_recording,
            "note_path": self.note_path,
        }


class AttachNotFoundError(Exception):
    """404: stem, sidecar, or target stub not found."""
    def __init__(self, what: str, **extra: object):
        self.what = what
        self.extra = extra
        super().__init__(what)

    def to_dict(self) -> dict:
        return {"error": self.what, **self.extra}


class AttachConfigError(Exception):
    """500: internal config corruption (e.g., sidecar references an
    unknown org). Distinct from user-error ValueErrors so the HTTP
    layer can map it to 500 instead of 400."""
    def __init__(self, what: str):
        self.what = what
        super().__init__(what)

    def to_dict(self) -> dict:
        return {"error": self.what}


def attach_event_to_recording(
    *, daemon: "Daemon", stem: str, event_id: str, replace: bool = False,
) -> AttachResult:
    """Orchestrate retroactive calendar bind per design Section 2.

    Raises AttachAlreadyBoundError, AttachConflictError, AttachNotFoundError,
    or ValueError on failure. Retry-safe via cleanup-on-no-op.
    """
    from recap.artifacts import (
        load_recording_metadata, rebind_recording_metadata_to_event,
        resolve_recording_path,
    )
    from recap.daemon.calendar.sync import find_note_by_event_id
    from recap.vault import _atomic_write_note

    # Defense-in-depth synthetic-id guard.
    if event_id.startswith("unscheduled:"):
        raise ValueError("target_event_must_be_real_calendar_event")

    # Step 1: Resolve audio path.
    audio_path = resolve_recording_path(daemon.config.recordings_path, stem)
    if audio_path is None:
        raise AttachNotFoundError("recording not found")

    # Step 2: Load sidecar + classify.
    sidecar = load_recording_metadata(audio_path)
    if sidecar is None:
        raise AttachNotFoundError("sidecar not found")

    classification = _classify_sidecar(sidecar, event_id)

    # Step 3: Resolve target stub.
    vault_path = Path(daemon.config.vault_path)
    # meetings_dir comes from the org's subfolder.
    # Use find_note_by_event_id with stale-heal.
    org_config = daemon.config.org_by_slug(sidecar.org)
    if org_config is None:
        raise AttachConfigError(f"unknown_org:{sidecar.org}")
    meetings_dir = org_config.resolve_subfolder(vault_path) / "Meetings"
    target_path = find_note_by_event_id(
        event_id, meetings_dir,
        vault_path=vault_path, event_index=daemon.event_index,
    )
    if target_path is None:
        raise AttachNotFoundError("event not found")

    # Step 4: Reconcile candidate with target.
    # Normalize to posix form for cross-platform comparison + emission.
    # Vault-relative paths in this codebase are forward-slash (see
    # artifacts.to_vault_relative); on Windows, target_path.relative_to()
    # would otherwise produce backslashes that don't match the sidecar's
    # forward-slash note_path.
    target_rel = target_path.relative_to(vault_path)
    target_rel_str = target_rel.as_posix()
    sidecar_note_str = str(sidecar.note_path).replace("\\", "/")
    if classification == "noop_candidate":
        if sidecar_note_str == target_rel_str:
            # Idempotent retry: sidecar already points at target. The
            # caller's prior attempt may have crashed mid-bind after the
            # sidecar was rewritten but before the synthetic EventIndex
            # entry / unscheduled note were cleaned up. Discover any such
            # orphan deterministically by scanning the meetings dir for
            # unscheduled notes whose frontmatter `recording` matches the
            # target stub's. Filesystem scan (not EventIndex scan) is
            # authoritative because the orphan file can outlive its index
            # entry when `_cleanup_after_bind` crashed between index-remove
            # and file-unlink.
            target_content = target_path.read_text(encoding="utf-8")
            target_fm = _parse_frontmatter(target_content) or {}
            recording_filename = target_fm.get("recording")
            synthetic_id, orphan_path = _find_orphan_unscheduled_note(
                vault_path=vault_path,
                meetings_dir=meetings_dir,
                recording_filename=recording_filename,
                target_path=target_path,
            )
            cleaned = _cleanup_after_bind(
                daemon,
                unscheduled_path=orphan_path,
                event_id_to_clear=synthetic_id,
            )
            return AttachResult(
                status="ok", note_path=target_rel_str,
                noop=True, cleanup_performed=cleaned,
            )
        raise AttachAlreadyBoundError(
            current_event_id=sidecar.event_id,
            current_note_path=str(sidecar.note_path),
        )

    # classification == "normal"
    # Step 5: Read source unscheduled note.
    source_abs = vault_path / sidecar.note_path
    if not source_abs.exists():
        raise AttachNotFoundError(
            "source note not found", note_path=str(sidecar.note_path),
        )
    source_content = source_abs.read_text(encoding="utf-8")
    source_fm = _parse_frontmatter(source_content) or {}
    source_body = _strip_frontmatter(source_content)

    # Conflict check on target's `recording` field.
    target_content = target_path.read_text(encoding="utf-8")
    target_fm = _parse_frontmatter(target_content) or {}
    target_body = _strip_frontmatter(target_content)
    target_recording = target_fm.get("recording")
    source_recording = source_fm.get("recording")
    if target_recording:
        if target_recording == source_recording:
            # Idempotent no-op: bind was already applied.
            cleaned = _cleanup_after_bind(
                daemon,
                unscheduled_path=source_abs,
                event_id_to_clear=sidecar.event_id,
            )
            # Sidecar still shows synthetic event_id; rewrite it now.
            rebind_recording_metadata_to_event(
                audio_path,
                event_id=event_id,
                note_path=target_rel_str,
                calendar_source=target_fm.get("calendar-source"),
                meeting_link=target_fm.get("meeting-link"),
                title=target_fm.get("title"),
            )
            return AttachResult(
                status="ok", note_path=target_rel_str,
                noop=True, cleanup_performed=cleaned,
            )
        if not replace:
            raise AttachConflictError(
                existing_recording=str(target_recording),
                note_path=target_rel_str,
            )

    # Sanity: cross-org.
    if target_fm.get("org") and target_fm.get("org") != source_fm.get("org"):
        raise ValueError(
            f"cross_org_bind_refused: source={source_fm.get('org')}, "
            f"target={target_fm.get('org')}",
        )

    # Sanity: date within +/- 1 day.
    src_date = source_fm.get("date") or ""
    tgt_date = target_fm.get("date") or ""
    if _date_diff_days(src_date, tgt_date) > 1:
        raise ValueError(
            f"date_out_of_window: source={src_date}, target={tgt_date}",
        )

    # Step 6-8: Merge bodies + frontmatter; atomic write merged note.
    merged_body = _merge_bodies(stub_body=target_body, source_body=source_body)
    merged_fm = _build_merged_frontmatter(target_fm, source_fm)
    merged_content = _render_frontmatter(merged_fm) + merged_body
    _atomic_write_note(target_path, merged_content)

    # Step 9: Rewrite sidecar.
    rebind_recording_metadata_to_event(
        audio_path,
        event_id=event_id,
        note_path=target_rel_str,
        calendar_source=target_fm.get("calendar-source"),
        meeting_link=target_fm.get("meeting-link"),
        title=target_fm.get("title"),
    )

    # Step 10-11: Cleanup.
    cleaned = _cleanup_after_bind(
        daemon,
        unscheduled_path=source_abs,
        event_id_to_clear=sidecar.event_id,
    )

    return AttachResult(
        status="ok", note_path=target_rel_str,
        noop=False, cleanup_performed=cleaned,
    )


# ---------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------


def _classify_sidecar(sidecar, event_id: str) -> str:
    """Classify sidecar state per Section 2 Step 2.

    Returns "normal" or "noop_candidate". Raises AttachAlreadyBoundError
    on class (c): sidecar already bound to a different real event.
    """
    if sidecar.event_id.startswith("unscheduled:"):
        return "normal"
    if sidecar.event_id == event_id:
        return "noop_candidate"
    raise AttachAlreadyBoundError(
        current_event_id=sidecar.event_id,
        current_note_path=sidecar.note_path,
    )


def _merge_bodies(*, stub_body: str, source_body: str) -> str:
    """Apply the Q3 Pre-Meeting Notes heuristic.

    1. Normalize line endings, trim outer whitespace on stub.
    2. If stub starts with "## Agenda": strip it once, trim remainder.
    3. If remainder empty: source unchanged.
    4. Otherwise: append "\n\n## Pre-Meeting Notes\n\n<remainder>".
    5. If stub doesn't start with "## Agenda": preserve whole stub body
       verbatim under "## Pre-Meeting Notes" (unexpected-shape fallback).
    """
    stub = stub_body.replace("\r\n", "\n").strip()
    if not stub:
        return source_body

    agenda_heading = "## Agenda"
    if stub.startswith(agenda_heading):
        remainder = stub[len(agenda_heading):].strip()
        if not remainder:
            return source_body
        appendix = remainder
    else:
        # Unexpected shape fallback.
        appendix = stub

    sep = "\n\n" if not source_body.endswith("\n") else "\n"
    return f"{source_body}{sep}## Pre-Meeting Notes\n\n{appendix}"


def _build_merged_frontmatter(stub_fm: dict, source_fm: dict) -> dict:
    """Build merged frontmatter per Section 2 Step 7.

    Two-pass merge: start with the stub's full frontmatter (calendar-owned
    keys + any user edits), then overlay every pipeline-owned key found on
    the source unscheduled note. This intentionally preserves stub keys
    that the source happens to lack (e.g. user-added `priority`) while
    making sure pipeline-owned fields like `platform` and `type` are not
    silently dropped during a rebind.

    Pipeline-owned overlay set mirrors `build_canonical_frontmatter` in
    recap/vault.py: any field that pipeline writes when a meeting note is
    finalized. Calendar-owned keys (event-id, calendar-source, meeting-link,
    time, date, title, org, org-subfolder) are NOT overlaid -- the stub is
    authoritative for those.

    Tags merge as a union with the "unscheduled" tag stripped, since the
    rebind has, by definition, scheduled the recording.
    """
    pipeline_overlay_keys = {
        "participants", "companies", "duration",
        "platform", "type",
        "recording",
        "audio-warnings", "system-audio-devices-seen",
        "audio_warnings", "system_audio_devices_seen",
        "recording-started-at", "recording_started_at",
        "pipeline-status",
    }

    # Start with the stub's full frontmatter (calendar identity + any user
    # edits we don't want to clobber).
    merged: dict = dict(stub_fm)

    # Overlay every pipeline-owned key the source has.
    for k in pipeline_overlay_keys:
        if k in source_fm:
            merged[k] = source_fm[k]

    # Tags: union, strip "unscheduled".
    tags: list = []
    for src in (stub_fm.get("tags") or []), (source_fm.get("tags") or []):
        for t in src:
            if t == "unscheduled":
                continue
            if t not in tags:
                tags.append(t)
    if tags:
        merged["tags"] = tags
    elif "tags" in merged:
        del merged["tags"]

    return merged


# ---------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------


def _strip_frontmatter(content: str) -> str:
    """Return the body after the closing --- of a YAML frontmatter block."""
    content = content.replace("\r\n", "\n")
    parts = content.split("---\n", 2)
    if len(parts) < 3:
        return content
    return parts[2].lstrip("\n")


def _render_frontmatter(fm: dict) -> str:
    import yaml
    return (
        "---\n"
        + yaml.dump(fm, sort_keys=False, default_flow_style=False)
        + "---\n\n"
    )


def _date_diff_days(d1: str, d2: str) -> int:
    from datetime import datetime
    if not d1 or not d2:
        return 0  # lenient; skip the check when dates missing
    fmt = "%Y-%m-%d"
    return abs((datetime.strptime(d1, fmt) - datetime.strptime(d2, fmt)).days)


def _cleanup_after_bind(
    daemon,
    *,
    unscheduled_path: Path | None,
    event_id_to_clear: str | None,
) -> bool:
    """Idempotent cleanup of mid-bind-crash orphans. Returns True if
    anything was cleaned. No-ops on missing input."""
    cleaned = False
    if event_id_to_clear is not None and event_id_to_clear.startswith("unscheduled:"):
        existing = daemon.event_index.lookup(event_id_to_clear)
        if existing is not None:
            daemon.event_index.remove(event_id_to_clear)
            cleaned = True
    if unscheduled_path is not None and unscheduled_path.exists():
        try:
            unscheduled_path.unlink()
            cleaned = True
        except OSError:
            logger.warning("unscheduled note delete failed", exc_info=True)
    return cleaned


def _find_orphan_unscheduled_note(
    *,
    vault_path: Path,
    meetings_dir: Path,
    recording_filename: str | None,
    target_path: Path,
) -> tuple[str | None, Path | None]:
    """Filesystem scan for an orphan unscheduled note whose `recording`
    frontmatter field matches *recording_filename*. Returns
    ``(synthetic_event_id, absolute_note_path)`` or ``(None, None)`` when
    no orphan is found.

    Authoritative for orphan discovery on the retry/no-op path because
    the filesystem reflects all crash combinations: the orphan file may
    still be present even when the synthetic EventIndex entry has been
    cleaned up by a prior crashed retry attempt. (`_cleanup_after_bind`
    runs index-remove before file-unlink; a crash between the two leaves
    a file-only orphan that an index-based scan cannot see.)

    *target_path* is the calendar stub the orchestrator is binding to;
    we exclude it from the scan so the stub itself is never mistaken for
    an orphan when it carries the same `recording` field.
    """
    if not recording_filename:
        return (None, None)
    if not meetings_dir.exists():
        return (None, None)

    for note_path in meetings_dir.rglob("*.md"):
        if note_path == target_path:
            continue
        try:
            content = note_path.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = _parse_frontmatter(content) or {}
        event_id = fm.get("event-id")
        if not isinstance(event_id, str) or not event_id.startswith("unscheduled:"):
            continue
        if fm.get("recording") == recording_filename:
            return (event_id, note_path)

    return (None, None)

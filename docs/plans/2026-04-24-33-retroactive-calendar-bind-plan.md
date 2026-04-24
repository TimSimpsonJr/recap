# Issue #33 — Retroactive Calendar Bind Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement this plan task-by-task.

**Goal:** Retroactively re-bind a recording from a synthetic `unscheduled:<uuid>` identity to a real calendar event via a new `POST /api/recordings/{stem}/attach-event` endpoint plus an Obsidian command that lets the user pick the target calendar event.

**Architecture:** Plugin scans vault for calendar stub notes within ±1 day of the recording's date, shows a picker, POSTs the chosen `event_id`. Daemon orchestrator merges the unscheduled note's content onto the calendar stub's path, preserves meaningful stub body as `## Pre-Meeting Notes`, rewrites the RecordingMetadata sidecar to bound-event state, updates EventIndex (remove synthetic entry), and deletes the unscheduled file. Conflict on target's existing `recording` returns 409; user confirms Replace and re-POSTs. Cleanup-on-no-op heals mid-bind-crash orphans. Sidecar and note writes upgraded to temp+os.replace for crash safety.

**Tech Stack:** Python 3.12 + aiohttp + ruamel.yaml (existing); Obsidian plugin (TypeScript + existing Vitest); pytest for unit/integration; manual acceptance for UI.

**Design reference:** [docs/plans/2026-04-24-33-retroactive-calendar-bind-design.md](docs/plans/2026-04-24-33-retroactive-calendar-bind-design.md)

---

## Task Overview

1. `write_recording_metadata` atomic temp+replace upgrade
2. `rebind_recording_metadata_to_event` helper
3. `_atomic_write_note` helper in vault.py
4. `recap/daemon/recorder/attach.py` module — orchestrator + error types + helpers
5. `POST /api/recordings/{stem}/attach-event` endpoint
6. Integration E2E tests
7. Plugin `DaemonError.body` + JSON-parsing in `get`/`post`
8. Plugin `DaemonClient.attachEvent` method + types
9. Plugin `CalendarEventPickerModal`
10. Plugin `ConfirmReplaceModal`
11. Plugin `main.ts` — command + orchestrator + candidate scan + submit handler
12. Plugin `MeetingListView` + `MeetingRow` context-menu entry
13. MANIFEST.md Key Relationships bullet + docs/handoffs acceptance checklist
14. Final verification + PR handoff

---

## Task 1: `write_recording_metadata` atomic upgrade

**Files:**
- Modify: `recap/artifacts.py` (`write_recording_metadata` near line 151)
- Modify: `tests/test_artifacts.py` (or create if it doesn't exist)

### Step 1: Write the failing test

Add to tests/test_artifacts.py:

```python
"""Tests for RecordingMetadata sidecar atomic write (#33 Task 1)."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from recap.artifacts import (
    RecordingMetadata,
    load_recording_metadata,
    write_recording_metadata,
)
from recap.models import Participant


def _make_metadata() -> RecordingMetadata:
    return RecordingMetadata(
        org="testorg",
        note_path="Test/Meetings/test.md",
        title="Test",
        date=date(2026, 4, 24).isoformat(),
        participants=[Participant(name="Alice")],
        platform="manual",
    )


class TestWriteRecordingMetadataAtomic:
    def test_roundtrip_unchanged(self, tmp_path: Path):
        """Atomic write must not break read-after-write."""
        audio = tmp_path / "rec.flac"
        audio.touch()
        md = _make_metadata()
        write_recording_metadata(audio, md)
        loaded = load_recording_metadata(audio)
        assert loaded is not None
        assert loaded.title == md.title
        assert loaded.participants[0].name == "Alice"

    def test_temp_file_does_not_remain_on_success(self, tmp_path: Path):
        audio = tmp_path / "rec.flac"
        audio.touch()
        write_recording_metadata(audio, _make_metadata())
        tmps = list(tmp_path.glob("*.tmp"))
        assert tmps == []

    def test_temp_file_cleaned_up_on_oserror(self, tmp_path: Path):
        """If os.replace fails, the temp file must not be left behind."""
        import os
        audio = tmp_path / "rec.flac"
        audio.touch()
        with patch("os.replace", side_effect=OSError("simulated replace fail")):
            with pytest.raises(OSError):
                write_recording_metadata(audio, _make_metadata())
        tmps = list(tmp_path.glob("*.tmp"))
        assert tmps == []

    def test_partial_write_does_not_corrupt_existing(self, tmp_path: Path):
        """Existing sidecar is not corrupted if the write fails mid-flight."""
        import os
        audio = tmp_path / "rec.flac"
        audio.touch()
        # Seed an initial good sidecar.
        good = _make_metadata()
        write_recording_metadata(audio, good)
        # Attempt a failing write.
        bad = _make_metadata()
        bad.title = "Bad"
        with patch("os.replace", side_effect=OSError("simulated")):
            with pytest.raises(OSError):
                write_recording_metadata(audio, bad)
        # Original content still readable.
        loaded = load_recording_metadata(audio)
        assert loaded is not None
        assert loaded.title == "Test"
```

### Step 2: Run test to verify it fails

Run: `.venv/Scripts/python -m pytest tests/test_artifacts.py::TestWriteRecordingMetadataAtomic -v --override-ini="addopts="`

Expected: `test_temp_file_cleaned_up_on_oserror` + `test_partial_write_does_not_corrupt_existing` fail because current write is direct (mocking os.replace has no effect on a direct write).

### Step 3: Upgrade `write_recording_metadata` in recap/artifacts.py

Current (around line 151):
```python
def write_recording_metadata(audio_path: Path, metadata: RecordingMetadata) -> None:
    sidecar_path = _sidecar_path(audio_path)
    sidecar_path.write_text(
        json.dumps(metadata.to_dict(), indent=2),
        encoding="utf-8",
    )
```

Replace with atomic temp+replace:
```python
def write_recording_metadata(audio_path: Path, metadata: RecordingMetadata) -> None:
    """Write the sidecar atomically (temp + os.replace).

    Upgraded from direct write in #33 because the retroactive-bind flow
    requires crash-safe sidecar rewrites. Pre-existing callers (recorder
    start, #29 on_before_finalize, pipeline reprocess) get stronger
    crash semantics for free.
    """
    import os
    sidecar_path = _sidecar_path(audio_path)
    tmp_path = sidecar_path.with_suffix(sidecar_path.suffix + ".tmp")
    try:
        tmp_path.write_text(
            json.dumps(metadata.to_dict(), indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, sidecar_path)
    except OSError:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise
```

If `os` is already imported at the top of artifacts.py, skip the inline import. Check first.

### Step 4: Run tests to verify they pass

```
.venv/Scripts/python -m pytest tests/test_artifacts.py::TestWriteRecordingMetadataAtomic -v --override-ini="addopts="
.venv/Scripts/python -m pytest tests/ --override-ini="addopts=" 2>&1 | tail -5
```

Expected: 4 new tests pass. Full suite has no regressions beyond pre-existing ffprobe failure.

### Step 5: Commit

```
git add recap/artifacts.py tests/test_artifacts.py
git commit -m "feat(#33): write_recording_metadata atomic temp+replace"
```

---

## Task 2: `rebind_recording_metadata_to_event` helper

**Files:**
- Modify: `recap/artifacts.py` (add new helper)
- Modify: `tests/test_artifacts.py` (extend)

### Step 1: Write the failing tests

Add to `TestRebindRecordingMetadata` class in tests/test_artifacts.py:

```python
class TestRebindRecordingMetadata:
    """Rewrite sidecar from unscheduled state to bound-event state (#33 Task 2)."""

    def test_rewrites_all_five_fields(self, tmp_path: Path):
        from recap.artifacts import rebind_recording_metadata_to_event
        audio = tmp_path / "rec.flac"
        audio.touch()
        md = _make_metadata()
        md.event_id = "unscheduled:abc123"
        md.note_path = "Test/Meetings/original.md"
        write_recording_metadata(audio, md)
        rebind_recording_metadata_to_event(
            audio,
            event_id="E1",
            note_path="Test/Meetings/new.md",
            calendar_source="google",
            meeting_link="https://meet.google.com/xyz",
            title="Sprint Planning",
        )
        loaded = load_recording_metadata(audio)
        assert loaded is not None
        assert loaded.event_id == "E1"
        assert loaded.note_path == "Test/Meetings/new.md"
        assert loaded.calendar_source == "google"
        assert loaded.meeting_link == "https://meet.google.com/xyz"
        assert loaded.title == "Sprint Planning"

    def test_preserves_other_fields(self, tmp_path: Path):
        """Non-rebound fields (participants, platform, etc.) stay intact."""
        from recap.artifacts import rebind_recording_metadata_to_event
        audio = tmp_path / "rec.flac"
        audio.touch()
        md = _make_metadata()
        md.event_id = "unscheduled:abc"
        write_recording_metadata(audio, md)
        rebind_recording_metadata_to_event(
            audio,
            event_id="E1",
            note_path="Test/Meetings/new.md",
            calendar_source="google",
            meeting_link="",
            title="T",
        )
        loaded = load_recording_metadata(audio)
        assert loaded is not None
        assert loaded.participants[0].name == "Alice"
        assert loaded.platform == "manual"

    def test_raises_on_missing_sidecar(self, tmp_path: Path):
        from recap.artifacts import rebind_recording_metadata_to_event
        audio = tmp_path / "rec.flac"
        # no sidecar
        with pytest.raises(ValueError, match="no sidecar"):
            rebind_recording_metadata_to_event(
                audio, event_id="E1", note_path="x", calendar_source=None,
                meeting_link=None, title=None,
            )

    def test_none_optional_fields_leave_existing_values(self, tmp_path: Path):
        """Passing None for optional fields keeps the current sidecar value."""
        from recap.artifacts import rebind_recording_metadata_to_event
        audio = tmp_path / "rec.flac"
        audio.touch()
        md = _make_metadata()
        md.event_id = "unscheduled:abc"
        md.calendar_source = "pre-existing"
        md.meeting_link = "pre-existing-link"
        md.title = "Pre-existing"
        write_recording_metadata(audio, md)
        rebind_recording_metadata_to_event(
            audio, event_id="E1", note_path="new",
            calendar_source=None, meeting_link=None, title=None,
        )
        loaded = load_recording_metadata(audio)
        assert loaded is not None
        assert loaded.event_id == "E1"
        assert loaded.note_path == "new"
        assert loaded.calendar_source == "pre-existing"
        assert loaded.meeting_link == "pre-existing-link"
        assert loaded.title == "Pre-existing"
```

### Step 2: Run failing tests

```
.venv/Scripts/python -m pytest tests/test_artifacts.py::TestRebindRecordingMetadata -v --override-ini="addopts="
```

Expected: ImportError on `rebind_recording_metadata_to_event`.

### Step 3: Implement the helper

Add to recap/artifacts.py, near `write_recording_metadata`:

```python
def rebind_recording_metadata_to_event(
    audio_path: Path,
    *,
    event_id: str,
    note_path: str,
    calendar_source: str | None,
    meeting_link: str | None,
    title: str | None,
) -> None:
    """Rewrite sidecar from unscheduled state to bound-event state.

    Called by the retroactive-bind flow (#33). Source unscheduled sidecar
    has event_id starting with "unscheduled:"; this helper overwrites it
    with the real event_id + linked calendar metadata so future
    reprocesses treat it as scheduled.

    Optional fields (calendar_source, meeting_link, title) leave the
    existing sidecar value when None. This lets callers skip rewriting
    a field they don't have fresh data for.

    Raises ValueError if the sidecar does not exist.
    """
    rm = load_recording_metadata(audio_path)
    if rm is None:
        raise ValueError(f"no sidecar for {audio_path}")
    rm.event_id = event_id
    rm.note_path = note_path
    if calendar_source is not None:
        rm.calendar_source = calendar_source
    if meeting_link is not None:
        rm.meeting_link = meeting_link
    if title is not None:
        rm.title = title
    write_recording_metadata(audio_path, rm)
```

### Step 4: Run tests to verify pass

```
.venv/Scripts/python -m pytest tests/test_artifacts.py::TestRebindRecordingMetadata -v --override-ini="addopts="
```

Expected: 4 tests pass.

### Step 5: Commit

```
git add recap/artifacts.py tests/test_artifacts.py
git commit -m "feat(#33): rebind_recording_metadata_to_event helper"
```

---

## Task 3: `_atomic_write_note` helper in vault.py

**Files:**
- Modify: `recap/vault.py`
- Modify: `tests/test_vault.py` (or create/extend)

### Step 1: Write failing tests

Add to tests/test_vault.py (create the file if it doesn't exist):

```python
"""Tests for _atomic_write_note helper (#33 Task 3)."""
from pathlib import Path
from unittest.mock import patch

import pytest

from recap.vault import _atomic_write_note


class TestAtomicWriteNote:
    def test_writes_content(self, tmp_path: Path):
        path = tmp_path / "note.md"
        _atomic_write_note(path, "# Hello\n\nBody content.")
        assert path.read_text(encoding="utf-8") == "# Hello\n\nBody content."

    def test_no_temp_file_on_success(self, tmp_path: Path):
        path = tmp_path / "note.md"
        _atomic_write_note(path, "content")
        assert list(tmp_path.glob("*.tmp")) == []

    def test_overwrites_existing(self, tmp_path: Path):
        path = tmp_path / "note.md"
        path.write_text("old", encoding="utf-8")
        _atomic_write_note(path, "new")
        assert path.read_text(encoding="utf-8") == "new"

    def test_temp_cleaned_up_on_replace_failure(self, tmp_path: Path):
        path = tmp_path / "note.md"
        with patch("os.replace", side_effect=OSError("boom")):
            with pytest.raises(OSError):
                _atomic_write_note(path, "content")
        assert list(tmp_path.glob("*.tmp")) == []

    def test_existing_file_unchanged_on_failure(self, tmp_path: Path):
        path = tmp_path / "note.md"
        path.write_text("original", encoding="utf-8")
        with patch("os.replace", side_effect=OSError("boom")):
            with pytest.raises(OSError):
                _atomic_write_note(path, "would-corrupt")
        assert path.read_text(encoding="utf-8") == "original"
```

### Step 2: Run failing tests

```
.venv/Scripts/python -m pytest tests/test_vault.py::TestAtomicWriteNote -v --override-ini="addopts="
```

Expected: ImportError on `_atomic_write_note`.

### Step 3: Implement

Add to recap/vault.py (near the other file-writing helpers, around line 158):

```python
def _atomic_write_note(path: Path, content: str) -> None:
    """Write a note atomically via temp-file + os.replace.

    Used by the retroactive-bind flow (#33) where a half-written merged
    note would corrupt the calendar stub on crash. Existing writers in
    this module write directly; this helper is opt-in and used where
    crash safety matters.
    """
    import os
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
```

### Step 4: Run tests

```
.venv/Scripts/python -m pytest tests/test_vault.py::TestAtomicWriteNote -v --override-ini="addopts="
```

Expected: 5 pass.

### Step 5: Commit

```
git add recap/vault.py tests/test_vault.py
git commit -m "feat(#33): _atomic_write_note helper"
```

---

## Task 4: `attach.py` module — orchestrator + error types + helpers

**Files:**
- Create: `recap/daemon/recorder/attach.py`
- Create: `tests/test_attach.py`

This is the largest task. Implementation broken into helpers, then orchestrator.

### Step 1: Write failing tests for error types + AttachResult

Create tests/test_attach.py:

```python
"""Tests for attach_event_to_recording orchestrator and helpers (#33 Task 4)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------
# Error type tests
# ---------------------------------------------------------------------


class TestErrorTypes:
    def test_attach_result_to_dict(self):
        from recap.daemon.recorder.attach import AttachResult
        r = AttachResult(status="ok", note_path="x/y.md")
        assert r.to_dict() == {
            "status": "ok", "note_path": "x/y.md",
            "noop": False, "cleanup_performed": False,
        }

    def test_attach_result_noop_cleanup(self):
        from recap.daemon.recorder.attach import AttachResult
        r = AttachResult(status="ok", note_path="x/y.md",
                         noop=True, cleanup_performed=True)
        assert r.to_dict()["noop"] is True
        assert r.to_dict()["cleanup_performed"] is True

    def test_already_bound_error_to_dict(self):
        from recap.daemon.recorder.attach import AttachAlreadyBoundError
        e = AttachAlreadyBoundError(
            current_event_id="E1",
            current_note_path="a/b.md",
        )
        d = e.to_dict()
        assert d["error"] == "already_bound_to_other_event"
        assert d["current_event_id"] == "E1"
        assert d["current_note_path"] == "a/b.md"

    def test_conflict_error_to_dict(self):
        from recap.daemon.recorder.attach import AttachConflictError
        e = AttachConflictError(existing_recording="rec1.flac", note_path="x.md")
        d = e.to_dict()
        assert d["error"] == "recording_conflict"
        assert d["existing_recording"] == "rec1.flac"
        assert d["note_path"] == "x.md"

    def test_not_found_error_to_dict(self):
        from recap.daemon.recorder.attach import AttachNotFoundError
        e = AttachNotFoundError(what="event not found")
        d = e.to_dict()
        assert d["error"] == "event not found"
```

### Step 2: Run failing tests

```
.venv/Scripts/python -m pytest tests/test_attach.py -v --override-ini="addopts="
```

Expected: ImportError.

### Step 3: Create attach.py with error types

```python
# recap/daemon/recorder/attach.py
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


def attach_event_to_recording(
    *, daemon: "Daemon", stem: str, event_id: str, replace: bool = False,
) -> AttachResult:
    """Orchestrate retroactive calendar bind. Raises the appropriate
    error type on each failure class. Retry-safe via cleanup-on-no-op."""
    raise NotImplementedError("implemented in Task 4 Step 7")
```

### Step 4: Run tests — error types should pass

```
.venv/Scripts/python -m pytest tests/test_attach.py::TestErrorTypes -v --override-ini="addopts="
```

Expected: 5 pass.

### Step 5: Write failing tests for helpers (classify, merge-bodies, merge-frontmatter)

Append to tests/test_attach.py:

```python
# ---------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------


class TestClassifySidecar:
    def test_unscheduled_returns_normal(self):
        from recap.daemon.recorder.attach import _classify_sidecar
        sidecar = MagicMock()
        sidecar.event_id = "unscheduled:abc123"
        assert _classify_sidecar(sidecar, "E1") == "normal"

    def test_same_event_id_returns_noop_candidate(self):
        from recap.daemon.recorder.attach import _classify_sidecar
        sidecar = MagicMock()
        sidecar.event_id = "E1"
        assert _classify_sidecar(sidecar, "E1") == "noop_candidate"

    def test_different_real_event_raises(self):
        from recap.daemon.recorder.attach import (
            _classify_sidecar, AttachAlreadyBoundError,
        )
        sidecar = MagicMock()
        sidecar.event_id = "E2"
        sidecar.note_path = "x/y.md"
        with pytest.raises(AttachAlreadyBoundError) as exc_info:
            _classify_sidecar(sidecar, "E1")
        assert exc_info.value.current_event_id == "E2"
        assert exc_info.value.current_note_path == "x/y.md"


class TestMergeBodies:
    def test_empty_stub_no_pre_meeting_notes(self):
        from recap.daemon.recorder.attach import _merge_bodies
        result = _merge_bodies(stub_body="", source_body="# Summary\n\nDetails")
        assert "Pre-Meeting Notes" not in result
        assert result == "# Summary\n\nDetails"

    def test_agenda_heading_only_no_append(self):
        from recap.daemon.recorder.attach import _merge_bodies
        result = _merge_bodies(stub_body="## Agenda\n\n", source_body="# S")
        assert "Pre-Meeting Notes" not in result

    def test_agenda_with_content_appended(self):
        from recap.daemon.recorder.attach import _merge_bodies
        stub = "## Agenda\n\nPrep: talk about Q4"
        result = _merge_bodies(stub_body=stub, source_body="# Summary")
        assert "## Pre-Meeting Notes" in result
        assert "Prep: talk about Q4" in result
        assert result.startswith("# Summary")

    def test_unexpected_shape_fallback_preserves_whole(self):
        from recap.daemon.recorder.attach import _merge_bodies
        stub = "# Custom Heading\n\nUser rewrote the stub"
        result = _merge_bodies(stub_body=stub, source_body="# Summary")
        assert "## Pre-Meeting Notes" in result
        assert "# Custom Heading" in result
        assert "User rewrote the stub" in result

    def test_source_body_always_first(self):
        from recap.daemon.recorder.attach import _merge_bodies
        result = _merge_bodies(
            stub_body="## Agenda\n\nprep",
            source_body="# Final Summary\n\nBody",
        )
        assert result.index("Final Summary") < result.index("Pre-Meeting Notes")


class TestMergeFrontmatter:
    def _stub_fm(self) -> dict:
        return {
            "date": "2026-04-24",
            "time": "14:00-15:00",
            "title": "Sprint Planning",
            "event-id": "E1",
            "calendar-source": "google",
            "meeting-link": "https://meet.google.com/xyz",
            "org": "test",
            "org-subfolder": "Test",
            "pipeline-status": "pending",
            "participants": ["[[Stub Alice]]"],
        }

    def _source_fm(self) -> dict:
        return {
            "date": "2026-04-24",
            "time": "14:30-15:15",
            "title": "Teams call",
            "event-id": "unscheduled:abc123",
            "org": "test",
            "org-subfolder": "Test",
            "pipeline-status": "complete",
            "participants": ["[[Alice]]", "[[Bob]]"],
            "companies": ["[[Acme]]"],
            "duration": "45:00",
            "recording": "2026-04-24 1430 Teams call.flac",
            "tags": ["meeting/test", "unscheduled"],
        }

    def test_calendar_keys_from_stub(self):
        from recap.daemon.recorder.attach import _build_merged_frontmatter
        merged = _build_merged_frontmatter(self._stub_fm(), self._source_fm())
        assert merged["event-id"] == "E1"
        assert merged["calendar-source"] == "google"
        assert merged["meeting-link"] == "https://meet.google.com/xyz"
        assert merged["time"] == "14:00-15:00"
        assert merged["title"] == "Sprint Planning"

    def test_recording_metadata_from_source(self):
        from recap.daemon.recorder.attach import _build_merged_frontmatter
        merged = _build_merged_frontmatter(self._stub_fm(), self._source_fm())
        assert merged["recording"] == "2026-04-24 1430 Teams call.flac"
        assert merged["duration"] == "45:00"
        assert "[[Acme]]" in merged["companies"]

    def test_unscheduled_tag_removed(self):
        from recap.daemon.recorder.attach import _build_merged_frontmatter
        merged = _build_merged_frontmatter(self._stub_fm(), self._source_fm())
        assert "unscheduled" not in merged.get("tags", [])
        assert "meeting/test" in merged["tags"]

    def test_pipeline_status_from_source(self):
        from recap.daemon.recorder.attach import _build_merged_frontmatter
        stub = self._stub_fm()
        stub["pipeline-status"] = "complete"
        src = self._source_fm()
        src["pipeline-status"] = "partial"
        merged = _build_merged_frontmatter(stub, src)
        assert merged["pipeline-status"] == "partial"

    def test_participants_from_source_override_stub(self):
        from recap.daemon.recorder.attach import _build_merged_frontmatter
        merged = _build_merged_frontmatter(self._stub_fm(), self._source_fm())
        # Source's participants win; stub's "[[Stub Alice]]" absent.
        assert "[[Alice]]" in merged["participants"]
        assert "[[Bob]]" in merged["participants"]
        assert "[[Stub Alice]]" not in merged["participants"]
```

### Step 6: Run failing tests

```
.venv/Scripts/python -m pytest tests/test_attach.py::TestClassifySidecar tests/test_attach.py::TestMergeBodies tests/test_attach.py::TestMergeFrontmatter -v --override-ini="addopts="
```

Expected: AttributeError on the helper names.

### Step 7: Implement helpers in attach.py

Append after the error types:

```python
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

    - Calendar keys (event-id, calendar-source, meeting-link, time, date,
      title, org, org-subfolder) from stub.
    - Non-calendar keys (participants, companies, duration, recording,
      audio_warnings, system_audio_devices_seen, recording_started_at)
      from source.
    - "unscheduled" tag removed from tags; other tags preserved.
    - pipeline-status always from source.
    """
    calendar_keys = {
        "event-id", "calendar-source", "meeting-link", "time",
        "date", "title", "org", "org-subfolder",
    }
    source_overlay_keys = {
        "participants", "companies", "duration", "recording",
        "audio-warnings", "system-audio-devices-seen",
        "audio_warnings", "system_audio_devices_seen",
        "recording-started-at", "recording_started_at",
    }

    merged: dict = {}
    # Start with stub's calendar-identity keys.
    for k in calendar_keys:
        if k in stub_fm:
            merged[k] = stub_fm[k]

    # Overlay source's recording-identity keys.
    for k in source_overlay_keys:
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

    # pipeline-status always from source.
    if "pipeline-status" in source_fm:
        merged["pipeline-status"] = source_fm["pipeline-status"]

    return merged
```

### Step 8: Run helper tests

```
.venv/Scripts/python -m pytest tests/test_attach.py -v --override-ini="addopts="
```

Expected: classify (3) + merge_bodies (5) + merge_frontmatter (5) + error types (5) = 18 tests pass. Orchestrator tests not yet written.

### Step 9: Write failing tests for the orchestrator

Append to tests/test_attach.py:

```python
# ---------------------------------------------------------------------
# Orchestrator end-to-end tests (via real daemon setup)
# ---------------------------------------------------------------------


@pytest.fixture
def attach_daemon(tmp_path: Path):
    """Build a minimal real Daemon with recordings + vault + EventIndex."""
    import yaml
    from recap.daemon.calendar.index import EventIndex
    from recap.daemon.config import load_daemon_config
    from recap.daemon.service import Daemon

    vault = tmp_path / "vault"
    meetings = vault / "Test" / "Meetings"
    meetings.mkdir(parents=True)
    recordings = tmp_path / "recordings"
    recordings.mkdir()

    doc = {
        "config-version": 1,
        "vault-path": str(vault),
        "recordings-path": str(recordings),
        "user-name": "Tester",
        "default-org": "test",
        "orgs": {"test": {"subfolder": "Test"}},
        "detection": {},
        "calendar": {},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(doc))
    config = load_daemon_config(config_path)

    daemon = Daemon(config=config, config_path=config_path)
    daemon.event_index = EventIndex(vault / ".recap" / "event-index.json")
    return daemon


def _seed_unscheduled_recording(
    daemon, *, stem: str, event_id: str, note_path: str, body: str,
) -> Path:
    """Write an unscheduled recording setup: audio, sidecar, note."""
    from recap.artifacts import write_recording_metadata
    from recap.models import Participant, RecordingMetadata

    audio = daemon.config.recordings_path / f"{stem}.flac"
    audio.touch()
    md = RecordingMetadata(
        org="test", note_path=note_path, title="Teams call",
        date="2026-04-24", participants=[Participant(name="Alice")],
        platform="manual",
    )
    md.event_id = event_id
    write_recording_metadata(audio, md)

    vault = daemon.config.vault_path
    (vault / note_path).parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "date": "2026-04-24",
        "time": "14:30-15:15",
        "title": "Teams call",
        "event-id": event_id,
        "org": "test",
        "org-subfolder": "Test",
        "participants": ["[[Alice]]"],
        "companies": [],
        "duration": "45:00",
        "recording": f"{stem}.flac",
        "tags": ["meeting/test", "unscheduled"],
        "pipeline-status": "complete",
    }
    import yaml
    content = "---\n" + yaml.dump(fm, sort_keys=False) + "---\n\n" + body
    (vault / note_path).write_text(content, encoding="utf-8")
    daemon.event_index.add(
        event_id, Path(note_path), "test",
    )
    return audio


def _seed_calendar_stub(
    daemon, *, event_id: str, title: str, stub_body: str,
) -> Path:
    """Write a calendar stub note."""
    vault = daemon.config.vault_path
    stub_path = Path("Test/Meetings") / f"2026-04-24 - {title.lower().replace(' ', '-')}.md"
    full = vault / stub_path
    fm = {
        "date": "2026-04-24",
        "time": "14:00-15:00",
        "title": title,
        "event-id": event_id,
        "calendar-source": "google",
        "meeting-link": "https://meet.google.com/xyz",
        "org": "test",
        "org-subfolder": "Test",
        "participants": [],
        "pipeline-status": "pending",
    }
    import yaml
    content = "---\n" + yaml.dump(fm, sort_keys=False) + "---\n\n" + stub_body
    full.write_text(content, encoding="utf-8")
    daemon.event_index.add(event_id, stub_path, "test")
    return full


class TestAttachOrchestrationHappyPath:
    def test_binds_to_calendar_stub(self, attach_daemon):
        from recap.daemon.recorder.attach import attach_event_to_recording

        audio = _seed_unscheduled_recording(
            attach_daemon,
            stem="2026-04-24 1430 Teams call",
            event_id="unscheduled:abc",
            note_path="Test/Meetings/2026-04-24 1430 - Teams call.md",
            body="# Meeting Summary\n\nPipeline output.",
        )
        stub = _seed_calendar_stub(
            attach_daemon,
            event_id="E1",
            title="Sprint Planning",
            stub_body="## Agenda\n\n",
        )

        result = attach_event_to_recording(
            daemon=attach_daemon,
            stem="2026-04-24 1430 Teams call",
            event_id="E1",
        )

        assert result.status == "ok"
        assert result.noop is False
        # Merged note at stub path.
        merged = stub.read_text(encoding="utf-8")
        assert "Pipeline output" in merged
        assert "event-id: E1" in merged
        assert "unscheduled" not in merged.splitlines()[1:10]  # not in tags near top
        # Unscheduled note gone.
        unscheduled = attach_daemon.config.vault_path / "Test/Meetings/2026-04-24 1430 - Teams call.md"
        assert not unscheduled.exists()
        # EventIndex: synthetic removed.
        assert attach_daemon.event_index.lookup("unscheduled:abc") is None
        assert attach_daemon.event_index.lookup("E1") is not None
        # Sidecar rewritten.
        from recap.artifacts import load_recording_metadata
        loaded = load_recording_metadata(audio)
        assert loaded is not None
        assert loaded.event_id == "E1"
        assert loaded.calendar_source == "google"


class TestAttachOrchestrationNoOp:
    def test_sidecar_already_bound_paths_match(self, attach_daemon):
        """Sidecar + note both reference E1; return noop."""
        from recap.daemon.recorder.attach import attach_event_to_recording
        from recap.artifacts import write_recording_metadata, load_recording_metadata
        from recap.models import Participant, RecordingMetadata

        stub = _seed_calendar_stub(
            attach_daemon, event_id="E1", title="Sprint Planning",
            stub_body="## Agenda\n\n",
        )
        # Sidecar already points at E1 + stub path.
        audio = attach_daemon.config.recordings_path / "rec.flac"
        audio.touch()
        md = RecordingMetadata(
            org="test", note_path="Test/Meetings/2026-04-24 - sprint-planning.md",
            title="Sprint Planning", date="2026-04-24",
            participants=[Participant(name="Alice")], platform="manual",
        )
        md.event_id = "E1"
        write_recording_metadata(audio, md)

        result = attach_event_to_recording(
            daemon=attach_daemon, stem="rec", event_id="E1",
        )
        assert result.noop is True

    def test_sidecar_bound_but_orphan_unscheduled_note_cleaned(self, attach_daemon):
        """Simulates partial crash: sidecar bound + synthetic index still present."""
        from recap.daemon.recorder.attach import attach_event_to_recording
        from recap.artifacts import write_recording_metadata
        from recap.models import Participant, RecordingMetadata
        import yaml

        stub = _seed_calendar_stub(
            attach_daemon, event_id="E1", title="Sprint Planning",
            stub_body="## Agenda\n\n",
        )
        # Simulated orphan state: sidecar is bound to E1,
        # synthetic EventIndex entry still present, unscheduled note file still present.
        audio = attach_daemon.config.recordings_path / "rec.flac"
        audio.touch()
        md = RecordingMetadata(
            org="test",
            note_path=str(Path(stub).relative_to(attach_daemon.config.vault_path)),
            title="Sprint Planning", date="2026-04-24",
            participants=[Participant(name="A")], platform="manual",
        )
        md.event_id = "E1"
        write_recording_metadata(audio, md)
        # Add synthetic entry + unscheduled file (orphans).
        attach_daemon.event_index.add("unscheduled:abc", Path("Test/Meetings/u.md"), "test")
        orphan = attach_daemon.config.vault_path / "Test/Meetings/u.md"
        orphan.write_text("---\n" + yaml.dump({
            "event-id": "unscheduled:abc", "org": "test",
            "org-subfolder": "Test", "date": "2026-04-24", "time": "14:30-15:15",
        }) + "---\n\nOrphan body.", encoding="utf-8")

        result = attach_event_to_recording(
            daemon=attach_daemon, stem="rec", event_id="E1",
        )
        assert result.noop is True
        assert result.cleanup_performed is True
        # Orphan note deleted, synthetic entry removed.
        assert not orphan.exists()
        assert attach_daemon.event_index.lookup("unscheduled:abc") is None


class TestAttachOrchestrationErrors:
    def test_synthetic_event_id_raises(self, attach_daemon):
        from recap.daemon.recorder.attach import attach_event_to_recording
        with pytest.raises(ValueError, match="target_event_must_be_real_calendar_event"):
            attach_event_to_recording(
                daemon=attach_daemon, stem="rec", event_id="unscheduled:x",
            )

    def test_stem_not_found(self, attach_daemon):
        from recap.daemon.recorder.attach import (
            attach_event_to_recording, AttachNotFoundError,
        )
        with pytest.raises(AttachNotFoundError, match="recording not found"):
            attach_event_to_recording(
                daemon=attach_daemon, stem="ghost", event_id="E1",
            )

    def test_sidecar_missing(self, attach_daemon):
        from recap.daemon.recorder.attach import (
            attach_event_to_recording, AttachNotFoundError,
        )
        (attach_daemon.config.recordings_path / "rec.flac").touch()
        with pytest.raises(AttachNotFoundError, match="sidecar not found"):
            attach_event_to_recording(
                daemon=attach_daemon, stem="rec", event_id="E1",
            )

    def test_event_id_not_found(self, attach_daemon):
        from recap.daemon.recorder.attach import (
            attach_event_to_recording, AttachNotFoundError,
        )
        _seed_unscheduled_recording(
            attach_daemon, stem="rec", event_id="unscheduled:abc",
            note_path="Test/Meetings/u.md", body="body",
        )
        with pytest.raises(AttachNotFoundError, match="event not found"):
            attach_event_to_recording(
                daemon=attach_daemon, stem="rec", event_id="ghost",
            )

    def test_already_bound_to_other_event(self, attach_daemon):
        from recap.daemon.recorder.attach import (
            attach_event_to_recording, AttachAlreadyBoundError,
        )
        _seed_unscheduled_recording(
            attach_daemon, stem="rec", event_id="E2",
            note_path="Test/Meetings/u.md", body="body",
        )
        _seed_calendar_stub(
            attach_daemon, event_id="E1", title="Sprint",
            stub_body="## Agenda\n\n",
        )
        with pytest.raises(AttachAlreadyBoundError) as exc_info:
            attach_event_to_recording(
                daemon=attach_daemon, stem="rec", event_id="E1",
            )
        assert exc_info.value.current_event_id == "E2"

    def test_recording_conflict(self, attach_daemon):
        from recap.daemon.recorder.attach import (
            attach_event_to_recording, AttachConflictError,
        )
        _seed_unscheduled_recording(
            attach_daemon, stem="rec-new", event_id="unscheduled:abc",
            note_path="Test/Meetings/u.md", body="new body",
        )
        # Stub already has a different `recording` field (from a prior bind).
        vault = attach_daemon.config.vault_path
        stub_path = Path("Test/Meetings/2026-04-24 - sprint.md")
        import yaml
        fm = {
            "date": "2026-04-24", "time": "14:00-15:00", "title": "Sprint",
            "event-id": "E1", "calendar-source": "google",
            "meeting-link": "", "org": "test", "org-subfolder": "Test",
            "recording": "other-rec.flac",  # existing recording
            "pipeline-status": "complete",
        }
        (vault / stub_path).write_text(
            "---\n" + yaml.dump(fm, sort_keys=False) + "---\n\n## Agenda\n\n",
            encoding="utf-8",
        )
        attach_daemon.event_index.add("E1", stub_path, "test")

        with pytest.raises(AttachConflictError) as exc_info:
            attach_event_to_recording(
                daemon=attach_daemon, stem="rec-new", event_id="E1",
                replace=False,
            )
        assert exc_info.value.existing_recording == "other-rec.flac"

    def test_replace_skips_conflict(self, attach_daemon):
        """With replace=true, conflict is ignored and bind proceeds."""
        from recap.daemon.recorder.attach import attach_event_to_recording
        _seed_unscheduled_recording(
            attach_daemon, stem="rec-new", event_id="unscheduled:abc",
            note_path="Test/Meetings/u.md", body="new body",
        )
        vault = attach_daemon.config.vault_path
        stub_path = Path("Test/Meetings/2026-04-24 - sprint.md")
        import yaml
        fm = {
            "date": "2026-04-24", "time": "14:00-15:00", "title": "Sprint",
            "event-id": "E1", "calendar-source": "google",
            "meeting-link": "", "org": "test", "org-subfolder": "Test",
            "recording": "other-rec.flac",
            "pipeline-status": "complete",
        }
        (vault / stub_path).write_text(
            "---\n" + yaml.dump(fm, sort_keys=False) + "---\n\n## Agenda\n\n",
            encoding="utf-8",
        )
        attach_daemon.event_index.add("E1", stub_path, "test")

        result = attach_event_to_recording(
            daemon=attach_daemon, stem="rec-new", event_id="E1", replace=True,
        )
        assert result.status == "ok"
        assert result.noop is False
        # New recording field overwrote old.
        content = (vault / stub_path).read_text()
        assert "rec-new.flac" in content

    def test_cross_org_bind_refused(self, attach_daemon):
        """Stub in a different org raises ValueError cross_org_bind_refused."""
        # For this test, seed source in org 'test' but stub's frontmatter
        # manually set to org 'other'. Orchestrator should 400.
        # Implementer: setup details depend on how org_config resolves;
        # may need to register a second org in the fixture.
        pass
```

### Step 10: Run failing orchestrator tests

```
.venv/Scripts/python -m pytest tests/test_attach.py -v --override-ini="addopts="
```

Expected: orchestrator tests fail with NotImplementedError.

### Step 11: Implement the orchestrator

Replace the `attach_event_to_recording` stub in attach.py:

```python
def attach_event_to_recording(
    *, daemon: "Daemon", stem: str, event_id: str, replace: bool = False,
) -> AttachResult:
    """Orchestrate retroactive calendar bind per design Section 2.

    Raises AttachAlreadyBoundError, AttachConflictError, AttachNotFoundError,
    or ValueError on failure. Retry-safe via cleanup-on-no-op.
    """
    import json
    import yaml
    from recap.artifacts import (
        load_recording_metadata, rebind_recording_metadata_to_event,
        resolve_recording_path,
    )
    from recap.daemon.calendar.sync import (
        _parse_frontmatter, find_note_by_event_id,
    )
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
        raise ValueError(f"unknown org: {sidecar.org}")
    meetings_dir = org_config.resolve_subfolder(vault_path) / "Meetings"
    target_path = find_note_by_event_id(
        event_id, meetings_dir,
        vault_path=vault_path, event_index=daemon.event_index,
    )
    if target_path is None:
        raise AttachNotFoundError("event not found")

    # Step 4: Reconcile candidate with target.
    target_rel = target_path.relative_to(vault_path)
    if classification == "noop_candidate":
        if str(sidecar.note_path) == str(target_rel):
            # No-op path: fire cleanup for orphans.
            cleaned = _cleanup_after_bind(
                daemon,
                synthetic_id=None,  # sidecar not synthetic here
                unscheduled_path=None,
                event_id_to_clear=None,
            )
            return AttachResult(
                status="ok", note_path=str(target_rel),
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
                synthetic_id=sidecar.event_id,
                unscheduled_path=source_abs,
                event_id_to_clear=sidecar.event_id,
            )
            # Sidecar still shows synthetic event_id; rewrite it now.
            rebind_recording_metadata_to_event(
                audio_path,
                event_id=event_id,
                note_path=str(target_rel),
                calendar_source=target_fm.get("calendar-source"),
                meeting_link=target_fm.get("meeting-link"),
                title=target_fm.get("title"),
            )
            return AttachResult(
                status="ok", note_path=str(target_rel),
                noop=True, cleanup_performed=cleaned,
            )
        if not replace:
            raise AttachConflictError(
                existing_recording=str(target_recording),
                note_path=str(target_rel),
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
        note_path=str(target_rel),
        calendar_source=target_fm.get("calendar-source"),
        meeting_link=target_fm.get("meeting-link"),
        title=target_fm.get("title"),
    )

    # Step 10-11: Cleanup.
    cleaned = _cleanup_after_bind(
        daemon,
        synthetic_id=sidecar.event_id,
        unscheduled_path=source_abs,
        event_id_to_clear=sidecar.event_id,
    )

    return AttachResult(
        status="ok", note_path=str(target_rel),
        noop=False, cleanup_performed=cleaned,
    )


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
    synthetic_id: str | None,
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
```

### Step 12: Run tests

```
.venv/Scripts/python -m pytest tests/test_attach.py -v --override-ini="addopts="
.venv/Scripts/python -m pytest tests/ --override-ini="addopts=" 2>&1 | tail -5
```

Expected: all attach tests pass (error types + helpers + orchestrator). Full suite green modulo ffprobe.

### Step 13: Commit

```
git add recap/daemon/recorder/attach.py tests/test_attach.py
git commit -m "feat(#33): attach_event_to_recording orchestrator + helpers"
```

---

## Task 5: `POST /api/recordings/{stem}/attach-event` endpoint

**Files:**
- Modify: `recap/daemon/server.py`
- Modify: `tests/test_daemon_server.py`

### Step 1: Write failing tests

Add `TestApiAttachEvent` class to tests/test_daemon_server.py:

```python
@pytest.mark.asyncio
class TestApiAttachEvent:
    """POST /api/recordings/{stem}/attach-event endpoint (#33 Task 5)."""

    async def test_401_without_auth(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post(
            "/api/recordings/rec/attach-event", json={"event_id": "E1"},
        )
        assert resp.status == 401

    async def test_400_invalid_stem(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post(
            "/api/recordings/..%2Fevil/attach-event",
            json={"event_id": "E1"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

    async def test_400_missing_event_id(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post(
            "/api/recordings/rec/attach-event", json={},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

    async def test_400_synthetic_event_id(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post(
            "/api/recordings/rec/attach-event",
            json={"event_id": "unscheduled:abc"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400
        data = await resp.json()
        assert data["error"] == "target_event_must_be_real_calendar_event"

    async def test_404_stem_unresolved(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post(
            "/api/recordings/ghost/attach-event",
            json={"event_id": "E1"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 404

    async def test_409_on_recording_conflict(self, daemon_client):
        """Implementer: seed unscheduled + calendar stub with different existing recording.
        Assert 409 + body.error == 'recording_conflict' + structured fields."""
        pass  # Implementer: full setup — see test_attach.py harness.

    async def test_200_happy_path(self, daemon_client):
        """Happy-path bind via HTTP. Implementer: seed + POST + verify 200."""
        pass  # Implementer.
```

### Step 2: Run failing tests

```
.venv/Scripts/python -m pytest tests/test_daemon_server.py::TestApiAttachEvent -v --override-ini="addopts="
```

### Step 3: Implement `_api_attach_event` handler

Add to recap/daemon/server.py near other /api/recordings handlers:

```python
async def _api_attach_event(request: web.Request) -> web.Response:
    """POST /api/recordings/<stem>/attach-event -- retroactive calendar bind.

    See docs/plans/2026-04-24-33-retroactive-calendar-bind-design.md Section 4.
    """
    daemon: Daemon = request.app["daemon"]
    stem = request.match_info["stem"]
    if not _STEM_RE.fullmatch(stem):
        return web.json_response({"error": "invalid stem"}, status=400)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response(
            {"error": "body must be an object"}, status=400,
        )

    event_id = body.get("event_id")
    replace = bool(body.get("replace", False))
    if not isinstance(event_id, str) or not event_id:
        return web.json_response({"error": "missing event_id"}, status=400)
    if event_id.startswith("unscheduled:"):
        return web.json_response(
            {"error": "target_event_must_be_real_calendar_event"}, status=400,
        )

    from recap.daemon.recorder.attach import (
        attach_event_to_recording,
        AttachAlreadyBoundError, AttachConflictError, AttachNotFoundError,
    )
    try:
        result = attach_event_to_recording(
            daemon=daemon, stem=stem, event_id=event_id, replace=replace,
        )
        return web.json_response(result.to_dict())
    except AttachAlreadyBoundError as e:
        return web.json_response(e.to_dict(), status=400)
    except AttachConflictError as e:
        return web.json_response(e.to_dict(), status=409)
    except AttachNotFoundError as e:
        return web.json_response(e.to_dict(), status=404)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as e:
        logger.exception("attach-event failed for stem=%s", stem)
        return web.json_response(
            {"error": f"attach failed: {e}"}, status=500,
        )
```

Register the route near other `/api/recordings/*` routes:

```python
app.router.add_post(
    "/api/recordings/{stem}/attach-event", _api_attach_event,
)
```

### Step 4: Flesh out the placeholder tests (happy path + conflict)

Implement the `pass` bodies in `TestApiAttachEvent` based on the patterns in `test_attach.py::TestAttachOrchestration*`. Use `daemon_client` fixture; seed unscheduled note + calendar stub + sidecar; POST; assert response body + disk state.

### Step 5: Run tests

```
.venv/Scripts/python -m pytest tests/test_daemon_server.py::TestApiAttachEvent -v --override-ini="addopts="
.venv/Scripts/python -m pytest tests/ --override-ini="addopts=" 2>&1 | tail -5
```

Expected: endpoint tests pass; full suite green.

### Step 6: Commit

```
git add recap/daemon/server.py tests/test_daemon_server.py
git commit -m "feat(#33): POST /api/recordings/{stem}/attach-event endpoint"
```

---

## Task 6: Integration E2E test

**Files:**
- Create: `tests/test_attach_integration.py`

### Step 1: Write 4 scenarios

Mirror `tests/test_speaker_correction_integration.py` pattern. Use real `Daemon` + real aiohttp + real disk. Scenarios:

1. `test_happy_path_bind_unscheduled_to_calendar_event` — seed unscheduled recording + sidecar + unscheduled note + calendar stub with untouched body. POST. Assert merged note on target path; correct frontmatter + pipeline body; NO Pre-Meeting Notes section (stub was empty template); sidecar rewritten; EventIndex has only real entry; unscheduled file gone.
2. `test_bind_preserves_user_edits_under_pre_meeting_notes` — seed with user-edited stub body. Assert merged note has `## Pre-Meeting Notes` section with preserved content after the pipeline output.
3. `test_replace_path_overrides_existing_recording` — seed target stub with prior recording (different stem). POST with `replace=True`. Assert stub body overwritten with new recording's pipeline output; old recording's artifacts still on disk (FLAC, transcript, etc.).
4. `test_retry_after_partial_success_heals_orphans` — pre-seed state that simulates "crash after merged-note-write but before EventIndex cleanup": merged note present, sidecar bound, synthetic EventIndex entry still present, unscheduled file still present. POST again. Assert no-op result with `cleanup_performed=true`; both orphans removed.

Implementer: reuse the `_seed_unscheduled_recording` and `_seed_calendar_stub` helpers from `test_attach.py` (either via conftest promotion or by duplicating — follow what the #28 tests did).

### Step 2: Run tests

```
.venv/Scripts/python -m pytest tests/test_attach_integration.py -v --override-ini="addopts="
```

Expected: 4 pass.

### Step 3: Commit

```
git add tests/test_attach_integration.py
git commit -m "test(#33): integration E2E for retroactive bind"
```

---

## Task 7: Plugin `DaemonError.body` + JSON parsing

**Files:**
- Modify: `obsidian-recap/src/api.ts`

### Step 1: Inspect current `DaemonError` + `get`/`post`

Read `obsidian-recap/src/api.ts` lines 1-140. Find `DaemonError` class and the `get`/`post`/`delete` helpers.

### Step 2: Extend DaemonError

```typescript
export class DaemonError extends Error {
    constructor(
        public status: number,
        message: string,
        public body?: unknown,  // parsed JSON body when available
    ) {
        super(message);
    }
}
```

### Step 3: Update `get<T>` and `post<T>` to parse JSON error bodies

```typescript
async get<T>(path: string): Promise<T> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
        headers: { "Authorization": `Bearer ${this.token}` },
    });
    if (!resp.ok) {
        const text = await resp.text();
        let parsed: unknown;
        try { parsed = JSON.parse(text); } catch {}
        throw new DaemonError(resp.status, text, parsed);
    }
    return resp.json() as Promise<T>;
}

async post<T>(path: string, body?: unknown): Promise<T> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
        method: "POST",
        headers: {
            "Authorization": `Bearer ${this.token}`,
            "Content-Type": "application/json",
        },
        body: body ? JSON.stringify(body) : undefined,
    });
    if (!resp.ok) {
        const text = await resp.text();
        let parsed: unknown;
        try { parsed = JSON.parse(text); } catch {}
        throw new DaemonError(resp.status, text, parsed);
    }
    return resp.json() as Promise<T>;
}
```

(Leave `delete` unchanged unless it has a non-ok path — same one-line change pattern applies.)

### Step 4: Test via existing Vitest suite

```
cd obsidian-recap && npm test
```

Expected: all existing tests still pass (backward compatible: existing callers don't use `.body` and `.message` keeps the text fallback).

### Step 5: Commit

```
cd ..
git add obsidian-recap/src/api.ts
git commit -m "feat(#33): DaemonError.body + JSON parse in get/post"
```

---

## Task 8: Plugin `DaemonClient.attachEvent` method

**Files:**
- Modify: `obsidian-recap/src/api.ts`

### Step 1: Add types + method

```typescript
export interface AttachEventResponse {
    status: string;
    note_path: string;
    noop?: boolean;
    cleanup_performed?: boolean;
}

export interface AttachEventConflict {
    error: "recording_conflict";
    existing_recording: string;
    note_path: string;
}

export interface AttachEventAlreadyBound {
    error: "already_bound_to_other_event";
    current_event_id: string;
    current_note_path?: string;
}

// In DaemonClient class:
async attachEvent(params: {
    stem: string;
    event_id: string;
    replace?: boolean;
}): Promise<AttachEventResponse> {
    return this.post(
        `/api/recordings/${encodeURIComponent(params.stem)}/attach-event`,
        {event_id: params.event_id, replace: params.replace ?? false},
    );
}
```

### Step 2: Verify build

```
cd obsidian-recap && npm run build && npm test
```

Expected: clean build + all tests pass.

### Step 3: Commit

```
cd ..
git add obsidian-recap/src/api.ts
git commit -m "feat(#33): DaemonClient.attachEvent method + types"
```

---

## Task 9: `CalendarEventPickerModal`

**Files:**
- Create: `obsidian-recap/src/views/CalendarEventPickerModal.ts`

### Step 1: Write the file

```typescript
import { App, SuggestModal } from "obsidian";

export interface CalendarEventCandidate {
    event_id: string;
    title: string;
    date: string;
    time: string;
    calendar_source: string;
    note_path: string;
}

export class CalendarEventPickerModal extends SuggestModal<CalendarEventCandidate> {
    constructor(
        app: App,
        private candidates: CalendarEventCandidate[],
        private onPick: (picked: CalendarEventCandidate) => void | Promise<void>,
    ) {
        super(app);
        this.setPlaceholder("Type to filter calendar events...");
    }

    getSuggestions(query: string): CalendarEventCandidate[] {
        const q = query.toLowerCase();
        if (!q) return this.candidates;
        return this.candidates.filter(c =>
            c.title.toLowerCase().includes(q)
            || c.date.includes(q)
            || c.calendar_source.toLowerCase().includes(q),
        );
    }

    renderSuggestion(c: CalendarEventCandidate, el: HTMLElement): void {
        const parts = [c.title, c.date, c.time, c.calendar_source]
            .filter(Boolean)
            .join(" -- ");
        el.createEl("div", { text: parts });
    }

    onChooseSuggestion(c: CalendarEventCandidate): void {
        void this.onPick(c);
    }
}
```

### Step 2: Verify build

```
cd obsidian-recap && npm run build
```

Expected: clean.

### Step 3: Commit

```
cd ..
git add obsidian-recap/src/views/CalendarEventPickerModal.ts
git commit -m "feat(#33): CalendarEventPickerModal SuggestModal"
```

---

## Task 10: `ConfirmReplaceModal`

**Files:**
- Create: `obsidian-recap/src/views/ConfirmReplaceModal.ts`

### Step 1: Write the file

```typescript
import { App, Modal } from "obsidian";

export class ConfirmReplaceModal extends Modal {
    private resolvePromise?: (confirmed: boolean) => void;

    constructor(
        app: App,
        private existingRecording: string,
        private newRecording: string,
    ) {
        super(app);
    }

    prompt(): Promise<boolean> {
        return new Promise<boolean>((resolve) => {
            this.resolvePromise = resolve;
            this.open();
        });
    }

    onOpen(): void {
        const { contentEl } = this;
        contentEl.empty();
        contentEl.createEl("h2", { text: "Replace existing recording?" });
        contentEl.createEl("p", {
            text: `Event already has recording "${this.existingRecording}" attached.`,
        });
        contentEl.createEl("p", {
            text: `Replacing will overwrite its note content with pipeline output from "${this.newRecording}". Old recording artifacts on disk are not deleted.`,
        });

        const btnContainer = contentEl.createEl("div", {
            attr: { style: "display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px;" },
        });
        const replaceBtn = btnContainer.createEl("button", {
            text: "Replace",
            cls: "mod-warning",
        });
        const cancelBtn = btnContainer.createEl("button", { text: "Cancel" });

        replaceBtn.onclick = () => {
            this.resolvePromise?.(true);
            this.close();
        };
        cancelBtn.onclick = () => {
            this.resolvePromise?.(false);
            this.close();
        };
    }

    onClose(): void {
        // If closed without a button click, treat as cancel.
        this.resolvePromise?.(false);
        this.resolvePromise = undefined;
        this.contentEl.empty();
    }
}
```

### Step 2: Verify build

```
cd obsidian-recap && npm run build
```

### Step 3: Commit

```
cd ..
git add obsidian-recap/src/views/ConfirmReplaceModal.ts
git commit -m "feat(#33): ConfirmReplaceModal"
```

---

## Task 11: Plugin `main.ts` — command + orchestrator + candidate scan

**Files:**
- Modify: `obsidian-recap/src/main.ts`

### Step 1: Import the new views + DaemonError

Near the top of main.ts:

```typescript
import { CalendarEventPickerModal, CalendarEventCandidate } from "./views/CalendarEventPickerModal";
import { ConfirmReplaceModal } from "./views/ConfirmReplaceModal";
import { DaemonError, AttachEventConflict } from "./api";
```

### Step 2: Register command in `onload`

```typescript
this.addCommand({
    id: "recap-link-to-calendar-event",
    name: "Link to calendar event",
    checkCallback: (checking: boolean) => {
        const file = this.app.workspace.getActiveFile();
        if (!file) return false;
        const cache = this.app.metadataCache.getFileCache(file);
        const eventId = cache?.frontmatter?.["event-id"];
        const isUnscheduled = typeof eventId === "string"
            && eventId.startsWith("unscheduled:");
        if (!isUnscheduled) return false;
        if (checking) return true;
        void this.openLinkToCalendarFlow(file);
        return true;
    },
});
```

### Step 3: Add orchestrator + helpers

```typescript
private async openLinkToCalendarFlow(file: TFile): Promise<void> {
    if (!this.client) { new Notice("Daemon not connected"); return; }

    const cache = this.app.metadataCache.getFileCache(file);
    const fm = cache?.frontmatter;
    const recording = (fm?.recording ?? "").toString().replace(/\[\[|\]\]/g, "");
    const stem = recording.replace(/\.(flac|m4a|aac)$/i, "");
    const orgSubfolder = fm?.["org-subfolder"] || "";
    const recordingDate = fm?.date || "";
    if (!stem || !orgSubfolder || !recordingDate) {
        new Notice("Missing recording/date/org-subfolder in frontmatter");
        return;
    }

    const candidates = this.scanCalendarStubCandidates(
        orgSubfolder, recordingDate,
    );
    if (candidates.length === 0) {
        new Notice("No calendar events found within one day of this recording");
        return;
    }

    new CalendarEventPickerModal(this.app, candidates, async (picked) => {
        await this.submitAttachEvent(file, stem, picked.event_id);
    }).open();
}

private scanCalendarStubCandidates(
    orgSubfolder: string, recordingDate: string,
): CalendarEventCandidate[] {
    const prefix = orgSubfolder.endsWith("/")
        ? `${orgSubfolder}Meetings/`
        : `${orgSubfolder}/Meetings/`;
    const recordingDay = new Date(recordingDate + "T00:00:00Z");
    const out: CalendarEventCandidate[] = [];

    for (const file of this.app.vault.getMarkdownFiles()) {
        if (!file.path.startsWith(prefix)) continue;
        const fm = this.app.metadataCache.getFileCache(file)?.frontmatter;
        if (!fm) continue;
        const eventId = fm["event-id"];
        if (typeof eventId !== "string") continue;
        if (eventId.startsWith("unscheduled:")) continue;

        const date = fm.date;
        if (typeof date !== "string") continue;
        const eventDay = new Date(date + "T00:00:00Z");
        const diffDays = Math.abs(
            (eventDay.getTime() - recordingDay.getTime()) / (24 * 60 * 60 * 1000),
        );
        if (diffDays > 1) continue;

        out.push({
            event_id: eventId,
            title: String(fm.title ?? file.basename),
            date,
            time: String(fm.time ?? ""),
            calendar_source: String(fm["calendar-source"] ?? ""),
            note_path: file.path,
        });
    }
    out.sort((a, b) => a.date !== b.date
        ? a.date.localeCompare(b.date)
        : a.time.localeCompare(b.time));
    return out;
}

private async submitAttachEvent(
    sourceFile: TFile, stem: string, eventId: string, replace: boolean = false,
): Promise<void> {
    if (!this.client) return;
    try {
        const result = await this.client.attachEvent({stem, event_id: eventId, replace});
        new Notice(result.noop
            ? "Already bound to this event."
            : "Linked to calendar event. Opening note...");
        await this.openTargetNote(result.note_path);
    } catch (e) {
        if (e instanceof DaemonError) {
            if (e.status === 409 && e.body && typeof e.body === "object") {
                const body = e.body as AttachEventConflict;
                if (body.error === "recording_conflict") {
                    const confirmed = await new ConfirmReplaceModal(
                        this.app, body.existing_recording, stem,
                    ).prompt();
                    if (confirmed) {
                        await this.submitAttachEvent(sourceFile, stem, eventId, true);
                    }
                    return;
                }
            }
            if (e.status === 400) {
                new Notice(`Recap: ${e.message || "bad request"}`);
                return;
            }
            if (e.status === 404) {
                new Notice(`Recap: not found`);
                return;
            }
        }
        new Notice(`Recap: link failed -- ${e}`);
    }
}

private async openTargetNote(notePath: string): Promise<void> {
    const file = this.app.vault.getAbstractFileByPath(notePath);
    if (file instanceof TFile) {
        await this.app.workspace.getLeaf().openFile(file);
    }
}
```

### Step 4: Build + test

```
cd obsidian-recap && npm run build && npm test
```

### Step 5: Commit

```
cd ..
git add obsidian-recap/src/main.ts
git commit -m "feat(#33): Link to calendar event command + orchestrator"
```

---

## Task 12: `MeetingListView` + `MeetingRow` context-menu entry

**Files:**
- Modify: `obsidian-recap/src/views/MeetingListView.ts`
- Modify: `obsidian-recap/src/components/MeetingRow.ts`

### Step 1: Thread a new callback through `MeetingListView`'s deps

Find the constructor of `MeetingListView` (check existing shape). Add a new optional callback prop:

```typescript
interface MeetingListViewDeps {
    // ... existing ...
    onLinkToCalendar?: (file: TFile) => void;
}
```

Plumb the callback from the plugin onload where the view is constructed. Invoke `this.openLinkToCalendarFlow(file)`.

### Step 2: Render context-menu handler in `MeetingRow`

Add a right-click handler (`contextmenu` event) to the row element:

```typescript
rowEl.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    const menu = new Menu();
    menu.addItem((item) =>
        item.setTitle("Link to calendar event")
            .setIcon("link")
            .onClick(() => deps.onLinkToCalendar?.(file))
    );
    menu.showAtMouseEvent(e);
});
```

Only show the item when the row's note is unscheduled (check frontmatter).

### Step 3: Build + test

```
cd obsidian-recap && npm run build && npm test
```

### Step 4: Commit

```
cd ..
git add obsidian-recap/src/views/MeetingListView.ts obsidian-recap/src/components/MeetingRow.ts
git commit -m "feat(#33): MeetingRow context-menu entry for Link to calendar event"
```

---

## Task 13: MANIFEST + acceptance checklist

**Files:**
- Modify: `MANIFEST.md`
- Create: `docs/handoffs/2026-04-24-33-acceptance.md`

### Step 1: Update MANIFEST.md

Add a new Key Relationships bullet after the existing #28 bullet:

```markdown
- **Retroactive calendar bind (#33):** `POST /api/recordings/<stem>/attach-event`
  lets the user re-bind a recording from a synthetic `unscheduled:<uuid>`
  identity to a real calendar event. Plugin's "Link to calendar event"
  command scans `<org-subfolder>/Meetings/*.md` for calendar stubs within
  +/- 1 day of the recording's date and presents a `CalendarEventPickerModal`.
  Daemon's `attach_event_to_recording` orchestrator (in
  `recap/daemon/recorder/attach.py`) merges the unscheduled note's content
  onto the calendar stub's path, preserves meaningful stub body under
  `## Pre-Meeting Notes` (Q3 heuristic with unexpected-shape fallback),
  rewrites the `RecordingMetadata` sidecar to bound-event state via
  `rebind_recording_metadata_to_event`, removes the synthetic EventIndex
  entry, and deletes the unscheduled note file. Conflict on target's
  existing `recording` field returns 409 + structured body; plugin's
  `ConfirmReplaceModal` captures user consent; re-POST with `replace=true`
  proceeds. Cleanup-on-no-op heals orphaned EventIndex entries and
  unscheduled note files after mid-bind crashes, keeping retry safe.
  `write_recording_metadata` and the new `_atomic_write_note` helper use
  temp+os.replace for crash safety. `DaemonError` gains an optional
  parsed `body` field so every future structured-error endpoint benefits.
  Multi-recording merge for same event deferred to #39.
```

### Step 2: Create `docs/handoffs/2026-04-24-33-acceptance.md`

ASCII-only (follow the #28 handoff pattern to avoid mojibake). 9 manual scenarios:

```markdown
# Issue #33 Manual Acceptance Checklist

Covers scenarios that unit + integration tests can't exercise.

## Preflight

- [ ] `pytest tests/test_artifacts.py tests/test_vault.py tests/test_attach.py tests/test_daemon_server.py tests/test_attach_integration.py -v --override-ini="addopts="` passes.
- [ ] `cd obsidian-recap && npm test && npm run build` clean.
- [ ] Test vault has at least 2 unscheduled recordings + corresponding calendar stubs within +/- 1 day.

## Core scenarios

1. **Command visible on unscheduled notes only**
   - [ ] Open an unscheduled meeting note. Run "Link to calendar event" from command palette. Command appears.
   - [ ] Open a scheduled note (event-id does not start with unscheduled:). Run command palette, type "Link to calendar event". Command is hidden.

2. **Picker shows events within +/- 1 day**
   - [ ] Run the command on an unscheduled note. Picker opens with candidate calendar events.
   - [ ] Confirm no events with event-id starting with `unscheduled:` appear.
   - [ ] Confirm events more than 1 day away from the recording's date are filtered out.

3. **Happy-path bind on untouched stub**
   - [ ] Pick a calendar event whose stub body is just "## Agenda" (no user edits).
   - [ ] After successful bind, the merged note opens automatically.
   - [ ] Verify frontmatter has real event-id, calendar-source, meeting-link, time.
   - [ ] Verify body is pipeline output only (NO ## Pre-Meeting Notes section).
   - [ ] Verify the unscheduled note file is gone from the Meetings folder.

4. **Happy-path bind on user-edited stub**
   - [ ] Before binding, edit the stub's body to include user notes under "## Agenda".
   - [ ] Run the bind.
   - [ ] Verify merged note has pipeline output first, then "## Pre-Meeting Notes" with preserved user content.

5. **Conflict path: replace confirmed**
   - [ ] Bind a recording to a calendar event. Then unscheduled-record a second meeting and retroactively attempt to bind it to the same calendar event.
   - [ ] Confirmation modal appears: "Event already has recording <X> attached. Replace...?"
   - [ ] Click Replace. Verify the merged note overwrites with the new pipeline output.
   - [ ] Confirm old recording's artifacts (FLAC, transcript, analysis, speakers.json) remain on disk in the recordings folder.

6. **Conflict path: cancel**
   - [ ] Repeat scenario 5 but click Cancel.
   - [ ] Verify nothing changed: merged note still has the old content, sidecar still has old event_id, unscheduled note still exists.

7. **Retry safety**
   - 7a: Duplicate POST after success via CLI (`curl` / `httpie`):
     - [ ] After a successful bind, run a second POST with the same stem + event_id. Expect 200 with `{"noop": true}`.
   - 7b: Healing after partial crash:
     - [ ] Manually simulate orphan state (instructions deferred to the design doc or an ops runbook).
     - [ ] Re-POST same request. Expect 200 with `cleanup_performed: true`.
     - [ ] Verify orphan synthetic EventIndex entry + orphan unscheduled note file removed.

8. **No candidate events**
   - [ ] Create an unscheduled recording whose date has no calendar events within +/- 1 day.
   - [ ] Run the command. Expect notice: "No calendar events found within one day of this recording".

9. **Calendar sync during bind (documented race)**
   - [ ] While a calendar sync cycle is happening, trigger a bind. Expect it to succeed.
   - [ ] Document any weirdness observed; the design accepts this as a v1 race.

## Sign-off

- [ ] All 9 scenarios pass.
- [ ] No unexpected errors in daemon logs.
- [ ] Plugin build + Python tests all green.
- [ ] Ready for PR review.
```

### Step 3: Verify ASCII-only on acceptance file

```
python -c "open('docs/handoffs/2026-04-24-33-acceptance.md', encoding='utf-8').read().encode('ascii'); print('ok')"
```

If this raises, sanitize (same script as #28 used).

### Step 4: Commit

```
git add MANIFEST.md docs/handoffs/2026-04-24-33-acceptance.md
git commit -m "docs(#33): MANIFEST update + manual acceptance checklist"
```

---

## Task 14: Final verification

### Step 1: Full test suite

```
.venv/Scripts/python -m pytest tests/ --override-ini="addopts=" 2>&1 | tail -5
```

Expected: all passing, modulo the pre-existing ffprobe failure carried over from master.

### Step 2: Plugin build + tests

```
cd obsidian-recap && npm run build && npm test && cd ..
```

### Step 3: Branch summary

```
git log --oneline master..HEAD
```

Expected: ~14 commits (one per task + design doc).

### Step 4: Regenerate plugin bundle

`main.js` needs to be committed with the latest build output per the repo's convention (matches #28's pattern):

```
cd obsidian-recap && npm run build && cd ..
git add obsidian-recap/main.js
git commit -m "chore(#33): regenerate plugin bundle"
```

(Only needed if build changed the bundle.)

### Step 5: Manual acceptance spot-check

Run scenarios 1-4 from the acceptance checklist against a real vault before handing off the PR.

### Step 6: Handoff

Invoke `superpowers:finishing-a-development-branch` to pick Option 2 (push + PR).

---

## Implementation notes

- **TDD throughout.** Each task starts with failing tests, goes to green, commits.
- **YAGNI.** No thread offload, no auto-reconcile, no multi-recording merge (deferred to #39).
- **Codex review recommended between Tasks 4, 5, 11** — these are the integration-heavy steps where subtle semantic errors (merge logic, endpoint error mapping, UI state handling) cost the most. Running under SDD's automatic review-between-tasks covers this.
- **Skip JS DOM testing** beyond type checks + Vitest for pure functions — modal UI is covered via manual acceptance.

## References

- Design: [docs/plans/2026-04-24-33-retroactive-calendar-bind-design.md](docs/plans/2026-04-24-33-retroactive-calendar-bind-design.md)
- Issue: [#33](https://github.com/TimSimpsonJr/recap/issues/33)
- Prerequisite (merged): #27 / PR #34 (unscheduled meetings)
- Follow-up: [#39](https://github.com/TimSimpsonJr/recap/issues/39) (merge multiple recordings)
- Related: #28 speaker correction (merged PR #38) — established atomic sidecar write + `DaemonError.body` patterns reused here

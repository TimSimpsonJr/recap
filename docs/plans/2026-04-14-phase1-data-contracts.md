# Phase 1: Data Contracts Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Lock down the canonical meeting-note contract and the `RecordingMetadata` shape, and disambiguate the two `PipelineConfig` classes. Stops the silent frontmatter backfill bug and makes calendar-seeded notes produce complete output.

**Architecture:** Field-level merge into a canonical frontmatter dict via a new `upsert_note(path, frontmatter, marker, body)` helper. `write_meeting_note` becomes a thin wrapper that builds canonical frontmatter and delegates. `RecordingMetadata` gains `llm_backend`, threaded through `_build_runtime_config` so Signal's popup choice reaches `analyze`. Two renames eliminate the `PipelineConfig` naming collision: daemon-side settings become `PipelineSettings`, per-run runtime config becomes `PipelineRuntimeConfig`.

**Tech Stack:** Python 3.10+, dataclasses, PyYAML, pytest + pytest-asyncio, real tmp filesystems (no mocks of `write_meeting_note`).

**Read before starting:** `docs/plans/2026-04-14-fix-everything-design.md`, specifically §0.1 (canonical note contract + upsert rules), §0.3 (RecordingMetadata shape), §0.6 (config naming). Those sections are the source of truth — this plan is the execution path.

**Baseline commit:** `91f4ff2` (docs: contract freeze).

---

## Conventions for every task

- Every task ends with a commit using Conventional Commits (`feat:`, `refactor:`, `test:`, `fix:`, `chore:`).
- Tests go in `tests/` mirroring module paths. Use `pytest` with the existing `conftest.py` fixtures (`tmp_vault`, `tmp_recordings`).
- Never mock `write_meeting_note`, `upsert_note`, or `_update_note_frontmatter` in tests — use a real tmp vault.
- When a test already mocks these, the task fixing that test rewrites it to hit real filesystem.
- Run the **full** test suite (`uv run pytest -q`) at the end of every task, not just the file you touched. A rename in one file breaks imports in others.

---

## Task 1: Rename `recap.daemon.config.PipelineConfig` → `PipelineSettings`

**Files:**
- Modify: `recap/daemon/config.py:63`, `recap/daemon/config.py:104`, `recap/daemon/config.py:223`
- Modify: `tests/test_daemon_config.py` (any references)

**Step 1: Establish baseline**

Run: `uv run pytest tests/test_daemon_config.py -v`
Expected: all current tests PASS. Save the count.

**Step 2: Rename the class and its references inside `recap/daemon/config.py`**

Rename `class PipelineConfig:` → `class PipelineSettings:`
Update `pipeline: PipelineConfig = field(default_factory=PipelineConfig)` → `pipeline: PipelineSettings = field(default_factory=PipelineSettings)`
Update `pipeline = PipelineConfig(...)` in `load_daemon_config` → `pipeline = PipelineSettings(...)`

**Step 3: Search for any other references in the codebase**

Run: `grep -rn "daemon.config.*PipelineConfig\|from recap.daemon.config import.*PipelineConfig" recap/ tests/`
Expected: no hits (the only import path into this symbol was via `DaemonConfig.pipeline`, not a direct import).

**Step 4: Run full test suite**

Run: `uv run pytest -q`
Expected: all tests still pass.

**Step 5: Commit**

```bash
git add recap/daemon/config.py tests/test_daemon_config.py
git commit -m "refactor: rename daemon PipelineConfig to PipelineSettings"
```

---

## Task 2: Rename `recap.pipeline.PipelineConfig` → `PipelineRuntimeConfig`

**Files:**
- Modify: `recap/pipeline/__init__.py:35` (class), `:56, :63, :69, :77, :85, :238, :286` (type hints)
- Modify: `recap/cli.py:11, :83`
- Modify: `recap/daemon/__main__.py:30` (remove the `as PipelineCfg` alias; import directly as `PipelineRuntimeConfig`)
- Modify: `tests/test_pipeline.py:17, :64`

**Step 1: Rename in `recap/pipeline/__init__.py`**

Find `class PipelineConfig:` at line 35; rename to `class PipelineRuntimeConfig:`. Replace all type hints in the same file (`config: PipelineConfig` → `config: PipelineRuntimeConfig`).

**Step 2: Update `recap/cli.py`**

Change `from recap.pipeline import PipelineConfig, run_pipeline` → `from recap.pipeline import PipelineRuntimeConfig, run_pipeline`.
Change `pipeline_config = PipelineConfig(` → `pipeline_config = PipelineRuntimeConfig(`.

**Step 3: Update `recap/daemon/__main__.py`**

Change `from recap.pipeline import PipelineConfig as PipelineCfg, run_pipeline` → `from recap.pipeline import PipelineRuntimeConfig, run_pipeline`.
Change `_build_pipeline_config(...) -> PipelineCfg:` → `-> PipelineRuntimeConfig:`.
Change `return PipelineCfg(` → `return PipelineRuntimeConfig(`.
Update the docstring ("Build a PipelineConfig…" → "Build a PipelineRuntimeConfig…").
Rename the function itself: `_build_pipeline_config` → `_build_runtime_config` (shorter, matches the new type name).

**Step 4: Update `tests/test_pipeline.py`**

Change `from recap.pipeline import PipelineConfig, run_pipeline` → `from recap.pipeline import PipelineRuntimeConfig, run_pipeline`.
Change `return PipelineConfig(` → `return PipelineRuntimeConfig(`.

**Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: all tests pass.

**Step 6: Commit**

```bash
git add recap/pipeline/__init__.py recap/cli.py recap/daemon/__main__.py tests/test_pipeline.py
git commit -m "refactor: rename pipeline PipelineConfig to PipelineRuntimeConfig"
```

---

## Task 3: Add `llm_backend` to `RecordingMetadata`

**Files:**
- Modify: `recap/artifacts.py:24-72` (the `RecordingMetadata` dataclass + serialization)
- Modify: `tests/test_models.py` or create `tests/test_artifacts.py` (test round-trip)

**Step 1: Write the failing test**

Create or extend test (preferred file: `tests/test_artifacts.py` — if it doesn't exist, create it):

```python
"""Tests for recording sidecar artifacts."""
from __future__ import annotations

import pathlib

from recap.artifacts import RecordingMetadata, load_recording_metadata, write_recording_metadata
from recap.models import Participant


class TestRecordingMetadataLLMBackend:
    def test_default_llm_backend_is_claude(self):
        metadata = RecordingMetadata(
            org="test",
            note_path="",
            title="t",
            date="2026-04-14",
            participants=[],
            platform="manual",
        )
        assert metadata.llm_backend == "claude"

    def test_explicit_llm_backend_round_trips(self, tmp_path: pathlib.Path):
        audio_path = tmp_path / "recording.flac"
        audio_path.touch()
        original = RecordingMetadata(
            org="test",
            note_path="",
            title="t",
            date="2026-04-14",
            participants=[Participant(name="Alice")],
            platform="signal",
            llm_backend="ollama",
        )
        write_recording_metadata(audio_path, original)

        loaded = load_recording_metadata(audio_path)
        assert loaded is not None
        assert loaded.llm_backend == "ollama"

    def test_legacy_metadata_without_llm_backend_loads_as_claude(self, tmp_path: pathlib.Path):
        import json

        audio_path = tmp_path / "legacy.flac"
        audio_path.touch()
        legacy_data = {
            "org": "test",
            "note_path": "",
            "title": "t",
            "date": "2026-04-14",
            "participants": [],
            "platform": "manual",
        }
        (audio_path.with_suffix(".metadata.json")).write_text(json.dumps(legacy_data))

        loaded = load_recording_metadata(audio_path)
        assert loaded is not None
        assert loaded.llm_backend == "claude"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_artifacts.py -v`
Expected: FAIL — `RecordingMetadata` has no `llm_backend` attribute.

**Step 3: Implement in `recap/artifacts.py`**

Add the field to the dataclass (after `meeting_link`, keep default last):

```python
@dataclass
class RecordingMetadata:
    org: str
    note_path: str
    title: str
    date: str
    participants: list[Participant]
    platform: str
    calendar_source: str | None = None
    event_id: str | None = None
    meeting_link: str = ""
    llm_backend: str = "claude"
```

Update `from_dict`:

```python
return cls(
    ...
    meeting_link=data.get("meeting_link", ""),
    llm_backend=data.get("llm_backend", "claude"),
)
```

Update `to_dict`:

```python
return {
    ...
    "meeting_link": self.meeting_link,
    "llm_backend": self.llm_backend,
}
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_artifacts.py -v`
Expected: PASS.

Run: `uv run pytest -q`
Expected: full suite still passes (field with default is backward-compatible).

**Step 5: Commit**

```bash
git add recap/artifacts.py tests/test_artifacts.py
git commit -m "feat: add llm_backend to RecordingMetadata"
```

---

## Task 4: Extract the canonical frontmatter builder

**Context:** Today, `vault.py:_generate_meeting_markdown` inlines frontmatter construction. We need this as a reusable pure function so `upsert_note` can call it for the create path and the pipeline can call it for the merge path.

**Files:**
- Create: `recap/vault.py` — new `build_canonical_frontmatter(metadata, analysis, duration_seconds, recording_path, org, org_subfolder) -> dict` helper
- Create: `tests/test_vault_canonical.py`

**Step 1: Write the failing test**

```python
"""Tests for canonical frontmatter builder."""
from __future__ import annotations

import pathlib
from datetime import date

from recap.models import (
    AnalysisResult,
    MeetingMetadata,
    Participant,
    ProfileStub,
)
from recap.vault import build_canonical_frontmatter


def _make_analysis(meeting_type: str = "standup", companies: list[str] | None = None) -> AnalysisResult:
    return AnalysisResult(
        speaker_mapping={},
        meeting_type=meeting_type,
        summary="s",
        key_points=[],
        decisions=[],
        action_items=[],
        follow_ups=[],
        relationship_notes=None,
        people=[],
        companies=[ProfileStub(name=n) for n in (companies or [])],
    )


class TestCanonicalFrontmatter:
    def test_required_fields_populated(self):
        metadata = MeetingMetadata(
            title="Q2 Review",
            date=date(2026, 4, 14),
            participants=[Participant(name="Alice"), Participant(name="Bob")],
            platform="google_meet",
        )
        analysis = _make_analysis(meeting_type="quarterly_review", companies=["Acme"])

        fm = build_canonical_frontmatter(
            metadata=metadata,
            analysis=analysis,
            duration_seconds=4320.0,
            recording_path=pathlib.Path("2026-04-14-140000-disbursecloud.m4a"),
            org="disbursecloud",
            org_subfolder="Clients/Disbursecloud",
        )

        assert fm["date"] == "2026-04-14"
        assert fm["title"] == "Q2 Review"
        assert fm["org"] == "disbursecloud"
        assert fm["org-subfolder"] == "Clients/Disbursecloud"
        assert fm["platform"] == "google_meet"
        assert fm["participants"] == ["[[Alice]]", "[[Bob]]"]
        assert fm["companies"] == ["[[Acme]]"]
        assert fm["duration"] == "1h 12m"
        assert fm["type"] == "quarterly_review"
        assert fm["tags"] == ["meeting/quarterly_review"]
        assert fm["pipeline-status"] == "complete"
        assert fm["recording"] == "2026-04-14-140000-disbursecloud.m4a"

    def test_org_is_always_the_slug_not_the_subfolder(self):
        metadata = MeetingMetadata(
            title="t",
            date=date(2026, 4, 14),
            participants=[],
            platform="manual",
        )
        analysis = _make_analysis()
        fm = build_canonical_frontmatter(
            metadata=metadata,
            analysis=analysis,
            duration_seconds=60.0,
            recording_path=pathlib.Path("r.m4a"),
            org="disbursecloud",
            org_subfolder="Clients/Disbursecloud",
        )
        assert fm["org"] == "disbursecloud"
        assert "/" not in fm["org"]

    def test_recording_is_filename_not_path(self):
        metadata = MeetingMetadata(
            title="t", date=date(2026, 4, 14), participants=[], platform="manual",
        )
        fm = build_canonical_frontmatter(
            metadata=metadata,
            analysis=_make_analysis(),
            duration_seconds=60.0,
            recording_path=pathlib.Path("/abs/path/to/recording.m4a"),
            org="o",
            org_subfolder="O",
        )
        assert fm["recording"] == "recording.m4a"
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_vault_canonical.py -v`
Expected: FAIL — `build_canonical_frontmatter` not found.

**Step 3: Implement in `recap/vault.py`**

Add near the top, after `_format_duration`:

```python
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
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_vault_canonical.py -v`
Expected: PASS.

Run: `uv run pytest -q`
Expected: full suite still passes (pure addition).

**Step 5: Commit**

```bash
git add recap/vault.py tests/test_vault_canonical.py
git commit -m "feat: add build_canonical_frontmatter helper"
```

---

## Task 5: Implement `upsert_note` — case 1 (new note)

**Context:** `upsert_note` is the shared primitive for all write paths into a meeting note. We'll build it up case by case.

**Files:**
- Modify: `recap/vault.py` — add `upsert_note(path, frontmatter, body)` function
- Create: `tests/test_vault_upsert.py`

**Step 1: Write the failing test**

```python
"""Tests for upsert_note across the four cases from design doc §0.1."""
from __future__ import annotations

import pathlib

import yaml

from recap.vault import MEETING_RECORD_MARKER, upsert_note


class TestUpsertCase1NewNote:
    def test_creates_note_with_frontmatter_marker_and_body(self, tmp_path: pathlib.Path):
        note_path = tmp_path / "new.md"
        frontmatter = {
            "date": "2026-04-14",
            "title": "New Meeting",
            "org": "test",
            "pipeline-status": "complete",
        }
        body = "## Summary\n\nIt went well.\n"

        upsert_note(note_path, frontmatter, body)

        assert note_path.exists()
        content = note_path.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        _, fm_block, rest = content.split("---\n", 2)
        fm = yaml.safe_load(fm_block)
        assert fm["title"] == "New Meeting"
        assert fm["pipeline-status"] == "complete"
        assert MEETING_RECORD_MARKER in rest
        assert "It went well." in rest
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_vault_upsert.py -v`
Expected: FAIL — `upsert_note` not found.

**Step 3: Implement case 1 in `recap/vault.py`**

```python
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

    # Cases 2, 3, 4 land here in future tasks.
    raise NotImplementedError("upsert cases 2-4 not yet implemented")


def _write_new_note(note_path: pathlib.Path, frontmatter: dict, body: str) -> None:
    fm_block = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).strip()
    content = f"---\n{fm_block}\n---\n\n{MEETING_RECORD_MARKER}\n\n{body.lstrip()}"
    note_path.write_text(content, encoding="utf-8")
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_vault_upsert.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add recap/vault.py tests/test_vault_upsert.py
git commit -m "feat: upsert_note case 1 (new note)"
```

---

## Task 6: `upsert_note` — case 2 (existing note, no frontmatter, no marker)

**Files:**
- Modify: `recap/vault.py`
- Modify: `tests/test_vault_upsert.py`

**Step 1: Add the failing test**

Append to `tests/test_vault_upsert.py`:

```python
class TestUpsertCase2BareExistingNote:
    def test_prepends_frontmatter_and_appends_marker_plus_body(self, tmp_path: pathlib.Path):
        note_path = tmp_path / "bare.md"
        note_path.write_text("Some pre-existing notes\nwritten by the user.\n", encoding="utf-8")

        frontmatter = {"date": "2026-04-14", "title": "Bare", "org": "test", "pipeline-status": "complete"}
        body = "## Summary\n\nAnalysis output.\n"

        upsert_note(note_path, frontmatter, body)

        content = note_path.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        _, fm_block, rest = content.split("---\n", 2)
        fm = yaml.safe_load(fm_block)
        assert fm["title"] == "Bare"

        # Original user content preserved above the marker
        assert "Some pre-existing notes" in rest
        assert "written by the user." in rest

        # Marker + body present
        assert MEETING_RECORD_MARKER in rest
        marker_idx = rest.index(MEETING_RECORD_MARKER)
        assert "Some pre-existing notes" in rest[:marker_idx]
        assert "Analysis output." in rest[marker_idx:]
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_vault_upsert.py::TestUpsertCase2BareExistingNote -v`
Expected: FAIL — `NotImplementedError` from the stub.

**Step 3: Implement case 2**

Replace the `raise NotImplementedError` in `upsert_note` with case detection:

```python
    existing = note_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    has_frontmatter = existing.startswith("---\n") and existing.count("---\n") >= 2
    has_marker = MEETING_RECORD_MARKER in existing

    if not has_frontmatter and not has_marker:
        _prepend_fm_and_append_body(note_path, existing, frontmatter, body)
        return

    # Cases 3 and 4 land in future tasks.
    raise NotImplementedError("upsert cases 3-4 not yet implemented")
```

Add the helper:

```python
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
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_vault_upsert.py -v`
Expected: cases 1 and 2 PASS.

**Step 5: Commit**

```bash
git add recap/vault.py tests/test_vault_upsert.py
git commit -m "feat: upsert_note case 2 (bare existing note)"
```

---

## Task 7: `upsert_note` — case 3 (calendar-seeded note, no marker). **This is the key bug fix.**

**Context:** This is the case that silently drops frontmatter today. Calendar sync writes notes with `date/time/title/participants/calendar-source/org/meeting-link/event-id/pipeline-status: pending`, then the pipeline appends below-marker content without ever merging canonical frontmatter (duration, type, tags, companies, recording).

**Field ownership (design doc §0.1):**
- Calendar-owned (preserved from existing): `time`, `event-id`, `meeting-link`, `calendar-source`
- Pipeline-owned (canonical wins): `duration`, `type`, `tags`, `companies`, `recording`, `pipeline-status`, `pipeline-error`
- Shared (canonical wins; but calendar values are usually consistent): `date`, `title`, `org`, `org-subfolder`, `platform`, `participants`

**Files:**
- Modify: `recap/vault.py`
- Modify: `tests/test_vault_upsert.py`

**Step 1: Add the failing test**

```python
class TestUpsertCase3CalendarSeeded:
    def test_merges_frontmatter_preserving_calendar_keys_and_appends_marker(self, tmp_path: pathlib.Path):
        note_path = tmp_path / "calendar.md"
        # Simulate what calendar sync writes
        calendar_content = (
            "---\n"
            "date: 2026-04-14\n"
            "time: 14:00-15:00\n"
            "title: Q2 Review\n"
            "participants:\n"
            "- '[[Alice]]'\n"
            "- '[[Bob]]'\n"
            "calendar-source: google\n"
            "org: disbursecloud\n"
            "meeting-link: https://meet.google.com/abc\n"
            "event-id: evt-123\n"
            "pipeline-status: pending\n"
            "---\n"
            "\n"
            "## Agenda\n\nDiscuss Q2 targets.\n"
        )
        note_path.write_text(calendar_content, encoding="utf-8")

        canonical = {
            "date": "2026-04-14",
            "title": "Q2 Review",
            "org": "disbursecloud",
            "org-subfolder": "Clients/Disbursecloud",
            "platform": "google_meet",
            "participants": ["[[Alice]]", "[[Bob]]"],
            "companies": ["[[Acme]]"],
            "duration": "1h 12m",
            "type": "quarterly_review",
            "tags": ["meeting/quarterly_review"],
            "pipeline-status": "complete",
            "recording": "2026-04-14-140000-disbursecloud.m4a",
        }
        body = "## Summary\n\nGreat meeting.\n"

        upsert_note(note_path, canonical, body)

        content = note_path.read_text(encoding="utf-8")
        _, fm_block, rest = content.split("---\n", 2)
        fm = yaml.safe_load(fm_block)

        # Calendar keys preserved
        assert fm["time"] == "14:00-15:00"
        assert fm["calendar-source"] == "google"
        assert fm["meeting-link"] == "https://meet.google.com/abc"
        assert fm["event-id"] == "evt-123"

        # Pipeline keys authoritative
        assert fm["pipeline-status"] == "complete"
        assert fm["duration"] == "1h 12m"
        assert fm["type"] == "quarterly_review"
        assert fm["tags"] == ["meeting/quarterly_review"]
        assert fm["companies"] == ["[[Acme]]"]
        assert fm["recording"] == "2026-04-14-140000-disbursecloud.m4a"

        # Shared keys from canonical (slug, not path)
        assert fm["org"] == "disbursecloud"
        assert fm["org-subfolder"] == "Clients/Disbursecloud"
        assert fm["platform"] == "google_meet"

        # Agenda preserved above marker, body below
        assert "## Agenda" in rest
        assert "Discuss Q2 targets." in rest
        marker_idx = rest.index(MEETING_RECORD_MARKER)
        assert "## Agenda" in rest[:marker_idx]
        assert "Great meeting." in rest[marker_idx:]
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_vault_upsert.py::TestUpsertCase3CalendarSeeded -v`
Expected: FAIL — still hits `NotImplementedError`.

**Step 3: Implement case 3**

Add field ownership constants near the top of `vault.py`:

```python
# Field ownership for canonical merge (design doc §0.1)
_CALENDAR_OWNED_KEYS = {"time", "event-id", "meeting-link", "calendar-source"}
```

Extend `upsert_note` with the case-3 branch and the field-level merge helper:

```python
    if has_frontmatter and not has_marker:
        _merge_fm_and_append_body(note_path, existing, frontmatter, body)
        return

    raise NotImplementedError("upsert case 4 not yet implemented")
```

```python
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
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_vault_upsert.py -v`
Expected: cases 1, 2, 3 PASS.

**Step 5: Commit**

```bash
git add recap/vault.py tests/test_vault_upsert.py
git commit -m "fix: backfill canonical frontmatter on calendar-seeded notes (case 3)"
```

---

## Task 8: `upsert_note` — case 4 (existing note with marker)

**Files:**
- Modify: `recap/vault.py`
- Modify: `tests/test_vault_upsert.py`

**Step 1: Add the failing test**

```python
class TestUpsertCase4WithMarker:
    def test_merges_fm_and_replaces_below_marker(self, tmp_path: pathlib.Path):
        note_path = tmp_path / "with-marker.md"
        note_path.write_text(
            "---\n"
            "date: 2026-04-14\n"
            "time: 14:00-15:00\n"
            "title: Q2 Review\n"
            "calendar-source: google\n"
            "event-id: evt-123\n"
            "meeting-link: https://meet.google.com/abc\n"
            "pipeline-status: failed:analyze\n"
            "pipeline-error: old error\n"
            "duration: old-value\n"
            "---\n"
            "\n"
            "## Agenda\n\nOld agenda.\n\n"
            "## Meeting Record\n\n"
            "## Summary\n\nStale content.\n",
            encoding="utf-8",
        )

        canonical = {
            "date": "2026-04-14",
            "title": "Q2 Review",
            "org": "disbursecloud",
            "org-subfolder": "Clients/Disbursecloud",
            "platform": "google_meet",
            "participants": ["[[Alice]]"],
            "companies": ["[[Acme]]"],
            "duration": "1h 12m",
            "type": "quarterly_review",
            "tags": ["meeting/quarterly_review"],
            "pipeline-status": "complete",
            "recording": "rec.m4a",
        }
        body = "## Summary\n\nFresh content.\n"

        upsert_note(note_path, canonical, body)

        content = note_path.read_text(encoding="utf-8")
        _, fm_block, rest = content.split("---\n", 2)
        fm = yaml.safe_load(fm_block)

        # Calendar keys preserved
        assert fm["time"] == "14:00-15:00"
        assert fm["calendar-source"] == "google"
        assert fm["event-id"] == "evt-123"

        # Pipeline keys authoritative
        assert fm["pipeline-status"] == "complete"
        assert fm["duration"] == "1h 12m"
        assert fm["recording"] == "rec.m4a"
        # pipeline-error removed since pipeline-status is no longer failed
        assert "pipeline-error" not in fm

        # Agenda preserved above marker, fresh body below
        assert "## Agenda" in rest
        assert "Old agenda." in rest
        marker_idx = rest.index(MEETING_RECORD_MARKER)
        assert "## Agenda" in rest[:marker_idx]
        assert "Fresh content." in rest[marker_idx:]
        assert "Stale content." not in rest  # replaced below marker
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_vault_upsert.py::TestUpsertCase4WithMarker -v`
Expected: FAIL — still hits `NotImplementedError`.

**Step 3: Implement case 4**

Replace the final `raise NotImplementedError` with:

```python
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
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_vault_upsert.py -v`
Expected: all four cases PASS.

**Step 5: Commit**

```bash
git add recap/vault.py tests/test_vault_upsert.py
git commit -m "feat: upsert_note case 4 (existing marker, replace below)"
```

---

## Task 9: Refactor `write_meeting_note` to use `upsert_note`

**Context:** `write_meeting_note` currently has three branches that independently handle "new file," "exists with marker," "exists without marker" — none of which handle frontmatter backfill correctly. We replace all of it with a call to `upsert_note` and `build_canonical_frontmatter`. The existing body-building helpers (`_generate_pipeline_content`) are kept.

**Files:**
- Modify: `recap/vault.py:179-241` (`write_meeting_note` + `_generate_meeting_markdown`)
- Modify: `tests/test_vault.py` — existing tests may need small updates if they assert on frontmatter absence

**Step 1: Run the existing `test_vault.py` to establish the baseline.**

Run: `uv run pytest tests/test_vault.py -v`
Expected: all current tests pass.

**Step 2: Rewrite `write_meeting_note`**

Replace lines 179-241 with:

```python
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
) -> pathlib.Path:
    """Upsert a canonical meeting note.

    Delegates to `upsert_note` — handles new notes, bare notes, calendar-seeded
    notes, and fully-processed notes via field-level frontmatter merge.
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
    )

    body = _generate_pipeline_content(
        metadata=metadata,
        analysis=analysis,
        duration_seconds=duration_seconds,
        recording_path=recording_path,
        previous_meeting=previous_meeting,
        user_name=user_name,
    )

    upsert_note(note_path, frontmatter, body)
    logger.info("Upserted meeting note: %s", note_path)
    return note_path
```

Delete `_generate_meeting_markdown` — no longer used. (Grep first to confirm: `grep -rn "_generate_meeting_markdown" recap/ tests/`. If `tests/test_vault.py` still references it, they get updated in the next step.)

**Step 3: Update `tests/test_vault.py`**

Many tests currently call `_generate_meeting_markdown` directly. Rewrite those tests to call `write_meeting_note` into a `tmp_path` and assert on the resulting file content. Example conversion:

Before:
```python
md = _generate_meeting_markdown(metadata, analysis, 3600, Path("r.m4a"))
assert "## Summary" in md
```

After:
```python
note_path = tmp_path / "note.md"
write_meeting_note(
    metadata=metadata, analysis=analysis,
    duration_seconds=3600, recording_path=Path("r.m4a"),
    meetings_dir=tmp_path, note_path=note_path,
)
assert "## Summary" in note_path.read_text(encoding="utf-8")
```

Apply this transformation to every `_generate_meeting_markdown` call in `tests/test_vault.py`. If a test asserts on frontmatter that used to be absent, it should now assert on the canonical frontmatter being *present*.

Remove the import of `_generate_meeting_markdown` from the test file.

**Step 4: Run the test suite**

Run: `uv run pytest tests/test_vault.py -v`
Expected: all tests pass (possibly after updating assertions to match canonical frontmatter).

Run: `uv run pytest -q`
Expected: full suite passes.

**Step 5: Commit**

```bash
git add recap/vault.py tests/test_vault.py
git commit -m "refactor: route write_meeting_note through upsert_note"
```

---

## Task 10: Thread `llm_backend` through `_build_runtime_config`

**Context:** `RecordingMetadata.llm_backend` exists (Task 3) but nothing reads it. `_build_runtime_config` in `__main__.py` hardcodes `llm_backend=org_config.llm_backend`. We change it to prefer `recording_metadata.llm_backend` when set.

**Files:**
- Modify: `recap/daemon/__main__.py:35-50` (`_build_runtime_config`) — signature and body
- Modify: `recap/daemon/__main__.py:85` (caller in `process_recording`)
- Create test: `tests/test_daemon_main.py` (if doesn't exist) OR add to existing daemon test

**Step 1: Write the failing test**

Create `tests/test_daemon_main.py`:

```python
"""Tests for daemon __main__ helpers."""
from __future__ import annotations

from recap.artifacts import RecordingMetadata
from recap.daemon.__main__ import _build_runtime_config
from recap.daemon.config import DaemonConfig, OrgConfig


def _make_daemon_config() -> DaemonConfig:
    cfg = DaemonConfig.__new__(DaemonConfig)
    # Fill required fields minimally — DaemonConfig has many defaults
    import pathlib
    cfg.vault_path = pathlib.Path("/tmp/vault")
    cfg.recordings_path = pathlib.Path("/tmp/rec")
    return cfg


def _make_org(llm_backend: str = "claude") -> OrgConfig:
    return OrgConfig(name="test", subfolder="Test", llm_backend=llm_backend)


class TestBuildRuntimeConfig:
    def test_uses_recording_metadata_backend_when_set(self):
        daemon_config = _make_daemon_config()
        org = _make_org(llm_backend="claude")
        metadata = RecordingMetadata(
            org="test", note_path="", title="t",
            date="2026-04-14", participants=[], platform="signal",
            llm_backend="ollama",
        )

        runtime = _build_runtime_config(daemon_config, org, metadata)
        assert runtime.llm_backend == "ollama"

    def test_falls_back_to_org_config_when_metadata_backend_absent(self):
        daemon_config = _make_daemon_config()
        org = _make_org(llm_backend="claude")
        # Simulate legacy metadata by setting the default
        metadata = RecordingMetadata(
            org="test", note_path="", title="t",
            date="2026-04-14", participants=[], platform="manual",
            # llm_backend defaults to "claude", which matches org default
        )

        runtime = _build_runtime_config(daemon_config, org, metadata)
        assert runtime.llm_backend == "claude"
```

Note: the fallback test here is soft because both defaults to "claude". It's still useful coverage. If you want stronger coverage, you could add a `None` sentinel to `RecordingMetadata.llm_backend` — but keeping the string default is simpler and the explicit-override test above is the one that actually proves the Signal popup choice survives.

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_daemon_main.py -v`
Expected: FAIL — `_build_runtime_config` has the old signature `(config, org_config)`.

**Step 3: Modify `_build_runtime_config`**

In `recap/daemon/__main__.py`:

```python
def _build_runtime_config(
    config: DaemonConfig,
    org_config,
    recording_metadata: RecordingMetadata | None = None,
) -> PipelineRuntimeConfig:
    """Build a PipelineRuntimeConfig from daemon config, org config, and (optionally) recording metadata.

    If recording_metadata has an llm_backend set, it overrides org_config.llm_backend.
    This is how the Signal popup's backend choice reaches analyze.
    """
    backend = (
        recording_metadata.llm_backend
        if recording_metadata is not None and recording_metadata.llm_backend
        else org_config.llm_backend
    )
    return PipelineRuntimeConfig(
        transcription_model=config.pipeline.transcription_model,
        diarization_model=config.pipeline.diarization_model,
        device="cuda",
        llm_backend=backend,
        ollama_model="",
        archive_format=config.recording.archive_format,
        archive_bitrate="64k",
        delete_source_after_archive=config.recording.delete_source_after_archive,
        auto_retry=config.pipeline.auto_retry,
        max_retries=config.pipeline.max_retries,
        prompt_template_path=None,
        status_dir=config.vault_path / "_Recap" / ".recap" / "status",
    )
```

Update the caller in `process_recording` (~line 85):

```python
pipeline_config = _build_runtime_config(config, org_config, recording_metadata)
```

Add import at top of `__main__.py`:

```python
from recap.artifacts import RecordingMetadata, load_recording_metadata
```

(`RecordingMetadata` may already be imported — verify and dedupe.)

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_daemon_main.py -v`
Expected: PASS.

Run: `uv run pytest -q`
Expected: full suite passes.

**Step 5: Commit**

```bash
git add recap/daemon/__main__.py tests/test_daemon_main.py
git commit -m "feat: honor RecordingMetadata.llm_backend in runtime config"
```

---

## Task 11: Update `run_pipeline` export stage to build full canonical frontmatter

**Context:** Today, `run_pipeline` calls `write_meeting_note` with `org=org_subfolder` (line 452 of `pipeline/__init__.py`), which is why frontmatter `org` can end up being a folder path. We need to pass the *slug* as `org` and the *subfolder* as `org_subfolder`.

**Files:**
- Modify: `recap/pipeline/__init__.py:280-294` (`run_pipeline` signature — add `org_slug`)
- Modify: `recap/pipeline/__init__.py:452` (the `write_meeting_note` call)
- Modify: `recap/daemon/__main__.py:85-102` (`process_recording` passes slug + subfolder to `run_pipeline`)
- Modify: `recap/cli.py:83` (ditto for CLI)

**Step 1: Add the failing test**

Append to `tests/test_pipeline.py` a real-fs integration test for export:

```python
def test_run_pipeline_export_writes_canonical_frontmatter(tmp_path, monkeypatch):
    """End-to-end test of the export stage: pipeline produces canonical frontmatter."""
    from recap.artifacts import save_transcript, save_analysis, write_recording_metadata, RecordingMetadata
    from recap.models import (
        AnalysisResult, MeetingMetadata, Participant, ProfileStub,
        TranscriptResult, Utterance,
    )
    from recap.pipeline import run_pipeline, PipelineRuntimeConfig
    from datetime import date
    import yaml

    # Arrange: a fake audio path with pre-existing transcript + analysis artifacts
    audio_path = tmp_path / "2026-04-14-140000-disbursecloud.flac"
    audio_path.touch()

    transcript = TranscriptResult(
        utterances=[Utterance(speaker="Alice", start=0.0, end=1.0, text="hi")],
        raw_text="hi", language="en",
    )
    save_transcript(audio_path, transcript)

    analysis = AnalysisResult(
        speaker_mapping={},
        meeting_type="standup", summary="s",
        key_points=[], decisions=[], action_items=[], follow_ups=[],
        relationship_notes=None,
        people=[],
        companies=[ProfileStub(name="Acme")],
    )
    save_analysis(audio_path, analysis)

    metadata = MeetingMetadata(
        title="Standup",
        date=date(2026, 4, 14),
        participants=[Participant(name="Alice")],
        platform="google_meet",
    )

    vault = tmp_path / "vault"
    config = PipelineRuntimeConfig(
        archive_format="flac",  # skip convert stage
    )

    # Act: run pipeline from export stage
    note_path = run_pipeline(
        audio_path=audio_path,
        metadata=metadata,
        config=config,
        org_slug="disbursecloud",
        org_subfolder="Clients/Disbursecloud",
        vault_path=vault,
        user_name="Tim",
        from_stage="export",
    )

    # Assert: canonical frontmatter present, org is slug, org-subfolder is path
    content = note_path.read_text(encoding="utf-8")
    _, fm_block, _ = content.split("---\n", 2)
    fm = yaml.safe_load(fm_block)

    assert fm["org"] == "disbursecloud"  # slug, not path
    assert fm["org-subfolder"] == "Clients/Disbursecloud"
    assert fm["duration"]  # set (non-empty)
    assert fm["type"] == "standup"
    assert fm["tags"] == ["meeting/standup"]
    assert fm["companies"] == ["[[Acme]]"]
    assert fm["recording"] == "2026-04-14-140000-disbursecloud.flac"
    assert fm["pipeline-status"] == "complete"
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_pipeline.py::test_run_pipeline_export_writes_canonical_frontmatter -v`
Expected: FAIL — signature mismatch (`org_subfolder` arg vs the test's `org_slug` + `org_subfolder`), or frontmatter missing canonical fields.

**Step 3: Update `run_pipeline` signature**

In `recap/pipeline/__init__.py`:

```python
def run_pipeline(
    audio_path: pathlib.Path,
    metadata: MeetingMetadata,
    config: PipelineRuntimeConfig,
    org_slug: str,               # NEW: identity
    org_subfolder: str,          # RENAMED: filesystem path (was org_subfolder already)
    vault_path: pathlib.Path,
    user_name: str,
    streaming_transcript: TranscriptResult | None = None,
    from_stage: str | None = None,
    recording_metadata: RecordingMetadata | None = None,
) -> pathlib.Path:
```

Update the vault-directory resolution:

```python
    org_dir = vault_path / org_subfolder
    meetings_dir = org_dir / "Meetings"
    ...
```

Update the export call:

```python
            written = write_meeting_note(
                metadata=metadata,
                analysis=analysis,
                duration_seconds=duration,
                recording_path=recording_reference_path,
                meetings_dir=meetings_dir,
                org=org_slug,
                org_subfolder=org_subfolder,
                previous_meeting=previous,
                user_name=user_name,
                note_path=note_path,
            )
```

**Step 4: Update callers**

`recap/daemon/__main__.py:process_recording`:

```python
note_path = await asyncio.to_thread(
    run_pipeline,
    audio_path=flac_path,
    metadata=metadata,
    config=pipeline_config,
    org_slug=org_config.name,
    org_subfolder=org_config.subfolder,
    vault_path=config.vault_path,
    user_name=config.user_name,
    streaming_transcript=streaming_transcript,
    from_stage=from_stage,
    recording_metadata=recording_metadata,
)
```

`recap/cli.py` — update whatever call pattern exists there similarly. If CLI lacks `org_slug`/`org_subfolder` handling, set both from the existing `--org` flag for now (CLI is for solo use; org is both slug and subfolder).

**Step 5: Run the test suite**

Run: `uv run pytest -q`
Expected: all tests pass including the new integration test.

**Step 6: Commit**

```bash
git add recap/pipeline/__init__.py recap/daemon/__main__.py recap/cli.py tests/test_pipeline.py
git commit -m "feat: run_pipeline produces canonical frontmatter with org slug and subfolder"
```

---

## Task 12: Rewrite over-mocked tests in `test_pipeline.py`

**Context:** `tests/test_pipeline.py` currently has `_PATCH_WRITE_NOTE = "recap.vault.write_meeting_note"` and tests that patch it out and then assert `pipeline-status: complete` — which is precisely the "prove the mock works, not the contract" problem Codex called out.

**Files:**
- Modify: `tests/test_pipeline.py`

**Step 1: Identify the offenders**

Run: `grep -n "_PATCH_WRITE_NOTE\|patch.*write_meeting_note\|mock.*write_meeting_note" tests/test_pipeline.py`

**Step 2: For each test that patches `write_meeting_note`, rewrite it to:**

- Use a real `tmp_path` as `vault_path`.
- Let `run_pipeline` call the real `write_meeting_note` → real `upsert_note` → real file on disk.
- Assert on the actual file content (frontmatter + body), not on a mock call.

If a test needed the mock because it was patching `transcribe` / `diarize` / `analyze` to skip the heavy ML stages: keep those patches (they're legitimate — ML is out of scope for this test), but let the export stage write real files.

If a test literally only asserts `pipeline-status: complete` and nothing else, delete it. That's the "proves the mock works" class — it provides zero coverage.

**Step 3: Verify all remaining tests still pass**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: PASS. Test count may decrease if we deleted empty-assertion tests — that's fine.

Run: `uv run pytest -q`
Expected: full suite passes.

**Step 4: Commit**

```bash
git add tests/test_pipeline.py
git commit -m "test: rewrite pipeline tests against real filesystem, drop mock-only tests"
```

---

## Task 13: Update MANIFEST and remove stale `recap/config.py` reference

**Files:**
- Modify: `MANIFEST.md`

**Step 1: Inspect**

Run: `grep -n "config.py" MANIFEST.md`
Expected: a line mentioning `config.py` at the top level under `recap/`. This file does not exist — it's a stale pointer from the pre-pivot era.

**Step 2: Remove the stale line**

Delete the `config.py` line from the MANIFEST structure block. If there are other stale pointers (e.g., references to `PipelineConfig` by name), update them to the new names (`PipelineSettings`, `PipelineRuntimeConfig`).

**Step 3: Commit**

```bash
git add MANIFEST.md
git commit -m "docs: update MANIFEST for Phase 1 renames"
```

---

## Post-Phase Verification

Run each command and confirm output:

| Command | Expected |
|---|---|
| `uv run pytest -q` | all pass |
| `grep -rn "PipelineConfig[^RS]" recap/ tests/` | no hits (outside of git history) |
| `grep -n "class PipelineSettings\|class PipelineRuntimeConfig" recap/` | two hits, one per file |
| `grep -rn "_generate_meeting_markdown" recap/ tests/` | no hits |
| `grep -rn "llm_backend" recap/artifacts.py recap/daemon/__main__.py recap/pipeline/__init__.py` | non-empty (field is threaded through) |

**Acceptance checklist (from design doc §Phase 1):**

- [ ] Running the pipeline against an existing calendar note produces a fully backfilled canonical note, not just appended body text. → Verified by `TestUpsertCase3CalendarSeeded` + `test_run_pipeline_export_writes_canonical_frontmatter`.
- [ ] `org` in frontmatter is always the slug, never a folder path. → Verified by `test_org_is_always_the_slug_not_the_subfolder` + the integration test.
- [ ] Recording metadata persists and reloads `llm_backend`. → Verified by `TestRecordingMetadataLLMBackend`.
- [ ] Signal backend choice actually affects the runtime pipeline backend (data path). → Verified by `test_uses_recording_metadata_backend_when_set`. End-to-end verification of the popup itself lands in Phase 3.
- [ ] The two pipeline config names are no longer ambiguous. → Verified by grep.
- [ ] Contract tests use a real tmp vault and real note files. → All four upsert-case tests + the integration test use `tmp_path`.
- [ ] No contract test mocks the note-writing function it is supposed to verify. → Task 12 removed those.

---

## Handoff Notes for Phase 2

Phase 2 (Org Model + Event-ID Index) will:
- Delete `recap/daemon/calendar/sync.py:org_subfolder()` (the hardcoded capitalizer).
- Replace it with `OrgConfig.resolve_subfolder(vault_path)`.
- Build a persistent `EventIndex` at `_Recap/.recap/event-index.json`.
- Wire `upsert_note` from Phase 1 to call `EventIndex.add` when frontmatter has `event-id`. (The hook point is now in one place thanks to Phase 1.)

Phase 2 can start immediately after Phase 1's final commit lands. It only touches `recap/daemon/config.py`, `recap/daemon/calendar/*`, and new `recap/daemon/calendar/index.py` — no overlap with Phase 1's files.

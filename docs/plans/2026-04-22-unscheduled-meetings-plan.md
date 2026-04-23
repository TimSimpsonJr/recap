# Unscheduled Meetings Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give unscheduled auto-recordings a stable synthetic identity, a deterministic non-PII filename, and minimum-viable frontmatter so the downstream pipeline, vault writer, EventIndex, MeetingListView, and analyzer all behave coherently without any special-casing.

**Architecture:** Synthesis happens at detection time inside `_build_recording_metadata` so both poll-detected and extension-detected paths are covered for free. The sidecar persists `event_id = "unscheduled:<uuid>"`, a precomputed `note_path`, and a new `recording_started_at` timestamp field. Downstream code runs its existing calendar-backed codepaths unchanged, with two small additions in `vault.build_canonical_frontmatter` (time-range from `recording_started_at + duration`, plus an `unscheduled` tag) and one conditional branch in the analyze prompt for empty rosters.

**Tech Stack:** Python 3.10+, pytest, pytest-asyncio (already in use), pyyaml (frontmatter), dataclasses, datetime.timezone. No new dependencies.

**Design doc:** [docs/plans/2026-04-22-unscheduled-meetings-design.md](./2026-04-22-unscheduled-meetings-design.md)

**Branch:** `feat/27-unscheduled-meetings` (already created, design doc committed at 3c69959)

**Convention:** Each task is TDD — write a failing test, verify it fails, implement minimally, verify it passes, commit. Use Conventional Commits format (`feat(scope): ...`, `test(scope): ...`). Keep commits small; never batch unrelated changes.

---

## Task 1: Add `recording_started_at` to `RecordingMetadata`

**Files:**
- Modify: `recap/artifacts.py:45-95`
- Test: `tests/test_artifacts.py` (add new cases)

**Context:** `RecordingMetadata` is a dataclass with manual `to_dict`/`from_dict` (not `asdict`). Datetime serializes as ISO string. Missing field on deserialize → `None`.

### Step 1: Write the failing test

Add to `tests/test_artifacts.py`:

```python
from datetime import datetime, timezone
from recap.artifacts import RecordingMetadata

def test_recording_metadata_has_recording_started_at_field():
    """New field persists through sidecar serialization round-trip."""
    ts = datetime(2026, 4, 22, 14, 30, 0, tzinfo=timezone.utc)
    metadata = RecordingMetadata(
        org="acme", note_path="Meetings/test.md", title="Test",
        date="2026-04-22", participants=[], platform="teams",
        recording_started_at=ts,
    )
    assert metadata.recording_started_at == ts

    roundtripped = RecordingMetadata.from_dict(metadata.to_dict())
    assert roundtripped.recording_started_at == ts


def test_recording_metadata_missing_recording_started_at_deserializes_to_none():
    """Pre-#27 sidecars without the field load cleanly with None."""
    legacy_sidecar = {
        "org": "acme", "note_path": "x.md", "title": "Test",
        "date": "2026-04-22", "participants": [], "platform": "teams",
        "calendar_source": None, "event_id": None, "meeting_link": "",
    }
    metadata = RecordingMetadata.from_dict(legacy_sidecar)
    assert metadata.recording_started_at is None


def test_recording_metadata_default_recording_started_at_is_none():
    """Default factory omits the field cleanly."""
    metadata = RecordingMetadata(
        org="acme", note_path="", title="Test", date="2026-04-22",
        participants=[], platform="teams",
    )
    assert metadata.recording_started_at is None
```

### Step 2: Run test to verify it fails

Run: `uv run pytest tests/test_artifacts.py::test_recording_metadata_has_recording_started_at_field -v`

Expected: FAIL — `RecordingMetadata.__init__() got an unexpected keyword argument 'recording_started_at'`.

### Step 3: Write minimal implementation

In `recap/artifacts.py`, add the import at the top:

```python
from datetime import date, datetime
```

Add the field to the dataclass (must come after existing defaulted fields to stay valid):

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
    llm_backend: str | None = None
    audio_warnings: list[str] = field(default_factory=list)
    system_audio_devices_seen: list[str] = field(default_factory=list)
    recording_started_at: datetime | None = None
```

In `from_dict`, handle the ISO-string decode:

```python
started_raw = data.get("recording_started_at")
recording_started_at: datetime | None = (
    datetime.fromisoformat(started_raw) if started_raw else None
)
return cls(
    ...existing args...,
    recording_started_at=recording_started_at,
)
```

In `to_dict`, encode to ISO:

```python
return {
    ...existing entries...,
    "recording_started_at": (
        self.recording_started_at.isoformat()
        if self.recording_started_at is not None
        else None
    ),
}
```

### Step 4: Run test to verify it passes

Run: `uv run pytest tests/test_artifacts.py -v -k recording_started_at`

Expected: all three tests PASS.

### Step 5: Run the full test suite (regression check)

Run: `uv run pytest tests/test_artifacts.py -v`

Expected: all tests PASS (pre-existing tests unaffected).

### Step 6: Commit

```bash
git add recap/artifacts.py tests/test_artifacts.py
git commit -m "feat(artifacts): add recording_started_at field to RecordingMetadata

Additive optional datetime field for #27. Persists through sidecar
round-trip (ISO 8601 string on disk); missing field on legacy sidecars
deserializes to None.

Required by detector-time synthesis of unscheduled-meeting metadata."
```

---

## Task 2: Add org-subfolder resolution helper in detector

**Files:**
- Modify: `recap/daemon/recorder/detector.py:88-100` (extend `_resolve_org_config` OR add sibling helper)
- Test: `tests/test_detector.py` (create if absent, else add cases)

**Context:** `_build_recording_metadata` will need `org_config.resolve_subfolder(vault_path)` to construct the vault-relative `note_path`. Today `_resolve_org_config` returns only the `OrgConfig`. Keep the existing method's signature (other call sites use it); add a small sibling `_resolve_org_and_subfolder` returning the `(config, subfolder_path)` tuple.

### Step 1: Write the failing test

Add to `tests/test_detector.py` (or create it):

```python
from pathlib import Path
from unittest.mock import Mock
from recap.daemon.recorder.detector import MeetingDetector


def _make_detector_with_org(monkeypatch, tmp_path):
    """Factory: minimal detector where `acme` org resolves to a subfolder."""
    org_cfg = Mock()
    org_cfg.slug = "acme"
    org_cfg.resolve_subfolder = lambda vault: vault / "Acme"

    config = Mock()
    config.vault_path = str(tmp_path)
    config.org_by_slug = lambda slug: org_cfg if slug == "acme" else None
    config.default_org = org_cfg

    recorder = Mock()
    return MeetingDetector(config=config, recorder=recorder)


def test_resolve_org_and_subfolder_returns_tuple(tmp_path):
    """Helper returns (OrgConfig, resolved-subfolder-path)."""
    detector = _make_detector_with_org(None, tmp_path)
    org_cfg, subfolder = detector._resolve_org_and_subfolder("acme")
    assert org_cfg.slug == "acme"
    assert subfolder == tmp_path / "Acme"


def test_resolve_org_and_subfolder_returns_none_when_no_match(tmp_path):
    """Unknown slug + no default returns (None, None)."""
    config = Mock()
    config.vault_path = str(tmp_path)
    config.org_by_slug = lambda slug: None
    config.default_org = None
    detector = MeetingDetector(config=config, recorder=Mock())
    assert detector._resolve_org_and_subfolder("nonexistent") == (None, None)
```

### Step 2: Run test to verify it fails

Run: `uv run pytest tests/test_detector.py::test_resolve_org_and_subfolder_returns_tuple -v`

Expected: FAIL — `AttributeError: 'MeetingDetector' object has no attribute '_resolve_org_and_subfolder'`.

### Step 3: Write minimal implementation

Add to `recap/daemon/recorder/detector.py` right after `_resolve_org_config`:

```python
def _resolve_org_and_subfolder(
    self, org: str,
) -> tuple["OrgConfig | None", "Path | None"]:
    """Return ``(OrgConfig, vault/subfolder)`` for *org*, or ``(None, None)``.

    Unscheduled-meeting synthesis needs both values from one lookup site.
    Scheduled paths already have ``note_path`` from the calendar sync layer
    and don't need this helper.
    """
    config = self._resolve_org_config(org)
    if config is None:
        return None, None
    vault_path = Path(self._config.vault_path)
    return config, config.resolve_subfolder(vault_path)
```

### Step 4: Run test to verify it passes

Run: `uv run pytest tests/test_detector.py -v -k resolve_org_and_subfolder`

Expected: both tests PASS.

### Step 5: Commit

```bash
git add recap/daemon/recorder/detector.py tests/test_detector.py
git commit -m "feat(recorder): add _resolve_org_and_subfolder helper

Single-lookup-site accessor returning (OrgConfig, subfolder-path) tuple.
Keeps existing _resolve_org_config signature intact for other callers.
Prepares detector-time synthesis of unscheduled note_path."
```

---

## Task 3: Synthesize unscheduled metadata (base case, no collision)

**Files:**
- Modify: `recap/daemon/recorder/detector.py:126-147` (extract unscheduled-synthesis helper from `_build_recording_metadata`)
- Test: `tests/test_detector.py`

**Context:** When `event_id` is `None` (no calendar event) AND `note_path` is empty (no pre-existing note), we synthesize. Otherwise keep existing calendar-backed behavior. The `captured` instant must feed all three derived values (event_id embeds nothing time-based, but note_path and recording_started_at both need it).

### Step 1: Write the failing test

Add to `tests/test_detector.py`:

```python
import re
from datetime import datetime, timezone
from recap.models import Participant


def test_build_recording_metadata_synthesizes_unscheduled_identity(tmp_path, monkeypatch):
    """No calendar event + no existing note -> synthetic id + precomputed path."""
    frozen = datetime(2026, 4, 22, 14, 30, 0, tzinfo=timezone.utc)

    class _FakeDatetime:
        @staticmethod
        def now(tz=None):
            return frozen.astimezone(tz) if tz is not None else frozen.replace(tzinfo=None)

    # Freeze wall-clock inside detector module
    import recap.daemon.recorder.detector as det_mod
    monkeypatch.setattr(det_mod, "datetime", _FakeDatetime)

    detector = _make_detector_with_org(monkeypatch, tmp_path)
    # Org directory must exist for the collision-free path to settle.
    (tmp_path / "Acme" / "Meetings").mkdir(parents=True)

    metadata = detector._build_recording_metadata(
        org="acme",
        title="Whatever window said",  # should be replaced with platform label
        platform="teams",
        participants=[],
        meeting_link="",
        event_id=None,
    )

    assert metadata.event_id is not None
    assert re.fullmatch(r"unscheduled:[0-9a-f]{32}", metadata.event_id)
    assert metadata.note_path == "Acme/Meetings/2026-04-22 1430 - Teams call.md"
    assert metadata.recording_started_at is not None
    assert metadata.title == "Teams call"
    assert metadata.participants == []
    assert metadata.meeting_link == ""
    assert metadata.calendar_source is None
    assert metadata.platform == "teams"
    assert metadata.date == "2026-04-22"


def test_build_recording_metadata_with_event_id_keeps_calendar_path(tmp_path, monkeypatch):
    """With an event_id, no synthesis happens (scheduled path unchanged)."""
    detector = _make_detector_with_org(monkeypatch, tmp_path)
    # _find_calendar_note returns "" since no note exists, which is fine:
    # the scheduled path keeps an empty note_path and lets the pipeline
    # fall back to its own resolution. The key property: event_id is NOT
    # replaced with a synthetic one.
    metadata = detector._build_recording_metadata(
        org="acme", title="Sprint Planning", platform="teams",
        participants=[Participant(name="Alice")],
        meeting_link="https://teams.example/x",
        event_id="real-calendar-event-id-123",
    )
    assert metadata.event_id == "real-calendar-event-id-123"
    assert not metadata.event_id.startswith("unscheduled:")
    assert metadata.title == "Sprint Planning"  # original title preserved


def test_build_recording_metadata_platform_label_map(tmp_path, monkeypatch):
    """Each platform gets its 'X call' label; unknown platforms pass through."""
    import recap.daemon.recorder.detector as det_mod
    frozen = datetime(2026, 4, 22, 9, 7, 0, tzinfo=timezone.utc)

    class _FakeDatetime:
        @staticmethod
        def now(tz=None):
            return frozen.astimezone(tz) if tz is not None else frozen.replace(tzinfo=None)
    monkeypatch.setattr(det_mod, "datetime", _FakeDatetime)

    detector = _make_detector_with_org(monkeypatch, tmp_path)
    (tmp_path / "Acme" / "Meetings").mkdir(parents=True)

    for platform, label in [("teams", "Teams call"), ("zoom", "Zoom call"),
                             ("signal", "Signal call")]:
        m = detector._build_recording_metadata(
            org="acme", title="", platform=platform,
            participants=[], meeting_link="", event_id=None,
        )
        assert m.title == label
        assert f"- {label}.md" in m.note_path
```

### Step 2: Run test to verify it fails

Run: `uv run pytest tests/test_detector.py -v -k "synthesizes_unscheduled or platform_label"`

Expected: FAIL — synthetic id is not produced, `event_id` stays `None`.

### Step 3: Write minimal implementation

Add imports at the top of `detector.py`:

```python
import uuid
from datetime import datetime, timedelta, timezone
```

(timezone is the addition; the others are there.)

Add a module-level constant near `_PLATFORMS`:

```python
_PLATFORM_LABELS = {
    "teams":  "Teams call",
    "zoom":   "Zoom call",
    "signal": "Signal call",
}
```

Add a helper method on `MeetingDetector` (placed near `_build_recording_metadata`):

```python
def _synthesize_unscheduled_identity(
    self, *, org: str, platform: str, captured: datetime,
) -> tuple[str, str, str]:
    """Return (event_id, note_path, title) for an unscheduled recording.

    ``captured`` is the single instant that seeds all three values so
    retries on a persisted sidecar stay stable.
    """
    event_id = f"unscheduled:{uuid.uuid4().hex}"
    title = _PLATFORM_LABELS.get(platform, f"{platform.title()} call")
    _, subfolder = self._resolve_org_and_subfolder(org)
    if subfolder is None:
        # Degraded: no org config available. Fall back to empty note_path
        # and let the pipeline's existing filename fallback catch it.
        return event_id, "", title
    vault_path = Path(self._config.vault_path)
    base_name = f"{captured:%Y-%m-%d %H%M} - {title}.md"
    candidate = subfolder / "Meetings" / base_name
    # (Collision loop added in Task 4; base case here.)
    return event_id, to_vault_relative(candidate, vault_path), title
```

Modify `_build_recording_metadata` to use the helper when `event_id` is missing AND `_find_calendar_note` returns empty:

```python
def _build_recording_metadata(
    self, *, org, title, platform, participants, meeting_link="", event_id=None,
) -> RecordingMetadata:
    note_path = self._find_calendar_note(org, event_id)
    recording_started_at: datetime | None = None

    if not event_id and not note_path:
        captured = datetime.now(timezone.utc).astimezone()
        event_id, note_path, title = self._synthesize_unscheduled_identity(
            org=org, platform=platform, captured=captured,
        )
        recording_started_at = captured
        date_str = captured.date().isoformat()
    else:
        date_str = datetime.now().date().isoformat()

    return RecordingMetadata(
        org=org,
        note_path=note_path,
        title=title.strip() or "Meeting",
        date=date_str,
        participants=participants,
        platform=platform,
        calendar_source=None,
        event_id=event_id,
        meeting_link=meeting_link,
        recording_started_at=recording_started_at,
    )
```

### Step 4: Run test to verify it passes

Run: `uv run pytest tests/test_detector.py -v -k "synthesizes_unscheduled or calendar_path or platform_label"`

Expected: all three tests PASS.

### Step 5: Run the full detector test file

Run: `uv run pytest tests/test_detector.py -v`

Expected: no regressions.

### Step 6: Commit

```bash
git add recap/daemon/recorder/detector.py tests/test_detector.py
git commit -m "feat(recorder): synthesize unscheduled identity in _build_recording_metadata

Adds _synthesize_unscheduled_identity helper that mints:
- event_id = unscheduled:<uuid hex>
- note_path = {org-subfolder}/Meetings/YYYY-MM-DD HHMM - {Platform} call.md
- title = {Platform} call (Teams/Zoom/Signal)

All three values share one captured instant so pipeline retries that
reload the sidecar stay stable. Scheduled path with a real event_id
is untouched.

Covers #27 detector-time synthesis. Collision resolution in follow-up."
```

---

## Task 4: Filename collision resolution at detection time

**Files:**
- Modify: `recap/daemon/recorder/detector.py` (extend `_synthesize_unscheduled_identity`)
- Test: `tests/test_detector.py`

**Context:** Two unscheduled meetings starting in the same minute on the same platform would produce identical filenames. Resolve at detection time (NOT vault-write time — `upsert_note` treats existing paths as update targets and would overwrite the wrong note). Append `(2)`, `(3)`, … `(9)`; fall through to a full-seconds timestamp if still colliding.

### Step 1: Write the failing test

Append to `tests/test_detector.py`:

```python
def test_build_recording_metadata_collision_appends_suffix(tmp_path, monkeypatch):
    """Second same-minute Teams call gets '(2)' suffix."""
    import recap.daemon.recorder.detector as det_mod
    frozen = datetime(2026, 4, 22, 14, 30, 0, tzinfo=timezone.utc)

    class _FakeDatetime:
        @staticmethod
        def now(tz=None):
            return frozen.astimezone(tz) if tz is not None else frozen.replace(tzinfo=None)
    monkeypatch.setattr(det_mod, "datetime", _FakeDatetime)

    detector = _make_detector_with_org(monkeypatch, tmp_path)
    meetings_dir = tmp_path / "Acme" / "Meetings"
    meetings_dir.mkdir(parents=True)
    # Pre-create the base filename so the next call must disambiguate.
    (meetings_dir / "2026-04-22 1430 - Teams call.md").write_text("stub")

    metadata = detector._build_recording_metadata(
        org="acme", title="", platform="teams",
        participants=[], meeting_link="", event_id=None,
    )
    assert metadata.note_path == "Acme/Meetings/2026-04-22 1430 - Teams call (2).md"


def test_build_recording_metadata_collision_escalates_to_seconds(tmp_path, monkeypatch):
    """9 pre-existing suffixes -> falls through to HHMMSS timestamp."""
    import recap.daemon.recorder.detector as det_mod
    frozen = datetime(2026, 4, 22, 14, 30, 45, tzinfo=timezone.utc)

    class _FakeDatetime:
        @staticmethod
        def now(tz=None):
            return frozen.astimezone(tz) if tz is not None else frozen.replace(tzinfo=None)
    monkeypatch.setattr(det_mod, "datetime", _FakeDatetime)

    detector = _make_detector_with_org(monkeypatch, tmp_path)
    meetings_dir = tmp_path / "Acme" / "Meetings"
    meetings_dir.mkdir(parents=True)
    (meetings_dir / "2026-04-22 1430 - Teams call.md").write_text("stub")
    for n in range(2, 10):
        (meetings_dir / f"2026-04-22 1430 - Teams call ({n}).md").write_text("stub")

    metadata = detector._build_recording_metadata(
        org="acme", title="", platform="teams",
        participants=[], meeting_link="", event_id=None,
    )
    assert metadata.note_path == "Acme/Meetings/2026-04-22 143045 - Teams call.md"
```

### Step 2: Run tests to verify they fail

Run: `uv run pytest tests/test_detector.py -v -k collision`

Expected: FAIL — current helper never checks for existing files.

### Step 3: Write minimal implementation

Replace the body of `_synthesize_unscheduled_identity` after the `subfolder is None` guard:

```python
    vault_path = Path(self._config.vault_path)
    meetings_dir = subfolder / "Meetings"
    base = f"{captured:%Y-%m-%d %H%M} - {title}"
    candidate = meetings_dir / f"{base}.md"

    for n in range(2, 10):
        if not candidate.exists():
            break
        candidate = meetings_dir / f"{base} ({n}).md"
    else:
        if candidate.exists():
            # Extreme fallback: full seconds. Still deterministic.
            candidate = meetings_dir / f"{captured:%Y-%m-%d %H%M%S} - {title}.md"

    return event_id, to_vault_relative(candidate, vault_path), title
```

### Step 4: Run tests to verify they pass

Run: `uv run pytest tests/test_detector.py -v -k collision`

Expected: both collision tests PASS.

### Step 5: Regression check

Run: `uv run pytest tests/test_detector.py -v`

Expected: all detector tests still pass (including the base-case from Task 3).

### Step 6: Commit

```bash
git add recap/daemon/recorder/detector.py tests/test_detector.py
git commit -m "feat(recorder): collision resolution for unscheduled filenames

Same-minute same-platform collision appends (2)..(9) suffix; if still
colliding, falls through to a deterministic HHMMSS filename.

Resolution happens at detection time because upsert_note treats
existing paths as update targets, so pushing this to vault-write
would silently overwrite the wrong note."
```

---

## Task 5: Verify extension-detection path carries synthesis

**Files:**
- Test only: `tests/test_detector.py`
- No source changes expected (synthesis lives in `_build_recording_metadata`, which `_recording_metadata_from_enriched` already delegates to).

**Context:** [detector.py:152-170](../../recap/daemon/recorder/detector.py) shows `_recording_metadata_from_enriched` calls `_build_recording_metadata`. Task 3's synthesis should flow through automatically. This task is a belt-and-braces regression test so that layering stays true.

### Step 1: Write the test

Append to `tests/test_detector.py`:

```python
def test_extension_detection_path_synthesizes_unscheduled(tmp_path, monkeypatch):
    """`_recording_metadata_from_enriched` inherits synthesis behavior."""
    import recap.daemon.recorder.detector as det_mod
    frozen = datetime(2026, 4, 22, 16, 15, 0, tzinfo=timezone.utc)

    class _FakeDatetime:
        @staticmethod
        def now(tz=None):
            return frozen.astimezone(tz) if tz is not None else frozen.replace(tzinfo=None)
    monkeypatch.setattr(det_mod, "datetime", _FakeDatetime)

    detector = _make_detector_with_org(monkeypatch, tmp_path)
    (tmp_path / "Acme" / "Meetings").mkdir(parents=True)

    metadata = detector._recording_metadata_from_enriched(
        "acme",
        {"title": "Browser Meeting", "participants": [], "platform": "zoom"},
        meeting_link="https://zoom.example/42",
        event_id=None,
    )
    assert metadata.event_id is not None
    assert metadata.event_id.startswith("unscheduled:")
    assert metadata.title == "Zoom call"
    assert metadata.note_path == "Acme/Meetings/2026-04-22 1615 - Zoom call.md"
    assert metadata.meeting_link == "https://zoom.example/42"
    assert metadata.recording_started_at == frozen
```

### Step 2: Run test

Run: `uv run pytest tests/test_detector.py::test_extension_detection_path_synthesizes_unscheduled -v`

Expected: PASS (no source change needed).

### Step 3: Commit

```bash
git add tests/test_detector.py
git commit -m "test(recorder): extension path inherits unscheduled synthesis

Regression test covering _recording_metadata_from_enriched (browser
extension signal path) so future refactors don't break the
layering that makes #27 synthesis cover both entry points."
```

---

## Task 6: Add `unscheduled` tag to canonical frontmatter

**Files:**
- Modify: `recap/vault.py:86-136` (extend `build_canonical_frontmatter`)
- Test: `tests/test_vault.py` (add cases; create if absent)

**Context:** Today `tags` is always `[f"meeting/{analysis.meeting_type}"]`. For unscheduled notes (`event-id` starts with `unscheduled:`), append the `unscheduled` tag. Keep existing canonical `meeting/<type>` tag untouched — Codex explicit: preserve analyzed type.

### Step 1: Write the failing test

Add to `tests/test_vault.py`:

```python
from datetime import date
from pathlib import Path
from recap.artifacts import RecordingMetadata
from recap.models import MeetingMetadata, AnalysisResult
from recap.vault import build_canonical_frontmatter


def _stub_meta_and_analysis():
    meta = MeetingMetadata(
        title="Teams call", date=date(2026, 4, 22),
        participants=[], platform="teams",
    )
    analysis = AnalysisResult(
        speaker_mapping={}, meeting_type="general", summary="s",
        key_points=[], decisions=[], action_items=[],
        follow_ups=[], relationship_notes=None,
        people=[], companies=[],
    )
    return meta, analysis


def test_canonical_frontmatter_adds_unscheduled_tag(tmp_path):
    """event-id starting with unscheduled: → 'unscheduled' tag appended."""
    meta, analysis = _stub_meta_and_analysis()
    recording_meta = RecordingMetadata(
        org="acme", note_path="Acme/Meetings/x.md", title="Teams call",
        date="2026-04-22", participants=[], platform="teams",
        event_id="unscheduled:abc123",
    )
    fm = build_canonical_frontmatter(
        metadata=meta, analysis=analysis, duration_seconds=2712,
        recording_path=Path("x.flac"), org="acme", org_subfolder="Acme",
        recording_metadata=recording_meta,
    )
    assert fm["tags"] == ["meeting/general", "unscheduled"]
    assert fm["event-id"] == "unscheduled:abc123"


def test_canonical_frontmatter_keeps_single_tag_for_scheduled(tmp_path):
    """Real event-id → no 'unscheduled' tag."""
    meta, analysis = _stub_meta_and_analysis()
    recording_meta = RecordingMetadata(
        org="acme", note_path="Acme/Meetings/x.md", title="Teams call",
        date="2026-04-22", participants=[], platform="teams",
        event_id="real-cal-id-123",
    )
    fm = build_canonical_frontmatter(
        metadata=meta, analysis=analysis, duration_seconds=2712,
        recording_path=Path("x.flac"), org="acme", org_subfolder="Acme",
        recording_metadata=recording_meta,
    )
    assert fm["tags"] == ["meeting/general"]
```

### Step 2: Run test to verify it fails

Run: `uv run pytest tests/test_vault.py -v -k unscheduled_tag`

Expected: FAIL — `tags` doesn't include `unscheduled`.

### Step 3: Write minimal implementation

In `recap/vault.py`, inside `build_canonical_frontmatter`, after the block that populates `fm["event-id"]`:

```python
if recording_metadata is not None:
    ...existing conditional block...

# Tag augmentation for unscheduled meetings. Keep the canonical
# meeting/<type> tag (analyzed type is authoritative) and append
# 'unscheduled' so Dataview queries can surface them.
event_id = fm.get("event-id", "")
if isinstance(event_id, str) and event_id.startswith("unscheduled:"):
    fm["tags"] = list(fm["tags"]) + ["unscheduled"]
```

### Step 4: Run tests to verify they pass

Run: `uv run pytest tests/test_vault.py -v -k unscheduled_tag`

Expected: both tests PASS.

### Step 5: Commit

```bash
git add recap/vault.py tests/test_vault.py
git commit -m "feat(vault): append 'unscheduled' tag when event-id is synthetic

Dataview-queryable marker (FROM #unscheduled) for meetings the detector
auto-recorded without a calendar event. Canonical meeting/<type> tag is
preserved (analyzed type stays authoritative).

Complements #27 detector-time synthesis; no behavior change for
scheduled notes."
```

---

## Task 7: Add `time: "HH:MM-HH:MM"` to canonical frontmatter

**Files:**
- Modify: `recap/vault.py:86-136` (extend `build_canonical_frontmatter`)
- Test: `tests/test_vault.py`

**Context:** Today `build_canonical_frontmatter` never emits `time` — that key lives in `_CALENDAR_OWNED_KEYS` and is only set via calendar sync (`sync.py`). For unscheduled notes we need `time` so MeetingListView sorts and past/upcoming classification at [meetingTime.ts:13](../../obsidian-recap/src/lib/meetingTime.ts) works. Derive from `recording_started_at + duration_seconds`.

Degraded path: if `recording_started_at` is None OR `duration_seconds` is 0, emit `time: "HH:MM-HH:MM"` with start==end (still a valid range string; never bare `HH:MM` which parses as all-day).

### Step 1: Write the failing test

Add to `tests/test_vault.py`:

```python
from datetime import datetime, timezone


def test_canonical_frontmatter_time_range_from_started_at_and_duration():
    meta, analysis = _stub_meta_and_analysis()
    started = datetime(2026, 4, 22, 14, 30, 0, tzinfo=timezone.utc)
    recording_meta = RecordingMetadata(
        org="acme", note_path="Acme/Meetings/x.md", title="Teams call",
        date="2026-04-22", participants=[], platform="teams",
        event_id="unscheduled:abc",
        recording_started_at=started,
    )
    fm = build_canonical_frontmatter(
        metadata=meta, analysis=analysis,
        duration_seconds=2712,  # 45 min 12s
        recording_path=Path("x.flac"), org="acme", org_subfolder="Acme",
        recording_metadata=recording_meta,
    )
    # 14:30 + 45:12 = 15:15
    assert fm["time"] == "14:30-15:15"


def test_canonical_frontmatter_time_degenerate_on_missing_started_at():
    """No recording_started_at -> no time key (scheduled path uses calendar time)."""
    meta, analysis = _stub_meta_and_analysis()
    recording_meta = RecordingMetadata(
        org="acme", note_path="Acme/Meetings/x.md", title="Teams call",
        date="2026-04-22", participants=[], platform="teams",
        event_id="real-cal-id",
        recording_started_at=None,
    )
    fm = build_canonical_frontmatter(
        metadata=meta, analysis=analysis, duration_seconds=2712,
        recording_path=Path("x.flac"), org="acme", org_subfolder="Acme",
        recording_metadata=recording_meta,
    )
    assert "time" not in fm


def test_canonical_frontmatter_time_degenerate_on_zero_duration():
    meta, analysis = _stub_meta_and_analysis()
    started = datetime(2026, 4, 22, 14, 30, 0, tzinfo=timezone.utc)
    recording_meta = RecordingMetadata(
        org="acme", note_path="Acme/Meetings/x.md", title="Teams call",
        date="2026-04-22", participants=[], platform="teams",
        event_id="unscheduled:abc",
        recording_started_at=started,
    )
    fm = build_canonical_frontmatter(
        metadata=meta, analysis=analysis, duration_seconds=0,
        recording_path=Path("x.flac"), org="acme", org_subfolder="Acme",
        recording_metadata=recording_meta,
    )
    # Still a valid HH:MM-HH:MM range, never bare HH:MM.
    assert fm["time"] == "14:30-14:30"
```

### Step 2: Run tests to verify they fail

Run: `uv run pytest tests/test_vault.py -v -k "time_range or time_degenerate"`

Expected: FAIL on the first test (no `time` key emitted), second passes by coincidence (absent key).

### Step 3: Write minimal implementation

In `recap/vault.py`, add this block inside `build_canonical_frontmatter`, after the `recording_metadata is not None` block:

```python
# Time range for notes whose start is known (today: unscheduled
# synthesis — scheduled notes get `time` from the calendar sync layer,
# which is a calendar-owned field preserved via the merge rules).
if (
    recording_metadata is not None
    and recording_metadata.recording_started_at is not None
):
    started = recording_metadata.recording_started_at
    end = started + timedelta(seconds=int(duration_seconds))
    fm["time"] = f"{started:%H:%M}-{end:%H:%M}"
```

Add the `timedelta` import at the top of `vault.py`:

```python
from datetime import date, timedelta
```

### Step 4: Run tests to verify they pass

Run: `uv run pytest tests/test_vault.py -v -k "time_range or time_degenerate"`

Expected: all three tests PASS.

### Step 5: Verify the merge path doesn't clobber a calendar `time`

Add a quick regression test:

```python
def test_canonical_frontmatter_time_set_for_unscheduled_only(monkeypatch, tmp_path):
    """Scheduled notes (event-id without 'unscheduled:' prefix) with
    recording_started_at still emit the computed range. Calendar-set
    time survives via the _merge_frontmatter rules when upserting."""
    meta, analysis = _stub_meta_and_analysis()
    started = datetime(2026, 4, 22, 9, 0, 0, tzinfo=timezone.utc)
    rm = RecordingMetadata(
        org="acme", note_path="x.md", title="t", date="2026-04-22",
        participants=[], platform="teams", event_id="real-cal-123",
        recording_started_at=started,
    )
    fm = build_canonical_frontmatter(
        metadata=meta, analysis=analysis, duration_seconds=900,
        recording_path=Path("x.flac"), org="acme", org_subfolder="Acme",
        recording_metadata=rm,
    )
    # The canonical FM carries computed time. The merge layer (upsert_note
    # _CALENDAR_OWNED_KEYS) preserves the existing calendar-written time
    # when upserting over a calendar-seeded note.
    assert fm["time"] == "09:00-09:15"
```

Run: `uv run pytest tests/test_vault.py -v -k time`

Expected: all time tests PASS.

### Step 6: Commit

```bash
git add recap/vault.py tests/test_vault.py
git commit -m "feat(vault): emit time range from recording_started_at + duration

Derives 'time: HH:MM-HH:MM' from the persisted recording_started_at
field plus elapsed duration. When recording_started_at is None the
key is omitted, leaving the scheduled-note path (calendar-owned
'time' from sync.py) unaffected.

Degenerate case (zero duration) emits start==end so the plugin's
HH:MM-HH:MM parser at meetingTime.ts:13 never falls through to its
all-day sentinel.

Completes #27 frontmatter shape."
```

---

## Task 8: Empty-roster conditional in the analyze prompt

**Files:**
- Modify: `prompts/meeting_analysis.md` (template with two variants or a conditional placeholder)
- Modify: `recap/analyze.py:20-32` (`_build_prompt` emits the right variant)
- Test: `tests/test_analyze.py` (create if absent)

**Context:** Empty `participants` passes an empty `{{participants}}` block into the prompt while the template still says "map each SPEAKER_XX label to a participant name from the roster above." Contradictory instructions. JSON schema of `AnalysisResult` stays unchanged.

**Simpler implementation choice:** instead of branching inside the Markdown template (fragile), swap the "Participant Roster" section text inside `_build_prompt` based on roster emptiness. Keep `{{transcript}}` substitution unchanged.

### Step 1: Write the failing test

Create `tests/test_analyze.py` (or add to existing):

```python
from datetime import date
from recap.analyze import _build_prompt
from recap.models import MeetingMetadata, TranscriptResult, Utterance, Participant


def _stub_transcript():
    return TranscriptResult(
        utterances=[Utterance(speaker="SPEAKER_00", start=0, end=1, text="hi")],
    )


def test_build_prompt_with_participants_uses_roster_instructions():
    template = open("prompts/meeting_analysis.md").read()
    meta = MeetingMetadata(
        title="t", date=date(2026, 4, 22),
        participants=[Participant(name="Alice"), Participant(name="Bob", email="b@ex.com")],
        platform="teams",
    )
    prompt = _build_prompt(template, _stub_transcript(), meta)
    assert "- Alice" in prompt
    assert "- Bob (b@ex.com)" in prompt
    assert "map these labels to the participant roster above" in prompt


def test_build_prompt_with_empty_roster_uses_no_roster_wording():
    template = open("prompts/meeting_analysis.md").read()
    meta = MeetingMetadata(
        title="t", date=date(2026, 4, 22),
        participants=[],  # empty roster
        platform="teams",
    )
    prompt = _build_prompt(template, _stub_transcript(), meta)
    # No participant bullets should appear.
    assert "\n- " not in prompt.split("## Diarized Transcript")[0]
    # The empty-roster wording must appear.
    assert "No participant roster is available" in prompt
    # The contradictory roster instruction must NOT appear.
    assert "map these labels to the participant roster above" not in prompt
```

### Step 2: Run tests to verify they fail

Run: `uv run pytest tests/test_analyze.py -v`

Expected: the empty-roster test FAILS (current template always has roster instructions).

### Step 3: Modify the template

Replace the "Participant Roster" + transcript-instruction region of `prompts/meeting_analysis.md` with a placeholder that `_build_prompt` fills in:

```
{{roster_section}}

## Diarized Transcript

{{transcript_instruction}}

{{transcript}}
```

Replace the current lines 3-12 in `prompts/meeting_analysis.md` (the two blocks currently bookending the transcript) with the placeholders above. Keep everything under "## Instructions" (lines 15+) untouched.

### Step 4: Update `_build_prompt`

In `recap/analyze.py`:

```python
_ROSTER_WITH_PARTICIPANTS = """## Participant Roster

The following people were expected in this meeting:

{bullets}"""

_ROSTER_EMPTY = """## Participant Roster

No participant roster is available for this meeting."""

_TRANSCRIPT_INSTRUCTION_WITH_ROSTER = (
    "The transcript uses speaker labels (SPEAKER_00, SPEAKER_01, etc.) assigned "
    "by an automated diarization system. Use conversational context (name "
    "mentions, introductions, role references, topics discussed) to map these "
    "labels to the participant roster above."
)

_TRANSCRIPT_INSTRUCTION_NO_ROSTER = (
    "The transcript uses speaker labels (SPEAKER_00, SPEAKER_01, etc.) assigned "
    "by an automated diarization system. Only assign a real name if it is "
    "explicitly established in the transcript (e.g. a self-introduction, "
    "'Hi, I'm Alice'). Otherwise keep the speaker_mapping value as "
    "'Unknown Speaker N'."
)


def _build_prompt(
    template: str,
    transcript: TranscriptResult,
    metadata: MeetingMetadata,
) -> str:
    if metadata.participants:
        bullets = "\n".join(
            f"- {p.name} ({p.email})" if p.email else f"- {p.name}"
            for p in metadata.participants
        )
        roster_section = _ROSTER_WITH_PARTICIPANTS.format(bullets=bullets)
        transcript_instruction = _TRANSCRIPT_INSTRUCTION_WITH_ROSTER
    else:
        roster_section = _ROSTER_EMPTY
        transcript_instruction = _TRANSCRIPT_INSTRUCTION_NO_ROSTER

    prompt = template.replace("{{roster_section}}", roster_section)
    prompt = prompt.replace("{{transcript_instruction}}", transcript_instruction)
    prompt = prompt.replace("{{transcript}}", transcript.to_labelled_text())
    return prompt
```

### Step 5: Run tests to verify they pass

Run: `uv run pytest tests/test_analyze.py -v`

Expected: both tests PASS.

### Step 6: Regression check

Search for other call sites that use the `{{participants}}` placeholder to make sure nothing else depends on the old marker:

Run: `grep -rn "{{participants}}" .`

Expected: zero hits (we replaced the marker). If any hit appears in a non-prompt file, update it.

### Step 7: Commit

```bash
git add prompts/meeting_analysis.md recap/analyze.py tests/test_analyze.py
git commit -m "feat(analyze): empty-roster prompt branch for unscheduled meetings

Replaces the single {{participants}} placeholder with two swappable
sections ({{roster_section}} + {{transcript_instruction}}) so an
empty participant list produces coherent instructions instead of
'map SPEAKER_XX to a participant name from the roster above:' with
no roster.

JSON schema of AnalysisResult unchanged. No attempt to improve
diarization quality (that's #28). This purely removes the
contradictory prompt when #27 synthesis ships empty participants."
```

---

## Task 9: End-to-end integration test

**Files:**
- Create: `tests/test_unscheduled_integration.py`

**Context:** Exercise the full path: detector auto-record decision → sidecar write → pipeline resolve → vault upsert → EventIndex entry. No mocks of the three layers under test; mocks only at the I/O edges (recording audio, Claude CLI, NeMo). This is the test that proves the seams line up end to end.

### Step 1: Write the integration test

Create `tests/test_unscheduled_integration.py`:

```python
"""End-to-end test for unscheduled meeting synthesis.

Covers: detector synthesis -> sidecar -> pipeline resolve -> vault upsert
-> EventIndex entry. All Parakeet/NeMo/Claude calls are stubbed; the
three layers of interest (detector, pipeline resolution, vault writer)
run their real code paths.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from recap.artifacts import RecordingMetadata, write_recording_metadata
from recap.daemon.calendar.index import EventIndex
from recap.daemon.recorder.detector import MeetingDetector
from recap.models import AnalysisResult, MeetingMetadata, Participant, TranscriptResult, Utterance
from recap.vault import write_meeting_note


@pytest.fixture
def vault(tmp_path):
    vault_path = tmp_path / "vault"
    (vault_path / "Acme" / "Meetings").mkdir(parents=True)
    return vault_path


def _make_detector(vault):
    org_cfg = Mock()
    org_cfg.slug = "acme"
    org_cfg.resolve_subfolder = lambda v: v / "Acme"

    config = Mock()
    config.vault_path = str(vault)
    config.org_by_slug = lambda slug: org_cfg if slug == "acme" else None
    config.default_org = org_cfg

    return MeetingDetector(config=config, recorder=Mock())


def test_unscheduled_meeting_end_to_end(vault, monkeypatch, tmp_path):
    """Teams auto-record, no calendar event -> coherent note + EventIndex entry."""
    # --- Freeze wall clock to a deterministic moment. ---
    import recap.daemon.recorder.detector as det_mod
    frozen = datetime(2026, 4, 22, 14, 30, 0, tzinfo=timezone.utc)

    class _FakeDatetime:
        @staticmethod
        def now(tz=None):
            return frozen.astimezone(tz) if tz is not None else frozen.replace(tzinfo=None)
    monkeypatch.setattr(det_mod, "datetime", _FakeDatetime)

    # --- Detector synthesizes metadata. ---
    detector = _make_detector(vault)
    metadata = detector._build_recording_metadata(
        org="acme", title="Whatever Teams showed",
        platform="teams", participants=[], event_id=None,
    )
    assert metadata.event_id.startswith("unscheduled:")
    assert metadata.note_path == "Acme/Meetings/2026-04-22 1430 - Teams call.md"
    assert metadata.recording_started_at == frozen

    # --- Recorder would write the sidecar; simulate. ---
    recording_dir = tmp_path / "recordings"
    recording_dir.mkdir()
    audio_path = recording_dir / "2026-04-22 1430 Teams.flac"
    audio_path.write_bytes(b"")  # empty stub; pipeline audio is mocked
    write_recording_metadata(audio_path, metadata)

    # --- Vault write with stub analysis (no real Claude/NeMo). ---
    analysis = AnalysisResult(
        speaker_mapping={"SPEAKER_00": "Unknown Speaker 1"},
        meeting_type="general", summary="stub",
        key_points=[], decisions=[], action_items=[],
        follow_ups=[], relationship_notes=None,
        people=[], companies=[],
    )
    event_index = EventIndex(vault / ".recap" / "event-index.json")

    meeting_meta = MeetingMetadata(
        title=metadata.title, date=date(2026, 4, 22),
        participants=[], platform="teams",
    )
    note_path = write_meeting_note(
        metadata=meeting_meta,
        analysis=analysis,
        duration_seconds=2712,
        recording_path=audio_path,
        meetings_dir=vault / "Acme" / "Meetings",
        org="acme", org_subfolder="Acme",
        note_path=vault / metadata.note_path,
        recording_metadata=metadata,
        event_index=event_index,
        vault_path=vault,
    )

    # --- Assert note shape. ---
    assert note_path == vault / "Acme/Meetings/2026-04-22 1430 - Teams call.md"
    assert note_path.exists()
    content = note_path.read_text(encoding="utf-8")

    # Parse frontmatter.
    parts = content.split("---\n")
    fm = yaml.safe_load(parts[1])

    assert fm["event-id"] == metadata.event_id
    assert fm["title"] == "Teams call"
    assert fm["platform"] == "teams"
    assert fm["org"] == "acme"
    assert fm["org-subfolder"] == "Acme"
    assert fm["time"] == "14:30-15:15"
    assert fm["type"] == "general"
    assert "meeting/general" in fm["tags"]
    assert "unscheduled" in fm["tags"]
    assert "calendar-source" not in fm
    assert "meeting-link" not in fm
    assert fm["recording"] == "2026-04-22 1430 Teams.flac"

    # --- Assert EventIndex carries the synthetic id. ---
    assert event_index.lookup(metadata.event_id) is not None
    indexed_path = event_index.lookup(metadata.event_id)
    assert str(indexed_path).endswith("Acme/Meetings/2026-04-22 1430 - Teams call.md") or \
           str(indexed_path).endswith("Acme\\Meetings\\2026-04-22 1430 - Teams call.md")
```

### Step 2: Run the test

Run: `uv run pytest tests/test_unscheduled_integration.py -v`

Expected: PASS (assuming Tasks 1–7 are all green).

### Step 3: Full suite regression check

Run: `uv run pytest tests/ -v -k "not integration"` (exclude Phase 7 ML integration tier)

Expected: all tests PASS.

### Step 4: Commit

```bash
git add tests/test_unscheduled_integration.py
git commit -m "test(integration): end-to-end unscheduled meeting flow

Exercises the real code path from detector _build_recording_metadata
through sidecar write, vault.write_meeting_note, canonical frontmatter
emission, and EventIndex registration. Stubs only the I/O edges
(audio, Claude, NeMo).

Proves the #27 synthesis + vault-layer changes line up end to end
without special-casing in the pipeline or index layers."
```

---

## Task 10: MANIFEST and design-doc cross-reference

**Files:**
- Modify: `MANIFEST.md` (update `recap/artifacts.py`, `recap/daemon/recorder/detector.py`, `recap/vault.py`, `recap/analyze.py` descriptions + Key Relationships)
- Modify: `docs/plans/2026-04-22-unscheduled-meetings-design.md` (mark status "Implemented" with commit SHA once merged)

**Context:** MANIFEST is the structural-map convention. Any new field or seam that's not obvious from file listing needs a line. No docs-for-docs cleanup — just factual updates.

### Step 1: Update MANIFEST.md

In the structure tree, add/update these lines:

- `recap/artifacts.py` description: add `+ RecordingMetadata.recording_started_at`.
- `recap/daemon/recorder/detector.py` description: add `+ _synthesize_unscheduled_identity(unscheduled:<uuid>, deterministic filename, collision resolution)`.
- `recap/vault.py` description: add `+ unscheduled-tag append + time-range derivation from recording_started_at`.
- `recap/analyze.py` description: add `+ {{roster_section}}/{{transcript_instruction}} swap for empty-roster prompts`.
- `prompts/meeting_analysis.md` description: `+ {{roster_section}} + {{transcript_instruction}} placeholders (empty-roster branch)`.

Add a Key Relationships bullet:

```markdown
- **Unscheduled meetings (#27):** `_build_recording_metadata` in `recorder/detector.py` synthesizes `event_id = "unscheduled:<uuid>"`, a precomputed `note_path` under `{org}/Meetings/YYYY-MM-DD HHMM - {Platform} call.md`, and `recording_started_at`. Downstream pipeline + vault + EventIndex see a valid event-id and run their existing calendar-backed codepaths. Vault adds an `unscheduled` tag and a `time: HH:MM-HH:MM` range (computed from `recording_started_at + duration_seconds`). Analyze prompt swaps the participant-roster instructions for empty rosters. No retroactive calendar attachment — deferred to #33.
```

### Step 2: Commit MANIFEST

```bash
git add MANIFEST.md
git commit -m "docs(manifest): unscheduled meeting synthesis (#27)"
```

### Step 3: Sanity-check that nothing is dangling

Run: `uv run pytest tests/ -k "not integration"` one last time.
Run: `git log --oneline -15`

Confirm the commit sequence reads as an atomic story:
1. `feat(artifacts): add recording_started_at`
2. `feat(recorder): _resolve_org_and_subfolder helper`
3. `feat(recorder): synthesize unscheduled identity`
4. `feat(recorder): collision resolution`
5. `test(recorder): extension path inherits synthesis`
6. `feat(vault): 'unscheduled' tag`
7. `feat(vault): time range from recording_started_at`
8. `feat(analyze): empty-roster prompt branch`
9. `test(integration): end-to-end unscheduled flow`
10. `docs(manifest): unscheduled meeting synthesis (#27)`

### Step 4: Open PR

```bash
git push -u origin feat/27-unscheduled-meetings
gh pr create --title "fix(#27): unscheduled meeting synthesis and coherent frontmatter" --body "Implements the approved design at docs/plans/2026-04-22-unscheduled-meetings-design.md. Fixes #27. See design doc for decisions and design doc at docs/plans/2026-04-22-unscheduled-meetings-plan.md for the task breakdown."
```

---

## Rollback and safety notes

- Every task is its own commit. `git revert` any single commit to back it out without disturbing later commits, except Task 4 (collision) which depends on Task 3 (base synthesis).
- No destructive data migration — old sidecars still deserialize (missing field → None) and old notes with PII filenames are left in place.
- No daemon API change — no coordinated plugin/daemon deploy needed.

## Verification after merge

- Start the daemon, join a Teams call outside any calendar event.
- Confirm the note lands at `{default_org}/Meetings/YYYY-MM-DD HHMM - Teams call.md`.
- Open the note in Obsidian: time should show as a range (not blank), `unscheduled` tag present, content rendered correctly.
- Check `{vault}/_Recap/.recap/event-index.json`: entry for `unscheduled:<uuid>` mapping to the note's vault-relative path.
- Rename the note in Obsidian: plugin rename-queue should update EventIndex to the new path (existing behavior exercised for the first time on an unscheduled note).

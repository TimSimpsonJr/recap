# Issue #29 — Non-Teams Participant Enrichment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement this plan task-by-task.

**Goal:** Populate `RecordingMetadata.participants` for spontaneous Zoom, Google Meet, and Zoho meetings via UIA (Zoom) and browser-extension DOM scraping (Meet/Zoho), accumulated through a `ParticipantRoster` finalized at `Recorder.stop()`.

**Architecture:** `MeetingDetector` owns a `ParticipantRoster`. Three sources feed it: Teams UIA at detection (seeds initial sidecar + roster), Zoom UIA every 30s during recording, browser DOM via new HTTP endpoint every 30s. Recorder exposes `on_before_finalize` + `on_after_stop` hooks fired on every stop path; finalized roster overwrites `metadata.participants` before sidecar rewrite.

**Tech Stack:** Python 3.12 + aiohttp + `uiautomation`; Chrome MV3 extension (service worker + content script + `chrome.alarms`); pytest for unit/integration; manual acceptance for real UI.

**Design reference:** [docs/plans/2026-04-23-29-non-teams-enrichment-design.md](docs/plans/2026-04-23-29-non-teams-enrichment-design.md)

---

## Task Overview

1. `ParticipantRoster` class + unit tests
2. `extract_zoom_participants` + unit tests
3. `Recorder` stop-seam hooks + tests
4. `MeetingDetector` session lifecycle (begin/end) + tests
5. Detector Teams-path routing through roster
6. Detector Zoom UIA periodic refresh
7. HTTP endpoint `/api/meeting-participants-updated` + detector handler + tests
8. Extension `manifest.json` — content scripts + host permissions
9. Extension `content.js` — DOM scrapers
10. Extension `background.js` — alarm + refresh relay
11. Extension lockstep test
12. Integration E2E tests (4 scenarios)
13. MANIFEST.md + release notes + handoff acceptance checklist

---

## Task 1: `ParticipantRoster` class

**Files:**
- Create: `recap/daemon/recorder/roster.py`
- Create: `tests/test_roster.py`

**Step 1: Write failing tests**

Create `tests/test_roster.py`:

```python
"""Tests for ParticipantRoster accumulator."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from recap.daemon.recorder.roster import ParticipantRoster


def _now_tz() -> datetime:
    return datetime.now(timezone.utc)


class TestMerge:
    def test_empty_merge_returns_false(self):
        r = ParticipantRoster()
        assert r.merge("src", [], _now_tz()) is False
        assert r.current() == []

    def test_first_merge_returns_true_and_preserves_order(self):
        r = ParticipantRoster()
        assert r.merge("src", ["Alice", "Bob", "Carol"], _now_tz()) is True
        assert r.current() == ["Alice", "Bob", "Carol"]

    def test_same_names_same_case_returns_false(self):
        r = ParticipantRoster()
        r.merge("src", ["Alice", "Bob"], _now_tz())
        assert r.merge("src", ["Alice", "Bob"], _now_tz()) is False
        assert r.current() == ["Alice", "Bob"]

    def test_same_names_different_case_returns_true_and_upgrades_display(self):
        r = ParticipantRoster()
        r.merge("src", ["alice"], _now_tz())
        assert r.merge("src", ["Alice Smith"], _now_tz()) is True
        assert r.current() == ["Alice Smith"]

    def test_new_names_appended_in_order(self):
        r = ParticipantRoster()
        r.merge("src", ["Alice"], _now_tz())
        assert r.merge("src", ["Bob"], _now_tz()) is True
        assert r.current() == ["Alice", "Bob"]

    def test_whitespace_only_names_skipped(self):
        r = ParticipantRoster()
        assert r.merge("src", ["", "   ", "\t", "Alice"], _now_tz()) is True
        assert r.current() == ["Alice"]

    def test_whitespace_stripped_on_valid_names(self):
        r = ParticipantRoster()
        r.merge("src", ["  Alice  "], _now_tz())
        assert r.current() == ["Alice"]

    def test_naive_datetime_raises_value_error(self):
        r = ParticipantRoster()
        with pytest.raises(ValueError, match="timezone-aware"):
            r.merge("src", ["Alice"], datetime(2026, 1, 1, 12, 0, 0))

    def test_last_merge_per_source_updated(self):
        r = ParticipantRoster()
        t1 = _now_tz()
        r.merge("teams_uia_detection", ["Alice"], t1)
        assert r._last_merge_per_source["teams_uia_detection"] == t1

    def test_multi_source_interleaving_preserves_first_seen_order(self):
        r = ParticipantRoster()
        r.merge("teams", ["Alice"], _now_tz())
        r.merge("zoom", ["Bob"], _now_tz())
        r.merge("teams", ["Carol"], _now_tz())
        assert r.current() == ["Alice", "Bob", "Carol"]


class TestReadSurface:
    def test_current_equals_finalize_in_v1(self):
        r = ParticipantRoster()
        r.merge("src", ["Alice", "Bob"], _now_tz())
        assert r.current() == r.finalize()

    def test_current_safe_to_call_on_empty_roster(self):
        assert ParticipantRoster().current() == []

    def test_finalize_safe_to_call_on_empty_roster(self):
        assert ParticipantRoster().finalize() == []
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_roster.py -v
```

Expected: all tests fail with `ModuleNotFoundError: No module named 'recap.daemon.recorder.roster'`.

**Step 3: Implement `ParticipantRoster`**

Create `recap/daemon/recorder/roster.py`:

```python
"""Per-recording participant accumulator.

Owned by MeetingDetector. Fed by Teams UIA (one-shot at detection),
Zoom UIA (periodic during recording), and browser DOM extraction
(periodic HTTP push via /api/meeting-participants-updated).

Thread-safety: NONE. All callers run on the daemon's single asyncio
event loop. Introducing threads requires adding locks here.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

__all__ = ["ParticipantRoster"]


class ParticipantRoster:
    """Ordered-dedupe participant accumulator scoped to one recording.

    Shaped for future additive behavior: ``merge()`` returns whether
    the roster changed in a user-visible way (new name OR upgraded
    display form), so a later WebSocket ``participants_updated``
    broadcast can attach without redesign.

    Known limitation: cross-source name variants (``"Alice S."`` vs
    ``"Alice Smith"``) are NOT reconciled beyond casefold. Use
    ``match_known_contacts`` at the ingress boundary to normalize
    before merging.
    """

    def __init__(self) -> None:
        # key=casefold, value=display. dict preserves insertion order
        # (Py3.7+), so updating an existing key does not reorder.
        self._names: dict[str, str] = {}
        self._last_merge_per_source: dict[str, datetime] = {}

    def merge(
        self,
        source: str,
        names: Sequence[str],
        observed_at: datetime,
    ) -> bool:
        """Merge names from a source. Return True if the roster changed.

        A "change" is either a new name or a display-form upgrade on an
        existing casefold key. ``observed_at`` must be timezone-aware so
        timestamps stay usable downstream.
        """
        if observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        changed = False
        for raw in names:
            name = raw.strip()
            if not name:
                continue
            key = name.casefold()
            existing = self._names.get(key)
            if existing is None or existing != name:
                self._names[key] = name
                changed = True
        self._last_merge_per_source[source] = observed_at
        return changed

    def current(self) -> list[str]:
        """Current ordered deduped roster. Safe to call any time."""
        return list(self._names.values())

    def finalize(self) -> list[str]:
        """Final roster at Recorder.stop() time.

        Same as ``current()`` in v1. Separate method so future
        finalization logic (e.g. diarization reconciliation) can
        hook here without callers changing.
        """
        return self.current()
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_roster.py -v
```

Expected: all 13 tests pass.

**Step 5: Commit**

```bash
git add recap/daemon/recorder/roster.py tests/test_roster.py
git commit -m "feat(#29): ParticipantRoster ordered-dedupe accumulator"
```

---

## Task 2: `extract_zoom_participants` UIA walker

**Files:**
- Modify: `recap/daemon/recorder/call_state.py` (add new function near existing `_walk_for_participants`)
- Modify: `tests/test_enrichment.py` (or `tests/test_call_state.py` if it exists; check first)

**Step 1: Verify existing test file**

```bash
ls tests/test_enrichment.py tests/test_call_state.py 2>/dev/null
```

If `tests/test_enrichment.py` exists, extend it. Otherwise place new tests in a file matching the existing pattern for Teams (the Teams participant extractor likely has tests in one of these).

**Step 2: Write failing tests**

Add to the discovered tests file:

```python
class TestExtractZoomParticipants:
    """Zoom UIA participant extraction — same structural pattern as Teams."""

    def test_returns_names_from_list_items(self, monkeypatch):
        import recap.daemon.recorder.call_state as cs

        class FakeControl:
            def __init__(self, control_type, name="", children=()):
                self.ControlTypeName = control_type
                self.Name = name
                self._children = list(children)
            def GetChildren(self):
                return self._children

        roster = FakeControl("PaneControl", "Participants", children=[
            FakeControl("ListItemControl", "Alice"),
            FakeControl("ListItemControl", "Bob"),
        ])
        root = FakeControl("WindowControl", children=[roster])

        class FakeAuto:
            @staticmethod
            def ControlFromHandle(hwnd): return root

        monkeypatch.setitem(__import__("sys").modules, "uiautomation", FakeAuto)

        result = cs.extract_zoom_participants(42)
        assert result == ["Alice", "Bob"]

    def test_returns_none_when_no_participants(self, monkeypatch):
        import recap.daemon.recorder.call_state as cs

        class FakeControl:
            ControlTypeName = "WindowControl"
            Name = ""
            def GetChildren(self): return []

        class FakeAuto:
            @staticmethod
            def ControlFromHandle(hwnd): return FakeControl()

        monkeypatch.setitem(__import__("sys").modules, "uiautomation", FakeAuto)
        assert cs.extract_zoom_participants(42) is None

    def test_returns_none_on_uia_exception(self, monkeypatch):
        import recap.daemon.recorder.call_state as cs

        class FakeAuto:
            @staticmethod
            def ControlFromHandle(hwnd): raise RuntimeError("UIA boom")

        monkeypatch.setitem(__import__("sys").modules, "uiautomation", FakeAuto)
        assert cs.extract_zoom_participants(42) is None

    def test_returns_none_when_control_from_handle_returns_none(self, monkeypatch):
        import recap.daemon.recorder.call_state as cs

        class FakeAuto:
            @staticmethod
            def ControlFromHandle(hwnd): return None

        monkeypatch.setitem(__import__("sys").modules, "uiautomation", FakeAuto)
        assert cs.extract_zoom_participants(42) is None

    def test_returns_none_when_uiautomation_import_fails(self, monkeypatch):
        import recap.daemon.recorder.call_state as cs
        import sys
        # Make `import uiautomation` fail
        monkeypatch.setitem(sys.modules, "uiautomation", None)
        assert cs.extract_zoom_participants(42) is None
```

**Step 3: Run tests to verify they fail**

```bash
pytest tests/test_enrichment.py::TestExtractZoomParticipants -v
```

Expected: `AttributeError: module 'recap.daemon.recorder.call_state' has no attribute 'extract_zoom_participants'`.

**Step 4: Implement**

Add to `recap/daemon/recorder/call_state.py` near the existing `extract_teams_participants` function (around line 106):

```python
def extract_zoom_participants(hwnd: int) -> list[str] | None:
    """Extract participant names from a Zoom window via UI Automation.

    Mirrors ``extract_teams_participants``. Returns a list of display
    names, or ``None`` on any failure. Must never crash the caller.

    Walks the UIA tree up to ``max_depth=15`` looking for ListItem
    controls with a non-empty Name property (the Zoom participant
    panel renders roster items this way).
    """
    try:
        import uiautomation as auto  # type: ignore[import-untyped]
        if auto is None:
            return None

        control = auto.ControlFromHandle(hwnd)
        if not control:
            logger.debug("UIA: no control for zoom hwnd %s", hwnd)
            return None

        names: list[str] = []
        _walk_for_participants(control, names)
        if not names:
            logger.debug("UIA: no zoom participant names found for hwnd %s", hwnd)
            return None
        return names

    except Exception:
        logger.debug("UIA zoom extraction failed for hwnd %s", hwnd, exc_info=True)
        return None
```

Note: This reuses the existing `_walk_for_participants` helper that Teams uses. Zoom's participant panel also uses ListItem controls, so the walker applies directly.

Add to the module's `__all__` export if one exists:

```python
__all__ = [..., "extract_zoom_participants"]
```

**Step 5: Run tests**

```bash
pytest tests/test_enrichment.py::TestExtractZoomParticipants -v
```

Expected: 5 passing.

**Step 6: Commit**

```bash
git add recap/daemon/recorder/call_state.py tests/test_enrichment.py
git commit -m "feat(#29): extract_zoom_participants UIA walker"
```

---

## Task 3: Recorder stop-seam hooks

**Files:**
- Modify: `recap/daemon/recorder/recorder.py` (`__init__`, `stop` method around lines 288-301)
- Create: `tests/test_recorder_finalize.py`

**Harness reference:** The existing tests in [tests/test_recorder_orchestrator.py](tests/test_recorder_orchestrator.py) show the canonical way to exercise `Recorder.stop()` without spinning up PyAudio. Study `test_stop_persists_audio_warnings_into_sidecar` (lines 149-190) and `test_stop_captures_audio_warnings_after_final_drain_tick` (lines 193-240) — the tests below reuse that exact harness pattern: inject a `MagicMock` as `_audio_capture`, call `write_recording_metadata` to seed the sidecar, drive state machine into `RECORDING`, call `await recorder.stop()`, then `load_recording_metadata` + assert. No full `start()` invocation is needed.

**Step 1: Write failing tests**

Create `tests/test_recorder_finalize.py`:

```python
"""Tests for Recorder on_before_finalize / on_after_stop hooks (#29).

Harness pattern mirrors tests/test_recorder_orchestrator.py —
inject MagicMock for audio_capture, seed sidecar + state machine,
call stop(), assert on the loaded sidecar.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from recap.artifacts import (
    RecordingMetadata,
    load_recording_metadata,
    write_recording_metadata,
)
from recap.daemon.recorder.recorder import Recorder


def _make_recorder_ready_to_stop(
    tmp_path,
    *,
    initial_participants: list[str] | None = None,
    audio_warnings: list[str] | None = None,
) -> tuple[Recorder, MagicMock]:
    """Build a Recorder with a fake audio_capture in RECORDING state,
    ready for stop(). Returns (recorder, fake_capture)."""
    recorder = Recorder(recordings_path=tmp_path)

    fake_capture = MagicMock()
    fake_capture._audio_warnings = list(audio_warnings or [])
    fake_capture._system_audio_devices_seen = []
    fake_capture.stop = MagicMock()

    audio_path = tmp_path / "test.flac"
    audio_path.touch()
    initial_metadata = RecordingMetadata(
        org="testorg",
        note_path="",
        title="Test",
        date="2026-04-23",
        participants=list(initial_participants or []),
        platform="manual",
    )
    write_recording_metadata(audio_path, initial_metadata)

    recorder._audio_capture = fake_capture
    recorder._current_path = audio_path
    recorder._current_metadata = initial_metadata
    recorder.state_machine.detected("testorg")
    recorder.state_machine.start_recording("testorg")

    return recorder, fake_capture


@pytest.mark.asyncio
async def test_on_before_finalize_called_during_stop(tmp_path):
    recorder, _ = _make_recorder_ready_to_stop(tmp_path)
    called: list[str] = []

    def finalizer() -> list[str]:
        called.append("before")
        return []

    recorder.on_before_finalize = finalizer
    await recorder.stop()
    assert called == ["before"]


@pytest.mark.asyncio
async def test_on_after_stop_called_after_before_finalize(tmp_path):
    recorder, _ = _make_recorder_ready_to_stop(tmp_path)
    order: list[str] = []
    recorder.on_before_finalize = lambda: (order.append("before"), [])[1]
    recorder.on_after_stop = lambda: order.append("after")
    await recorder.stop()
    assert order == ["before", "after"]


@pytest.mark.asyncio
async def test_finalize_raising_does_not_abort_stop(tmp_path, caplog):
    recorder, _ = _make_recorder_ready_to_stop(tmp_path)

    def boom() -> list[str]:
        raise RuntimeError("finalize boom")

    after_called: list[int] = []
    recorder.on_before_finalize = boom
    recorder.on_after_stop = lambda: after_called.append(1)

    path = await recorder.stop()
    assert path is not None  # stop completed
    assert after_called == [1]
    assert "Participant finalizer failed" in caplog.text


@pytest.mark.asyncio
async def test_after_stop_raising_does_not_abort_stop(tmp_path, caplog):
    recorder, _ = _make_recorder_ready_to_stop(tmp_path)

    def boom() -> None:
        raise RuntimeError("after boom")

    recorder.on_after_stop = boom
    path = await recorder.stop()
    assert path is not None
    assert "on_after_stop hook failed" in caplog.text


@pytest.mark.asyncio
async def test_finalize_empty_list_does_not_rewrite(tmp_path):
    """Empty finalize output with no audio warnings → no rewrite.
    Sidecar retains the initial (empty) participants."""
    recorder, _ = _make_recorder_ready_to_stop(
        tmp_path, initial_participants=[],
    )
    recorder.on_before_finalize = lambda: []
    await recorder.stop()

    loaded = load_recording_metadata(recorder._current_path or tmp_path / "test.flac")
    # If no rewrite happens, the sidecar still has the initial empty list.
    assert loaded is not None
    assert loaded.participants == []


@pytest.mark.asyncio
async def test_finalize_same_as_initial_does_not_rewrite(tmp_path):
    """Finalized list identical to initial → no rewrite. Teams one-shot
    path relies on this to avoid redundant sidecar writes."""
    initial = ["Alice", "Bob"]
    recorder, _ = _make_recorder_ready_to_stop(
        tmp_path, initial_participants=initial,
    )
    recorder.on_before_finalize = lambda: list(initial)
    await recorder.stop()

    loaded = load_recording_metadata(tmp_path / "test.flac")
    assert loaded is not None
    assert loaded.participants == initial


@pytest.mark.asyncio
async def test_finalize_new_list_rewrites_sidecar(tmp_path):
    """Finalized list differs from initial → sidecar rewritten with new list."""
    recorder, _ = _make_recorder_ready_to_stop(
        tmp_path, initial_participants=[],
    )
    recorder.on_before_finalize = lambda: ["Alice", "Bob"]
    await recorder.stop()

    loaded = load_recording_metadata(tmp_path / "test.flac")
    assert loaded is not None
    assert loaded.participants == ["Alice", "Bob"]


@pytest.mark.asyncio
async def test_audio_warnings_and_participants_single_rewrite(tmp_path):
    """Both audio_warnings AND new participants → single combined rewrite."""
    recorder, fake_capture = _make_recorder_ready_to_stop(
        tmp_path,
        initial_participants=[],
        audio_warnings=["test_warning"],
    )
    recorder.on_before_finalize = lambda: ["Alice"]
    await recorder.stop()

    loaded = load_recording_metadata(tmp_path / "test.flac")
    assert loaded is not None
    assert loaded.participants == ["Alice"]
    assert "test_warning" in loaded.audio_warnings


@pytest.mark.asyncio
async def test_no_hooks_registered_leaves_initial_behavior_intact(tmp_path):
    """No hooks → stop() behaves exactly as pre-#29 (audio_warnings path only)."""
    recorder, _ = _make_recorder_ready_to_stop(
        tmp_path,
        initial_participants=["Pre29"],
        audio_warnings=["legacy_warning"],
    )
    # on_before_finalize and on_after_stop both None.
    await recorder.stop()

    loaded = load_recording_metadata(tmp_path / "test.flac")
    assert loaded is not None
    assert loaded.participants == ["Pre29"]
    assert "legacy_warning" in loaded.audio_warnings
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_recorder_finalize.py -v
```

Expected: tests fail on `AttributeError: 'Recorder' object has no attribute 'on_before_finalize'` (or fixture errors depending on harness).

**Step 3: Implement in `Recorder.__init__`**

Edit `recap/daemon/recorder/recorder.py`. Find `__init__` and add near the end of initialization (before the `# Monitoring tasks` section or similar):

```python
# #29: roster finalization hooks.
# on_before_finalize is invoked inside every stop() path before the
# sidecar rewrite decision. Detector uses this to merge the accumulated
# ParticipantRoster into metadata.participants.
# on_after_stop is invoked at end of stop() regardless of rewrite
# outcome; detector uses it to clear session state.
# Hooks persist across sessions (harmless) and are cleared only when
# the next begin-session overwrites them.
self.on_before_finalize: Callable[[], list[str]] | None = None
self.on_after_stop: Callable[[], None] | None = None
```

Ensure `Callable` is imported: `from typing import Callable` (if not already).

**Step 4: Implement in `Recorder.stop()`**

Replace the existing sidecar-rewrite block at [recorder.py:288-301](recap/daemon/recorder/recorder.py:288) with:

```python
# #29: call finalizer before deciding whether to rewrite. Empty or
# unchanged finalized lists do not trigger rewrite; audio warnings
# still can.
finalized_participants: list[str] | None = None
if self.on_before_finalize is not None:
    try:
        finalized_participants = self.on_before_finalize()
    except Exception:
        logger.warning("Participant finalizer failed", exc_info=True)

should_rewrite_for_participants = (
    finalized_participants is not None
    and self._current_metadata is not None
    and finalized_participants != self._current_metadata.participants
)

if (
    path is not None
    and self._current_metadata is not None
    and (audio_warnings or devices_seen or should_rewrite_for_participants)
):
    try:
        self._current_metadata.audio_warnings = audio_warnings
        self._current_metadata.system_audio_devices_seen = devices_seen
        if should_rewrite_for_participants:
            self._current_metadata.participants = finalized_participants
        write_recording_metadata(path, self._current_metadata)
    except OSError:
        logger.warning(
            "Failed to persist sidecar for %s", path, exc_info=True,
        )
```

Then AFTER the `# Stop streaming and merge results` block (around line 304) but BEFORE `# Reset silence detector`, insert:

```python
# #29: after_stop hook fires once, regardless of rewrite outcome.
# Detector uses this to clear ParticipantRoster session state on
# every stop path (API, silence, duration, fatal, extension).
if self.on_after_stop is not None:
    try:
        self.on_after_stop()
    except Exception:
        logger.warning("on_after_stop hook failed", exc_info=True)
```

**Step 5: Run tests**

```bash
pytest tests/test_recorder_finalize.py tests/test_recorder.py -v
```

Expected: new tests pass, existing recorder tests still pass (no regression).

**Step 6: Commit**

```bash
git add recap/daemon/recorder/recorder.py tests/test_recorder_finalize.py
git commit -m "feat(#29): Recorder on_before_finalize + on_after_stop hooks"
```

---

## Task 4: MeetingDetector session lifecycle

**Files:**
- Modify: `recap/daemon/recorder/detector.py` (add methods + attributes)
- Modify: `tests/test_detector.py` (add session lifecycle tests)

**Step 1: Write failing tests**

Add to `tests/test_detector.py`:

```python
class TestRosterSessionLifecycle:
    """Session begin/end contract for the ParticipantRoster."""

    def test_begin_creates_fresh_roster(self, detector_fixture):
        detector_fixture._begin_roster_session()
        assert detector_fixture._active_roster is not None
        assert detector_fixture._active_roster.current() == []

    def test_begin_seeds_from_initial_names(self, detector_fixture):
        detector_fixture._begin_roster_session(
            initial_names=["Alice", "Bob"],
            initial_source="teams_uia_detection",
        )
        assert detector_fixture._active_roster.current() == ["Alice", "Bob"]

    def test_begin_registers_both_recorder_hooks(self, detector_fixture):
        detector_fixture._begin_roster_session()
        assert detector_fixture._recorder.on_before_finalize is not None
        assert detector_fixture._recorder.on_after_stop is not None

    def test_begin_stores_tab_id(self, detector_fixture):
        detector_fixture._begin_roster_session(tab_id=42)
        assert detector_fixture._extension_recording_tab_id == 42

    def test_end_clears_all_session_state(self, detector_fixture):
        detector_fixture._begin_roster_session(tab_id=42)
        detector_fixture._polls_since_roster_refresh = 7
        detector_fixture._end_roster_session()
        assert detector_fixture._active_roster is None
        assert detector_fixture._extension_recording_tab_id is None
        assert detector_fixture._polls_since_roster_refresh == 0

    @pytest.mark.asyncio
    async def test_end_fires_via_on_after_stop_hook(self, detector_with_recorder):
        detector_with_recorder._begin_roster_session(tab_id=5)
        # Simulate a stop path via recorder directly.
        await detector_with_recorder._recorder.stop()
        assert detector_with_recorder._active_roster is None
        assert detector_with_recorder._extension_recording_tab_id is None
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_detector.py::TestRosterSessionLifecycle -v
```

Expected: `AttributeError: 'MeetingDetector' has no attribute '_begin_roster_session'`.

**Step 3: Implement on `MeetingDetector`**

Edit `recap/daemon/recorder/detector.py`.

Add imports at the top:
```python
from collections.abc import Sequence
from datetime import datetime

from recap.daemon.recorder.roster import ParticipantRoster
```

In `MeetingDetector.__init__`, add near the existing `_extension_recording_tab_id` initialization:
```python
# #29: roster accumulator for the currently-active recording. None
# when not recording. Set by _begin_roster_session() AFTER
# recorder.start() succeeds, cleared by _end_roster_session().
self._active_roster: ParticipantRoster | None = None
self._polls_since_roster_refresh: int = 0
# Captured at browser-path start so periodic refreshes can tag
# the merge with "browser_dom_<platform>".
self._current_browser_platform: str | None = None
```

Add new methods (place them near the existing state-management methods, e.g. after `mark_active_recording`):

```python
def _begin_roster_session(
    self,
    initial_names: Sequence[str] = (),
    initial_source: str | None = None,
    tab_id: int | None = None,
    browser_platform: str | None = None,
) -> None:
    """Arm a fresh roster and register stop hooks.

    MUST be called AFTER recorder.start() succeeds so a failed start
    cannot leak detector session state. Seeds the roster when the
    caller has a one-shot extraction (e.g. Teams UIA at detection),
    so finalize() is idempotent when no later merges happen.
    """
    roster = ParticipantRoster()
    if initial_names and initial_source:
        roster.merge(
            initial_source,
            list(initial_names),
            datetime.now().astimezone(),
        )
    self._active_roster = roster
    self._extension_recording_tab_id = tab_id
    self._current_browser_platform = browser_platform
    self._polls_since_roster_refresh = 0
    self._recorder.on_before_finalize = roster.finalize
    self._recorder.on_after_stop = self._end_roster_session

def _end_roster_session(self) -> None:
    """Clear detector-owned session state. Registered as
    Recorder.on_after_stop so it fires on every stop path — API,
    silence, duration, fatal, extension."""
    self._active_roster = None
    self._extension_recording_tab_id = None
    self._current_browser_platform = None
    self._polls_since_roster_refresh = 0
```

**Step 4: Run tests**

```bash
pytest tests/test_detector.py::TestRosterSessionLifecycle -v
```

Expected: 6 passing.

**Step 5: Commit**

```bash
git add recap/daemon/recorder/detector.py tests/test_detector.py
git commit -m "feat(#29): MeetingDetector _begin_roster_session / _end_roster_session"
```

---

## Task 5: Route Teams one-shot + Zoom start sites through roster

**Files:**
- Modify: `recap/daemon/recorder/detector.py` (four `recorder.start()` call sites)
- Modify: `tests/test_detector.py` (wire-up assertions)

**Step 1: Write failing tests**

Add to `tests/test_detector.py`:

```python
class TestStartPathsUseRoster:
    @pytest.mark.asyncio
    async def test_auto_record_path_primes_roster_with_enriched_participants(
        self, detector_fixture, monkeypatch,
    ):
        # Mock enrich_meeting_metadata to return Teams participants.
        monkeypatch.setattr(
            "recap.daemon.recorder.detector.enrich_meeting_metadata",
            lambda hwnd, title, platform, contacts: {
                "title": title, "platform": platform,
                "participants": ["Alice", "Bob"],
            },
        )
        # Simulate detection of a Teams meeting and run one poll.
        # (Harness-specific — follow existing test_detector.py pattern.)
        await detector_fixture._run_single_poll_with_meeting(
            hwnd=100, platform="teams", title="Standup | Microsoft Teams",
        )
        assert detector_fixture._active_roster is not None
        assert detector_fixture._active_roster.current() == ["Alice", "Bob"]

    @pytest.mark.asyncio
    async def test_initial_metadata_participants_match_enriched_for_teams(
        self, detector_fixture, monkeypatch,
    ):
        monkeypatch.setattr(
            "recap.daemon.recorder.detector.enrich_meeting_metadata",
            lambda *a, **kw: {
                "title": "x", "platform": "teams",
                "participants": ["Alice"],
            },
        )
        await detector_fixture._run_single_poll_with_meeting(
            hwnd=100, platform="teams", title="x",
        )
        metadata = detector_fixture._recorder._current_metadata
        assert metadata.participants == ["Alice"]

    @pytest.mark.asyncio
    async def test_zoom_path_initial_metadata_empty(
        self, detector_fixture, monkeypatch,
    ):
        monkeypatch.setattr(
            "recap.daemon.recorder.detector.enrich_meeting_metadata",
            lambda *a, **kw: {
                "title": "Zoom Meeting", "platform": "zoom",
                "participants": [],
            },
        )
        await detector_fixture._run_single_poll_with_meeting(
            hwnd=200, platform="zoom", title="Zoom Meeting",
        )
        metadata = detector_fixture._recorder._current_metadata
        assert metadata.participants == []

    @pytest.mark.asyncio
    async def test_begin_roster_session_only_after_successful_start(
        self, detector_fixture, monkeypatch,
    ):
        # Force recorder.start() to raise.
        async def boom(*a, **kw): raise RuntimeError("start failed")
        monkeypatch.setattr(detector_fixture._recorder, "start", boom)
        try:
            await detector_fixture._run_single_poll_with_meeting(
                hwnd=300, platform="zoom", title="Zoom Meeting",
            )
        except RuntimeError:
            pass
        # Start failure → no session state leaked.
        assert detector_fixture._active_roster is None
        assert detector_fixture._extension_recording_tab_id is None

    @pytest.mark.asyncio
    async def test_browser_path_primes_tab_id_and_browser_platform(
        self, detector_with_recorder,
    ):
        await detector_with_recorder.handle_extension_meeting_detected(
            platform="google_meet",
            url="https://meet.google.com/abc-defg-hij",
            title="Quick Call",
            tab_id=77,
        )
        assert detector_with_recorder._extension_recording_tab_id == 77
        assert detector_with_recorder._current_browser_platform == "google_meet"
        assert detector_with_recorder._active_roster is not None
```

**Step 2: Run tests, expect failures**

```bash
pytest tests/test_detector.py::TestStartPathsUseRoster -v
```

**Step 3: Modify `detector.py` — armed detection path**

Around [detector.py:389](recap/daemon/recorder/detector.py:389), the armed-event path. Locate:

```python
await self._recorder.start(org, metadata=metadata, detected=True)
self._recording_hwnd = meeting.hwnd
self._armed_event = None  # consumed
```

Change to:

```python
await self._recorder.start(org, metadata=metadata, detected=True)
self._recording_hwnd = meeting.hwnd
initial_source = (
    f"{meeting.platform}_uia_detection"
    if enriched.get("participants")
    else None
)
self._begin_roster_session(
    initial_names=enriched.get("participants", ()),
    initial_source=initial_source,
)
self._armed_event = None  # consumed
```

**Step 4: Modify `detector.py` — auto-record path**

Around [detector.py:399](recap/daemon/recorder/detector.py:399):

```python
if behavior == "auto-record" and not self._recorder.is_recording:
    org = self.get_default_org(meeting.platform)
    metadata = self._recording_metadata_from_enriched(org, enriched)
    logger.info("Auto-recording %s meeting (org=%s)", meeting.platform, org)
    await self._recorder.start(org, metadata=metadata, detected=True)
    self._recording_hwnd = meeting.hwnd
```

Append after `self._recording_hwnd = meeting.hwnd`:

```python
    initial_source = (
        f"{meeting.platform}_uia_detection"
        if enriched.get("participants")
        else None
    )
    self._begin_roster_session(
        initial_names=enriched.get("participants", ()),
        initial_source=initial_source,
    )
```

**Step 5: Modify `detector.py` — browser extension path**

In `handle_extension_meeting_detected`, around [detector.py:310](recap/daemon/recorder/detector.py:310). After:

```python
await self._recorder.start(org, metadata=metadata, detected=True)
self._extension_recording_tab_id = tab_id
```

Replace with:
```python
await self._recorder.start(org, metadata=metadata, detected=True)
self._begin_roster_session(
    tab_id=tab_id,
    browser_platform=platform,
)
```

(The `_begin_roster_session` call sets `_extension_recording_tab_id` itself — remove the inline assignment.)

**Step 6: Modify `detector.py` — Signal prompt acceptance path**

Find where the Signal popup callback starts recording (look for `mark_active_recording` or similar — search for "_on_signal_detected" usage). After the recorder.start() call succeeds, add:

```python
self._begin_roster_session()  # empty roster — Signal has no participants
```

If Signal's accept path lives outside detector.py (e.g. in a separate signal_popup module), ensure it calls back into detector to begin the session. If not straightforward, document the gap and skip — Signal's known non-goal is empty participants, so a missing roster session results in no finalization call, which is the same as an empty-roster finalization.

**Step 7: Remove redundant `_extension_recording_tab_id` clear**

Find [detector.py:327](recap/daemon/recorder/detector.py:327) in `handle_extension_meeting_ended`:

```python
await self._recorder.stop()
self._extension_recording_tab_id = None
```

Remove the explicit clear (now handled by `_end_roster_session` via `on_after_stop`):

```python
await self._recorder.stop()
# _extension_recording_tab_id cleared by _end_roster_session via Recorder.on_after_stop.
```

**Step 8: Run tests**

```bash
pytest tests/test_detector.py -v
```

Expected: new tests pass + existing detector tests still pass.

**Step 9: Commit**

```bash
git add recap/daemon/recorder/detector.py tests/test_detector.py
git commit -m "feat(#29): route all start paths through ParticipantRoster"
```

---

## Task 6: Zoom UIA periodic refresh in poll loop

**Files:**
- Modify: `recap/daemon/recorder/detector.py` (add `_refresh_roster_uia`, wire into `_poll_once`)
- Modify: `tests/test_detector.py`

**Step 1: Write failing tests**

Add to `tests/test_detector.py`:

```python
class TestZoomPeriodicRefresh:
    @pytest.mark.asyncio
    async def test_refresh_every_tenth_poll(self, recording_zoom_fixture, monkeypatch):
        """Poll interval is 3s; refresh cadence is every 10 polls (30s)."""
        call_count = 0
        def fake_extract(hwnd):
            nonlocal call_count
            call_count += 1
            return ["Alice"]
        monkeypatch.setattr(
            "recap.daemon.recorder.detector.extract_zoom_participants",
            fake_extract,
        )
        # Run 10 polls.
        for _ in range(10):
            await recording_zoom_fixture._poll_once()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_off_cycle_polls_skip_uia(self, recording_zoom_fixture, monkeypatch):
        called = []
        monkeypatch.setattr(
            "recap.daemon.recorder.detector.extract_zoom_participants",
            lambda hwnd: called.append(hwnd) or [],
        )
        for _ in range(9):
            await recording_zoom_fixture._poll_once()
        assert called == []

    @pytest.mark.asyncio
    async def test_refresh_merges_into_roster(self, recording_zoom_fixture, monkeypatch):
        monkeypatch.setattr(
            "recap.daemon.recorder.detector.extract_zoom_participants",
            lambda hwnd: ["Dana", "Eve"],
        )
        for _ in range(10):
            await recording_zoom_fixture._poll_once()
        assert "Dana" in recording_zoom_fixture._active_roster.current()
        assert "Eve" in recording_zoom_fixture._active_roster.current()

    @pytest.mark.asyncio
    async def test_refresh_skipped_when_not_recording(self, detector_fixture, monkeypatch):
        called = []
        monkeypatch.setattr(
            "recap.daemon.recorder.detector.extract_zoom_participants",
            lambda hwnd: called.append(hwnd),
        )
        # Not recording → no refresh regardless of poll count.
        for _ in range(20):
            await detector_fixture._poll_once()
        assert called == []

    @pytest.mark.asyncio
    async def test_refresh_skipped_for_non_zoom_platform(
        self, recording_teams_fixture, monkeypatch,
    ):
        """Teams deliberately skipped in v1 per issue non-goal."""
        called = []
        monkeypatch.setattr(
            "recap.daemon.recorder.detector.extract_zoom_participants",
            lambda hwnd: called.append(hwnd),
        )
        for _ in range(10):
            await recording_teams_fixture._poll_once()
        assert called == []
```

**Step 2: Run tests to verify failures**

**Step 3: Implement in `detector.py`**

Add at module level near the `_POLL_INTERVAL_SECONDS` constant:
```python
_ROSTER_REFRESH_POLLS = 10  # 10 polls × 3s base interval = 30s cadence
```

Add import at top:
```python
from recap.daemon.recorder.call_state import extract_zoom_participants
from recap.daemon.recorder.enrichment import match_known_contacts
```

Add method to `MeetingDetector`:

```python
async def _refresh_roster_uia(self) -> None:
    """Platform-dispatched UIA roster refresh during active recording.

    v1 scope: Zoom only. Teams deliberately skipped per issue non-goal
    'don't change Teams enrichment.' Browser-platform recordings don't
    have a daemon-side hwnd to walk — their refresh comes over HTTP.
    """
    if self._active_roster is None or self._recording_hwnd is None:
        return
    platform = self._recorder.state_machine.current_org  # not the right source
    # Look up the platform from the tracked meeting. If the hwnd-based
    # recording came from a windowed detection, _tracked_meetings has it.
    meeting = self._tracked_meetings.get(self._recording_hwnd)
    if meeting is None or meeting.platform != "zoom":
        return
    names = extract_zoom_participants(self._recording_hwnd)
    if not names:
        return
    matched = match_known_contacts(names, self._config.known_contacts)
    self._active_roster.merge(
        "zoom_uia_periodic",
        matched,
        datetime.now().astimezone(),
    )
```

**Note:** The `platform = self._recorder.state_machine.current_org` line is placeholder pseudocode — the correct lookup is from `_tracked_meetings[self._recording_hwnd].platform` as shown below it. Remove the placeholder line in actual implementation.

Wire into `_poll_once` AFTER the existing stop-monitoring + detection logic but BEFORE the end-of-poll prune. Insert:

```python
# --- Periodic roster refresh for hwnd-based recordings (Zoom v1) ---
if (
    self._recorder.is_recording
    and self._recording_hwnd is not None
    and self._active_roster is not None
):
    self._polls_since_roster_refresh += 1
    if self._polls_since_roster_refresh >= _ROSTER_REFRESH_POLLS:
        self._polls_since_roster_refresh = 0
        await self._refresh_roster_uia()
```

**Step 4: Run tests**

```bash
pytest tests/test_detector.py::TestZoomPeriodicRefresh -v
```

**Step 5: Commit**

```bash
git add recap/daemon/recorder/detector.py tests/test_detector.py
git commit -m "feat(#29): Zoom UIA periodic roster refresh every 30s"
```

---

## Task 7: `/api/meeting-participants-updated` endpoint

**Files:**
- Modify: `recap/daemon/server.py` (add handler + route registration)
- Modify: `recap/daemon/recorder/detector.py` (add `handle_extension_participants_updated`)
- Modify: `tests/test_daemon_server.py` (add endpoint tests)
- Modify: `tests/test_detector.py` (add handler tests)

**Step 1: Write failing tests for endpoint**

Add to `tests/test_daemon_server.py`:

```python
class TestParticipantsUpdatedEndpoint:
    async def test_missing_auth_returns_401(self, client):
        resp = await client.post(
            "/api/meeting-participants-updated",
            json={"tabId": 1, "participants": ["Alice"]},
        )
        assert resp.status == 401

    async def test_missing_tab_id_returns_400(self, authed_client):
        resp = await authed_client.post(
            "/api/meeting-participants-updated",
            json={"participants": ["Alice"]},
        )
        assert resp.status == 400

    async def test_missing_participants_returns_400(self, authed_client):
        resp = await authed_client.post(
            "/api/meeting-participants-updated",
            json={"tabId": 1},
        )
        assert resp.status == 400

    async def test_participants_not_a_list_returns_400(self, authed_client):
        resp = await authed_client.post(
            "/api/meeting-participants-updated",
            json={"tabId": 1, "participants": "Alice"},
        )
        assert resp.status == 400

    async def test_non_string_entries_filtered(self, authed_client, detector_with_active_recording):
        resp = await authed_client.post(
            "/api/meeting-participants-updated",
            json={"tabId": detector_with_active_recording._extension_recording_tab_id,
                  "participants": ["Alice", None, {"x": "y"}, 42, "Carol"]},
        )
        assert resp.status == 200
        assert (await resp.json())["status"] == "accepted"
        assert set(detector_with_active_recording._active_roster.current()) >= {"Alice", "Carol"}

    async def test_truncation_at_100(self, authed_client, detector_with_active_recording, caplog):
        big = [f"User{i}" for i in range(150)]
        resp = await authed_client.post(
            "/api/meeting-participants-updated",
            json={"tabId": detector_with_active_recording._extension_recording_tab_id,
                  "participants": big},
        )
        assert resp.status == 200
        assert len(detector_with_active_recording._active_roster.current()) == 100
        assert "truncated" in caplog.text.lower()

    async def test_no_active_recording_returns_ignored(self, authed_client, detector_idle):
        resp = await authed_client.post(
            "/api/meeting-participants-updated",
            json={"tabId": 42, "participants": ["Alice"]},
        )
        assert resp.status == 200
        assert (await resp.json())["status"] == "ignored"

    async def test_wrong_tab_id_returns_ignored(self, authed_client, detector_with_active_recording):
        wrong = detector_with_active_recording._extension_recording_tab_id + 999
        resp = await authed_client.post(
            "/api/meeting-participants-updated",
            json={"tabId": wrong, "participants": ["Alice"]},
        )
        assert resp.status == 200
        assert (await resp.json())["status"] == "ignored"

    async def test_valid_payload_accepted_and_merged(
        self, authed_client, detector_with_active_recording,
    ):
        tab_id = detector_with_active_recording._extension_recording_tab_id
        resp = await authed_client.post(
            "/api/meeting-participants-updated",
            json={"tabId": tab_id, "participants": ["Alice", "Bob"]},
        )
        assert resp.status == 200
        assert (await resp.json())["status"] == "accepted"
        assert detector_with_active_recording._active_roster.current() == ["Alice", "Bob"]
```

**Step 2: Run tests, expect failures**

**Step 3: Implement detector handler**

Add to `MeetingDetector`:

```python
async def handle_extension_participants_updated(
    self,
    *,
    tab_id: int | None,
    participants: list[str],
) -> bool:
    """Browser-extension hook for live participant roster updates.

    Returns True if merged. Silently returns False for:
      - no active recording
      - roster not armed
      - wrong tab id (stale post from closed meeting)
    """
    if (
        tab_id is None
        or tab_id != self._extension_recording_tab_id
        or self._active_roster is None
        or not self._recorder.is_recording
    ):
        return False
    platform = self._current_browser_platform or "unknown"
    source = f"browser_dom_{platform}"
    matched = match_known_contacts(participants, self._config.known_contacts)
    self._active_roster.merge(source, matched, datetime.now().astimezone())
    return True
```

**Step 4: Implement server endpoint**

Add to `recap/daemon/server.py` (alongside the existing `_meeting_detected_api` around line 983):

```python
async def _meeting_participants_updated_api(request: web.Request) -> web.Response:
    """Browser-extension hook for live participant roster refresh."""
    detector: MeetingDetector | None = request.app.get(_DETECTOR_KEY)
    if detector is None:
        return web.json_response({"error": "detector not available"}, status=503)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    if not isinstance(body, dict):
        return web.json_response(
            {"error": "request body must be a JSON object"}, status=400
        )

    tab_id = body.get("tabId")
    raw_list = body.get("participants")
    if tab_id is None:
        return web.json_response({"error": "missing required field: tabId"}, status=400)
    if not isinstance(raw_list, list):
        return web.json_response({"error": "participants must be a list"}, status=400)

    # Filter non-string entries rather than stringify — don't leak junk.
    participants = [p for p in raw_list if isinstance(p, str)]
    if len(participants) != len(raw_list):
        dropped = len(raw_list) - len(participants)
        logger.debug(
            "participants endpoint dropped %d non-string entries (tabId=%s)",
            dropped, tab_id,
        )

    # Defense against pathological DOM.
    if len(participants) > 100:
        logger.warning(
            "participants endpoint truncated %d-item payload to 100 (tabId=%s)",
            len(participants), tab_id,
        )
        participants = participants[:100]

    accepted = await detector.handle_extension_participants_updated(
        tab_id=int(tab_id) if isinstance(tab_id, int) else None,
        participants=participants,
    )
    return web.json_response({
        "status": "accepted" if accepted else "ignored",
    })
```

Register the route. Find the existing registration around [server.py:1151](recap/daemon/server.py:1151):
```python
app.router.add_post("/api/meeting-detected", _meeting_detected_api)
```

Add directly after:
```python
app.router.add_post("/api/meeting-participants-updated", _meeting_participants_updated_api)
```

**Step 5: Run tests**

```bash
pytest tests/test_daemon_server.py::TestParticipantsUpdatedEndpoint tests/test_detector.py -v
```

**Step 6: Commit**

```bash
git add recap/daemon/server.py recap/daemon/recorder/detector.py \
        tests/test_daemon_server.py tests/test_detector.py
git commit -m "feat(#29): /api/meeting-participants-updated endpoint"
```

---

## Task 8: Extension manifest — content scripts + host permissions

**Files:**
- Modify: `extension/manifest.json`

**Step 1: Edit manifest**

Read current contents first:
```bash
cat extension/manifest.json
```

Replace with:

```json
{
  "manifest_version": 3,
  "name": "Recap Meeting Detector",
  "version": "1.1.0",
  "description": "Detects browser-based meetings and notifies Recap for recording",
  "permissions": ["tabs", "storage", "alarms"],
  "host_permissions": [
    "http://localhost/*",
    "https://meet.google.com/*",
    "https://meeting.zoho.com/*",
    "https://meeting.zoho.eu/*",
    "https://meeting.zoho.in/*",
    "https://meeting.zoho.com.au/*",
    "https://meeting.tranzpay.io/*"
  ],
  "background": {
    "service_worker": "background.js"
  },
  "content_scripts": [
    {
      "matches": [
        "https://meet.google.com/*",
        "https://meeting.zoho.com/*",
        "https://meeting.zoho.eu/*",
        "https://meeting.zoho.in/*",
        "https://meeting.zoho.com.au/*",
        "https://meeting.tranzpay.io/*"
      ],
      "js": ["content.js"],
      "run_at": "document_idle"
    }
  ],
  "options_page": "options.html",
  "icons": {
    "16": "icons/icon-16.png",
    "48": "icons/icon-48.png",
    "128": "icons/icon-128.png"
  },
  "action": {
    "default_icon": {
      "16": "icons/icon-16.png",
      "48": "icons/icon-48.png"
    },
    "default_title": "Recap — Not connected"
  }
}
```

**Step 2: Commit**

```bash
git add extension/manifest.json
git commit -m "feat(#29): extension manifest — content_scripts + host_permissions for Meet/Zoho/tranzpay"
```

---

## Task 9: Extension `content.js` — DOM scrapers

**Files:**
- Replace contents: `extension/content.js`

**Step 1: Rewrite `content.js`**

```javascript
// content.js — scrapes participant rosters on request from background.
// Runs only on domains declared in manifest content_scripts.matches
// (Meet, Zoho regional variants, tranzpay).
//
// LIMITATION: Teams-via-browser (teams.microsoft.com) is a known v1 gap
// and is deliberately absent from content_scripts.matches.

function platformForHost(hostname) {
  if (hostname === "meet.google.com") return "google_meet";
  if (hostname.startsWith("meeting.zoho.") || hostname === "meeting.tranzpay.io") return "zoho_meet";
  return null;
}

function scrapeMeet() {
  // Meet's roster lives in the People side panel. Fallback selector
  // ladder — first non-empty result wins. Selectors drift; re-tune
  // from docs/handoffs/29-fixtures/ when they break.
  const selectors = [
    '[role="list"][aria-label*="participant" i] [role="listitem"] [data-self-name]',
    '[role="list"][aria-label*="participant" i] [role="listitem"] span',
    '[data-participant-id]',
    'div[jsname][data-participant-id] span',
  ];
  for (const sel of selectors) {
    const nodes = document.querySelectorAll(sel);
    if (nodes.length === 0) continue;
    const names = Array.from(nodes, n =>
      (n.getAttribute("data-self-name") || n.textContent || "").trim()
    ).filter(Boolean);
    if (names.length) return names;
  }
  return [];
}

function scrapeZoho() {
  // Zoho Meeting participant panel. Selectors TBD from fixture HTML.
  const selectors = [
    '[data-testid="participant-name"]',
    '.participant-list .participant-name',
    '.zm-participants-item__name',
  ];
  for (const sel of selectors) {
    const nodes = document.querySelectorAll(sel);
    if (nodes.length === 0) continue;
    const names = Array.from(nodes, n => (n.textContent || "").trim()).filter(Boolean);
    if (names.length) return names;
  }
  return [];
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "recap:get-roster") {
    const platform = platformForHost(window.location.hostname);
    let participants = [];
    try {
      if (platform === "google_meet") participants = scrapeMeet();
      else if (platform === "zoho_meet") participants = scrapeZoho();
    } catch (e) {
      console.warn("Recap content-script scrape failed:", e.message);
    }
    sendResponse({ platform, participants });
    return true;  // keep channel open for async sendResponse
  }
});
```

**Step 2: Commit**

```bash
git add extension/content.js
git commit -m "feat(#29): content.js DOM scrapers for Meet and Zoho"
```

---

## Task 10: Extension `background.js` — alarm + refresh relay

**Files:**
- Modify: `extension/background.js` (add alarm + `refreshAllRosters` function)

**Step 1: Edit `background.js`**

Read current contents:

```bash
cat extension/background.js
```

Find the existing alarm-registration block around line 141:

```javascript
chrome.alarms.create("recap-health-check", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "recap-health-check") void findRecapDaemon();
});
```

Replace with:

```javascript
chrome.alarms.create("recap-health-check", { periodInMinutes: 0.5 });
chrome.alarms.create("recap-roster-refresh", { periodInMinutes: 0.5 });

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === "recap-health-check") { void findRecapDaemon(); return; }
  if (alarm.name === "recap-roster-refresh") { void refreshAllRosters(); return; }
});

// #29: poll every active meeting tab's content script for its current
// participant roster and forward to the daemon.
// LIMITATION: only built-in hosts (Meet/Zoho/tranzpay) receive a
// content script, so user-added meeting patterns won't refresh here.
// Teams-via-browser deliberately excluded — v1 known gap.
async function refreshAllRosters() {
  for (const [tabId, tab] of activeMeetingTabs) {
    try {
      const response = await chrome.tabs.sendMessage(tabId, { type: "recap:get-roster" });
      if (!response) continue;
      const participants = (response.participants || []).slice(0, 50);
      if (participants.length === 0) continue;  // skip empty pushes
      await notifyRecap("/api/meeting-participants-updated", { tabId, participants });
    } catch (e) {
      // Expected on: Teams-via-browser tabs (no content script),
      // tabs closed mid-message, page reloads. Silent.
    }
  }
}
```

**Step 2: Commit**

```bash
git add extension/background.js
git commit -m "feat(#29): background.js alarm + refreshAllRosters relay"
```

---

## Task 11: Extension lockstep test

**Files:**
- Create: `tests/test_extension_lockstep.py`

**Step 1: Write tests**

```python
"""Static agreement between background.js default patterns,
options.js defaults, manifest content_scripts.matches, and
manifest host_permissions.

If any of these drift apart, a user-visible detection either won't
record (host_permissions miss) or will record but never refresh its
participant roster (content_scripts miss)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

EXTENSION_DIR = Path(__file__).resolve().parent.parent / "extension"

# The canonical built-in set. Updating this is the single-place
# mechanism for adding a host. Lockstep tests fail until background.js,
# options.js, and manifest.json agree.
BUILT_IN_HOSTS: set[str] = {
    "meet.google.com",
    "meeting.zoho.com",
    "meeting.zoho.eu",
    "meeting.zoho.in",
    "meeting.zoho.com.au",
    "meeting.tranzpay.io",
}

# Teams-via-browser is the explicit v1 gap — detected but not refreshed.
EXPECTED_V1_GAPS: set[str] = {"teams.microsoft.com"}


def _extract_default_patterns(js_path: Path, const_name: str) -> list[dict[str, str]]:
    """Parse a meeting-patterns constant from a JS file.

    The two files use different constant names:
      - extension/background.js uses DEFAULT_MEETING_PATTERNS
      - extension/options.js uses DEFAULT_PATTERNS

    Fragile by design — the regex breaks if the constant is restructured,
    which is exactly what these tests want to catch.
    """
    text = js_path.read_text()
    match = re.search(
        rf"{re.escape(const_name)}\s*=\s*\[(.*?)\];",
        text, re.DOTALL,
    )
    assert match, f"{const_name} not found in {js_path}"
    block = match.group(1)
    entries = re.findall(
        r"\{\s*pattern:\s*\"([^\"]+)\"\s*,\s*platform:\s*\"([^\"]+)\"",
        block,
    )
    return [{"pattern": p, "platform": pf} for p, pf in entries]


def test_background_defaults_cover_built_in_hosts():
    patterns = _extract_default_patterns(
        EXTENSION_DIR / "background.js", "DEFAULT_MEETING_PATTERNS",
    )
    hosts = {p["pattern"].split("/")[0] for p in patterns}
    missing = BUILT_IN_HOSTS - hosts
    assert not missing, f"BUILT_IN_HOSTS missing from background.js: {missing}"


def test_options_defaults_agree_with_background():
    bg = _extract_default_patterns(
        EXTENSION_DIR / "background.js", "DEFAULT_MEETING_PATTERNS",
    )
    opts = _extract_default_patterns(
        EXTENSION_DIR / "options.js", "DEFAULT_PATTERNS",
    )
    bg_set = {(p["pattern"], p["platform"]) for p in bg}
    opts_set = {(p["pattern"], p["platform"]) for p in opts}
    # options.js may include a subset (no requirePath/excludeExact extras)
    # but must agree on (pattern, platform) pairs for built-in hosts.
    bg_built_in = {pp for pp in bg_set if pp[0].split("/")[0] in BUILT_IN_HOSTS}
    opts_built_in = {pp for pp in opts_set if pp[0].split("/")[0] in BUILT_IN_HOSTS}
    assert bg_built_in == opts_built_in, (
        f"background and options disagree on built-in patterns: "
        f"bg={bg_built_in} opts={opts_built_in}"
    )


def test_manifest_content_scripts_cover_built_in_hosts():
    manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text())
    matches = {m for cs in manifest.get("content_scripts", []) for m in cs["matches"]}
    for host in BUILT_IN_HOSTS:
        assert any(host in m for m in matches), (
            f"built-in host {host} missing from manifest content_scripts.matches"
        )


def test_manifest_host_permissions_cover_content_script_matches():
    manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text())
    host_perms = set(manifest.get("host_permissions", []))
    cs_matches = {m for cs in manifest.get("content_scripts", []) for m in cs["matches"]}
    missing = cs_matches - host_perms
    assert not missing, (
        f"content_scripts.matches not covered by host_permissions: {missing}"
    )


def test_teams_via_browser_stays_a_known_gap():
    """teams.microsoft.com is in background.js detection patterns but
    deliberately NOT in BUILT_IN_HOSTS or content_scripts.matches.
    If someone adds it, they must update this test + design docs."""
    manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text())
    matches = {m for cs in manifest.get("content_scripts", []) for m in cs["matches"]}
    for gap in EXPECTED_V1_GAPS:
        # Gap should NOT be covered.
        assert not any(gap in m for m in matches), (
            f"{gap} is covered by content_scripts but documented as v1 gap; "
            f"update BUILT_IN_HOSTS + design docs intentionally."
        )
```

**Step 2: Run tests**

```bash
pytest tests/test_extension_lockstep.py -v
```

Expected: 5 passing (assuming Tasks 8–10 are complete).

**Step 3: Commit**

```bash
git add tests/test_extension_lockstep.py
git commit -m "test(#29): extension lockstep — BUILT_IN_HOSTS vs manifest/bg/options"
```

---

## Task 12: Integration E2E tests

**Files:**
- Create: `tests/test_unscheduled_enrichment_integration.py` (or extend `tests/test_unscheduled_integration.py` from #27)

**Step 1: Inspect existing integration-test harness**

```bash
cat tests/test_unscheduled_integration.py | head -40
```

Use that as the template. The goal is a detector+recorder+mock-enrichment harness that drives a full meeting lifecycle and asserts on the final sidecar.

**Step 2: Write four scenarios**

Create `tests/test_unscheduled_enrichment_integration.py`:

```python
"""End-to-end scenarios for #29: spontaneous-meeting participant
enrichment across Teams (regression), Zoom (UIA), Meet (DOM via endpoint),
and Zoho/tranzpay (DOM via endpoint).

Assertions focus on the final sidecar carrying participants. The
harness mocks win32gui/UIA/HTTP so no external infrastructure is needed.
"""
from __future__ import annotations

# Implementer note: follow the harness pattern from
# tests/test_unscheduled_integration.py. Key mock points:
#   - detection._enumerate_windows → yields (hwnd, title)
#   - call_state.is_call_active → True
#   - call_state.extract_teams_participants / extract_zoom_participants
#   - recorder._audio_capture minimal stub
#   - vault writer captured via a tmp_path

import pytest
from datetime import datetime


@pytest.mark.asyncio
async def test_spontaneous_zoom_populates_participants_from_uia(
    unscheduled_harness, monkeypatch,
):
    monkeypatch.setattr(
        "recap.daemon.recorder.call_state.extract_zoom_participants",
        lambda hwnd: ["Dana", "Eve"],
    )
    harness = unscheduled_harness(platform="zoom", title="Zoom Meeting")
    await harness.run_detection()
    # Run 10+ polls to trigger a refresh cycle.
    for _ in range(10):
        await harness.tick()
    await harness.stop_recording()
    sidecar = harness.read_final_sidecar()
    assert "Dana" in sidecar.participants
    assert "Eve" in sidecar.participants


@pytest.mark.asyncio
async def test_spontaneous_meet_populates_via_endpoint(
    unscheduled_harness, authed_client,
):
    harness = unscheduled_harness(platform="browser", url="https://meet.google.com/abc")
    tab_id = await harness.start_browser_recording(platform="google_meet", tab_id=55)
    resp = await authed_client.post(
        "/api/meeting-participants-updated",
        json={"tabId": tab_id, "participants": ["Fiona", "Greg"]},
    )
    assert resp.status == 200
    await harness.stop_recording()
    sidecar = harness.read_final_sidecar()
    assert "Fiona" in sidecar.participants
    assert "Greg" in sidecar.participants


@pytest.mark.asyncio
async def test_spontaneous_zoho_tranzpay_populates_via_endpoint(
    unscheduled_harness, authed_client,
):
    harness = unscheduled_harness(
        platform="browser", url="https://meeting.tranzpay.io/room/xyz",
    )
    tab_id = await harness.start_browser_recording(platform="zoho_meet", tab_id=77)
    await authed_client.post(
        "/api/meeting-participants-updated",
        json={"tabId": tab_id, "participants": ["Henry", "Ivy"]},
    )
    await harness.stop_recording()
    sidecar = harness.read_final_sidecar()
    assert "Henry" in sidecar.participants
    assert "Ivy" in sidecar.participants


@pytest.mark.asyncio
async def test_teams_no_regression_sidecar_carries_initial_names(
    unscheduled_harness, monkeypatch,
):
    """Teams one-shot populates initial metadata AND roster. Finalize
    returns same list → no rewrite → initial sidecar preserved."""
    monkeypatch.setattr(
        "recap.daemon.recorder.call_state.extract_teams_participants",
        lambda hwnd: ["Alice", "Bob"],
    )
    harness = unscheduled_harness(platform="teams", title="Standup | Microsoft Teams")
    await harness.run_detection()
    initial_sidecar = harness.read_current_sidecar()
    assert initial_sidecar.participants == ["Alice", "Bob"]
    for _ in range(15):
        await harness.tick()  # Teams deliberately skipped in periodic refresh
    await harness.stop_recording()
    final_sidecar = harness.read_final_sidecar()
    assert final_sidecar.participants == ["Alice", "Bob"]
    # Verify no unnecessary rewrite happened
    assert harness.sidecar_write_count == 1  # only the initial write
```

**Step 3: Run tests**

```bash
pytest tests/test_unscheduled_enrichment_integration.py -v
```

**Step 4: Commit**

```bash
git add tests/test_unscheduled_enrichment_integration.py
git commit -m "test(#29): integration E2E — Zoom/Meet/Zoho/Teams scenarios"
```

---

## Task 13: MANIFEST.md + release notes + handoff acceptance checklist

**Files:**
- Modify: `MANIFEST.md` (add #29 Key Relationships bullet)
- Create: `docs/handoffs/2026-04-23-29-acceptance.md`

**Step 1: Update MANIFEST.md**

Read current state:
```bash
cat MANIFEST.md
```

Find the Key Relationships section. Add a bullet:

```markdown
- **Participant enrichment triad (#29)** — `MeetingDetector` owns
  `ParticipantRoster` for each active recording; fed by Teams UIA at
  detection (one-shot, seeds initial sidecar), Zoom UIA every 30s from
  the poll loop, and browser DOM via `/api/meeting-participants-updated`.
  Finalized into `RecordingMetadata.participants` via
  `Recorder.on_before_finalize` hook that fires on every stop path
  (API, silence, duration, fatal, extension). Browser enrichment scoped
  to built-in hosts only; `tests/test_extension_lockstep.py` prevents
  manifest/background/options drift.
```

**Step 2: Write acceptance checklist**

Create `docs/handoffs/2026-04-23-29-acceptance.md`:

```markdown
# Issue #29 Manual Acceptance Checklist

This covers scenarios that unit/integration tests can't exercise:
real UIA trees, real browser DOM, and the extension permission reload
flow. Run each scenario against a built daemon + reloaded extension.

## Preflight

- [ ] `pytest` passes (`pytest tests/test_roster.py tests/test_recorder_finalize.py tests/test_detector.py tests/test_daemon_server.py tests/test_extension_lockstep.py tests/test_unscheduled_enrichment_integration.py -v`)
- [ ] Extension version bumped to `1.1.0` in `manifest.json`

## Extension reload

- [ ] Load `extension/` as unpacked in Chrome.
- [ ] Chrome prompts for new host permissions: `meet.google.com`,
      `meeting.zoho.*`, `meeting.tranzpay.io`.
- [ ] User accepts; extension badge shows `ON` (connected state).

## Core scenarios

1. **Spontaneous Zoom call with 2+ participants**
   - [ ] Open Zoom, start an instant meeting.
   - [ ] Invite a second account/device, have it join.
   - [ ] Daemon auto-records (auto-record behavior for Zoom).
   - [ ] Wait ~45 seconds (ensure at least one 30s refresh cycle).
   - [ ] Stop the meeting.
   - [ ] Open the resulting note; confirm frontmatter `participants`
         contains both display names.
   - [ ] Daemon log shows `roster.merge source=zoom_uia_periodic` entries.

2. **Spontaneous Google Meet call with participants panel open**
   - [ ] Navigate to `https://meet.google.com/new`, create a call.
   - [ ] Click "People" to open the participants panel.
   - [ ] Have a second account join.
   - [ ] Daemon starts a recording (extension-triggered path).
   - [ ] Wait ~45 seconds.
   - [ ] End the call (or close the tab).
   - [ ] Confirm frontmatter `participants` contains both names.

3. **Spontaneous Zoho / tranzpay call**
   - [ ] Start a call on `meeting.zoho.com` or `meeting.tranzpay.io`.
   - [ ] Second participant joins.
   - [ ] Daemon records; wait for a refresh cycle.
   - [ ] Stop; confirm frontmatter has both names.

4. **Teams native client regression**
   - [ ] Start a Teams call in the native client.
   - [ ] Confirm detection + recording as today.
   - [ ] Verify frontmatter `participants` still populated (Teams UIA
         one-shot path, should match pre-#29 behavior).
   - [ ] Sidecar should have been written exactly once (no redundant
         rewrite from finalize).

5. **Teams-via-browser documented gap**
   - [ ] Join a Teams meeting via `teams.microsoft.com` in Chrome.
   - [ ] Confirm recording starts (extension detection path still fires).
   - [ ] Confirm frontmatter `participants` is empty — this is the
         documented v1 gap.
   - [ ] No errors in daemon or extension logs.

## Edge cases

6. **Meet with participants panel NEVER opened**
   - [ ] Join a Meet call; do NOT click "People".
   - [ ] Confirm recording runs, completes.
   - [ ] Confirm frontmatter `participants` is empty; no errors.
         (Documented limitation.)

7. **Browser tab closed mid-call**
   - [ ] Join a Meet call; record briefly.
   - [ ] Close the tab without ending the call cleanly.
   - [ ] Daemon detects tab closure, stops recording.
   - [ ] Next alarm tick silently skips the dead tab (no log noise).

8. **Late joiner in Meet appears within ~30s**
   - [ ] Start a Meet call with yourself.
   - [ ] After 45 seconds, have a second account join.
   - [ ] Within the next 30-second refresh tick, the late joiner appears
         in daemon logs (`roster.merge` entry).
   - [ ] Final frontmatter contains the late joiner.

9. **Zoom UIA periodic cadence**
   - [ ] During a Zoom recording, watch daemon debug logs.
   - [ ] Confirm `extract_zoom_participants` is called roughly every
         30 seconds, not every 3 seconds.

10. **Daemon restart mid-recording (crash simulation)**
    - [ ] Start a Zoom recording.
    - [ ] Let a few 30s cycles accumulate names.
    - [ ] Kill the daemon process (simulating a crash).
    - [ ] Inspect the sidecar: initial participants preserved (for
          Teams it's the UIA one-shot; for Zoom/browser it's empty).
    - [ ] In-memory roster is lost — expected degradation, not a bug.

11. **Roster filter rejection**
    - [ ] Post a payload with mixed valid/invalid entries to
          `/api/meeting-participants-updated` during an active recording:
          `{"tabId": <real>, "participants": ["Alice", null, 42, "Bob"]}`
    - [ ] Response is `200 accepted`.
    - [ ] Roster contains `Alice` and `Bob` only; daemon debug log
          records the two dropped entries.

## Sign-off

- [ ] All core scenarios pass on a real Zoom, Meet, Zoho/tranzpay,
      Teams native, Teams browser session.
- [ ] No new errors in daemon log beyond expected debug entries.
- [ ] Extension badge never drops to `offline` during refresh ticks.
- [ ] Ready for PR review.
```

**Step 3: Commit**

```bash
git add MANIFEST.md docs/handoffs/2026-04-23-29-acceptance.md
git commit -m "docs(#29): MANIFEST update + manual acceptance checklist"
```

---

## Task 14: Final verification

**Step 1: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass, no regressions.

**Step 2: Run linting if configured**

```bash
# Check for a ruff/black/mypy config
ls pyproject.toml .ruff.toml 2>/dev/null
# If ruff is configured:
ruff check recap/ tests/
```

**Step 3: Verify file coverage**

Confirm these files exist and are committed:

```bash
git log --name-only --oneline -14 | head -50
```

Expected to see (across the 13 commits):
- `recap/daemon/recorder/roster.py`
- `recap/daemon/recorder/call_state.py` (modified)
- `recap/daemon/recorder/recorder.py` (modified)
- `recap/daemon/recorder/detector.py` (modified)
- `recap/daemon/server.py` (modified)
- `extension/manifest.json`, `content.js`, `background.js`
- 7 test files
- `MANIFEST.md`, `docs/handoffs/2026-04-23-29-acceptance.md`

**Step 4: Manual smoke (optional, before PR)**

Run the acceptance checklist scenarios 1, 4 at minimum. Others can happen in PR review.

**Step 5: Hand off to review**

Use `superpowers:finishing-a-development-branch` to present: (1) merge locally, (2) push + PR, (3) keep as-is, (4) discard.

---

## Implementation notes

- **TDD throughout:** every task starts with a failing test and ends with a commit after green.
- **YAGNI:** no WS broadcast, no MutationObserver, no chrome.scripting dynamic registration.
- **Known v1 residual risks** are documented but not mitigated (Zoom UIA hang, DOM selector rot). See design doc Section 5.7.
- **Codex review is recommended between Tasks 3, 5, 7, and 12** — these have the highest potential for subtle regression (Recorder hook contract, Teams path funneling, endpoint contract, E2E assertions).
- **Do NOT rebuild `obsidian-recap/main.js`** — this issue doesn't touch the Obsidian plugin.

## References

- Design doc: [docs/plans/2026-04-23-29-non-teams-enrichment-design.md](docs/plans/2026-04-23-29-non-teams-enrichment-design.md)
- Issue: [GitHub #29](https://github.com/TimSimpsonJr/recap/issues/29)
- Related: #27 (unscheduled meeting plumbing, merged as #34), #28 (speaker correction, follows this), #30 (Teams detection, merged as #32)

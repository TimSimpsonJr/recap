# Phase 3: Runtime Foundation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Collapse `__main__.py` into a thin entry point behind a `Daemon` service class; retire `_loop_holder`/`_app_holder`; add an append-only `EventJournal`; make Signal popup truly async; kill `AudioCapture` monkey-patching; add extension bootstrap-token pairing; delete `autostart.py`; retire detector `_org_subfolder` hand-join (Phase 2 carryover).

**Architecture:** A single `Daemon` object owns `config`, `loop`, `app`, `recorder`, `detector`, `scheduler`, `event_journal`, `event_index`, `started_at`. Callbacks take a `Daemon` reference instead of closing over holder lists. The journal is the append-only log behind `/api/status` uptime/errors and the plugin's live notification history. Extension auth uses an explicit tray-initiated one-shot pairing window bound to loopback; no automatic bootstrap endpoint.

**Tech Stack:** Python 3.10+, aiohttp, asyncio, tkinter (for Signal popup via run_in_executor), existing `pystray`-based tray, `EventIndex` from Phase 2.

**Read before starting:**
- `docs/plans/2026-04-14-fix-everything-design.md` §0.4 (event journal schema), §0.5 (extension auth protocol), §Phase 3 (goals + acceptance criteria), §Final Integration Pass
- `docs/plans/2026-04-14-phase2-org-and-event-index.md` — Phase 2 is complete. `EventIndex` is singleton-injected via `__main__.py` today; Phase 3 moves ownership to `Daemon`. Do NOT break the unconditional-rebuild-on-start invariant (Codex lock-in).

**Baseline commit:** `f27fa2b` (Phase 2 final: cross-folder stale-heal closed). Test suite at 386.

---

## Conventions for every task

- Commit style: Conventional Commits (`feat:`, `refactor:`, `fix:`, `test:`, `chore:`, `docs:`).
- Never stage `uv.lock` or `docs/reviews/`.
- Run `uv run pytest -q` at the end of every task; a rename or signature change in one file can break imports in another.
- Prefer real filesystems via `tmp_path` / real `Daemon` fixtures over mocks. The one exception: network-level tests (Signal popup, OAuth callbacks) may mock at the framework boundary.
- Tests for new public modules live in files mirroring the module name (`tests/test_event_journal.py`, `tests/test_daemon_service.py`, `tests/test_pairing.py`, etc.).
- **Do not retouch Phase 2 code** unless the task explicitly targets it. `EventIndex`, `resolve_note_path`, `to_vault_relative`, `OrgConfig.resolve_subfolder`, `DaemonConfig.org_by_slug` are all frozen.
- When the `Daemon` class replaces a closure, migrate all call sites in the same task — do not leave half-migrated state.

---

## Task 1: `EventJournal` with append/rotate/tail API

**Context:** Single source of truth for daemon-side lifecycle events. Phase 3 consumers: real `/api/status` errors (Task 6), pairing lifecycle (Task 8), notifications (Task 11). Plugin reads this journal instead of hosting its own (per §0.4 contract — plugin becomes a thin renderer). Schema v1 per design doc §0.4.

**Files:**
- Create: `recap/daemon/events.py`
- Create: `tests/test_event_journal.py`

**Step 1: Write failing tests**

Create `tests/test_event_journal.py`:

```python
"""Tests for the daemon event journal (design §0.4)."""
from __future__ import annotations

import json
import pathlib
import threading

from recap.daemon.events import EventJournal


def _make_journal(tmp_path: pathlib.Path, **kwargs) -> EventJournal:
    return EventJournal(tmp_path / "events.jsonl", **kwargs)


class TestEventJournalAppend:
    def test_append_writes_one_line_per_entry(self, tmp_path):
        j = _make_journal(tmp_path)
        j.append("info", "startup", "Daemon started")
        j.append("warning", "silence_warning", "No audio for 5 minutes")
        lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        e0 = json.loads(lines[0])
        assert e0["level"] == "info"
        assert e0["event"] == "startup"
        assert e0["message"] == "Daemon started"
        assert "ts" in e0
        assert "payload" not in e0  # omitted when None

    def test_append_includes_payload_when_provided(self, tmp_path):
        j = _make_journal(tmp_path)
        j.append("error", "pipeline_failed", "boom", payload={"stage": "analyze"})
        line = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()[0]
        e = json.loads(line)
        assert e["payload"] == {"stage": "analyze"}

    def test_append_is_thread_safe(self, tmp_path):
        j = _make_journal(tmp_path)
        def writer(n):
            for i in range(50):
                j.append("info", "t", f"w{n}-{i}")
        threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 200
        # Each line must be valid JSON (no interleaving corruption)
        for line in lines:
            json.loads(line)


class TestEventJournalTail:
    def test_tail_returns_last_n_in_order(self, tmp_path):
        j = _make_journal(tmp_path)
        for i in range(5):
            j.append("info", "e", f"m{i}")
        entries = j.tail(limit=3)
        assert len(entries) == 3
        assert [e["message"] for e in entries] == ["m2", "m3", "m4"]

    def test_tail_filters_by_level(self, tmp_path):
        j = _make_journal(tmp_path)
        j.append("info", "a", "m-info")
        j.append("error", "b", "m-error-1")
        j.append("warning", "c", "m-warn")
        j.append("error", "d", "m-error-2")
        errors = j.tail(level="error", limit=10)
        assert [e["message"] for e in errors] == ["m-error-1", "m-error-2"]

    def test_tail_empty_file_returns_empty_list(self, tmp_path):
        j = _make_journal(tmp_path)
        assert j.tail(limit=10) == []

    def test_tail_ignores_corrupt_lines(self, tmp_path):
        j = _make_journal(tmp_path)
        j.append("info", "a", "ok")
        (tmp_path / "events.jsonl").open("a", encoding="utf-8").write("not json\n")
        j.append("info", "b", "ok-2")
        entries = j.tail(limit=10)
        assert [e["message"] for e in entries] == ["ok", "ok-2"]


class TestEventJournalRotation:
    def test_rotates_at_max_bytes(self, tmp_path):
        # Tiny threshold to trigger rotation reliably
        j = _make_journal(tmp_path, max_bytes=256)
        for i in range(20):
            j.append("info", "e", f"message-{i:03d}-{'x' * 20}")
        assert (tmp_path / "events.jsonl").exists()
        assert (tmp_path / "events.jsonl.1").exists()
        # Current file is below threshold after rotation
        assert (tmp_path / "events.jsonl").stat().st_size <= 256 * 2

    def test_rotation_keeps_one_backup(self, tmp_path):
        j = _make_journal(tmp_path, max_bytes=128)
        for i in range(40):
            j.append("info", "e", f"m{i}" + "x" * 30)
        # Only events.jsonl and events.jsonl.1 — no .2, .3
        assert (tmp_path / "events.jsonl").exists()
        assert (tmp_path / "events.jsonl.1").exists()
        assert not (tmp_path / "events.jsonl.2").exists()

    def test_prune_old_backups_deletes_stale(self, tmp_path):
        import os, time
        j = _make_journal(tmp_path, max_bytes=64)
        for i in range(30):
            j.append("info", "e", f"m{i}" + "x" * 10)
        backup = tmp_path / "events.jsonl.1"
        assert backup.exists()
        # Artificially age the backup by 31 days
        old = time.time() - 31 * 86400
        os.utime(backup, (old, old))
        j.prune_old_backups(max_age_days=30)
        assert not backup.exists()
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_event_journal.py -v`
Expected: FAIL — module does not exist.

**Step 3: Implement**

Create `recap/daemon/events.py`:

```python
"""Append-only daemon event journal (design doc §0.4).

Schema v1 line format (one per line):
  {"ts": "<RFC3339>", "level": "info|warning|error", "event": "<snake_case>",
   "message": "<human>", "payload": { ... optional }}

Rotation: when the active file exceeds ``max_bytes``, it is moved to
``<path>.1`` (one backup kept). Older backups (``.2``, ``.3``, ...) are
not created; ``prune_old_backups`` deletes ``.1`` if older than N days.
"""
from __future__ import annotations

import json
import logging
import pathlib
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB per §0.4
_VALID_LEVELS = {"info", "warning", "error"}


class EventJournal:
    """Thread-safe append-only JSON-lines journal with size-based rotation."""

    def __init__(
        self,
        path: pathlib.Path,
        *,
        max_bytes: int = _DEFAULT_MAX_BYTES,
    ) -> None:
        self._path = path
        self._backup = pathlib.Path(str(path) + ".1")
        self._max_bytes = max_bytes
        self._lock = threading.Lock()

    def append(
        self,
        level: str,
        event: str,
        message: str,
        *,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        if level not in _VALID_LEVELS:
            raise ValueError(f"invalid level {level!r}; expected one of {_VALID_LEVELS}")
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "level": level,
            "event": event,
            "message": message,
        }
        if payload is not None:
            entry["payload"] = payload
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed_locked(len(line.encode("utf-8")))
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line)

    def tail(self, *, level: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            if not self._path.exists():
                return []
            try:
                raw = self._path.read_text(encoding="utf-8")
            except OSError:
                return []
        out: list[dict[str, Any]] = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if level is not None and entry.get("level") != level:
                continue
            out.append(entry)
        return out[-limit:] if limit > 0 else out

    def prune_old_backups(self, *, max_age_days: int = 30) -> None:
        with self._lock:
            if not self._backup.exists():
                return
            age = time.time() - self._backup.stat().st_mtime
            if age > max_age_days * 86400:
                try:
                    self._backup.unlink()
                except OSError as exc:
                    logger.warning("Could not prune old event-journal backup: %s", exc)

    def _rotate_if_needed_locked(self, incoming_bytes: int) -> None:
        try:
            current = self._path.stat().st_size if self._path.exists() else 0
        except OSError:
            current = 0
        if current + incoming_bytes <= self._max_bytes:
            return
        # Rotate: current -> .1 (overwriting any existing .1)
        if self._backup.exists():
            try:
                self._backup.unlink()
            except OSError as exc:
                logger.warning("Could not remove stale journal backup: %s", exc)
        try:
            self._path.rename(self._backup)
        except OSError as exc:
            logger.warning("Could not rotate event journal: %s", exc)
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_event_journal.py -v`
Expected: PASS.

Run: `uv run pytest -q`
Expected: full suite still passes.

**Step 5: Commit**

```bash
git add recap/daemon/events.py tests/test_event_journal.py
git commit -m "feat: append-only EventJournal with rotation and filtered tail"
```

---

## Task 2: `Daemon` service class

**Context:** The orchestrating object for the daemon process. Owns `config`, `loop`, `app`, `event_journal`, `event_index`, `recorder`, `detector`, `scheduler`, `started_at`. Replaces the `_loop_holder`/`_app_holder` closure-bag pattern. Task 3 migrates `__main__.py` to construct and start a `Daemon`; Tasks 5-12 consume it.

**Files:**
- Create: `recap/daemon/service.py`
- Create: `tests/test_daemon_service.py`

**Step 1: Write failing tests**

```python
"""Tests for the Daemon service class."""
from __future__ import annotations

import asyncio
import pathlib
from datetime import datetime

import pytest

from recap.daemon.config import DaemonConfig, OrgConfig
from recap.daemon.service import Daemon


def _make_config(tmp_path: pathlib.Path) -> DaemonConfig:
    cfg = DaemonConfig.__new__(DaemonConfig)
    cfg.vault_path = tmp_path / "vault"
    cfg.vault_path.mkdir()
    cfg.recordings_path = tmp_path / "rec"
    cfg.recordings_path.mkdir()
    cfg._orgs = [OrgConfig(name="d", subfolder="Clients/D", default=True)]
    # Minimum surface the Daemon class needs. Extend with more fields once
    # Task 3 migrates __main__.py callers.
    return cfg


class TestDaemonConstruction:
    def test_constructs_with_config(self, tmp_path):
        cfg = _make_config(tmp_path)
        d = Daemon(cfg)
        assert d.config is cfg
        assert d.event_journal is not None
        assert d.event_index is not None
        assert d.started_at is None  # set by start()
        assert d.loop is None        # set by start()
        assert d.app is None         # set by start()

    def test_event_journal_points_at_vault_recap_dir(self, tmp_path):
        cfg = _make_config(tmp_path)
        d = Daemon(cfg)
        expected = cfg.vault_path / "_Recap" / ".recap" / "events.jsonl"
        assert d.event_journal_path == expected

    def test_event_index_points_at_vault_recap_dir(self, tmp_path):
        cfg = _make_config(tmp_path)
        d = Daemon(cfg)
        expected = cfg.vault_path / "_Recap" / ".recap" / "event-index.json"
        assert d.event_index_path == expected


class TestDaemonStart:
    def test_start_sets_started_at_and_rebuilds_index(self, tmp_path):
        cfg = _make_config(tmp_path)
        d = Daemon(cfg)
        # Simulate service startup (everything except the aiohttp server bring-up)
        d.start_services_only_for_test()
        assert isinstance(d.started_at, datetime)
        # Index file exists after unconditional rebuild (Codex lock-in from Phase 2)
        assert d.event_index_path.exists()

    def test_emit_event_writes_to_journal(self, tmp_path):
        cfg = _make_config(tmp_path)
        d = Daemon(cfg)
        d.start_services_only_for_test()
        d.emit_event("info", "test_event", "hello")
        entries = d.event_journal.tail(limit=10)
        assert any(e["event"] == "test_event" and e["message"] == "hello" for e in entries)


class TestDaemonLoopAccess:
    def test_run_in_loop_schedules_coroutine(self, tmp_path):
        cfg = _make_config(tmp_path)
        d = Daemon(cfg)
        d.start_services_only_for_test()
        # Give the Daemon a real loop (simulating post-start state)
        loop = asyncio.new_event_loop()
        d.loop = loop

        async def _coro():
            return 42

        try:
            future = d.run_in_loop(_coro())
            # run_in_loop returns a concurrent.futures.Future; drive the loop to complete it
            loop.run_until_complete(asyncio.wait_for(asyncio.wrap_future(future), timeout=1))
            assert future.result() == 42
        finally:
            loop.close()
            d.loop = None
```

**Step 2: Run to verify failure**

`uv run pytest tests/test_daemon_service.py -v` → FAIL (no module).

**Step 3: Implement**

Create `recap/daemon/service.py`:

```python
"""Daemon service object.

Replaces the ``_loop_holder`` / ``_app_holder`` closure-bag pattern with a
single ``Daemon`` that owns runtime state, loop access, services, and
lifecycle.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import pathlib
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from aiohttp import web

from recap.daemon.calendar.index import EventIndex
from recap.daemon.events import EventJournal

if TYPE_CHECKING:
    from recap.daemon.config import DaemonConfig

logger = logging.getLogger(__name__)


class Daemon:
    """Runtime container for the Recap daemon process.

    Owns: config, loop, app, event_journal, event_index, started_at. After
    Task 3 migration, also holds recorder, detector, scheduler.
    """

    def __init__(self, config: "DaemonConfig") -> None:
        self.config = config
        recap_dir = config.vault_path / "_Recap" / ".recap"
        self.event_journal_path = recap_dir / "events.jsonl"
        self.event_index_path = recap_dir / "event-index.json"
        self.event_journal = EventJournal(self.event_journal_path)
        self.event_index = EventIndex(self.event_index_path)

        # Runtime state (populated by start()):
        self.started_at: Optional[datetime] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.app: Optional[web.Application] = None

        # Subservices — populated after Task 3 migration from __main__.py:
        self.recorder: Any = None
        self.detector: Any = None
        self.scheduler: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_services_only_for_test(self) -> None:
        """Minimal start path for tests: journal rebuild + index rebuild.

        Real start() is invoked from __main__.py's main() and wires the
        aiohttp app, recorder, detector, scheduler. This test-only helper
        exists so Task 2 can validate the service object without bringing
        up the full aiohttp stack.
        """
        self.started_at = datetime.now(timezone.utc).astimezone()
        # Codex lock-in (Phase 2): unconditional rebuild every start.
        logger.info("Rebuilding EventIndex from vault (startup)")
        self.event_index.rebuild(self.config.vault_path)
        self.event_journal.prune_old_backups()
        self.emit_event("info", "daemon_started", "Daemon started")

    # ------------------------------------------------------------------
    # Journaling
    # ------------------------------------------------------------------

    def emit_event(
        self,
        level: str,
        event: str,
        message: str,
        *,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        """Append a lifecycle event to the journal. Safe to call from any thread."""
        try:
            self.event_journal.append(level, event, message, payload=payload)
        except Exception:
            # Journaling failures must not crash the daemon.
            logger.exception("Failed to append journal entry: level=%s event=%s", level, event)

    # ------------------------------------------------------------------
    # Loop access
    # ------------------------------------------------------------------

    def run_in_loop(self, coro) -> "concurrent.futures.Future[Any]":
        """Schedule ``coro`` on the daemon's event loop from another thread.

        Raises RuntimeError if the loop isn't running yet.
        """
        if self.loop is None:
            raise RuntimeError("Daemon loop is not running yet")
        return asyncio.run_coroutine_threadsafe(coro, self.loop)
```

**Step 4: Run to verify pass**

`uv run pytest tests/test_daemon_service.py -v` → PASS.
`uv run pytest -q` → full suite passes.

**Step 5: Commit**

```bash
git add recap/daemon/service.py tests/test_daemon_service.py
git commit -m "feat: Daemon service class owning loop, journal, and index"
```

---

## Task 3: Shrink `__main__.py` to use `Daemon`

**Context:** `__main__.py` currently hand-rolls a `_loop_holder`/`_app_holder` closure bag for 9 call sites. This task migrates all of them to go through a single `Daemon` instance. After this task, `__main__.py`'s `main()` is roughly `parse → load_config → Daemon(config).start()` and `_make_process_recording` / `_make_emit_event` close over `daemon`, not over holder lists.

**Files:**
- Modify: `recap/daemon/__main__.py`
- Modify: `recap/daemon/service.py` (add the real `start()` / `stop()` methods)
- Modify: `tests/test_daemon_service.py` (add integration-level test for start/stop)

**Step 1: Read the current structure**

Read `recap/daemon/__main__.py` end-to-end to understand:
- Where `_loop_holder` / `_app_holder` are populated (`_loop_holder[0] = asyncio.get_event_loop()` at ~375; `_app_holder[0] = app` at ~275).
- Every closure that reads from them.
- The existing EventIndex construction in `main()` — migrate that into `Daemon.start()`.
- Where `MeetingDetector`, `CalendarSyncScheduler`, `Recorder`, `_make_process_recording` are constructed — migrate into `Daemon.start()`.
- The Phase 2 event_index wiring (constructor kwargs + closure kwargs) — keep it working but sourced from `daemon.event_index`.

**Step 2: Expand `Daemon`**

In `recap/daemon/service.py`, add:

- `async def start(self, *, args: argparse.Namespace, callbacks: dict[str, Any]) -> None` — full start: construct recorder, detector, scheduler, aiohttp app, start the HTTP server, call `scheduler.start()`, call `detector.start()`. Assign `self.loop = asyncio.get_running_loop()`, `self.app = app`, `self.started_at = datetime.now(...)`. Perform the unconditional `event_index.rebuild()`.
- `async def stop(self) -> None` — inverse order: stop scheduler, stop detector, stop recorder, close HTTP runner, emit `daemon_stopped` event.

The `callbacks` dict is Phase-3-transitional — it exists so `__main__.py` can still wire callbacks it controls during this migration without Daemon needing to know about every subservice signature. Phase 3 later tasks may migrate specific callbacks into `Daemon` proper.

**Step 3: Migrate `__main__.py`**

Replace the holder-list pattern with a single `Daemon` reference. `_make_process_recording` becomes `_make_process_recording(daemon)` and reads `daemon.event_index`, `daemon.config`, etc. `_make_emit_event` becomes `daemon.emit_event` directly or a thin wrapper. Every `_loop_holder[0]` → `daemon.loop`; every `_app_holder[0]` → `daemon.app`; every `asyncio.run_coroutine_threadsafe(..., _loop_holder[0])` → `daemon.run_in_loop(...)`.

After migration, `main()` shrinks to roughly:

```python
def main() -> None:
    args = _parse_args()
    _configure_logging(args.log_level)
    config = load_daemon_config(args.config)
    daemon = Daemon(config)
    asyncio.run(_run_daemon(daemon, args))


async def _run_daemon(daemon: Daemon, args: argparse.Namespace) -> None:
    try:
        await daemon.start(args=args, callbacks=_build_callbacks(daemon))
        await _wait_for_shutdown(daemon)
    finally:
        await daemon.stop()
```

The `_build_callbacks(daemon)` function constructs the same callbacks that were inline before, now taking `daemon` instead of the holder lists.

**Step 4: Remove `_loop_holder` / `_app_holder`**

After migration: `grep -n "_loop_holder\|_app_holder" recap/daemon/__main__.py` returns 0 hits.

**Step 5: Add integration test**

In `tests/test_daemon_service.py`, add (as a new class):

```python
class TestDaemonLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_stop_cycle(self, tmp_path):
        """start() brings up services; stop() tears them down cleanly."""
        cfg = _make_config(tmp_path)
        d = Daemon(cfg)
        # Minimal args — use a random port, no auth token file
        args = _minimal_args(port=0)
        await d.start(args=args, callbacks=_stub_callbacks(d))
        assert d.started_at is not None
        assert d.loop is not None
        assert d.app is not None
        assert d.event_index_path.exists()  # rebuilt at startup
        journal_entries = d.event_journal.tail(limit=10)
        assert any(e["event"] == "daemon_started" for e in journal_entries)
        await d.stop()
        stop_entries = d.event_journal.tail(limit=10)
        assert any(e["event"] == "daemon_stopped" for e in stop_entries)
```

Helpers `_minimal_args` and `_stub_callbacks` live in the test file and stub out the recorder/scheduler subservices (use simple asyncio tasks that exit on cancel). The goal is to prove the lifecycle shape works, not to test every subservice.

**Step 6: Run tests**

- `uv run pytest tests/test_daemon_service.py -v` → all pass.
- `uv run pytest -q` → 386 still passes (+ new lifecycle test).

**Step 7: Commit**

```bash
git add recap/daemon/__main__.py recap/daemon/service.py tests/test_daemon_service.py
git commit -m "refactor: Daemon owns loop/app/services; retire _loop_holder/_app_holder"
```

**Scope guardrails for Task 3:**
- Do NOT modify route handlers in `server.py` — Task 6 owns that.
- Do NOT change recorder/detector signatures — Tasks 4/5 own those.
- Do NOT add new routes — Tasks 6/8/9 own those.
- Callback plumbing can be Phase-3-transitional (the `callbacks` dict shape); clean it up only if trivial.

---

## Task 4: `AudioCapture.on_chunk` callback; kill monkey-patch

**Context:** `recorder.py:_start_streaming` currently monkey-patches `audio_capture._interleave_and_encode` to siphon decoded frames into the streaming VAD. This reaches into a private method, so any rename in `audio.py` breaks the recorder silently. Replace with an explicit public `on_chunk` attribute.

**Files:**
- Modify: `recap/daemon/recorder/audio.py`
- Modify: `recap/daemon/recorder/recorder.py`
- Modify: `tests/test_audio_capture.py` (or create)
- Modify: `tests/test_recorder_orchestrator.py` (if it exists)

**Step 1: Write failing test for the new public surface**

Append to `tests/test_audio_capture.py`:

```python
def test_audio_capture_invokes_on_chunk_after_interleave(tmp_path):
    """Public on_chunk callback replaces the monkey-patch."""
    from recap.daemon.recorder.audio import AudioCapture
    captured: list[tuple[bytes, int]] = []

    cap = AudioCapture(output_path=tmp_path / "out.flac")
    cap.on_chunk = lambda chunk, sample_rate: captured.append((chunk, sample_rate))
    # Feed two fake frames through the combine-and-encode path using the
    # helper the class already exposes for tests. If no such helper exists,
    # simulate by calling the combiner directly.
    cap._test_feed_mock_frames(mic_frame=b"\x00" * 320, system_frame=b"\x01" * 320)
    cap._test_feed_mock_frames(mic_frame=b"\x02" * 320, system_frame=b"\x03" * 320)

    assert len(captured) == 2
    # Chunks are bytes and sample_rate is an int
    assert all(isinstance(c[0], bytes) and isinstance(c[1], int) for c in captured)
```

(If the current `AudioCapture` doesn't have a test-only feed helper, add one in Step 3 — `_test_feed_mock_frames` is fine as a pragma under `# pragma: no cover`.)

**Step 2: Run to verify failure**

`uv run pytest tests/test_audio_capture.py::test_audio_capture_invokes_on_chunk_after_interleave -v` → FAIL.

**Step 3: Implement in `audio.py`**

Add a public attribute + invoke it after the interleave call:

```python
class AudioCapture:
    on_chunk: Callable[[bytes, int], None] | None = None

    def __init__(self, ...):
        ...
        self.on_chunk = None
        ...

    def _interleave_and_encode(self, ...):
        chunk, sample_rate = self._combine_frames(...)
        # existing encode-to-FLAC logic unchanged
        ...
        if self.on_chunk is not None:
            try:
                self.on_chunk(chunk, sample_rate)
            except Exception:
                logger.exception("on_chunk callback raised")
        return chunk
```

The `try/except` is defensive — a bad callback must not crash the recording thread.

**Step 4: Remove monkey-patch in `recorder.py`**

Find `_start_streaming`:

```python
# BEFORE
original_interleave = self._audio_capture._interleave_and_encode
def _patched(*args, **kwargs):
    chunk = original_interleave(*args, **kwargs)
    self._feed_streaming_models(chunk, sample_rate)
    return chunk
self._audio_capture._interleave_and_encode = _patched
```

Replace with:

```python
# AFTER
self._audio_capture.on_chunk = self._feed_streaming_models
```

The signature of `_feed_streaming_models` must match `on_chunk: (chunk, sample_rate) -> None`. Verify or adapt.

**Step 5: Run tests**

- `uv run pytest tests/test_audio_capture.py tests/test_recorder_orchestrator.py -v` → all pass.
- `uv run pytest -q` → full suite passes.
- Grep sanity: `grep -rn "_interleave_and_encode" recap/daemon/recorder/` should show only the method definition and the internal callers, no more monkey-patch.

**Step 6: Commit**

```bash
git add recap/daemon/recorder/audio.py recap/daemon/recorder/recorder.py tests/test_audio_capture.py
git commit -m "refactor: AudioCapture.on_chunk public callback; drop monkey-patch"
```

---

## Task 5: Signal popup async + detector awaitable callback

**Context:** `signal_popup.show_signal_popup` is currently synchronous tkinter. The detector calls it on the same async tick that polls for meeting signals, so the poll loop blocks for the duration of the popup (user might take minutes to choose). Design §Phase 3 requires `show_signal_popup` become an async function that runs tkinter via `loop.run_in_executor(None, _blocking_dialog)`. The detector's `_on_signal_detected` hook also becomes awaitable, so the detector can keep polling while the popup is open.

Also in scope: wire the popup's backend choice into `RecordingMetadata.llm_backend` (Phase 1 did the data side; verify it still flows end-to-end after the async conversion) and retire the detector's `_org_subfolder` hand-join (Phase 2 carryover).

**Files:**
- Modify: `recap/daemon/recorder/signal_popup.py`
- Modify: `recap/daemon/recorder/detector.py`
- Modify: `tests/test_signal_popup.py` (or create)
- Modify: `tests/test_detector.py`

**Step 1: Write failing tests**

Signal popup (`tests/test_signal_popup.py`):

```python
import asyncio
import pytest
from recap.daemon.recorder.signal_popup import show_signal_popup


@pytest.mark.asyncio
async def test_show_signal_popup_is_async_and_non_blocking(monkeypatch):
    """Async popup yields to the event loop while the dialog is up."""
    # Stub the tkinter dialog to return immediately with a known result.
    def _fake_blocking(*args, **kwargs):
        return {"backend": "ollama", "org": "d"}

    monkeypatch.setattr(
        "recap.daemon.recorder.signal_popup._blocking_dialog", _fake_blocking,
    )

    poll_hits = []

    async def _other_coroutine():
        # Simulate the detector poll loop running concurrently
        for _ in range(3):
            poll_hits.append(True)
            await asyncio.sleep(0)

    result, _ = await asyncio.gather(
        show_signal_popup(org_slug="d", available_backends=["claude", "ollama"]),
        _other_coroutine(),
    )
    assert result == {"backend": "ollama", "org": "d"}
    assert len(poll_hits) == 3  # other coroutine ran during the await


@pytest.mark.asyncio
async def test_show_signal_popup_returns_none_on_cancel(monkeypatch):
    monkeypatch.setattr(
        "recap.daemon.recorder.signal_popup._blocking_dialog",
        lambda *a, **kw: None,
    )
    result = await show_signal_popup(org_slug="d", available_backends=["claude"])
    assert result is None
```

Detector (`tests/test_detector.py`, append):

```python
@pytest.mark.asyncio
async def test_detector_awaits_signal_callback_without_blocking_poll(tmp_path, monkeypatch):
    """The detector continues polling while the signal callback is awaited."""
    from recap.daemon.recorder.detector import MeetingDetector
    # Install a callback that blocks briefly to simulate Signal popup
    callback_hits = []
    async def _slow_callback(event_or_signal):
        await asyncio.sleep(0.02)
        callback_hits.append(event_or_signal)

    # ... construct detector with _slow_callback as on_signal_detected
    # Arrange a poll-loop run that emits ≥2 signals while a prior callback
    # is still awaiting. Assert both callbacks complete, poll loop ran N
    # ticks during the window.
```

**Step 2: Run to verify failure**

Targeted `uv run pytest tests/test_signal_popup.py tests/test_detector.py -v` → FAILs at the `await show_signal_popup(...)` call (currently sync) and detector callback tests.

**Step 3: Implement async popup**

`recap/daemon/recorder/signal_popup.py`:

```python
import asyncio
from typing import Optional


def _blocking_dialog(org_slug: str, available_backends: list[str]) -> Optional[dict]:
    """Existing synchronous tkinter code, unchanged."""
    # (lift the current body of show_signal_popup here)
    ...


async def show_signal_popup(
    *, org_slug: str, available_backends: list[str],
) -> Optional[dict]:
    """Async wrapper around the blocking tkinter dialog.

    Runs the dialog in a thread via loop.run_in_executor so the detector's
    poll loop continues while the user decides.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _blocking_dialog, org_slug, available_backends,
    )
```

**Step 4: Make detector callback awaitable**

In `recap/daemon/recorder/detector.py`:

- Change `self._on_signal_detected` annotation from `Callable[...]` to `Callable[..., Awaitable[None]]`.
- Call it with `await self._on_signal_detected(signal)`. The poll loop stays an asyncio task; awaiting the callback yields to the loop so other tasks run.
- Ensure the callback wrapping in `__main__.py` (now via `Daemon` / Task 3) builds an async function: it shows the popup, reads the user's choice, constructs `RecordingMetadata(llm_backend=<chosen_backend>)`, then calls `recorder.start(org, metadata=metadata)`.

**Step 5: Retire detector `_org_subfolder` hand-join (Phase 2 carryover)**

`detector.py:_org_subfolder` currently reads `org_config.subfolder` and joins it naively. Delete that private helper and use `org_config.resolve_subfolder(self._config.vault_path)` directly at the two call sites. Grep check:

```bash
grep -n "_org_subfolder" recap/daemon/recorder/detector.py
```

Should return zero hits in the implementation, only test references if any.

**Step 6: Run tests**

- `uv run pytest tests/test_signal_popup.py tests/test_detector.py -v` → pass.
- `uv run pytest -q` → full suite passes.

**Step 7: Commit**

```bash
git add recap/daemon/recorder/signal_popup.py recap/daemon/recorder/detector.py tests/test_signal_popup.py tests/test_detector.py
git commit -m "refactor: async Signal popup + awaitable detector callback; kill detector org_subfolder"
```

---

## Task 6: Real `/api/status` + journal WebSocket broadcast

**Context:** `/api/status` currently returns a placeholder. Now it returns real uptime (`now - daemon.started_at`) and real recent errors (`daemon.event_journal.tail(level="error", limit=10)`). The WebSocket handler also broadcasts a `{"event": "journal_entry", ...}` message for every new journal append so the plugin can render notifications in real time.

**Files:**
- Modify: `recap/daemon/server.py`
- Modify: `recap/daemon/service.py` (add a subscriber API on `EventJournal` or on `Daemon`)
- Modify: `tests/test_server.py` (or create)

**Step 1: Add a pub-sub shim**

In `recap/daemon/events.py`, extend `EventJournal`:

```python
def subscribe(self, callback: Callable[[dict], None]) -> Callable[[], None]:
    """Register a callback invoked for each append. Returns an unsubscribe fn."""
    with self._subscriber_lock:
        self._subscribers.append(callback)
    def _unsubscribe() -> None:
        with self._subscriber_lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)
    return _unsubscribe
```

And in `append()`, after the write, fan out (outside the file-write lock) to subscribers. Wrap in try/except — a bad subscriber must not block the journal.

**Step 2: Write failing tests**

```python
class TestJournalSubscribers:
    def test_subscribe_receives_appended_entries(self, tmp_path):
        j = EventJournal(tmp_path / "events.jsonl")
        received: list[dict] = []
        unsubscribe = j.subscribe(received.append)
        j.append("info", "e1", "m1")
        j.append("info", "e2", "m2")
        assert [e["event"] for e in received] == ["e1", "e2"]
        unsubscribe()
        j.append("info", "e3", "m3")
        assert [e["event"] for e in received] == ["e1", "e2"]


class TestApiStatus:
    @pytest.mark.asyncio
    async def test_api_status_returns_uptime_and_errors(self, aiohttp_client, tmp_path):
        # Spin up a Daemon test-start, emit a couple of events, assert via HTTP
        ...
```

**Step 3: Implement in `server.py`**

`_api_status`:

```python
async def _api_status(request: web.Request) -> web.Response:
    daemon: Daemon = request.app["daemon"]
    if daemon.started_at is None:
        uptime = 0.0
    else:
        uptime = (datetime.now(timezone.utc).astimezone() - daemon.started_at).total_seconds()
    errors = daemon.event_journal.tail(level="error", limit=10)
    return web.json_response({
        "uptime_seconds": uptime,
        "recent_errors": errors,
    })
```

WebSocket handler:

```python
async def _websocket_handler(request: web.Request) -> web.WebSocketResponse:
    daemon: Daemon = request.app["daemon"]
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    loop = asyncio.get_running_loop()

    def _on_journal_entry(entry: dict) -> None:
        # Called on the journal-writer thread; marshal to the loop.
        asyncio.run_coroutine_threadsafe(
            ws.send_json({"event": "journal_entry", "entry": entry}),
            loop,
        )

    unsubscribe = daemon.event_journal.subscribe(_on_journal_entry)
    try:
        # ... existing handshake / ping / await ws.close()
        ...
    finally:
        unsubscribe()
    return ws
```

Make sure `request.app["daemon"] = daemon` is set during `Daemon.start()` in Task 3.

**Step 4: Run tests**

Targeted + full suite. Full suite continues to pass.

**Step 5: Commit**

```bash
git add recap/daemon/server.py recap/daemon/service.py recap/daemon/events.py tests/test_server.py tests/test_event_journal.py
git commit -m "feat: real /api/status uptime+errors; WebSocket journal broadcast"
```

---

## Task 7: Server route cleanup + Bearer auth migration

**Context:** Per design §Phase 3:
1. Delete dead `_meeting_detected` (server.py:55) and `_meeting_ended` (server.py:78) — they're old sync hooks no caller hits.
2. Move `_meeting_detected_live` + `_meeting_ended_live` behind `/api/` and require Bearer auth via the existing middleware.
3. Delete `_autostart_status` (line 338) and the `/api/autostart` route — the entire `autostart.py` is being retired (Task 10 deletes the file).
4. Register routes in groups so `/api/` endpoints consistently go through Bearer auth.

Transitional note from §0.5: during Phase 3 the daemon supports both authenticated and unauthenticated `/meeting-detected`/`/meeting-ended` briefly so the extension isn't broken mid-refactor. By Phase 4, unauthenticated paths are removed. This task keeps legacy unauth routes but also registers the `/api/` versions with Bearer.

**Files:**
- Modify: `recap/daemon/server.py`
- Modify: `tests/test_server.py`

**Step 1: Test the expected end state**

Add tests:

- `_api_meeting_detected_requires_bearer`: POST without `Authorization` header returns 401.
- `_api_meeting_detected_with_valid_bearer_returns_200`.
- `_api_meeting_ended` equivalents.
- `_autostart_status_is_gone`: GET `/api/autostart` returns 404.
- `_dead_sync_routes_are_gone`: POST `/meeting-detected` (the OLD non-`/api/` one that was dead) returns 404 — i.e., assert the new route only exists under `/api/`.

Wait — the unauthenticated `/meeting-detected` route must stay as a transitional bridge (per §0.5). Both the unauth legacy route AND the new auth'd `/api/` route exist. The test should therefore assert:
- Legacy `/meeting-detected` (unauth) still works temporarily.
- New `/api/meeting-detected` requires Bearer.
- Old dead handlers `_meeting_detected` / `_meeting_ended` (the ones at 55/78 that no caller uses) are fully removed.

**Step 2: Implement**

- Delete `_meeting_detected` (55) and `_meeting_ended` (78) from `server.py`.
- Rename `_meeting_detected_live` → `_meeting_detected_api` (or similar), wrap with Bearer middleware. Register at `/api/meeting-detected`. Keep a thin legacy handler at `/meeting-detected` that delegates to the same logic, also Bearer-optional for now (add `# Transitional: remove in Phase 4` comment).
- Same for `_meeting_ended_live`.
- Delete `_autostart_status` and unregister `/api/autostart`.
- Ensure Bearer middleware keys off `request.match_info.route.resource.canonical.startswith("/api/")` (or an existing equivalent) so `/api/` routes are auth-required.

**Step 3: Run tests**

- `uv run pytest tests/test_server.py -v` → all pass.
- `uv run pytest -q` → full suite passes.

**Step 4: Commit**

```bash
git add recap/daemon/server.py tests/test_server.py
git commit -m "refactor: /api/* requires Bearer; delete dead sync hooks and /api/autostart"
```

---

## Task 8: Extension auth — `PairingWindow` + `/bootstrap/token` + tray menu

**Context:** Implement design §0.5. Tray menu item "Pair browser extension…" opens a short-lived bootstrap window. The `/bootstrap/token` endpoint is disabled until the window opens, binds to loopback only, closes on the first successful fetch, and auto-closes after 60 s as a safety valve. Every lifecycle transition is journaled.

**Files:**
- Create: `recap/daemon/pairing.py`
- Modify: `recap/daemon/server.py` (add the conditional `/bootstrap/token` route)
- Modify: `recap/daemon/tray.py` (add menu item)
- Modify: `recap/daemon/service.py` (wire `PairingWindow` into `Daemon`)
- Create: `tests/test_pairing.py`

**Step 1: Write failing tests for `PairingWindow`**

```python
"""Tests for the pairing window lifecycle (design §0.5)."""
from __future__ import annotations

import pytest

from recap.daemon.pairing import PairingWindow
# Journal stub
class _StubJournal:
    def __init__(self): self.entries = []
    def append(self, level, event, message, *, payload=None):
        self.entries.append((level, event, message, payload))


def test_initial_state_closed():
    j = _StubJournal()
    w = PairingWindow(journal=j)
    assert w.is_open is False
    assert w.current_token is None


def test_open_enables_endpoint_and_journals():
    j = _StubJournal()
    w = PairingWindow(journal=j)
    w.open()
    assert w.is_open
    assert w.current_token is not None
    assert any(e[1] == "pairing_opened" for e in j.entries)


def test_consume_token_once_only():
    j = _StubJournal()
    w = PairingWindow(journal=j)
    w.open()
    token = w.consume(requester_ip="127.0.0.1")
    assert token is not None
    assert w.is_open is False  # one-shot
    assert any(e[1] == "pairing_token_issued" for e in j.entries)
    # Second call fails
    with pytest.raises(RuntimeError):
        w.consume(requester_ip="127.0.0.1")


def test_consume_from_non_loopback_fails_and_journals():
    j = _StubJournal()
    w = PairingWindow(journal=j)
    w.open()
    with pytest.raises(PermissionError):
        w.consume(requester_ip="10.0.0.5")
    assert any(e[1] == "pairing_failed_non_loopback" for e in j.entries)
    # Window stays open for the legitimate consumer
    assert w.is_open


def test_timeout_closes_and_journals(monkeypatch):
    j = _StubJournal()
    # Inject a controllable clock
    clock = {"t": 0.0}
    monkeypatch.setattr("recap.daemon.pairing._now", lambda: clock["t"])
    w = PairingWindow(journal=j, timeout_seconds=60)
    w.open()
    assert w.is_open
    # Advance past the timeout and poke
    clock["t"] = 61.0
    w.check_timeout()
    assert w.is_open is False
    assert any(e[1] == "pairing_closed_timeout" for e in j.entries)
```

**Step 2: Write failing tests for `/bootstrap/token` route**

```python
@pytest.mark.asyncio
async def test_bootstrap_token_returns_404_when_window_closed(aiohttp_client, ...):
    # GET /bootstrap/token with window closed -> 404 (route not registered or 404'd)
    ...


@pytest.mark.asyncio
async def test_bootstrap_token_returns_token_when_window_open_and_loopback(...):
    # PairingWindow.open() called programmatically; GET returns the token; window closes
    ...


@pytest.mark.asyncio
async def test_bootstrap_token_rejects_non_loopback(...):
    # Simulate X-Forwarded-For or non-loopback peer; returns 403
    ...
```

**Step 3: Implement**

Create `recap/daemon/pairing.py`:

```python
"""Pairing window for extension auth (design §0.5)."""
from __future__ import annotations

import secrets
import threading
import time
from typing import Optional

_LOOPBACK_IPS = {"127.0.0.1", "::1"}


def _now() -> float:
    return time.monotonic()


class PairingWindow:
    """One-shot, loopback-only, journaled pairing token issuer."""

    def __init__(self, *, journal, timeout_seconds: float = 60.0) -> None:
        self._journal = journal
        self._timeout = timeout_seconds
        self._lock = threading.Lock()
        self._is_open = False
        self._token: Optional[str] = None
        self._opened_at: Optional[float] = None

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._is_open

    @property
    def current_token(self) -> Optional[str]:
        with self._lock:
            return self._token if self._is_open else None

    def open(self) -> None:
        with self._lock:
            if self._is_open:
                return
            self._token = secrets.token_urlsafe(32)
            self._is_open = True
            self._opened_at = _now()
        self._journal.append("info", "pairing_opened", "Pairing window opened")

    def consume(self, *, requester_ip: str) -> str:
        with self._lock:
            if not self._is_open:
                raise RuntimeError("pairing window closed")
            if requester_ip not in _LOOPBACK_IPS:
                # Do NOT close the window — a legitimate loopback caller can still succeed.
                self._journal.append(
                    "warning", "pairing_failed_non_loopback",
                    f"Non-loopback pairing attempt from {requester_ip}",
                    payload={"requester_ip": requester_ip},
                )
                raise PermissionError(f"non-loopback requester {requester_ip}")
            token = self._token
            assert token is not None
            self._is_open = False
            self._token = None
            self._opened_at = None
        self._journal.append(
            "info", "pairing_token_issued", "Pairing token issued",
            payload={"requester_ip": requester_ip},
        )
        return token

    def check_timeout(self) -> None:
        with self._lock:
            if not self._is_open or self._opened_at is None:
                return
            elapsed = _now() - self._opened_at
            if elapsed < self._timeout:
                return
            self._is_open = False
            self._token = None
            self._opened_at = None
        self._journal.append(
            "warning", "pairing_closed_timeout", "Pairing window expired with no consumer",
        )
```

Add a `Daemon.pairing` attribute constructed in `Daemon.__init__`. Add `/bootstrap/token` route in `server.py` that:
- Reads `daemon.pairing`.
- If `not daemon.pairing.is_open`: return 404.
- Extracts peer IP from the transport; call `daemon.pairing.consume(requester_ip=ip)`.
- On `PermissionError`: 403.
- On success: `{"token": "<scoped-or-full>"}`.

Issue either a scoped extension token (if the auth middleware accepts a simple allow-list check) or the full daemon token. Decision recorded in the commit message.

Add a timer in `Daemon.start()` (asyncio task) that periodically calls `pairing.check_timeout()` every ~5 s.

Add `tray.py` menu item:

```python
menu_items = [
    ...
    MenuItem("Pair browser extension…", lambda: daemon.pairing.open()),
    ...
]
```

**Step 4: Run tests**

Targeted + full suite. Full suite passes.

**Step 5: Commit**

```bash
git add recap/daemon/pairing.py recap/daemon/server.py recap/daemon/tray.py recap/daemon/service.py tests/test_pairing.py tests/test_server.py
git commit -m "feat: extension pairing window, /bootstrap/token, tray menu item"
```

Commit body: note whether the token is scoped or full-access, and why.

---

## Task 9: `/api/index/rename` endpoint

**Context:** Phase 4's plugin rename processor will POST `{"event_id": "...", "old_path": "...", "new_path": "..."}` to this endpoint. The handler updates the `EventIndex` via `rename()` (preserves `org`) and returns 200. Phase 4 wires the plugin side.

**Files:**
- Modify: `recap/daemon/server.py`
- Modify: `tests/test_server.py`

**Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_api_index_rename_updates_index(aiohttp_client, tmp_path, ...):
    """POST /api/index/rename updates the index path; preserves org."""
    # Set up Daemon with an index entry; call the endpoint; verify lookup
    ...
```

**Step 2: Implement**

```python
async def _api_index_rename(request: web.Request) -> web.Response:
    daemon: Daemon = request.app["daemon"]
    body = await request.json()
    event_id = body.get("event_id")
    new_path = body.get("new_path")
    if not event_id or not new_path:
        return web.json_response({"error": "event_id and new_path required"}, status=400)
    # Validate that new_path is vault-relative
    p = pathlib.PurePosixPath(new_path)
    if p.is_absolute():
        return web.json_response({"error": "new_path must be vault-relative"}, status=400)
    daemon.event_index.rename(event_id, p)
    daemon.emit_event(
        "info", "index_rename",
        f"Renamed event-index entry {event_id} -> {new_path}",
        payload={"event_id": event_id, "new_path": str(p)},
    )
    return web.json_response({"status": "ok"})
```

Register at `/api/index/rename` (Bearer-required via the middleware pattern Task 7 established).

**Step 3: Run tests**

Targeted + full suite pass.

**Step 4: Commit**

```bash
git add recap/daemon/server.py tests/test_server.py
git commit -m "feat: /api/index/rename endpoint for plugin rename processor"
```

---

## Task 10: Delete `autostart.py`

**Context:** Final cleanup. `autostart.py` is 51 lines of decorative surface area with no real implementation. Task 7 already removed `/api/autostart`. This task deletes the file entirely and scrubs imports.

**Files:**
- Delete: `recap/daemon/autostart.py`
- Modify: any file that imports from it (grep to find)

**Step 1: Find residual references**

```bash
grep -rn "from recap.daemon.autostart\|import.*autostart" recap/ tests/
```

Expected hits: zero after Task 7 route removal. If any remain, remove them.

**Step 2: Delete the file**

```bash
git rm recap/daemon/autostart.py
```

**Step 3: Run tests**

Full suite passes.

**Step 4: Commit**

```bash
git commit -m "chore: delete recap/daemon/autostart.py (unused)"
```

---

## Task 11: Notifications → journal integration

**Context:** `recap/daemon/notifications.py:notify()` currently just logs + shows an OS notification. Make it ALSO append to the event journal so the plugin can render a notification history over daemon data (per §0.4: "plugin never writes to the journal; `NotificationHistory.ts` becomes a thin renderer over daemon data").

**Files:**
- Modify: `recap/daemon/notifications.py`
- Modify: `tests/test_notifications.py` (or create)

**Step 1: Write failing test**

```python
def test_notify_appends_to_journal(tmp_path):
    from recap.daemon.events import EventJournal
    from recap.daemon.notifications import notify

    journal = EventJournal(tmp_path / "events.jsonl")
    notify("Test Title", "Test body", journal=journal, level="info", event="test")
    entries = journal.tail(limit=10)
    assert any(e["message"] == "Test body" and e["event"] == "test" for e in entries)
```

**Step 2: Implement**

```python
def notify(
    title: str,
    body: str,
    *,
    journal: Optional["EventJournal"] = None,
    level: str = "info",
    event: str = "notification",
) -> None:
    # Existing OS-notification code unchanged
    ...
    if journal is not None:
        try:
            journal.append(level, event, body, payload={"title": title})
        except Exception:
            logger.exception("Failed to journal notification")
```

All call sites must pass `journal=daemon.event_journal` (grep `notify(` and adapt).

**Step 3: Run tests**

Targeted + full suite pass.

**Step 4: Commit**

```bash
git add recap/daemon/notifications.py tests/test_notifications.py
git commit -m "feat: notify() also appends to event journal"
```

---

## Task 12: End-to-end integration test

**Files:**
- Create: `tests/test_phase3_integration.py`

**Step 1: Write the integration test**

```python
"""Phase 3 integration: Daemon + journal + pairing + WebSocket broadcast."""
import asyncio
import json
import pytest

from recap.daemon.service import Daemon


@pytest.mark.asyncio
async def test_full_daemon_lifecycle_with_pairing_and_journaled_events(tmp_path):
    cfg = _make_daemon_config(tmp_path)
    daemon = Daemon(cfg)
    await daemon.start(args=_minimal_args(port=0), callbacks=_stub_callbacks(daemon))

    try:
        # 1. Startup was journaled
        entries = daemon.event_journal.tail(limit=100)
        assert any(e["event"] == "daemon_started" for e in entries)

        # 2. /api/status returns real uptime
        async with _client_to(daemon) as client:
            resp = await client.get("/api/status")
            status = await resp.json()
            assert status["uptime_seconds"] > 0
            assert isinstance(status["recent_errors"], list)

            # 3. Pairing flow (happy path)
            daemon.pairing.open()
            resp = await client.get("/bootstrap/token")
            assert resp.status == 200
            token = (await resp.json())["token"]
            assert token
            # Second call now 404 (window is one-shot)
            resp2 = await client.get("/bootstrap/token")
            assert resp2.status == 404

            # 4. /api/index/rename (Bearer required)
            headers = {"Authorization": f"Bearer {token}"}
            daemon.event_index.add("evt-1", pathlib.PurePosixPath("Clients/D/Meetings/x.md"), "d")
            resp = await client.post(
                "/api/index/rename",
                json={"event_id": "evt-1", "new_path": "Clients/D/Meetings/renamed.md"},
                headers=headers,
            )
            assert resp.status == 200
            assert str(daemon.event_index.lookup("evt-1").path) == "Clients/D/Meetings/renamed.md"

        # 5. Journaled events include every lifecycle transition
        final = daemon.event_journal.tail(limit=100)
        events = [e["event"] for e in final]
        assert "pairing_opened" in events
        assert "pairing_token_issued" in events
        assert "index_rename" in events

    finally:
        await daemon.stop()
        stopped = daemon.event_journal.tail(limit=10)
        assert any(e["event"] == "daemon_stopped" for e in stopped)
```

**Step 2: Run**

`uv run pytest tests/test_phase3_integration.py -v` → PASS.
`uv run pytest -q` → full suite passes.

**Step 3: Commit**

```bash
git add tests/test_phase3_integration.py
git commit -m "test: end-to-end Daemon lifecycle with pairing, status, journal, rename"
```

---

## Task 13: MANIFEST update

**Files:**
- Modify: `MANIFEST.md`

**Step 1: Edit**

Add the new files to Structure:
- `recap/daemon/service.py` — `Daemon` service object
- `recap/daemon/events.py` — `EventJournal` append-only journal
- `recap/daemon/pairing.py` — `PairingWindow` for extension auth
- `tests/test_daemon_service.py`, `tests/test_event_journal.py`, `tests/test_pairing.py`, `tests/test_phase3_integration.py`

Remove from Structure:
- `recap/daemon/autostart.py` (deleted in Task 10)

Update annotations on changed files:
- `recap/daemon/__main__.py` — thin entry point; constructs `Daemon(config).start()`
- `recap/daemon/server.py` — routes consume `request.app["daemon"]`; `/api/*` require Bearer; `/bootstrap/token` guarded by `Daemon.pairing`
- `recap/daemon/recorder/audio.py` — public `on_chunk` callback (no monkey-patching)
- `recap/daemon/recorder/recorder.py` — uses `audio_capture.on_chunk`
- `recap/daemon/recorder/signal_popup.py` — async via `loop.run_in_executor`
- `recap/daemon/recorder/detector.py` — awaitable signal callback; `resolve_subfolder` (no hand-join)
- `recap/daemon/notifications.py` — writes to event journal
- `recap/daemon/tray.py` — adds "Pair browser extension…" menu item

Update Key Relationships:
- Replace Phase 2's "EventIndex singleton in __main__" with "Daemon owns EventIndex + EventJournal; subservices receive via constructor or `request.app['daemon']`"
- Add: "Extension auth via explicit tray-initiated one-shot PairingWindow bound to loopback; `/bootstrap/token` serves only while open; all transitions journaled"
- Add: "EventJournal is single source of truth for `/api/status` recent errors + plugin notification history (no plugin-side writes)"
- Remove detector `_org_subfolder` caveat (fixed in Task 5)
- Remove any `_loop_holder`/`_app_holder` reference if the old MANIFEST mentioned it

Keep total length 50-80 lines.

**Step 2: Verify**

```bash
uv run pytest -q  # still 386+ passed (actual count depends on tests added in tasks 1-12)
```

**Step 3: Commit**

```bash
git add MANIFEST.md
git commit -m "docs: update MANIFEST for Phase 3 runtime foundation"
```

---

## Post-Phase Verification

| Command | Expected |
|---|---|
| `uv run pytest -q` | all pass |
| `grep -rn "_loop_holder\|_app_holder" recap/` | 0 hits |
| `grep -rn "from recap.daemon.autostart\|import.*autostart" recap/ tests/` | 0 hits |
| `grep -rn "_interleave_and_encode" recap/daemon/recorder/ \| grep -v "def _interleave"` | no monkey-patch call sites |
| `grep -rn "_org_subfolder" recap/daemon/recorder/detector.py` | 0 hits |
| `grep -n "class Daemon\b" recap/daemon/service.py` | 1 hit |
| `grep -n "class EventJournal\b" recap/daemon/events.py` | 1 hit |
| `grep -n "class PairingWindow\b" recap/daemon/pairing.py` | 1 hit |
| Test `Daemon.started_at` is a datetime after start | passes |
| Test `/bootstrap/token` returns 404 when window closed | passes |
| Test `/api/status.uptime_seconds > 0` after 1 s | passes |

Acceptance criteria (from design doc §Phase 3):

- [ ] `__main__.py` is a thin entry point. No `_loop_holder`, no `_app_holder`, no closure bag.
- [ ] A single `Daemon` service object owns runtime state, loop access, and lifecycle.
- [ ] `/api/status` returns real uptime (> 0 after daemon running for a second) and real recent errors (populated when journal has error entries).
- [ ] Signal prompting no longer blocks the detector poll loop (verified in `test_detector_awaits_signal_callback_without_blocking_poll`).
- [ ] Signal backend choice survives: popup returns `ollama`, `RecordingMetadata.llm_backend == "ollama"`, `PipelineRuntimeConfig.llm_backend == "ollama"`, analyze invokes `ollama run ...`.
- [ ] `AudioCapture` exposes `on_chunk` as a public callback. `Recorder` does not access any underscore-prefixed attribute of `AudioCapture`.
- [ ] Daemon writes to `events.jsonl`; journal rotation works at 10 MB.
- [ ] Extension auth endpoint lives. `/bootstrap/token` is disabled by default, openable only from the tray, loopback-bound, one-shot, journaled. `/api/meeting-detected` requires Bearer.
- [ ] `/api/autostart` and `recap/daemon/autostart.py` are gone. No residual references anywhere in the codebase.

Bonus (Phase 2 carryover, closed here):
- [ ] Detector no longer hand-joins `org_config.subfolder`; uses `resolve_subfolder(vault_path)` like scheduler and sync.

---

## Handoff to Phase 4

Phase 4 (Plugin Parity + Extension) will:

- Wire the extension to consume `/bootstrap/token` and send `Authorization: Bearer <token>` on `/api/meeting-detected` + `/api/meeting-ended`.
- Plugin-side rename queue processor hits `/api/index/rename`.
- Plugin `NotificationHistory.ts` becomes a thin renderer over `GET /api/events` (tail) + WebSocket `journal_entry` broadcasts.
- Narrow `MeetingListView` to configured subfolders.
- Kill silent `catch {}` blocks in plugin code.
- Speaker correction audio preview.
- Remove the transitional unauthenticated `/meeting-detected` and `/meeting-ended` routes once the extension is on Bearer.

Phase 4 depends on Phase 3's `Daemon` + `EventJournal` + `PairingWindow` + `/api/index/rename`. No Phase 4 implementation begins until Codex re-reviews Phase 3.

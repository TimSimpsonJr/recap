# Phase 2: Org Model + Event-ID Index Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate the hardcoded `_Recap/<Capitalized>` calendar-subfolder capitalizer, add a persistent `EventIndex` for O(1) event-id lookups, and normalize `note_path` across all write points to vault-relative strings per design doc §0.3.

**Architecture:** Org identity (`org_slug`) and filesystem location (`org_subfolder`) are now independent: `OrgConfig.resolve_subfolder(vault_path)` is the only function that turns an org slug into an on-disk path. A new `EventIndex` at `<vault>/_Recap/.recap/event-index.json` maps `event_id → {path, org, mtime}` with vault-relative paths; it becomes the sole owner of event-id resolution and is updated by `upsert_note` on write and by the scheduler on calendar-sync cycles. `note_path` in `RecordingMetadata` and all downstream writers stores vault-relative strings; the pipeline resolver is the one place that anchors against `vault_path` for I/O.

**Tech Stack:** Python 3.10+, dataclasses, PyYAML, pytest, real tmp filesystems. No new third-party dependencies.

**Read before starting:**
- `docs/plans/2026-04-14-fix-everything-design.md` §0.1 (canonical note contract), §0.2 (org model), §0.3 (RecordingMetadata incl. vault-relative `note_path`), §Phase 2.
- `docs/plans/2026-04-14-phase1-data-contracts.md` (complete). `upsert_note` is now the sole note-writing primitive and is the natural hook for index updates.

**Baseline commit:** `881f0db` (Phase 1 final fix: calendar fields in canonical frontmatter). Test suite at 342.

---

## Conventions for every task

- Commit style: Conventional Commits (`feat:`, `refactor:`, `fix:`, `test:`, `chore:`, `docs:`).
- Never stage `uv.lock` or `docs/reviews/`.
- Run `uv run pytest -q` at the end of every task; a rename or signature change in one file can break imports in another.
- Never mock the functions under test (`upsert_note`, `write_calendar_note`, `find_note_by_event_id`, `EventIndex` methods); use real tmp filesystems via `tmp_path` or the `tmp_vault` fixture in `tests/conftest.py`.
- Tests for new public functions live in files mirroring the module name (`tests/test_event_index.py`, `tests/test_calendar_sync.py`, etc.).

---

## Task 1: Org helpers on `DaemonConfig` / `OrgConfig`

**Files:**
- Modify: `recap/daemon/config.py`
- Create: `tests/test_daemon_config_helpers.py` (or append to `tests/test_daemon_config.py` if it already exists)

**Step 1: Write failing tests**

Create `tests/test_daemon_config_helpers.py`:

```python
"""Tests for the org-lookup helpers on DaemonConfig / OrgConfig."""
from __future__ import annotations

import pathlib

from recap.daemon.config import DaemonConfig, OrgConfig


def _make_config_with_orgs(orgs: list[OrgConfig]) -> DaemonConfig:
    cfg = DaemonConfig.__new__(DaemonConfig)
    cfg.vault_path = pathlib.Path("/tmp/vault")
    cfg.recordings_path = pathlib.Path("/tmp/rec")
    cfg._orgs = orgs
    return cfg


class TestOrgBySlug:
    def test_returns_matching_org(self):
        a = OrgConfig(name="disbursecloud", subfolder="Clients/Disbursecloud")
        b = OrgConfig(name="personal", subfolder="Personal")
        cfg = _make_config_with_orgs([a, b])
        assert cfg.org_by_slug("personal") is b
        assert cfg.org_by_slug("disbursecloud") is a

    def test_returns_none_for_unknown_slug(self):
        cfg = _make_config_with_orgs([OrgConfig(name="a", subfolder="A")])
        assert cfg.org_by_slug("nope") is None

    def test_case_sensitive_match(self):
        """Slugs are lowercase per §0.2; lookup does not fuzzy-match."""
        cfg = _make_config_with_orgs([OrgConfig(name="disbursecloud", subfolder="X")])
        assert cfg.org_by_slug("DisburseCloud") is None


class TestResolveSubfolder:
    def test_returns_absolute_path_under_vault(self):
        org = OrgConfig(name="disbursecloud", subfolder="Clients/Disbursecloud")
        vault = pathlib.Path("/tmp/vault")
        assert org.resolve_subfolder(vault) == vault / "Clients/Disbursecloud"

    def test_handles_nested_subfolder(self):
        org = OrgConfig(name="x", subfolder="a/b/c")
        assert org.resolve_subfolder(pathlib.Path("/v")) == pathlib.Path("/v/a/b/c")

    def test_empty_subfolder_resolves_to_vault_root(self):
        org = OrgConfig(name="x", subfolder="")
        assert org.resolve_subfolder(pathlib.Path("/v")) == pathlib.Path("/v")
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_daemon_config_helpers.py -v`
Expected: FAIL — helpers do not exist.

**Step 3: Implement**

In `recap/daemon/config.py`:

Add a method to `OrgConfig`:

```python
@dataclass
class OrgConfig:
    name: str
    subfolder: str
    llm_backend: str = "claude"
    default: bool = False

    def resolve_subfolder(self, vault_path: pathlib.Path) -> pathlib.Path:
        """Return the absolute path to this org's subfolder under the vault."""
        if not self.subfolder:
            return vault_path
        return vault_path / self.subfolder
```

Add a method to `DaemonConfig`:

```python
def org_by_slug(self, slug: str) -> Optional[OrgConfig]:
    """Return the org config with matching slug, or None. Case-sensitive."""
    for org in self._orgs:
        if org.name == slug:
            return org
    return None
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_daemon_config_helpers.py -v`
Expected: PASS.

Run: `uv run pytest -q`
Expected: full suite still passes.

**Step 5: Commit**

```bash
git add recap/daemon/config.py tests/test_daemon_config_helpers.py
git commit -m "feat: add OrgConfig.resolve_subfolder and DaemonConfig.org_by_slug"
```

---

## Task 2: Kill `org_subfolder()` in `sync.py`; `write_calendar_note` takes `OrgConfig`

**Context:** Today, `recap/daemon/calendar/sync.py:36-38` hardcodes `_Recap/<Capitalized>`. This is the second half of Codex's org-bifurcation bug (Phase 1 fixed the pipeline side). After this task, calendar notes are written under the user-configured subfolder, identical to the pipeline.

**Files:**
- Modify: `recap/daemon/calendar/sync.py`
- Modify: `tests/test_calendar_sync.py`

**Step 1: Update / add failing tests**

Find existing tests in `tests/test_calendar_sync.py` that pass a string `org` to `write_calendar_note`. They need to pass an `OrgConfig` instead. Update them. Additionally, add a new test that explicitly exercises the configured subfolder:

```python
def test_write_calendar_note_uses_configured_subfolder(tmp_path):
    from recap.daemon.calendar.sync import CalendarEvent, write_calendar_note
    from recap.daemon.config import OrgConfig

    org = OrgConfig(name="disbursecloud", subfolder="Clients/Disbursecloud")
    event = CalendarEvent(
        event_id="evt-1",
        title="Meeting",
        date="2026-04-14",
        time="14:00-15:00",
        participants=["Alice"],
        calendar_source="google",
        org="disbursecloud",  # still the slug — frontmatter identity
        meeting_link="https://meet.google.com/x",
        description="",
    )

    note_path = write_calendar_note(event, tmp_path, org)
    assert note_path == tmp_path / "Clients/Disbursecloud/Meetings/2026-04-14 - meeting.md"
    assert note_path.exists()


def test_write_calendar_note_frontmatter_org_is_slug_not_subfolder(tmp_path):
    import yaml
    from recap.daemon.calendar.sync import CalendarEvent, write_calendar_note
    from recap.daemon.config import OrgConfig

    org = OrgConfig(name="disbursecloud", subfolder="Clients/Disbursecloud")
    event = CalendarEvent(
        event_id="evt-1", title="X", date="2026-04-14", time="09:00-10:00",
        participants=[], calendar_source="google", org="disbursecloud",
        meeting_link="", description="",
    )
    note_path = write_calendar_note(event, tmp_path, org)
    content = note_path.read_text(encoding="utf-8")
    _, fm_block, _ = content.split("---\n", 2)
    fm = yaml.safe_load(fm_block)
    assert fm["org"] == "disbursecloud"  # slug, not the folder path
    # Subfolder is part of file layout, not part of the stored metadata.
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_calendar_sync.py -v`
Expected: some tests fail (signature change + new assertions).

**Step 3: Implement**

In `recap/daemon/calendar/sync.py`:

- Delete `org_subfolder()` function entirely (lines ~28–38).
- Change `write_calendar_note` signature to take `org_config: OrgConfig` instead of reading a free string. Replace `subfolder = org_subfolder(event.org)` with `meetings_dir = org_config.resolve_subfolder(vault_path) / "Meetings"`.
- Change `should_update_note` signature to take `org_config: OrgConfig` instead of `org_subfolder: str`. Replace `meetings_dir = vault_path / org_subfolder / "Meetings"` with `meetings_dir = org_config.resolve_subfolder(vault_path) / "Meetings"`.
- The import at the top of `sync.py`: add `from recap.daemon.config import OrgConfig` behind a `TYPE_CHECKING` block if needed to avoid circular imports; otherwise direct import is fine (config.py does not import from sync.py).

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_calendar_sync.py -v`
Expected: PASS. Run full suite: `uv run pytest -q`. Full suite may fail at scheduler call sites — that's Task 3.

If the full suite fails ONLY in `tests/test_calendar_scheduler.py` (which still calls the old signatures), that's expected. Continue to Task 3.

**Step 5: Commit**

```bash
git add recap/daemon/calendar/sync.py tests/test_calendar_sync.py
git commit -m "refactor: write_calendar_note takes OrgConfig, drop hardcoded subfolder"
```

---

## Task 3: Update scheduler callers

**Files:**
- Modify: `recap/daemon/calendar/scheduler.py`
- Modify: `tests/test_calendar_scheduler.py`

**Step 1: Establish baseline and identify breakage**

Run: `uv run pytest tests/test_calendar_scheduler.py -v`
Expected: failures stemming from Task 2's signature changes.

**Step 2: Update `scheduler.py`**

Remove the `org_subfolder` import from `recap.daemon.calendar.sync`. Scheduler's import block becomes:

```python
from recap.daemon.calendar.sync import (
    CalendarEvent,
    find_note_by_event_id,
    should_update_note,
    update_calendar_note,
    write_calendar_note,
)
```

At scheduler.py:106, replace:

```python
subfolder = org_subfolder(event.org)
# ...uses `subfolder` as a str path...
meetings_dir = vault_path / subfolder / "Meetings"
```

with:

```python
org_config = self._config.org_by_slug(event.org)
if org_config is None:
    logger.warning("No OrgConfig for slug %s; skipping event %s", event.org, event.event_id)
    continue
meetings_dir = org_config.resolve_subfolder(self._vault_path) / "Meetings"
```

At line ~120 (the `find_note_by_event_id` call), the meetings_dir is already computed via the code above.

At the `write_calendar_note` / `should_update_note` call sites, pass `org_config` instead of a string.

**Step 3: Update scheduler tests**

Tests that set up `write_calendar_note` / `should_update_note` will need to build a `DaemonConfig` with at least one `OrgConfig` so `org_by_slug` returns something. Use the `_make_config_with_orgs` helper pattern from Task 1 or define a local fixture.

**Step 4: Run tests**

Run: `uv run pytest tests/test_calendar_scheduler.py -v`
Expected: PASS.

Run: `uv run pytest -q`
Expected: full suite passes (Tasks 2+3 together close the first half of the Phase 2 work).

**Step 5: Commit**

```bash
git add recap/daemon/calendar/scheduler.py tests/test_calendar_scheduler.py
git commit -m "refactor: scheduler resolves subfolder via OrgConfig"
```

---

## Task 4: `EventIndex` class with rebuild + persistence

**Context:** Single source of truth for event-id → note path. Path format is vault-relative from Day 1 so Phase 2 Task 8 (note_path normalization) can use it unchanged.

**Files:**
- Create: `recap/daemon/calendar/index.py`
- Create: `tests/test_event_index.py`

**Step 1: Write failing tests**

```python
"""Tests for the event-id index."""
from __future__ import annotations

import json
import pathlib

from recap.daemon.calendar.index import EventIndex


def _make_index(tmp_path: pathlib.Path) -> EventIndex:
    return EventIndex(tmp_path / "_Recap" / ".recap" / "event-index.json")


class TestEventIndexAddLookup:
    def test_add_then_lookup_returns_stored_entry(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.add("evt-1", pathlib.Path("Clients/Disbursecloud/Meetings/2026-04-14 - q2.md"), "disbursecloud")
        entry = idx.lookup("evt-1")
        assert entry is not None
        assert entry.path == pathlib.Path("Clients/Disbursecloud/Meetings/2026-04-14 - q2.md")
        assert entry.org == "disbursecloud"

    def test_lookup_missing_returns_none(self, tmp_path):
        idx = _make_index(tmp_path)
        assert idx.lookup("nope") is None

    def test_add_overwrites_existing_entry(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.add("evt-1", pathlib.Path("old.md"), "o")
        idx.add("evt-1", pathlib.Path("new.md"), "o")
        assert idx.lookup("evt-1").path == pathlib.Path("new.md")


class TestEventIndexRemoveRename:
    def test_remove_deletes_entry(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.add("evt-1", pathlib.Path("x.md"), "o")
        idx.remove("evt-1")
        assert idx.lookup("evt-1") is None

    def test_remove_nonexistent_is_noop(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.remove("evt-1")  # must not raise

    def test_rename_updates_path(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.add("evt-1", pathlib.Path("old.md"), "o")
        idx.rename("evt-1", pathlib.Path("new.md"))
        assert idx.lookup("evt-1").path == pathlib.Path("new.md")

    def test_rename_nonexistent_is_noop(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.rename("evt-1", pathlib.Path("x.md"))  # must not raise
        assert idx.lookup("evt-1") is None


class TestEventIndexPersistence:
    def test_add_persists_to_disk(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.add("evt-1", pathlib.Path("x.md"), "o")
        index_file = tmp_path / "_Recap" / ".recap" / "event-index.json"
        assert index_file.exists()
        data = json.loads(index_file.read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert "evt-1" in data["entries"]
        assert data["entries"]["evt-1"]["path"] == "x.md"
        assert data["entries"]["evt-1"]["org"] == "o"
        assert "mtime" in data["entries"]["evt-1"]

    def test_new_instance_reads_persisted_index(self, tmp_path):
        idx1 = _make_index(tmp_path)
        idx1.add("evt-1", pathlib.Path("x.md"), "o")
        # Fresh instance pointed at the same file
        idx2 = _make_index(tmp_path)
        assert idx2.lookup("evt-1") is not None


class TestEventIndexRebuild:
    def test_rebuild_scans_vault_and_populates_entries(self, tmp_path):
        # Arrange: calendar-seeded notes on disk
        meetings = tmp_path / "Clients/Disbursecloud/Meetings"
        meetings.mkdir(parents=True)
        (meetings / "2026-04-14 - a.md").write_text(
            "---\nevent-id: evt-a\norg: disbursecloud\n---\n\n## Agenda\n", encoding="utf-8"
        )
        (meetings / "2026-04-15 - b.md").write_text(
            "---\nevent-id: evt-b\norg: disbursecloud\n---\n\n## Agenda\n", encoding="utf-8"
        )
        # A note without event-id — should be skipped
        (meetings / "2026-04-16 - adhoc.md").write_text(
            "---\ntitle: adhoc\n---\n\nbody\n", encoding="utf-8"
        )

        idx = _make_index(tmp_path)
        idx.rebuild(tmp_path)

        assert idx.lookup("evt-a") is not None
        assert idx.lookup("evt-a").path == pathlib.Path("Clients/Disbursecloud/Meetings/2026-04-14 - a.md")
        assert idx.lookup("evt-b") is not None
        # Note without event-id is not indexed
        assert len([e for e in idx.all_entries() if e.event_id == "adhoc"]) == 0

    def test_rebuild_replaces_stale_entries(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.add("evt-stale", pathlib.Path("nonexistent.md"), "o")
        # No notes on disk → rebuild should drop the stale entry
        idx.rebuild(tmp_path)
        assert idx.lookup("evt-stale") is None

    def test_all_entries_returns_list(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.add("evt-1", pathlib.Path("a.md"), "o")
        idx.add("evt-2", pathlib.Path("b.md"), "o")
        entries = idx.all_entries()
        assert {e.event_id for e in entries} == {"evt-1", "evt-2"}
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_event_index.py -v`
Expected: FAIL — module does not exist.

**Step 3: Implement**

Create `recap/daemon/calendar/index.py`:

```python
"""Persistent event-id → note path index.

Path format is vault-relative. Consumers anchor against the vault root when
they need an absolute path.

Schema v1:
{
  "version": 1,
  "entries": {
    "<event_id>": {"path": "Clients/X/Meetings/2026-04-14 - foo.md", "org": "x", "mtime": "2026-04-14T14:30:00"}
  }
}
"""
from __future__ import annotations

import json
import logging
import pathlib
import threading
from dataclasses import dataclass
from datetime import datetime

import yaml

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class IndexEntry:
    event_id: str
    path: pathlib.Path   # vault-relative
    org: str
    mtime: str           # ISO timestamp


class EventIndex:
    """Thread-safe JSON-backed event-id index.

    All writes persist immediately. Stores vault-relative paths; callers
    combine with vault_path when they need absolute paths.
    """

    def __init__(self, path: pathlib.Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._entries: dict[str, IndexEntry] = {}
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lookup(self, event_id: str) -> IndexEntry | None:
        with self._lock:
            return self._entries.get(event_id)

    def add(self, event_id: str, path: pathlib.Path, org: str) -> None:
        """Insert or replace an entry. Path must be vault-relative."""
        with self._lock:
            self._entries[event_id] = IndexEntry(
                event_id=event_id,
                path=pathlib.Path(path),
                org=org,
                mtime=datetime.now().isoformat(timespec="seconds"),
            )
            self._persist_locked()

    def remove(self, event_id: str) -> None:
        with self._lock:
            if event_id in self._entries:
                del self._entries[event_id]
                self._persist_locked()

    def rename(self, event_id: str, new_path: pathlib.Path) -> None:
        """Update path for an existing entry. No-op if entry missing."""
        with self._lock:
            existing = self._entries.get(event_id)
            if existing is None:
                return
            self._entries[event_id] = IndexEntry(
                event_id=event_id,
                path=pathlib.Path(new_path),
                org=existing.org,
                mtime=datetime.now().isoformat(timespec="seconds"),
            )
            self._persist_locked()

    def rebuild(self, vault_path: pathlib.Path) -> None:
        """Scan the vault for notes with event-id frontmatter and repopulate.

        Drops any stale entries pointing to notes that no longer exist or no
        longer have a matching event-id.
        """
        with self._lock:
            new_entries: dict[str, IndexEntry] = {}
            recap_root = vault_path
            if not recap_root.exists():
                self._entries = new_entries
                self._persist_locked()
                return

            for md_file in recap_root.rglob("Meetings/*.md"):
                try:
                    content = md_file.read_text(encoding="utf-8")
                except OSError:
                    continue
                fm = _parse_frontmatter(content)
                if fm is None:
                    continue
                event_id = fm.get("event-id")
                org = fm.get("org")
                if not event_id:
                    continue
                rel = md_file.relative_to(vault_path)
                new_entries[str(event_id)] = IndexEntry(
                    event_id=str(event_id),
                    path=rel,
                    org=str(org) if org else "",
                    mtime=datetime.fromtimestamp(md_file.stat().st_mtime).isoformat(timespec="seconds"),
                )
            self._entries = new_entries
            self._persist_locked()

    def all_entries(self) -> list[IndexEntry]:
        with self._lock:
            return list(self._entries.values())

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load event index at %s: %s", self._path, exc)
            return
        if data.get("version") != _SCHEMA_VERSION:
            logger.warning(
                "Unexpected event-index schema version %s; ignoring", data.get("version"),
            )
            return
        for event_id, raw in data.get("entries", {}).items():
            self._entries[event_id] = IndexEntry(
                event_id=event_id,
                path=pathlib.Path(raw["path"]),
                org=raw.get("org", ""),
                mtime=raw.get("mtime", ""),
            )

    def _persist_locked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": _SCHEMA_VERSION,
            "entries": {
                eid: {
                    "path": str(entry.path).replace("\\", "/"),
                    "org": entry.org,
                    "mtime": entry.mtime,
                }
                for eid, entry in self._entries.items()
            },
        }
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _parse_frontmatter(content: str) -> dict | None:
    content = content.replace("\r\n", "\n")
    parts = content.split("---\n", 2)
    if len(parts) < 3:
        return None
    try:
        return yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_event_index.py -v`
Expected: PASS for every case.

Run: `uv run pytest -q`
Expected: full suite passes (this task adds new code; no existing call sites reference `EventIndex` yet).

**Step 5: Commit**

```bash
git add recap/daemon/calendar/index.py tests/test_event_index.py
git commit -m "feat: persistent EventIndex with rebuild and thread-safe writes"
```

---

## Task 5: Wire `EventIndex.add` / `.remove` into write paths

**Context:** The index is useless if nothing updates it. Two write paths need hooks:
1. `upsert_note` (pipeline path) — when frontmatter has `event-id`, add/update.
2. `write_calendar_note` (calendar sync path) — always has `event-id`; add on write.

**Files:**
- Modify: `recap/vault.py`
- Modify: `recap/daemon/calendar/sync.py`
- Modify: `tests/test_vault_upsert.py`
- Modify: `tests/test_calendar_sync.py`

**Step 1: Add the index-hook arg to both writers (optional)**

`upsert_note` and `write_calendar_note` should both accept `event_index: EventIndex | None = None`. When provided and frontmatter/event has an `event-id`, the writer calls `event_index.add(event_id, vault_relative_path, org)`.

**Step 2: Write failing tests**

Append to `tests/test_vault_upsert.py`:

```python
class TestUpsertIndexIntegration:
    def test_upsert_adds_to_index_when_frontmatter_has_event_id(self, tmp_path):
        from recap.daemon.calendar.index import EventIndex
        from recap.vault import upsert_note

        vault = tmp_path / "vault"
        meetings_dir = vault / "Clients/Disbursecloud/Meetings"
        note_path = meetings_dir / "2026-04-14 - q2.md"

        index = EventIndex(vault / "_Recap" / ".recap" / "event-index.json")

        frontmatter = {
            "date": "2026-04-14",
            "title": "Q2",
            "org": "disbursecloud",
            "event-id": "evt-abc",
            "pipeline-status": "complete",
        }
        body = "## Summary\n\nHi.\n"

        upsert_note(note_path, frontmatter, body, event_index=index, vault_path=vault)

        entry = index.lookup("evt-abc")
        assert entry is not None
        assert entry.path == pathlib.Path("Clients/Disbursecloud/Meetings/2026-04-14 - q2.md")
        assert entry.org == "disbursecloud"

    def test_upsert_without_event_id_does_not_touch_index(self, tmp_path):
        from recap.daemon.calendar.index import EventIndex
        from recap.vault import upsert_note

        vault = tmp_path / "vault"
        note_path = vault / "Personal/Meetings/2026-04-14 - adhoc.md"
        index = EventIndex(vault / "_Recap" / ".recap" / "event-index.json")

        upsert_note(
            note_path,
            {"date": "2026-04-14", "title": "Adhoc", "org": "personal", "pipeline-status": "complete"},
            "## Summary\n\nx\n",
            event_index=index,
            vault_path=vault,
        )
        assert index.all_entries() == []
```

Append to `tests/test_calendar_sync.py`:

```python
def test_write_calendar_note_adds_to_index_when_provided(tmp_path):
    from recap.daemon.calendar.index import EventIndex
    from recap.daemon.calendar.sync import CalendarEvent, write_calendar_note
    from recap.daemon.config import OrgConfig

    org = OrgConfig(name="d", subfolder="Clients/D")
    event = CalendarEvent(
        event_id="evt-1", title="M", date="2026-04-14", time="09:00-10:00",
        participants=[], calendar_source="google", org="d",
        meeting_link="", description="",
    )
    index = EventIndex(tmp_path / "_Recap" / ".recap" / "event-index.json")
    note_path = write_calendar_note(event, tmp_path, org, event_index=index)

    entry = index.lookup("evt-1")
    assert entry is not None
    assert entry.path == note_path.relative_to(tmp_path)
```

**Step 3: Run to verify failure**

Run: `uv run pytest tests/test_vault_upsert.py::TestUpsertIndexIntegration tests/test_calendar_sync.py::test_write_calendar_note_adds_to_index_when_provided -v`
Expected: FAIL — kwargs not accepted.

**Step 4: Implement**

In `recap/vault.py: upsert_note`:

```python
def upsert_note(
    note_path: pathlib.Path,
    frontmatter: dict,
    body: str,
    *,
    event_index: "EventIndex | None" = None,
    vault_path: pathlib.Path | None = None,
) -> None:
    # ... existing body ...
    # After the write branches return successfully:
    _update_index_if_applicable(note_path, frontmatter, event_index, vault_path)
```

Add helper at module level:

```python
def _update_index_if_applicable(
    note_path: pathlib.Path,
    frontmatter: dict,
    event_index: "EventIndex | None",
    vault_path: pathlib.Path | None,
) -> None:
    if event_index is None or vault_path is None:
        return
    event_id = frontmatter.get("event-id")
    if not event_id:
        return
    try:
        rel_path = note_path.relative_to(vault_path)
    except ValueError:
        # note_path outside vault — skip (shouldn't happen in production)
        return
    event_index.add(str(event_id), rel_path, str(frontmatter.get("org", "")))
```

Restructure `upsert_note` so every branch falls through to `_update_index_if_applicable`:

```python
def upsert_note(note_path, frontmatter, body, *, event_index=None, vault_path=None):
    note_path.parent.mkdir(parents=True, exist_ok=True)

    if not note_path.exists():
        _write_new_note(note_path, frontmatter, body)
    else:
        existing = note_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        has_frontmatter = existing.startswith("---\n") and existing.count("---\n") >= 2
        has_marker = MEETING_RECORD_MARKER in existing

        if not has_frontmatter and not has_marker:
            _prepend_fm_and_append_body(note_path, existing, frontmatter, body)
        elif has_frontmatter and not has_marker:
            _merge_fm_and_append_body(note_path, existing, frontmatter, body)
        elif has_marker and not has_frontmatter:
            _prepend_fm_and_replace_below_marker(note_path, existing, frontmatter, body)
        else:
            _merge_fm_and_replace_below_marker(note_path, existing, frontmatter, body)

    _update_index_if_applicable(note_path, frontmatter, event_index, vault_path)
```

In `recap/daemon/calendar/sync.py: write_calendar_note`:

```python
def write_calendar_note(
    event: CalendarEvent,
    vault_path: Path,
    org_config: "OrgConfig",
    *,
    event_index: "EventIndex | None" = None,
) -> Path:
    # ... existing body ...
    # After note_path.write_text(...):
    if event_index is not None and event.event_id:
        try:
            rel_path = note_path.relative_to(vault_path)
            event_index.add(event.event_id, rel_path, event.org)
        except ValueError:
            logger.warning("Note written outside vault root: %s", note_path)
    return note_path
```

Callers (`run_pipeline`, scheduler) wire the index through in Task 6.

**Step 5: Run to verify pass**

Run: `uv run pytest -q`
Expected: full suite passes. New tests validate the index-hook behavior.

**Step 6: Commit**

```bash
git add recap/vault.py recap/daemon/calendar/sync.py tests/test_vault_upsert.py tests/test_calendar_sync.py
git commit -m "feat: write paths update EventIndex when event_id is present"
```

---

## Task 6: `find_note_by_event_id` delegates to `EventIndex`; update callers

**Files:**
- Modify: `recap/daemon/calendar/sync.py`
- Modify: `recap/pipeline/__init__.py`
- Modify: `recap/daemon/calendar/scheduler.py`
- Modify: `recap/daemon/recorder/detector.py`
- Create/modify: `tests/test_calendar_sync.py` (index-backed path)

**Step 1: Add failing test**

```python
def test_find_note_by_event_id_uses_index_when_provided(tmp_path):
    from recap.daemon.calendar.index import EventIndex
    from recap.daemon.calendar.sync import find_note_by_event_id

    vault = tmp_path
    meetings = vault / "Clients/D/Meetings"
    meetings.mkdir(parents=True)
    note = meetings / "2026-04-14 - x.md"
    note.write_text("---\nevent-id: evt-1\n---\n\nbody\n", encoding="utf-8")

    index = EventIndex(vault / "_Recap" / ".recap" / "event-index.json")
    index.add("evt-1", note.relative_to(vault), "d")

    result = find_note_by_event_id("evt-1", meetings, vault_path=vault, event_index=index)
    assert result == note


def test_find_note_by_event_id_falls_back_to_scan_without_index(tmp_path):
    from recap.daemon.calendar.sync import find_note_by_event_id

    meetings = tmp_path / "Meetings"
    meetings.mkdir()
    note = meetings / "2026-04-14 - a.md"
    note.write_text("---\nevent-id: evt-1\n---\n\nbody\n", encoding="utf-8")

    # No index → falls back to O(n) scan
    result = find_note_by_event_id("evt-1", meetings)
    assert result == note
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_calendar_sync.py::test_find_note_by_event_id_uses_index_when_provided -v`
Expected: FAIL — kwargs not accepted.

**Step 3: Implement**

Change `find_note_by_event_id` signature:

```python
def find_note_by_event_id(
    event_id: str,
    search_path: Path,
    *,
    vault_path: Path | None = None,
    event_index: "EventIndex | None" = None,
) -> Path | None:
    """Find a note by event-id. Uses index when provided; else scans."""
    if event_index is not None and vault_path is not None:
        entry = event_index.lookup(event_id)
        if entry is not None:
            abs_path = vault_path / entry.path
            if abs_path.exists():
                return abs_path
            # Stale index entry — log a warning and fall through to scan.
            logger.warning(
                "Stale EventIndex entry for %s: %s does not exist; falling back to scan",
                event_id, abs_path,
            )
    if not search_path.exists():
        return None
    for md_file in search_path.glob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        fm = _parse_frontmatter(content)
        if fm and fm.get("event-id") == event_id:
            return md_file
    return None
```

Ensure `logger` is available in `sync.py` (add `logger = logging.getLogger(__name__)` if missing). Add a test that exercises the stale-entry path via `caplog`:

```python
def test_find_note_by_event_id_logs_warning_on_stale_entry(tmp_path, caplog):
    import logging
    from recap.daemon.calendar.index import EventIndex
    from recap.daemon.calendar.sync import find_note_by_event_id

    vault = tmp_path
    meetings = vault / "Clients/D/Meetings"
    meetings.mkdir(parents=True)
    # Index points at a note that never existed
    index = EventIndex(vault / "_Recap" / ".recap" / "event-index.json")
    index.add("evt-1", pathlib.Path("Clients/D/Meetings/gone.md"), "d")

    with caplog.at_level(logging.WARNING, logger="recap.daemon.calendar.sync"):
        result = find_note_by_event_id(
            "evt-1", meetings, vault_path=vault, event_index=index,
        )
    assert result is None
    assert any("Stale EventIndex entry" in rec.message for rec in caplog.records)
```

Update callers to pass `event_index` and `vault_path` when they have them:
- `recap/pipeline/__init__.py:_resolve_note_path` — needs `event_index` and `vault_path` as args. See Task 7 for the full signature change.
- `recap/daemon/calendar/scheduler.py:120` — scheduler has `self._vault_path` and will get an `event_index` injected in Task 8.
- `recap/daemon/recorder/detector.py:95` — detector has `self._config.vault_path` and needs access to the index. Inject via constructor (see Task 8).

For this task, keep the existing no-kwargs callers working via the fallback. New kwargs just enable the fast path.

**Step 4: Run tests**

Run: `uv run pytest -q`
Expected: full suite passes.

**Step 5: Commit**

```bash
git add recap/daemon/calendar/sync.py tests/test_calendar_sync.py
git commit -m "feat: find_note_by_event_id consults EventIndex with scan fallback"
```

---

## Task 7: Normalize `note_path` to vault-relative

**Context:** Codex's deferred P2. Today `RecordingMetadata.note_path` is stored as an absolute string. Design doc §0.3 says vault-relative. Phase 2's `EventIndex` already stores vault-relative paths; aligning `note_path` removes the last inconsistency.

**Files:**
- Modify: `recap/pipeline/__init__.py` (resolver + write points)
- Modify: `recap/daemon/__main__.py` (write point in `process_recording`)
- Modify: `recap/daemon/recorder/detector.py` (`_find_calendar_note` returns vault-relative)
- Modify: `recap/artifacts.py` — add a helper to read absolute-or-relative `note_path` against a vault root, for legacy support
- Modify: `tests/test_pipeline.py`, `tests/test_detector.py`, `tests/test_recorder_orchestrator.py`

**Step 1: Add failing tests**

In `tests/test_pipeline.py` (append):

```python
def test_run_pipeline_writes_vault_relative_note_path(tmp_path):
    """After Phase 2, recording_metadata.note_path is vault-relative after pipeline run."""
    from recap.artifacts import (
        save_transcript, save_analysis, load_recording_metadata, RecordingMetadata,
    )
    from recap.models import (
        AnalysisResult, MeetingMetadata, Participant, ProfileStub,
        TranscriptResult, Utterance,
    )
    from recap.pipeline import run_pipeline, PipelineRuntimeConfig
    from datetime import date

    audio_path = tmp_path / "2026-04-14-140000-d.flac"
    audio_path.touch()
    save_transcript(audio_path, TranscriptResult(
        utterances=[Utterance(speaker="Alice", start=0, end=1, text="hi")],
        raw_text="hi", language="en",
    ))
    save_analysis(audio_path, AnalysisResult(
        speaker_mapping={}, meeting_type="standup", summary="s",
        key_points=[], decisions=[], action_items=[], follow_ups=[],
        relationship_notes=None, people=[], companies=[],
    ))
    metadata = MeetingMetadata(
        title="Standup", date=date(2026, 4, 14), participants=[Participant(name="Alice")], platform="manual",
    )
    recording_metadata = RecordingMetadata(
        org="d", note_path="", title="Standup", date="2026-04-14",
        participants=[Participant(name="Alice")], platform="manual",
    )
    vault = tmp_path / "vault"
    config = PipelineRuntimeConfig(archive_format="flac")

    run_pipeline(
        audio_path=audio_path, metadata=metadata, config=config,
        org_slug="d", org_subfolder="DFolder", vault_path=vault, user_name="T",
        from_stage="export", recording_metadata=recording_metadata,
    )

    # After the run, metadata file should have a vault-relative note_path
    reloaded = load_recording_metadata(audio_path)
    assert reloaded is not None
    assert reloaded.note_path  # non-empty
    assert not pathlib.Path(reloaded.note_path).is_absolute()
    # And the path should resolve correctly
    abs_path = vault / reloaded.note_path
    assert abs_path.exists()


def test_run_pipeline_reads_legacy_absolute_note_path(tmp_path):
    """Legacy metadata files with absolute note_path should still work."""
    from recap.artifacts import (
        save_transcript, save_analysis, write_recording_metadata, RecordingMetadata,
    )
    from recap.models import (
        AnalysisResult, MeetingMetadata, Participant, ProfileStub,
        TranscriptResult, Utterance,
    )
    from recap.pipeline import run_pipeline, PipelineRuntimeConfig
    from datetime import date

    audio_path = tmp_path / "rec.flac"
    audio_path.touch()
    save_transcript(audio_path, TranscriptResult(
        utterances=[Utterance(speaker="A", start=0, end=1, text="hi")], raw_text="hi", language="en",
    ))
    save_analysis(audio_path, AnalysisResult(
        speaker_mapping={}, meeting_type="standup", summary="s",
        key_points=[], decisions=[], action_items=[], follow_ups=[],
        relationship_notes=None, people=[], companies=[],
    ))

    vault = tmp_path / "vault"
    meetings = vault / "DFolder/Meetings"
    meetings.mkdir(parents=True)
    legacy_note = meetings / "2026-04-14 - Standup.md"
    legacy_note.write_text("---\ndate: 2026-04-14\n---\n\n## Agenda\n", encoding="utf-8")

    recording_metadata = RecordingMetadata(
        org="d", note_path=str(legacy_note),  # absolute — legacy shape
        title="Standup", date="2026-04-14", participants=[], platform="manual",
    )
    write_recording_metadata(audio_path, recording_metadata)

    metadata = MeetingMetadata(
        title="Standup", date=date(2026, 4, 14), participants=[], platform="manual",
    )
    config = PipelineRuntimeConfig(archive_format="flac")

    run_pipeline(
        audio_path=audio_path, metadata=metadata, config=config,
        org_slug="d", org_subfolder="DFolder", vault_path=vault, user_name="T",
        from_stage="export", recording_metadata=recording_metadata,
    )

    # The absolute path was resolved correctly and the note was updated
    content = legacy_note.read_text(encoding="utf-8")
    assert "pipeline-status: complete" in content
```

**Step 2: Run to verify failure**

Run these two tests — the first fails because `note_path` is still stored as absolute. The second may pass today (legacy is the current shape) but locks it in.

**Step 3: Implement**

Add a helper to `recap/artifacts.py`:

```python
def resolve_note_path(note_path_str: str, vault_path: pathlib.Path) -> pathlib.Path:
    """Resolve a stored note_path against the vault root.

    Accepts both absolute (legacy) and vault-relative (new) forms.
    """
    p = pathlib.Path(note_path_str)
    if p.is_absolute():
        return p
    return vault_path / p


def to_vault_relative(note_path: pathlib.Path, vault_path: pathlib.Path) -> str:
    """Convert an absolute path to a vault-relative string with forward slashes."""
    try:
        return str(note_path.relative_to(vault_path)).replace("\\", "/")
    except ValueError:
        # Path is outside vault — return as-is (degraded mode)
        return str(note_path)
```

In `recap/pipeline/__init__.py`:

- `_resolve_note_path` gains a `vault_path: pathlib.Path` parameter and a new optional `event_index` (from Task 6):
  ```python
  def _resolve_note_path(
      metadata, recording_metadata, meetings_dir, vault_path, event_index=None,
  ):
      from recap.artifacts import resolve_note_path
      if recording_metadata is not None:
          if recording_metadata.note_path:
              return resolve_note_path(recording_metadata.note_path, vault_path)
          if recording_metadata.event_id:
              from recap.daemon.calendar.sync import find_note_by_event_id
              note = find_note_by_event_id(
                  recording_metadata.event_id, meetings_dir,
                  vault_path=vault_path, event_index=event_index,
              )
              if note is not None:
                  recording_metadata.note_path = to_vault_relative(note, vault_path)
                  return note
      return meetings_dir / f"{metadata.date.isoformat()} - {safe_note_title(metadata.title)}.md"
  ```

- In `run_pipeline`, replace the write points where `recording_metadata.note_path` is assigned with calls to `to_vault_relative`:
  ```python
  if recording_metadata is not None and ...:
      recording_metadata.note_path = to_vault_relative(note_path, vault_path)
      write_recording_metadata(audio_path, recording_metadata)
  ```

- Update the call site of `_resolve_note_path` in `run_pipeline` to pass `vault_path`.

In `recap/daemon/__main__.py`:

- `process_recording` assigns `recording_metadata.note_path = str(note_path)`. Change to `to_vault_relative(note_path, config.vault_path)`.

In `recap/daemon/recorder/detector.py:_find_calendar_note`:

- Returns `str(note)` — change to `to_vault_relative(note, self._config.vault_path)`.

**Step 4: Run tests**

Run: `uv run pytest -q`
Expected: full suite passes, including the new vault-relative + legacy-migration tests.

**Step 5: Commit**

```bash
git add recap/artifacts.py recap/pipeline/__init__.py recap/daemon/__main__.py recap/daemon/recorder/detector.py tests/test_pipeline.py
git commit -m "refactor: note_path stored as vault-relative with legacy absolute support"
```

---

## Task 8: Wire `EventIndex` through the daemon service graph

**Context:** Tasks 4-7 gave us the index and the fast-path code. Tasks 8 connects the daemon runtime: one `EventIndex` instance is constructed at startup, rebuilt on demand, and injected into the scheduler, detector, and pipeline callers.

**Files:**
- Modify: `recap/daemon/__main__.py`
- Modify: `recap/daemon/calendar/scheduler.py`
- Modify: `recap/daemon/recorder/detector.py`
- Modify: `recap/pipeline/__init__.py` (accept `event_index` via a new optional arg to `run_pipeline`)

**Step 1: Implement**

In `__main__.py`:

```python
from recap.daemon.calendar.index import EventIndex

# Near the top of main(), after config is loaded:
event_index_path = config.vault_path / "_Recap" / ".recap" / "event-index.json"
event_index = EventIndex(event_index_path)
# Always rebuild on startup — cheap, heals drift from out-of-band renames
# or corrupt persisted indexes. Decision locked per Codex review 2026-04-14.
logger.info("Rebuilding EventIndex from vault (startup)")
event_index.rebuild(config.vault_path)
```

Pass `event_index` into:
- `MeetingDetector(config=..., recorder=..., on_signal_detected=..., event_index=event_index)` — add field + constructor arg.
- `CalendarSyncScheduler(config=..., vault_path=..., detector=..., on_rename_queued=..., event_index=event_index)` — same.
- `_make_process_recording(config, recorder, emit_event, event_index)` so `run_pipeline(..., event_index=event_index)` can be passed.

Update `run_pipeline` signature to accept `event_index: EventIndex | None = None`, thread it into `_resolve_note_path`, and pass it to `write_meeting_note` when it calls `upsert_note` via... actually `write_meeting_note` needs to accept `event_index` + `vault_path` too, to pass through. Update its signature.

In `detector.py` and `scheduler.py`, use `self._event_index` (and pass `self._vault_path` / `self._config.vault_path`) to the `find_note_by_event_id` call sites.

**Step 2: No scheduler-tick rebuild — startup-only**

**Decision locked (Codex review 2026-04-14):**
1. No scheduler-on-sync rebuild. Normal write paths (`upsert_note` + `write_calendar_note`) keep the index warm; a repeated whole-vault scan per sync tick is wasted work for a drift case Phase 4's rename endpoint will handle properly.
2. Startup rebuild is unconditional (not conditional on the file existing). A stale or corrupt persisted index should not be able to survive a restart. The rebuild is cheap and gives us "heal drift on launch" for free.
3. On a stale-lookup (index entry points at a file that no longer exists), Task 6's `find_note_by_event_id` already logs a warning and falls back to scan. Verify that warning fires via `caplog` in the Task 6 test.

Do NOT add a scheduler rebuild hook. Do NOT make the startup rebuild conditional. An Obsidian-side rename will cause a stale index entry until the next daemon restart; the warning log + fallback scan + Phase 4 rename endpoint make that acceptable.

**Step 3: Run tests**

Run: `uv run pytest -q`
Expected: full suite passes.

**Step 4: Commit**

```bash
git add recap/daemon/__main__.py recap/daemon/calendar/scheduler.py recap/daemon/recorder/detector.py recap/pipeline/__init__.py recap/vault.py
git commit -m "feat: inject EventIndex through daemon service graph"
```

---

## Task 9: End-to-end integration test

**Files:**
- Create: `tests/test_phase2_integration.py`

**Step 1: Write the test**

```python
"""Phase 2 integration: calendar sync → note → pipeline → index stays consistent."""
from __future__ import annotations

import pathlib
from datetime import date
from unittest.mock import patch

import yaml

from recap.artifacts import (
    RecordingMetadata, save_analysis, save_transcript,
)
from recap.daemon.calendar.index import EventIndex
from recap.daemon.calendar.sync import CalendarEvent, write_calendar_note
from recap.daemon.config import OrgConfig
from recap.models import (
    AnalysisResult, MeetingMetadata, Participant, ProfileStub,
    TranscriptResult, Utterance,
)
from recap.pipeline import run_pipeline, PipelineRuntimeConfig


def test_calendar_event_flow_to_pipeline_with_index(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    index_path = vault / "_Recap" / ".recap" / "event-index.json"
    index = EventIndex(index_path)

    # Calendar sync creates the note and populates the index
    org = OrgConfig(name="disbursecloud", subfolder="Clients/Disbursecloud")
    event = CalendarEvent(
        event_id="evt-integration",
        title="Q2 Review",
        date="2026-04-14",
        time="14:00-15:00",
        participants=["Alice", "Bob"],
        calendar_source="google",
        org="disbursecloud",
        meeting_link="https://meet.google.com/abc",
        description="Q2 agenda",
    )
    calendar_note = write_calendar_note(event, vault, org, event_index=index)
    assert index.lookup("evt-integration") is not None

    # A recording attaches to the same calendar event via event_id
    audio_path = tmp_path / "2026-04-14-140000-disbursecloud.flac"
    audio_path.touch()
    save_transcript(audio_path, TranscriptResult(
        utterances=[Utterance(speaker="Alice", start=0, end=1, text="hi")],
        raw_text="hi", language="en",
    ))
    save_analysis(audio_path, AnalysisResult(
        speaker_mapping={}, meeting_type="quarterly_review", summary="s",
        key_points=[], decisions=[], action_items=[], follow_ups=[],
        relationship_notes=None, people=[], companies=[ProfileStub(name="Acme")],
    ))
    recording_metadata = RecordingMetadata(
        org="disbursecloud",
        note_path="",  # empty — resolver uses event_id + index
        title="Q2 Review",
        date="2026-04-14",
        participants=[Participant(name="Alice")],
        platform="google_meet",
        calendar_source="google",
        event_id="evt-integration",
        meeting_link="https://meet.google.com/abc",
    )

    metadata = MeetingMetadata(
        title="Q2 Review", date=date(2026, 4, 14),
        participants=[Participant(name="Alice")], platform="google_meet",
    )
    config = PipelineRuntimeConfig(archive_format="flac")

    run_pipeline(
        audio_path=audio_path,
        metadata=metadata,
        config=config,
        org_slug="disbursecloud",
        org_subfolder="Clients/Disbursecloud",
        vault_path=vault,
        user_name="Tim",
        from_stage="export",
        recording_metadata=recording_metadata,
        event_index=index,
    )

    # The pre-existing calendar note should be backfilled, not a duplicate created
    content = calendar_note.read_text(encoding="utf-8")
    _, fm_block, rest = content.split("---\n", 2)
    fm = yaml.safe_load(fm_block)

    # Calendar-owned keys preserved
    assert fm["time"] == "14:00-15:00"
    assert fm["calendar-source"] == "google"
    assert fm["event-id"] == "evt-integration"
    assert fm["meeting-link"] == "https://meet.google.com/abc"
    # Pipeline-owned keys backfilled
    assert fm["pipeline-status"] == "complete"
    assert fm["type"] == "quarterly_review"
    assert fm["recording"] == "2026-04-14-140000-disbursecloud.flac"
    assert fm["companies"] == ["[[Acme]]"]
    # Agenda preserved
    assert "Q2 agenda" in rest

    # Index still consistent
    entry = index.lookup("evt-integration")
    assert entry is not None
    assert entry.path == calendar_note.relative_to(vault)
```

**Step 2: Run to verify pass**

Run: `uv run pytest tests/test_phase2_integration.py -v`
Expected: PASS. If any link in the chain (write_calendar_note indexes → event_id resolver uses index → resolver returns calendar note → pipeline upserts without creating duplicate → index entry survives) is broken, this test pinpoints where.

Run: `uv run pytest -q`
Expected: full suite passes.

**Step 3: Commit**

```bash
git add tests/test_phase2_integration.py
git commit -m "test: end-to-end calendar-sync → pipeline → index integration"
```

---

## Task 10: MANIFEST update

**Files:**
- Modify: `MANIFEST.md`

**Step 1: Edit**

Add the new `recap/daemon/calendar/index.py` line under the calendar block. Update the `sync.py` annotation to reflect that `org_subfolder()` is gone. Update the Key Relationships section if you mentioned the calendar-side hardcode.

**Step 2: Commit**

```bash
git add MANIFEST.md
git commit -m "docs: update MANIFEST for Phase 2 index + org model changes"
```

---

## Post-Phase Verification

| Command | Expected |
|---|---|
| `uv run pytest -q` | all pass |
| `grep -rn "org_subfolder(" recap/ tests/` | 0 hits in source (only in plan docs) |
| `grep -rn "_Recap/.+.upper" recap/` | 0 hits (no hardcoded capitalization) |
| `grep -n "class EventIndex" recap/daemon/calendar/index.py` | 1 hit |
| `grep -rn "find_note_by_event_id.*event_index=" recap/` | at least 3 hits (pipeline, scheduler, detector) |

Acceptance criteria (from design doc §Phase 2):

- [ ] Calendar sync respects configured org subfolders rather than capitalizing org names.
- [ ] Frontmatter identity uses `org_slug`; filesystem routing uses `org_subfolder`. Neither leaks.
- [ ] Event lookup is index-backed rather than repeated markdown scans in hot paths.
- [ ] The index updates correctly on create, rename, and delete.
- [ ] Pipeline note resolution uses the index and resolves the correct note.
- [ ] Tests cover index rebuild, stale entry handling, rename handling, and fallback behavior.
- [ ] There is no remaining correctness-critical O(n) event-id scan in the main path.

Bonus (deferred from Phase 1, closed here):
- [ ] `note_path` stored as vault-relative; legacy absolute paths resolved transparently.

---

## Handoff to Phase 3

Phase 3 (Runtime Foundation) will:
- Introduce `Daemon` service class, retire `_loop_holder` / `_app_holder`.
- Make Signal popup truly async (`run_in_executor` + awaitable callback).
- Delete `AudioCapture` monkey-patching in `recorder.py`; add public `on_chunk` callback.
- Add extension auth bootstrap-token endpoint and pairing tray menu item.
- Delete `autostart.py` and `/api/autostart`.
- Consider the `llm_backend` → `llm_backend_override` rename Codex suggested.

Phase 3 depends on Phase 2's `EventIndex` being wired into the daemon service graph. The `Daemon` service class from Phase 3 will own the `event_index` instance and pass it to sub-services instead of the current constructor injection in `__main__.py`.

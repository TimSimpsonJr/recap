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

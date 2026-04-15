"""Append-only daemon event journal (design doc §0.4).

Schema v1 line format (one per line):
  {"ts": "<RFC3339>", "level": "info|warning|error", "event": "<snake_case>",
   "message": "<human>", "payload": { ... optional }}

Rotation: when the active file exceeds ``max_bytes``, it is moved to
``<path>.1`` (one backup kept). Older backups (``.2``, ``.3``, ...) are
not created; ``prune_old_backups`` deletes ``.1`` if older than N days.

Subscribers: callers may register a callback via ``subscribe()`` to be
invoked with each new entry. Callbacks fire on whatever thread invoked
``append()``; subscribers that need to run on an asyncio loop are
responsible for marshalling via ``asyncio.run_coroutine_threadsafe``.
Subscriber exceptions are caught and logged so a misbehaving subscriber
cannot block the journal.
"""
from __future__ import annotations

import json
import logging
import pathlib
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

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
        self._subscribers: list[Callable[[dict[str, Any]], None]] = []
        self._subscriber_lock = threading.Lock()

    def subscribe(
        self, callback: Callable[[dict[str, Any]], None],
    ) -> Callable[[], None]:
        """Register ``callback`` to receive each appended entry.

        Returns an unsubscribe function. The callback is invoked on
        whatever thread called :meth:`append`; subscribers that need to
        run on an asyncio loop must marshal via ``run_coroutine_threadsafe``.
        """
        with self._subscriber_lock:
            self._subscribers.append(callback)

        def _unsubscribe() -> None:
            with self._subscriber_lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return _unsubscribe

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
            "ts": datetime.now(timezone.utc).astimezone().isoformat(),
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

        # Fan out to subscribers OUTSIDE the file-write lock so a slow
        # subscriber can't block concurrent appends. A snapshot of the
        # subscriber list is taken under the subscriber lock so an
        # unsubscribe during fan-out doesn't mutate the list in flight.
        with self._subscriber_lock:
            subscribers = list(self._subscribers)
        for cb in subscribers:
            try:
                cb(entry)
            except Exception:
                # A bad subscriber must not block the journal.
                logger.exception(
                    "Journal subscriber raised for event %r", event,
                )

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

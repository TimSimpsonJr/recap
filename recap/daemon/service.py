"""Daemon service object.

Replaces the ``_loop_holder`` / ``_app_holder`` closure-bag pattern with a
single ``Daemon`` that owns runtime state, loop access, services, and
lifecycle.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
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

        # Subservices -- populated after Task 3 migration from __main__.py:
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

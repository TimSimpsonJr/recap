"""Daemon service object.

Replaces the ``_loop_holder`` / ``_app_holder`` closure-bag pattern with a
single ``Daemon`` that owns runtime state, loop access, services, and
lifecycle.
"""
from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import logging
import os
import pathlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from aiohttp import web

from recap.daemon.calendar.index import EventIndex
from recap.daemon.events import EventJournal
from recap.daemon.pairing import PairingWindow
from recap.daemon.server import create_app

# How often the periodic timeout loop pokes ``pairing.check_timeout()``
# (seconds). The window's own timeout is 60s, so 5s polling means a
# dangling window closes within 5s of expiry.
_PAIRING_TIMEOUT_POLL_SECONDS = 5.0

if TYPE_CHECKING:
    from recap.daemon.config import DaemonConfig

logger = logging.getLogger(__name__)


class Daemon:
    """Runtime container for the Recap daemon process.

    Owns: config, loop, app, event_journal, event_index, started_at,
    recorder, detector, scheduler, and the aiohttp HTTP runner.

    Lifecycle:
        d = Daemon(config)
        await d.start(args=args, callbacks=callbacks)
        # ... daemon runs ...
        await d.stop()
    """

    def __init__(
        self,
        config: "DaemonConfig",
        *,
        config_path: Optional[pathlib.Path] = None,
    ) -> None:
        self.config = config
        self.config_path = config_path
        self.config_lock = threading.Lock()
        recap_dir = config.vault_path / "_Recap" / ".recap"
        self.event_journal_path = recap_dir / "events.jsonl"
        self.event_index_path = recap_dir / "event-index.json"
        self.event_journal = EventJournal(self.event_journal_path)
        self.event_index = EventIndex(self.event_index_path)
        # Extension-pairing one-shot window (§0.5). Tray item triggers
        # ``pairing.open()``; the loopback-only ``/bootstrap/token``
        # route calls ``pairing.consume()`` on the first hit.
        self.pairing = PairingWindow(journal=self.event_journal)

        # Runtime state (populated by start()):
        self.started_at: Optional[datetime] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.app: Optional[web.Application] = None

        # Subservices (populated by start() from the callbacks dict):
        self.recorder: Any = None
        self.detector: Any = None
        self.scheduler: Any = None

        # HTTP server runner + shutdown coordination (populated by start()):
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.BaseSite] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._stopped: bool = False
        self._pairing_timeout_task: Optional[asyncio.Task[None]] = None

        # Restart handshake: ``/api/admin/shutdown {"restart": true}`` and
        # the tray's future Restart item flip this flag before requesting
        # shutdown so ``__main__`` can translate it into
        # ``EXIT_RESTART_REQUESTED`` for the launcher watchdog.
        self.restart_requested: bool = False
        # ``RECAP_MANAGED=1`` marks this daemon as running under the
        # launcher wrapper, which is a prerequisite for self-restart.
        # Captured at construction so tests can control it via monkeypatch
        # and so ``/api/status`` reports a stable value per process.
        self.managed: bool = os.environ.get("RECAP_MANAGED") == "1"

        # Dedicated single-worker executor for tkinter popup work. All
        # popup tk state lives and dies on this one thread so finalization
        # never trips ``Tcl_AsyncDelete`` across workers. Created in start().
        self._popup_executor: Optional[ThreadPoolExecutor] = None

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

    async def start(
        self,
        *,
        args: argparse.Namespace,
        callbacks: dict[str, Any],
    ) -> None:
        """Bring up the daemon: rebuild index, wire services, start HTTP server.

        ``callbacks`` is a Phase-3-transitional dict providing the pre-built
        subservices and the auth token. Required keys:

        - ``auth_token`` (str): bytes/string auth token for the HTTP middleware.
        - ``recorder`` (Recorder): pre-constructed recorder with callbacks
          already wired (the callbacks may close over ``daemon`` -- they're
          only invoked after start() returns).
        - ``detector`` (MeetingDetector): pre-constructed detector.
        - ``scheduler`` (CalendarSyncScheduler): pre-constructed scheduler.
        - ``pipeline_trigger`` (callable): the async process_recording bound
          to this daemon, passed into ``create_app`` for HTTP routes.

        After start():
        - ``self.loop`` is the running event loop.
        - ``self.app`` is the aiohttp application, with ``app["daemon"] = self``
          available to route handlers (Tasks 6/8/9).
        - ``self.recorder`` / ``self.detector`` / ``self.scheduler`` are the
          live subservices.
        - HTTP server is listening on ``config.daemon_ports.plugin_port``.
        - Scheduler and detector polling loops are running.
        - A ``daemon_started`` entry has been appended to the journal.
        """
        if self.started_at is not None:
            raise RuntimeError("Daemon.start() called twice")

        self.loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()

        # Single-worker popup executor. ``max_workers=1`` is the whole
        # point: tkinter state must not hop threads.
        self._popup_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="signal-popup-ui",
        )

        # Codex lock-in (Phase 2): unconditional rebuild every start.
        logger.info("Rebuilding EventIndex from vault (startup)")
        self.event_index.rebuild(self.config.vault_path)
        self.event_journal.prune_old_backups()

        # Required subservices supplied by the caller.
        self.recorder = callbacks["recorder"]
        self.detector = callbacks["detector"]
        self.scheduler = callbacks["scheduler"]
        auth_token = callbacks["auth_token"]
        pipeline_trigger = callbacks["pipeline_trigger"]

        # Build the aiohttp app and expose ``daemon`` to route handlers.
        self.app = create_app(
            auth_token=auth_token,
            recorder=self.recorder,
            detector=self.detector,
            pipeline_trigger=pipeline_trigger,
            config=self.config,
            scheduler=self.scheduler,
        )
        self.app["daemon"] = self

        # Bring up the HTTP server (non-blocking).
        port = self.config.daemon_ports.plugin_port
        logger.info("Starting HTTP server on port %d", port)
        # ``shutdown_timeout`` caps how long ``_runner.cleanup()`` waits
        # for active handlers (notably the long-lived ``/api/ws``) to
        # drain. aiohttp's default is 60s and the cleanup goes through
        # two timeout-bounded phases, which produced a ~120s stall on
        # restart when the plugin's WebSocket was still connected. 5s
        # is a belt-and-suspenders backstop; the primary fix is
        # closing WS clients ourselves in ``stop()`` before cleanup.
        self._runner = web.AppRunner(self.app, shutdown_timeout=5.0)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1", port)
        await self._site.start()

        # Start subservice polling loops.
        await self.scheduler.start()
        logger.info("Calendar sync started")
        self.detector.start()
        logger.info("Meeting detection started")

        # Periodic pairing-window timeout poller. Cheap and cancellable;
        # keeps a dangling "Pair browser extension..." window from
        # staying armed forever if the user never clicks through in the
        # extension.
        self._pairing_timeout_task = asyncio.create_task(
            self._pairing_timeout_loop(),
            name="recap-pairing-timeout",
        )

        self.started_at = datetime.now(timezone.utc).astimezone()
        self._stopped = False
        self.emit_event("info", "daemon_started", "Daemon started")

    async def _pairing_timeout_loop(self) -> None:
        """Periodically poke :meth:`PairingWindow.check_timeout`.

        Runs until cancelled by :meth:`stop`. Errors are swallowed and
        logged so a bad subscriber or clock glitch cannot kill the loop.
        """
        while True:
            try:
                await asyncio.sleep(_PAIRING_TIMEOUT_POLL_SECONDS)
                self.pairing.check_timeout()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Pairing timeout loop error")

    async def stop(self) -> None:
        """Tear down the daemon. Idempotent.

        Stops in inverse order of start(): scheduler -> detector -> recorder ->
        HTTP runner. Emits ``daemon_stopped`` to the journal.

        Per-step timings are logged at INFO so slow shutdowns (which
        delay user-visible restart) can be traced without re-instrumenting.
        """
        if self._stopped:
            return
        self._stopped = True

        import time as _time
        shutdown_started = _time.monotonic()
        step_started = shutdown_started

        def _mark(step: str) -> None:
            """Log elapsed time since the previous ``_mark`` call."""
            nonlocal step_started
            now = _time.monotonic()
            logger.info(
                "shutdown: %s took %.2fs (total %.2fs)",
                step, now - step_started, now - shutdown_started,
            )
            step_started = now

        # Cancel the pairing timeout loop first; it's cheap and cannot
        # fail the shutdown sequence.
        if self._pairing_timeout_task is not None:
            self._pairing_timeout_task.cancel()
            try:
                await self._pairing_timeout_task
            except (asyncio.CancelledError, Exception):
                # CancelledError is the happy path; any other exception
                # is logged by the loop itself, so just ignore here.
                pass
            self._pairing_timeout_task = None
        _mark("pairing_timeout_task")

        # Scheduler (cancels its task).
        if self.scheduler is not None:
            try:
                self.scheduler.stop()
                logger.info("Calendar sync stopped")
            except Exception:
                logger.exception("Error stopping calendar scheduler")
        _mark("scheduler.stop")

        # Detector (cancels its task and drains pending signal callbacks).
        if self.detector is not None:
            try:
                await self.detector.stop()
                logger.info("Meeting detection stopped")
            except Exception:
                logger.exception("Error stopping meeting detector")
        _mark("detector.stop")

        # Signal popup worker: sticky-signal any running/queued dialogs to
        # bail out, then wait a bounded period for the dedicated executor
        # thread to exit. Without this, a popup mid-dialog blocks daemon
        # exit indefinitely.
        from recap.daemon.recorder import signal_popup
        signal_popup.request_shutdown()
        if not signal_popup.wait_for_shutdown(timeout=5.0):
            logger.warning(
                "signal popup worker did not finish within 5s; daemon "
                "shutdown compromised -- user may need to force-kill the "
                "process.",
            )
        if self._popup_executor is not None:
            self._popup_executor.shutdown(wait=False)
            self._popup_executor = None
        _mark("signal_popup + popup_executor")

        # Recorder: stop any active capture cleanly. No-op if idle.
        if self.recorder is not None:
            stop_method = getattr(self.recorder, "stop", None)
            if stop_method is not None:
                # Local import to avoid any circular-import risk at module load.
                from recap.daemon.recorder.state_machine import InvalidTransition

                try:
                    result = stop_method()
                    if asyncio.iscoroutine(result):
                        await result
                except InvalidTransition:
                    # Recorder wasn't recording -- normal for shutdown at idle.
                    logger.debug(
                        "Recorder not recording at shutdown; nothing to stop"
                    )
                except Exception:
                    logger.exception("Error stopping recorder")
        _mark("recorder.stop")

        # Proactively close tracked WebSocket clients before the runner
        # cleans up. The plugin holds a long-lived ``/api/ws`` connection
        # whose handler sits in ``async for msg in ws`` until the socket
        # closes; without this, ``runner.cleanup()`` waits out its
        # shutdown timeout (default 60s, now capped at 5s above) for each
        # connection-shutdown phase -- a ~120s stall on restart that the
        # user felt as a hung button. Closing here lets the handler's
        # ``async for`` return immediately.
        if self.app is not None:
            from recap.daemon.server import _WS_CLIENTS_KEY
            try:
                ws_clients = self.app.get(_WS_CLIENTS_KEY, set())
                # Snapshot the set because ``close()`` may trigger the
                # handler's ``finally`` which mutates ``ws_clients``.
                pending = [ws for ws in list(ws_clients) if not ws.closed]
                if pending:
                    logger.info(
                        "Closing %d WebSocket client(s) before shutdown",
                        len(pending),
                    )
                    await asyncio.gather(
                        *(ws.close(code=1001, message=b"server shutdown")
                          for ws in pending),
                        return_exceptions=True,
                    )
            except Exception:
                logger.exception("Error closing WebSocket clients")
        _mark("ws_clients.close")

        # HTTP runner.
        if self._runner is not None:
            try:
                await self._runner.cleanup()
            except Exception:
                logger.exception("Error cleaning up HTTP runner")
            self._runner = None
            self._site = None
        _mark("runner.cleanup")

        if self._stop_event is not None:
            self._stop_event.set()

        self.emit_event("info", "daemon_stopped", "Daemon stopped")

    async def wait_for_shutdown(self) -> None:
        """Block until ``request_shutdown()`` (or ``stop()``) is called."""
        if self._stop_event is None:
            raise RuntimeError("Daemon.start() must be called first")
        await self._stop_event.wait()

    @property
    def port(self) -> Optional[int]:
        """The TCP port the aiohttp server is actually listening on, or ``None``.

        Resolved from the running TCPSite's kernel-assigned socket. When
        ``config.daemon_ports.plugin_port == 0`` the OS picks a free port
        at ``site.start()`` time; tests (and any caller that needs the
        real URL) use this property instead of the configured value.
        Returns ``None`` before start() or after stop().
        """
        site = self._site
        if site is None:
            return None
        server = getattr(site, "_server", None)
        if server is None or not server.sockets:
            return None
        return server.sockets[0].getsockname()[1]

    def request_shutdown(self, *, restart: bool = False) -> None:
        """Signal the daemon to begin shutdown.

        When ``restart`` is true the ``restart_requested`` flag is set
        so ``__main__`` can return ``EXIT_RESTART_REQUESTED`` to the
        launcher watchdog, which respawns a fresh daemon child.

        Safe to call from a signal handler or another thread (uses
        ``loop.call_soon_threadsafe``).
        """
        if restart:
            self.restart_requested = True
        if self._stop_event is None or self.loop is None:
            return
        self.loop.call_soon_threadsafe(self._stop_event.set)

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

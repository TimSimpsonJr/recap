"""Tests for the Daemon service class."""
from __future__ import annotations

import argparse
import asyncio
import pathlib
from datetime import datetime
from typing import Any

import pytest

from recap.daemon.service import Daemon
from tests.conftest import (
    build_daemon_callbacks,
    make_daemon_config,
    minimal_daemon_args,
)


def _make_config(tmp_path: pathlib.Path):
    return make_daemon_config(tmp_path)


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

    def test_emit_event_swallows_journal_failures(self, tmp_path):
        """Journal failures must never crash the daemon."""
        cfg = _make_config(tmp_path)
        d = Daemon(cfg)

        class _BoomJournal:
            def append(self, *args, **kwargs):
                raise OSError("disk full")

        d.event_journal = _BoomJournal()
        # Should not raise -- just logs.
        d.emit_event("error", "boom", "kaboom")


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
            # run_in_loop returns a concurrent.futures.Future; drive the loop to complete it.
            # wrap_future must be told which loop the wrapping asyncio.Future belongs to,
            # otherwise it defaults to the current-thread loop and run_until_complete sees
            # a Future attached to a different loop.
            wrapped = asyncio.wrap_future(future, loop=loop)
            loop.run_until_complete(asyncio.wait_for(wrapped, timeout=1))
            assert future.result() == 42
        finally:
            loop.close()
            d.loop = None

    def test_run_in_loop_raises_when_loop_not_started(self, tmp_path):
        cfg = _make_config(tmp_path)
        d = Daemon(cfg)
        # loop is None by default -- run_in_loop must raise RuntimeError

        async def _c():
            return 1

        coro = _c()
        try:
            with pytest.raises(RuntimeError, match="not running"):
                d.run_in_loop(coro)
        finally:
            coro.close()  # avoid "coroutine was never awaited" warning


# ----------------------------------------------------------------------
# Stub subservices live in tests/conftest.py (Phase 3 Task 6 extraction).
# Local aliases keep the diff in this file minimal.
# ----------------------------------------------------------------------


def _stub_callbacks(daemon: Daemon) -> dict[str, Any]:
    return build_daemon_callbacks(daemon)


def _minimal_args() -> argparse.Namespace:
    return minimal_daemon_args()


class TestDaemonLifecycle:
    """Integration: full start() -> wait -> stop() round trip."""

    @pytest.mark.asyncio
    async def test_start_and_stop_cycle(self, tmp_path):
        """start() brings up services; stop() tears them down cleanly."""
        cfg = _make_config(tmp_path)
        d = Daemon(cfg)
        callbacks = _stub_callbacks(d)

        await d.start(args=_minimal_args(), callbacks=callbacks)

        # Daemon state is fully populated.
        assert d.started_at is not None
        assert d.loop is not None
        assert d.app is not None
        assert d.app["daemon"] is d
        # Index file rebuilt at startup (Codex lock-in from Phase 2).
        assert d.event_index_path.exists()

        # Subservices are wired and started.
        assert d.recorder is callbacks["recorder"]
        assert d.detector is callbacks["detector"]
        assert d.scheduler is callbacks["scheduler"]
        assert d.scheduler.started is True
        assert d.detector.started is True

        # Journal recorded the lifecycle event.
        journal_entries = d.event_journal.tail(limit=10)
        assert any(
            e["event"] == "daemon_started" for e in journal_entries
        ), f"expected daemon_started in {journal_entries}"

        await d.stop()

        # Subservices got stopped.
        assert d.scheduler.stopped is True
        assert d.detector.stopped is True
        assert d.recorder.stopped is True

        # Journal recorded the stop event.
        stop_entries = d.event_journal.tail(limit=10)
        assert any(
            e["event"] == "daemon_stopped" for e in stop_entries
        ), f"expected daemon_stopped in {stop_entries}"

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self, tmp_path):
        cfg = _make_config(tmp_path)
        d = Daemon(cfg)
        await d.start(args=_minimal_args(), callbacks=_stub_callbacks(d))
        await d.stop()
        # Second stop must not raise and must not double-emit daemon_stopped.
        await d.stop()
        stops = [
            e for e in d.event_journal.tail(limit=20)
            if e["event"] == "daemon_stopped"
        ]
        assert len(stops) == 1, f"expected exactly one daemon_stopped, got {len(stops)}"

    @pytest.mark.asyncio
    async def test_stop_quiet_when_recorder_not_recording(self, tmp_path, caplog):
        """Daemon.stop() must NOT log a traceback when recorder is idle.

        The real Recorder.stop() calls state_machine.stop_recording() which
        raises InvalidTransition from idle. That's the common Ctrl-C case
        (no active meeting) and must not produce an ERROR-level stack trace.
        """
        from recap.daemon.recorder.state_machine import InvalidTransition

        cfg = _make_config(tmp_path)
        d = Daemon(cfg)
        callbacks = _stub_callbacks(d)

        # Swap the stub recorder's stop() to mimic the real one's behavior
        # when the state machine is idle.
        def _raising_stop():
            raise InvalidTransition("Cannot stop_recording from idle")

        callbacks["recorder"].stop = _raising_stop

        await d.start(args=_minimal_args(), callbacks=callbacks)
        caplog.clear()
        with caplog.at_level("DEBUG"):
            await d.stop()

        # No ERROR/WARNING records mentioning the recorder should be emitted.
        bad = [
            r for r in caplog.records
            if r.levelname in ("ERROR", "WARNING")
            and "recorder" in r.getMessage().lower()
        ]
        assert bad == [], (
            f"Unexpected errors/warnings: "
            f"{[(r.levelname, r.getMessage()) for r in bad]}"
        )


class TestDaemonShutdownRestartFlag:
    """``request_shutdown(restart=True)`` sets ``restart_requested``.

    The launcher watchdog reads the process exit code to decide whether
    to loop (42) or stop (0). ``__main__.main`` translates
    ``daemon.restart_requested`` into that code, so this flag is the
    whole restart handshake on the Python side.
    """

    def test_default_restart_requested_is_false(self, tmp_path):
        cfg = _make_config(tmp_path)
        d = Daemon(cfg)
        assert d.restart_requested is False

    @pytest.mark.asyncio
    async def test_request_shutdown_without_restart_keeps_flag_false(
        self, tmp_path,
    ):
        cfg = _make_config(tmp_path)
        d = Daemon(cfg)
        await d.start(args=_minimal_args(), callbacks=_stub_callbacks(d))
        try:
            d.request_shutdown()
            await d.wait_for_shutdown()
            assert d.restart_requested is False
        finally:
            await d.stop()

    @pytest.mark.asyncio
    async def test_request_shutdown_with_restart_sets_flag(self, tmp_path):
        cfg = _make_config(tmp_path)
        d = Daemon(cfg)
        await d.start(args=_minimal_args(), callbacks=_stub_callbacks(d))
        try:
            d.request_shutdown(restart=True)
            await d.wait_for_shutdown()
            assert d.restart_requested is True
        finally:
            await d.stop()


class TestDaemonShutdownClosesWebSockets:
    """``Daemon.stop()`` must proactively close tracked WebSocket clients.

    Without this, the plugin's long-lived ``/api/ws`` connection kept
    the aiohttp runner cleanup blocked through its shutdown timeout
    (default 60s, cleanup goes through two phases -> ~120s total) on
    every restart. Closing clients ourselves lets the ``async for msg
    in ws`` loop return immediately."""

    @pytest.mark.asyncio
    async def test_stop_closes_tracked_ws_clients(self, tmp_path):
        from recap.daemon.server import _WS_CLIENTS_KEY

        cfg = _make_config(tmp_path)
        d = Daemon(cfg)
        await d.start(args=_minimal_args(), callbacks=_stub_callbacks(d))

        # Inject a fake WS client that tracks whether close() was awaited.
        class _FakeWS:
            def __init__(self) -> None:
                self.closed = False
                self.close_call: tuple | None = None

            async def close(self, *, code: int, message: bytes) -> None:
                self.close_call = (code, message)
                self.closed = True

        fake = _FakeWS()
        d.app[_WS_CLIENTS_KEY].add(fake)

        await d.stop()

        assert fake.close_call is not None, (
            "Daemon.stop() must call ws.close() on tracked clients"
        )
        assert fake.close_call[0] == 1001  # going-away status code
        assert fake.closed is True

    @pytest.mark.asyncio
    async def test_stop_skips_already_closed_ws_clients(self, tmp_path):
        """Closing an already-closed socket raises in aiohttp; skip it."""
        from recap.daemon.server import _WS_CLIENTS_KEY

        cfg = _make_config(tmp_path)
        d = Daemon(cfg)
        await d.start(args=_minimal_args(), callbacks=_stub_callbacks(d))

        class _FakeWS:
            def __init__(self, already_closed: bool) -> None:
                self.closed = already_closed
                self.close_called = False

            async def close(self, **_kwargs) -> None:
                self.close_called = True
                self.closed = True

        closed_ws = _FakeWS(already_closed=True)
        open_ws = _FakeWS(already_closed=False)
        d.app[_WS_CLIENTS_KEY].update({closed_ws, open_ws})

        await d.stop()

        assert closed_ws.close_called is False
        assert open_ws.close_called is True


class TestDaemonManagedMode:
    """``Daemon.managed`` reflects the ``RECAP_MANAGED`` env var.

    The plugin reads this (via ``/api/status``) to decide whether the
    Restart button is actionable. Unmanaged daemons can still shut down
    but cannot self-restart (nothing would spawn a replacement child).
    """

    def test_managed_false_when_env_unset(self, tmp_path, monkeypatch):
        monkeypatch.delenv("RECAP_MANAGED", raising=False)
        cfg = _make_config(tmp_path)
        d = Daemon(cfg)
        assert d.managed is False

    def test_managed_true_when_env_is_one(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RECAP_MANAGED", "1")
        cfg = _make_config(tmp_path)
        d = Daemon(cfg)
        assert d.managed is True

    def test_managed_false_for_other_values(self, tmp_path, monkeypatch):
        """Only the literal ``"1"`` counts. Empty, ``"0"``, ``"true"`` etc.
        all mean unmanaged -- keeps the contract boring and unambiguous."""
        cfg = _make_config(tmp_path)
        for raw in ("", "0", "true", "yes"):
            monkeypatch.setenv("RECAP_MANAGED", raw)
            d = Daemon(cfg)
            assert d.managed is False, f"RECAP_MANAGED={raw!r} should not be managed"


# ----------------------------------------------------------------------
# #28 Task 11: Daemon.refresh_config + subservice propagation
# ----------------------------------------------------------------------


def _write_refresh_config(
    tmp_path: pathlib.Path, extra_contacts: list[dict] | None = None,
) -> pathlib.Path:
    """Write a minimal valid on-disk config.yaml and return the path.

    Matches the kebab-case/dict-orgs shape ``parse_daemon_config_dict``
    consumes. ``extra_contacts`` seeds the ``known-contacts`` section so
    refresh tests can assert the in-memory list grows after reload.
    """
    import yaml

    (tmp_path / "vault").mkdir(parents=True, exist_ok=True)
    (tmp_path / "recordings").mkdir(parents=True, exist_ok=True)
    doc: dict = {
        "config-version": 1,
        "vault-path": str(tmp_path / "vault"),
        "recordings-path": str(tmp_path / "recordings"),
        "user-name": "Tester",
        "orgs": {
            "test": {
                "subfolder": "Test",
                "llm-backend": "claude",
                "default": True,
            },
        },
        "detection": {},
        "calendars": {},
    }
    if extra_contacts is not None:
        doc["known-contacts"] = extra_contacts
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(doc))
    return path


class TestDaemonRefreshConfig:
    """Daemon.refresh_config reloads + propagates to subservices (#28 Task 11)."""

    def test_refresh_updates_self_config(self, tmp_path):
        """After mutating disk, refresh_config reloads into self.config."""
        from recap.daemon.config import load_daemon_config

        config_path = _write_refresh_config(tmp_path, extra_contacts=[])
        config = load_daemon_config(config_path)
        daemon = Daemon(config, config_path=config_path)

        # No contacts in memory initially.
        assert daemon.config.known_contacts == []

        # Mutate on disk.
        new_path = _write_refresh_config(tmp_path, extra_contacts=[
            {"name": "Alice", "display-name": "Alice"},
        ])
        assert new_path == config_path

        daemon.refresh_config()

        assert len(daemon.config.known_contacts) == 1
        assert daemon.config.known_contacts[0].name == "Alice"

    def test_refresh_propagates_to_detector(self, tmp_path):
        """MeetingDetector's cached self._config updated after refresh."""
        from unittest.mock import MagicMock

        from recap.daemon.config import load_daemon_config

        config_path = _write_refresh_config(tmp_path, extra_contacts=[])
        config = load_daemon_config(config_path)
        daemon = Daemon(config, config_path=config_path)

        # Attach a mock detector with the cached _config attribute the real
        # detector carries. refresh_config must invoke on_config_reloaded
        # with the newly-loaded DaemonConfig.
        detector = MagicMock()
        detector._config = config
        daemon.detector = detector

        # Mutate disk.
        _write_refresh_config(tmp_path, extra_contacts=[
            {"name": "Bob", "display-name": "Bob"},
        ])
        daemon.refresh_config()

        detector.on_config_reloaded.assert_called_once()
        new_cfg = detector.on_config_reloaded.call_args[0][0]
        assert len(new_cfg.known_contacts) == 1
        assert new_cfg.known_contacts[0].name == "Bob"
        # The detector got the *same* object daemon.config now points at.
        assert new_cfg is daemon.config

    def test_refresh_when_detector_is_none_does_not_raise(self, tmp_path):
        """Before detector is constructed, refresh still works."""
        from recap.daemon.config import load_daemon_config

        config_path = _write_refresh_config(tmp_path, extra_contacts=[])
        config = load_daemon_config(config_path)
        daemon = Daemon(config, config_path=config_path)
        daemon.detector = None

        # Should not raise, and should still update self.config.
        _write_refresh_config(tmp_path, extra_contacts=[
            {"name": "Carol", "display-name": "Carol"},
        ])
        daemon.refresh_config()
        assert len(daemon.config.known_contacts) == 1


class TestDetectorOnConfigReloaded:
    """MeetingDetector.on_config_reloaded updates cached _config (#28 Task 11)."""

    def test_updates_cached_config_reference(self, tmp_path):
        """The new config object replaces the old one on self._config."""
        from unittest.mock import MagicMock

        from recap.daemon.recorder.detector import MeetingDetector

        config = MagicMock()
        # Minimal surface so __init__ / enabled_platforms don't blow up.
        config.detection.teams.enabled = False
        config.detection.zoom.enabled = False
        config.detection.signal.enabled = False

        detector = MeetingDetector(config=config, recorder=MagicMock())
        assert detector._config is config

        new_config = MagicMock()
        new_config.detection.teams.enabled = False
        new_config.detection.zoom.enabled = False
        new_config.detection.signal.enabled = False

        detector.on_config_reloaded(new_config)
        assert detector._config is new_config

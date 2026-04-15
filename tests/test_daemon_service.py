"""Tests for the Daemon service class."""
from __future__ import annotations

import argparse
import asyncio
import pathlib
from datetime import datetime
from typing import Any

import pytest

from recap.daemon.config import DaemonConfig, DaemonPortConfig, OrgConfig
from recap.daemon.service import Daemon


def _make_config(tmp_path: pathlib.Path) -> DaemonConfig:
    cfg = DaemonConfig.__new__(DaemonConfig)
    cfg.vault_path = tmp_path / "vault"
    cfg.vault_path.mkdir()
    cfg.recordings_path = tmp_path / "rec"
    cfg.recordings_path.mkdir()
    cfg._orgs = [OrgConfig(name="d", subfolder="Clients/D", default=True)]
    # Lifecycle test needs daemon_ports for the HTTP runner.
    cfg.daemon_ports = DaemonPortConfig(plugin_port=0)
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
# Stub subservices for the lifecycle test (Phase 3 Task 3)
# ----------------------------------------------------------------------


class _StubRecorder:
    """Minimal recorder stub: only exposes the surface ``stop()`` touches."""

    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _StubScheduler:
    """Stub CalendarSyncScheduler with async start() + sync stop()."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self.started = True
        # Spawn a benign task that just sleeps until cancelled, mirroring
        # the real scheduler's polling-loop shape.
        self._task = asyncio.get_running_loop().create_task(self._run())

    async def _run(self) -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            return

    def stop(self) -> None:
        self.stopped = True
        if self._task is not None:
            self._task.cancel()
            self._task = None


class _StubDetector:
    """Stub MeetingDetector: sync start() / stop() like the real one."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self.started = True
        self._task = asyncio.get_event_loop().create_task(self._run())

    async def _run(self) -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            return

    def stop(self) -> None:
        self.stopped = True
        if self._task is not None:
            self._task.cancel()
            self._task = None


def _stub_callbacks(daemon: Daemon) -> dict[str, Any]:
    async def _noop(*args, **kwargs):
        return None

    return {
        "auth_token": "test-token",
        "recorder": _StubRecorder(),
        "detector": _StubDetector(),
        "scheduler": _StubScheduler(),
        "pipeline_trigger": _noop,
    }


def _minimal_args() -> argparse.Namespace:
    return argparse.Namespace(config=pathlib.Path("test-config.yaml"))


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

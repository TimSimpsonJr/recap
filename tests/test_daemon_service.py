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

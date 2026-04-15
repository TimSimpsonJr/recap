"""Shared test fixtures."""
from __future__ import annotations

import argparse
import asyncio
import pathlib
from typing import Any

import pytest


@pytest.fixture
def tmp_vault(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a temporary vault structure for testing."""
    meetings = tmp_path / "Work" / "Meetings"
    meetings.mkdir(parents=True)
    people = tmp_path / "Work" / "People"
    people.mkdir(parents=True)
    companies = tmp_path / "Work" / "Companies"
    companies.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def tmp_recordings(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a temporary recordings directory."""
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    return recordings


# ----------------------------------------------------------------------
# Daemon test helpers (shared across test_daemon_service.py,
# test_daemon_server.py, and Phase 3 integration tests)
# ----------------------------------------------------------------------


def make_daemon_config(tmp_path: pathlib.Path):
    """Build a minimal :class:`DaemonConfig` for tests.

    Uses ``plugin_port=0`` so the aiohttp runner can bind on any free
    port, and seeds a single default org. Extracted from
    ``test_daemon_service.py`` in Phase 3 Task 6 so other test modules
    (server, integration) can reuse it.
    """
    from recap.daemon.config import DaemonConfig, DaemonPortConfig, OrgConfig

    cfg = DaemonConfig.__new__(DaemonConfig)
    cfg.vault_path = tmp_path / "vault"
    cfg.vault_path.mkdir()
    cfg.recordings_path = tmp_path / "rec"
    cfg.recordings_path.mkdir()
    cfg._orgs = [OrgConfig(name="d", subfolder="Clients/D", default=True)]
    cfg.daemon_ports = DaemonPortConfig(plugin_port=0)
    return cfg


class StubRecorder:
    """Minimal recorder stub: only exposes the surface ``Daemon.stop()`` touches."""

    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class StubScheduler:
    """Stub CalendarSyncScheduler with async start() + sync stop()."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.last_sync = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self.started = True
        # Spawn a benign task that sleeps until cancelled, mirroring the
        # real scheduler's polling-loop shape.
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


class StubDetector:
    """Stub MeetingDetector: sync start() / async stop() like the real one."""

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

    async def stop(self) -> None:
        self.stopped = True
        if self._task is not None:
            self._task.cancel()
            self._task = None


def build_daemon_callbacks(daemon) -> dict[str, Any]:
    """Construct the callbacks dict that ``Daemon.start()`` consumes.

    Returns fresh stub subservices each time. The ``daemon`` argument is
    unused today but kept so callers can introspect what the stubs close
    over when we need that in later phases.
    """
    async def _noop(*args, **kwargs):
        return None

    return {
        "auth_token": "test-token",
        "recorder": StubRecorder(),
        "detector": StubDetector(),
        "scheduler": StubScheduler(),
        "pipeline_trigger": _noop,
    }


def minimal_daemon_args() -> argparse.Namespace:
    """Return the minimal argparse Namespace Daemon.start() expects."""
    return argparse.Namespace(config=pathlib.Path("test-config.yaml"))

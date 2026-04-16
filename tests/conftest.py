"""Shared test fixtures."""
from __future__ import annotations

import argparse
import asyncio
import pathlib
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio


# Shared auth token for fixtures that wire a real Daemon + aiohttp app.
# Individual tests import this as ``tests.conftest.AUTH_TOKEN`` or can
# read it via the ``daemon_client`` fixture tuple.
AUTH_TOKEN = "test-secret-token-abc123"

# Minimal kebab-case config body used by ``daemon_client``. Matches
# the on-disk schema ``load_daemon_config`` consumes (see
# ``config.example.yaml``) so PATCH round-trips and real-loader
# validation both exercise the same shape. A top-of-file comment is
# included so comment-preservation tests have something to assert against.
MINIMAL_API_CONFIG_YAML = """\
# Top-of-file marker comment (do not remove)
config-version: 1
vault-path: "{vault}"
recordings-path: "{rec}"
user-name: "TestUser"
orgs:
  alpha:
    subfolder: Clients/Alpha
    llm-backend: claude
    default: true
  beta:
    subfolder: Clients/Beta
    llm-backend: claude
detection:
  teams:
    enabled: true
    behavior: auto-record
  zoom:
    enabled: true
    behavior: auto-record
  signal:
    enabled: true
    behavior: prompt
calendars: {{}}
known-contacts: []
recording:
  silence-timeout-minutes: 5
  max-duration-hours: 3
logging:
  retention-days: 7
daemon:
  plugin-port: 9847
"""


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
    from recap.daemon.config import (
        DaemonConfig,
        DaemonPortConfig,
        OllamaConfig,
        OrgConfig,
    )

    cfg = DaemonConfig.__new__(DaemonConfig)
    cfg.vault_path = tmp_path / "vault"
    cfg.vault_path.mkdir()
    cfg.recordings_path = tmp_path / "rec"
    cfg.recordings_path.mkdir()
    cfg._orgs = [OrgConfig(name="d", subfolder="Clients/D", default=True)]
    cfg.daemon_ports = DaemonPortConfig(plugin_port=0)
    cfg.ollama = OllamaConfig()
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


@pytest_asyncio.fixture
async def daemon_client(aiohttp_client, tmp_path):
    """Return ``(client, daemon)`` with an app wired to a real Daemon.

    Writes a minimal snake_case ``config.yaml`` to ``tmp_path`` and
    points ``daemon.config_path`` at it so ``/api/config`` has a real
    file to GET + PATCH. Shared by ``test_api_events``,
    ``test_api_config``, and the Phase 4 integration test.
    """
    from recap.daemon.server import create_app
    from recap.daemon.service import Daemon

    cfg = make_daemon_config(tmp_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        MINIMAL_API_CONFIG_YAML.format(
            vault=(tmp_path / "vault").as_posix(),
            rec=(tmp_path / "rec").as_posix(),
        ),
        encoding="utf-8",
    )
    daemon = Daemon(cfg, config_path=config_path)
    daemon.started_at = (
        datetime.now(timezone.utc).astimezone() - timedelta(seconds=5)
    )
    app = create_app(auth_token=AUTH_TOKEN)
    app["daemon"] = daemon
    client = await aiohttp_client(app)
    return client, daemon

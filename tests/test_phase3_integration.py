"""Phase 3 integration: Daemon + journal + pairing + HTTP surface.

Drives a real :class:`Daemon` through ``start()`` -> ``stop()`` with the
HTTP runner bound on a random free port (``plugin_port=0``), then exercises
the four feature areas added in Phase 3 Tasks 2-11:

1. Startup lifecycle journaling (``daemon_started`` entry).
2. ``/api/status`` returning real uptime + a ``recent_errors`` list.
3. Extension pairing: ``pairing.open()`` -> one-shot ``/bootstrap/token``.
4. ``/api/index/rename`` gated by Bearer + journaled as ``index_rename``.
5. Shutdown lifecycle journaling (``daemon_stopped`` entry).

This is the end-to-end pass: the same request path the browser extension
and Obsidian plugin use, with no in-process shortcut. The ``daemon_client``
fixture in ``test_daemon_server.py`` deliberately avoids ``Daemon.start()``
because it would try to bind a real TCP port; this module uses port 0 so
the OS hands us a free one and we talk to it over loopback.
"""
from __future__ import annotations

import pathlib
from contextlib import asynccontextmanager

import aiohttp
import pytest

from recap.daemon.service import Daemon
from tests.conftest import (
    StubRecorder,
    build_daemon_callbacks,
    make_daemon_config,
    minimal_daemon_args,
)


class _IdleState:
    value = "idle"


class _IdleStateMachine:
    state = _IdleState()
    current_org: str | None = None


class _StatusCompatibleStubRecorder(StubRecorder):
    """StubRecorder with the surface ``/api/status`` inspects.

    The shared :class:`StubRecorder` only exposes ``stop()`` (all the
    lifecycle tests need). The real status handler drills into
    ``recorder.state_machine.state.value`` + ``recorder.is_recording``,
    so we augment here with the minimum idle-shape attributes for the
    integration path.
    """

    def __init__(self) -> None:
        super().__init__()
        self.state_machine = _IdleStateMachine()

    @property
    def is_recording(self) -> bool:
        return False

    @property
    def current_recording_path(self):  # type: ignore[no-untyped-def]
        return None


@asynccontextmanager
async def _client_to(daemon: Daemon):
    """Open an aiohttp session pointed at the daemon's real bound port.

    Uses ``daemon.port`` (resolved from the running TCPSite) rather than
    the configured ``plugin_port``, because the test fixture binds with
    ``plugin_port=0`` so the OS picks a free port.
    """
    port = daemon.port
    assert port is not None and port > 0, (
        f"Daemon must be started before _client_to(); got port={port}"
    )
    base_url = f"http://127.0.0.1:{port}"
    async with aiohttp.ClientSession(base_url=base_url) as session:
        yield session


@pytest.mark.asyncio
async def test_full_daemon_lifecycle_with_pairing_and_journaled_events(tmp_path):
    """End-to-end: start -> status -> pairing -> rename -> stop, all journaled."""
    cfg = make_daemon_config(tmp_path)
    daemon = Daemon(cfg)
    callbacks = build_daemon_callbacks(daemon)
    # The shared StubRecorder doesn't expose ``state_machine`` (only
    # ``stop()``), which is all the lifecycle tests need. /api/status
    # drills into it, so swap in a status-aware stub for this test.
    callbacks["recorder"] = _StatusCompatibleStubRecorder()

    await daemon.start(args=minimal_daemon_args(), callbacks=callbacks)

    try:
        # 1. Startup was journaled.
        entries = daemon.event_journal.tail(limit=100)
        assert any(e["event"] == "daemon_started" for e in entries), (
            f"expected daemon_started in journal, got {[e['event'] for e in entries]}"
        )

        auth_token = callbacks["auth_token"]
        headers = {"Authorization": f"Bearer {auth_token}"}

        async with _client_to(daemon) as client:
            # 2. /api/status returns real uptime + recent_errors list.
            async with client.get("/api/status", headers=headers) as resp:
                assert resp.status == 200
                status = await resp.json()
            assert status["uptime_seconds"] > 0
            assert isinstance(status["recent_errors"], list)

            # 3. Pairing flow (happy path):
            #    open window -> first GET /bootstrap/token wins the token
            #    and closes the window; second GET sees 404.
            daemon.pairing.open()
            async with client.get("/bootstrap/token") as resp:
                assert resp.status == 200
                body = await resp.json()
            token = body["token"]
            assert token == auth_token

            async with client.get("/bootstrap/token") as resp2:
                assert resp2.status == 404

            # 4. /api/index/rename requires Bearer and journals the change.
            daemon.event_index.add(
                "evt-1",
                pathlib.PurePosixPath("Clients/D/Meetings/x.md"),
                "d",
            )
            async with client.post(
                "/api/index/rename",
                json={
                    "event_id": "evt-1",
                    "new_path": "Clients/D/Meetings/renamed.md",
                },
                headers=headers,
            ) as resp:
                assert resp.status == 200
            renamed = daemon.event_index.lookup("evt-1")
            assert renamed is not None
            assert str(renamed.path) == "Clients/D/Meetings/renamed.md"

        # 5. Journal includes every lifecycle transition from above.
        final_events = [e["event"] for e in daemon.event_journal.tail(limit=100)]
        assert "pairing_opened" in final_events
        assert "pairing_token_issued" in final_events
        assert "index_rename" in final_events

    finally:
        await daemon.stop()

    # 6. Shutdown journaling (outside the try so we still fail loudly if
    #    the assertions above blew up AND stop() failed to journal).
    stopped_events = [e["event"] for e in daemon.event_journal.tail(limit=10)]
    assert "daemon_stopped" in stopped_events, (
        f"expected daemon_stopped after stop(), got {stopped_events}"
    )

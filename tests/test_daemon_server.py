"""Tests for the daemon HTTP server."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from unittest.mock import MagicMock

from recap.daemon.server import create_app
from recap.daemon.service import Daemon
from tests.conftest import (
    build_daemon_callbacks,
    make_daemon_config,
    minimal_daemon_args,
)

AUTH_TOKEN = "test-secret-token-abc123"


@pytest_asyncio.fixture
async def client(aiohttp_client):
    """Create a test client for the daemon app."""
    app = create_app(auth_token=AUTH_TOKEN)
    return await aiohttp_client(app)


@pytest_asyncio.fixture
async def client_with_detector(aiohttp_client):
    """Create a test client with a mock detector."""
    mock_detector = MagicMock()
    app = create_app(auth_token=AUTH_TOKEN, detector=mock_detector)
    return await aiohttp_client(app), mock_detector


@pytest_asyncio.fixture
async def daemon_client(aiohttp_client, tmp_path):
    """Return (client, daemon) where the app is wired to a real Daemon.

    Avoids :meth:`Daemon.start` (which would bind a real TCP port via
    ``AppRunner``) by building the app directly and attaching the
    Daemon so ``/api/status`` and the WebSocket handler see a real
    ``EventJournal``. ``started_at`` is set to simulate an already-
    running daemon; tests can override it if they need a specific value.
    """
    cfg = make_daemon_config(tmp_path)
    daemon = Daemon(cfg)
    # Simulate post-start state. Uptime = 5s when tests hit /api/status.
    daemon.started_at = (
        datetime.now(timezone.utc).astimezone() - timedelta(seconds=5)
    )
    app = create_app(auth_token=AUTH_TOKEN)
    app["daemon"] = daemon
    client = await aiohttp_client(app)
    return client, daemon


@pytest.mark.asyncio
class TestHealthEndpoint:
    """GET /health — no auth required."""

    async def test_returns_200_with_status_ok(self, client):
        resp = await client.get("/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.2.0"


@pytest.mark.asyncio
class TestApiStatusAuth:
    """GET /api/status — requires Bearer token."""

    async def test_returns_401_without_auth(self, client):
        resp = await client.get("/api/status")
        assert resp.status == 401
        data = await resp.json()
        assert data["error"] == "unauthorized"

    async def test_returns_200_with_correct_token(self, client):
        resp = await client.get(
            "/api/status",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200

    async def test_returns_401_with_wrong_token(self, client):
        resp = await client.get(
            "/api/status",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status == 401
        data = await resp.json()
        assert data["error"] == "unauthorized"

    async def test_response_has_expected_fields(self, client):
        resp = await client.get(
            "/api/status",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["state"] == "idle"
        assert data["recording"] is None
        assert data["daemon_uptime"] == 0
        assert data["last_calendar_sync"] is None
        assert data["errors"] == []


@pytest.mark.asyncio
class TestArmEndpoint:
    """POST /api/arm — arm the detector for a calendar event."""

    async def test_arm_returns_200(self, client_with_detector):
        client, mock_detector = client_with_detector
        resp = await client.post(
            "/api/arm",
            json={
                "event_id": "evt1",
                "start_time": "2026-04-14T14:00:00",
                "org": "disbursecloud",
            },
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "armed"
        mock_detector.arm_for_event.assert_called_once()

    async def test_arm_missing_fields_returns_400(self, client_with_detector):
        client, _ = client_with_detector
        resp = await client.post(
            "/api/arm",
            json={"event_id": "evt1"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

    async def test_arm_no_detector_returns_503(self, client):
        resp = await client.post(
            "/api/arm",
            json={
                "event_id": "evt1",
                "start_time": "2026-04-14T14:00:00",
                "org": "disbursecloud",
            },
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 503


@pytest.mark.asyncio
class TestDisarmEndpoint:
    """POST /api/disarm — disarm the detector."""

    async def test_disarm_returns_200(self, client_with_detector):
        client, mock_detector = client_with_detector
        resp = await client.post(
            "/api/disarm",
            json={},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "disarmed"
        mock_detector.disarm.assert_called_once()

    async def test_disarm_no_detector_returns_503(self, client):
        resp = await client.post(
            "/api/disarm",
            json={},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 503


@pytest.mark.asyncio
class TestAutoStartEndpoint:
    """GET /api/autostart — auto-start status (stub)."""

    async def test_returns_not_implemented(self, client):
        resp = await client.get(
            "/api/autostart",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["enabled"] is False
        assert data["implemented"] is False

    async def test_requires_auth(self, client):
        resp = await client.get("/api/autostart")
        assert resp.status == 401


@pytest.mark.asyncio
class TestApiStatusReal:
    """Task 6: ``/api/status`` returns real uptime + recent errors.

    The ``client`` fixture has no daemon wired, so uptime is 0 and
    errors are empty. ``daemon_client`` wires a real Daemon with an
    EventJournal so uptime > 0 and journal errors surface in the
    response.
    """

    async def test_no_daemon_still_returns_placeholder(self, client):
        """Backwards-compatible: missing daemon yields uptime=0, errors=[]."""
        resp = await client.get(
            "/api/status",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["uptime_seconds"] == 0
        assert data["recent_errors"] == []
        # Legacy fields stay populated.
        assert data["daemon_uptime"] == 0
        assert data["errors"] == []

    async def test_returns_real_uptime_when_daemon_started(self, daemon_client):
        client, daemon = daemon_client
        resp = await client.get(
            "/api/status",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        # Fixture sets started_at = now - 5s, so uptime should be ~5s (with
        # some drift from the server handling the request).
        assert data["uptime_seconds"] >= 4.5
        assert data["uptime_seconds"] < 60
        # Legacy field mirrors the real uptime.
        assert data["daemon_uptime"] == data["uptime_seconds"]

    async def test_returns_recent_errors_from_journal(self, daemon_client):
        client, daemon = daemon_client
        daemon.event_journal.append("info", "boot", "ignored for error tail")
        daemon.event_journal.append("error", "pipeline_failed", "boom-1")
        daemon.event_journal.append("warning", "silence", "ignored")
        daemon.event_journal.append(
            "error", "disk_full", "boom-2", payload={"path": "/tmp/foo"},
        )

        resp = await client.get(
            "/api/status",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()

        messages = [e["message"] for e in data["recent_errors"]]
        assert messages == ["boom-1", "boom-2"]
        # All entries should be error level only.
        assert {e["level"] for e in data["recent_errors"]} == {"error"}
        # Payload passes through untouched.
        boom2 = next(e for e in data["recent_errors"] if e["message"] == "boom-2")
        assert boom2["payload"] == {"path": "/tmp/foo"}
        # Legacy ``errors`` field mirrors ``recent_errors``.
        assert data["errors"] == data["recent_errors"]

    async def test_recent_errors_capped_at_ten(self, daemon_client):
        client, daemon = daemon_client
        for i in range(15):
            daemon.event_journal.append("error", "e", f"m{i}")

        resp = await client.get(
            "/api/status",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        data = await resp.json()
        assert len(data["recent_errors"]) == 10
        # tail() returns the trailing slice, so the oldest surviving
        # message is m5 and the newest is m14.
        assert data["recent_errors"][0]["message"] == "m5"
        assert data["recent_errors"][-1]["message"] == "m14"


@pytest.mark.asyncio
class TestWebSocketJournalBroadcast:
    """Task 6: WS handler subscribes to EventJournal and broadcasts entries."""

    async def test_connect_without_token_returns_401(self, daemon_client):
        client, _ = daemon_client
        resp = await client.get("/api/ws")
        assert resp.status == 401

    async def test_broadcasts_journal_entry_on_append(self, daemon_client):
        client, daemon = daemon_client

        async with client.ws_connect(f"/api/ws?token={AUTH_TOKEN}") as ws:
            # Let the WS handler finish subscribing before we append.
            # A brief sleep is enough: subscribe() is synchronous
            # immediately after ws.prepare().
            await asyncio.sleep(0.05)

            daemon.event_journal.append(
                "info", "hello_ws", "streamed", payload={"k": "v"},
            )

            msg = await asyncio.wait_for(ws.receive(), timeout=2)
            assert msg.type.name in ("TEXT", "BINARY")
            data = json.loads(msg.data)
            assert data["event"] == "journal_entry"
            assert data["entry"]["event"] == "hello_ws"
            assert data["entry"]["message"] == "streamed"
            assert data["entry"]["payload"] == {"k": "v"}

    async def test_multiple_entries_each_broadcast(self, daemon_client):
        client, daemon = daemon_client

        async with client.ws_connect(f"/api/ws?token={AUTH_TOKEN}") as ws:
            await asyncio.sleep(0.05)
            daemon.event_journal.append("info", "a", "m1")
            daemon.event_journal.append("warning", "b", "m2")
            daemon.event_journal.append("error", "c", "m3")

            received_events: list[str] = []
            for _ in range(3):
                msg = await asyncio.wait_for(ws.receive(), timeout=2)
                received_events.append(json.loads(msg.data)["entry"]["event"])

            assert received_events == ["a", "b", "c"]

    async def test_entries_from_background_thread_are_broadcast(self, daemon_client):
        """Append from a non-asyncio thread still broadcasts.

        The journal callback fires on whatever thread called append(),
        and the WS subscriber must marshal to the loop via
        run_coroutine_threadsafe.
        """
        import threading

        client, daemon = daemon_client

        async with client.ws_connect(f"/api/ws?token={AUTH_TOKEN}") as ws:
            await asyncio.sleep(0.05)

            def _writer() -> None:
                daemon.event_journal.append("info", "from_thread", "background")

            t = threading.Thread(target=_writer)
            t.start()
            t.join()

            msg = await asyncio.wait_for(ws.receive(), timeout=2)
            data = json.loads(msg.data)
            assert data["event"] == "journal_entry"
            assert data["entry"]["event"] == "from_thread"

    async def test_disconnect_unsubscribes_from_journal(self, daemon_client):
        """After the WS closes, further journal appends should not feed it.

        Indirectly asserted by checking the journal's subscriber list
        is empty once the WS context exits.
        """
        client, daemon = daemon_client
        initial = len(daemon.event_journal._subscribers)

        async with client.ws_connect(f"/api/ws?token={AUTH_TOKEN}") as ws:
            await asyncio.sleep(0.05)
            # One listener added for this WS.
            assert len(daemon.event_journal._subscribers) == initial + 1
            await ws.close()

        # Give the server a tick to run the finally: unsubscribe().
        await asyncio.sleep(0.05)
        assert len(daemon.event_journal._subscribers) == initial

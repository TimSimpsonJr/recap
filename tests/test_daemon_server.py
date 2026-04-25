"""Tests for the daemon HTTP server."""

import asyncio
import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from unittest.mock import MagicMock

from recap.daemon.server import _WS_CLIENTS_KEY, broadcast, create_app
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
        assert data["uptime_seconds"] == 0
        assert data["last_calendar_sync"] is None
        assert data["recent_errors"] == []


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
class TestAutoStartRouteIsGone:
    """GET /api/autostart — removed in Phase 3 Task 7 (autostart.py retiring)."""

    async def test_api_autostart_returns_404(self, client):
        resp = await client.get(
            "/api/autostart",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 404

    async def test_api_autostart_returns_404_without_auth(self, client):
        # Even unauthenticated, the route simply doesn't exist. Middleware
        # gates `/api/*` so this is 401 before it can 404, but either way
        # the route is gone and should never return 200.
        resp = await client.get("/api/autostart")
        assert resp.status in (401, 404)


@pytest.mark.asyncio
class TestApiMeetingDetectedAuth:
    """POST /api/meeting-detected — new Bearer-authed extension path."""

    async def test_returns_401_without_auth(self, client_with_detector):
        client, _ = client_with_detector
        resp = await client.post(
            "/api/meeting-detected",
            json={"platform": "meet", "url": "https://meet.google.com/abc"},
        )
        assert resp.status == 401

    async def test_returns_401_with_wrong_bearer(self, client_with_detector):
        client, _ = client_with_detector
        resp = await client.post(
            "/api/meeting-detected",
            json={"platform": "meet", "url": "https://meet.google.com/abc"},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status == 401

    async def test_returns_200_with_valid_bearer(self, client_with_detector):
        client, mock_detector = client_with_detector
        async def _started(**_kwargs):
            return True
        mock_detector.handle_extension_meeting_detected = _started

        resp = await client.post(
            "/api/meeting-detected",
            json={
                "platform": "meet",
                "url": "https://meet.google.com/abc",
                "title": "Standup",
                "tabId": 42,
            },
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "recording_started"

    async def test_missing_fields_returns_400(self, client_with_detector):
        client, _ = client_with_detector
        resp = await client.post(
            "/api/meeting-detected",
            json={"platform": "meet"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400


@pytest.mark.asyncio
class TestApiMeetingEndedAuth:
    """POST /api/meeting-ended — new Bearer-authed extension path."""

    async def test_returns_401_without_auth(self, client_with_detector):
        client, _ = client_with_detector
        resp = await client.post(
            "/api/meeting-ended",
            json={"tabId": 42},
        )
        assert resp.status == 401

    async def test_returns_200_with_valid_bearer(self, client_with_detector):
        client, mock_detector = client_with_detector
        async def _stopped(**_kwargs):
            return True
        mock_detector.handle_extension_meeting_ended = _stopped

        resp = await client.post(
            "/api/meeting-ended",
            json={"tabId": 42},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "recording_stopped"


@pytest.mark.asyncio
class TestApiParticipantsUpdatedEndpoint:
    """POST /api/meeting-participants-updated — Bearer-authed browser roster push."""

    async def test_returns_401_without_auth(self, client_with_detector):
        client, _ = client_with_detector
        resp = await client.post(
            "/api/meeting-participants-updated",
            json={"tabId": 1, "participants": ["Alice"]},
        )
        assert resp.status == 401

    async def test_missing_tab_id_returns_400(self, client_with_detector):
        client, _ = client_with_detector
        resp = await client.post(
            "/api/meeting-participants-updated",
            json={"participants": ["Alice"]},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

    async def test_missing_participants_returns_400(self, client_with_detector):
        client, _ = client_with_detector
        resp = await client.post(
            "/api/meeting-participants-updated",
            json={"tabId": 1},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

    async def test_participants_not_a_list_returns_400(self, client_with_detector):
        client, _ = client_with_detector
        resp = await client.post(
            "/api/meeting-participants-updated",
            json={"tabId": 1, "participants": "Alice"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

    async def test_body_not_object_returns_400(self, client_with_detector):
        client, _ = client_with_detector
        resp = await client.post(
            "/api/meeting-participants-updated",
            json=["not", "an", "object"],
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

    async def test_invalid_json_returns_400(self, client_with_detector):
        client, _ = client_with_detector
        resp = await client.post(
            "/api/meeting-participants-updated",
            data="not json",
            headers={
                "Authorization": f"Bearer {AUTH_TOKEN}",
                "Content-Type": "application/json",
            },
        )
        assert resp.status == 400

    async def test_non_string_entries_filtered(self, client_with_detector):
        client, mock_detector = client_with_detector
        captured: dict = {}
        async def _handler(**kwargs):
            captured.update(kwargs)
            return True
        mock_detector.handle_extension_participants_updated = _handler

        resp = await client.post(
            "/api/meeting-participants-updated",
            json={"tabId": 42, "participants": ["Alice", None, {"x": "y"}, 123, "Carol"]},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        # Filtered down to only strings.
        assert captured["participants"] == ["Alice", "Carol"]

    async def test_truncates_at_100(self, client_with_detector, caplog):
        import logging
        client, mock_detector = client_with_detector
        captured: dict = {}
        async def _handler(**kwargs):
            captured.update(kwargs)
            return True
        mock_detector.handle_extension_participants_updated = _handler

        big = [f"User{i}" for i in range(150)]
        with caplog.at_level(logging.WARNING):
            resp = await client.post(
                "/api/meeting-participants-updated",
                json={"tabId": 1, "participants": big},
                headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            )
        assert resp.status == 200
        assert len(captured["participants"]) == 100
        assert any("truncated" in r.message.lower() for r in caplog.records)

    async def test_returns_ignored_when_handler_returns_false(self, client_with_detector):
        client, mock_detector = client_with_detector
        async def _handler(**kwargs): return False
        mock_detector.handle_extension_participants_updated = _handler

        resp = await client.post(
            "/api/meeting-participants-updated",
            json={"tabId": 42, "participants": ["Alice"]},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ignored"

    async def test_returns_accepted_when_handler_returns_true(self, client_with_detector):
        client, mock_detector = client_with_detector
        async def _handler(**kwargs): return True
        mock_detector.handle_extension_participants_updated = _handler

        resp = await client.post(
            "/api/meeting-participants-updated",
            json={"tabId": 42, "participants": ["Alice"]},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "accepted"

    async def test_no_detector_returns_503(self, client):
        resp = await client.post(
            "/api/meeting-participants-updated",
            json={"tabId": 1, "participants": ["Alice"]},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 503


@pytest.mark.asyncio
class TestLegacyRoutesDeleted:
    """Phase 4: the unauth ``/meeting-detected`` and ``/meeting-ended``
    transitional routes are gone. Only ``/api/meeting-*`` remains.
    """

    async def test_legacy_meeting_detected_returns_404(self, client):
        resp = await client.post(
            "/meeting-detected",
            json={
                "platform": "meet",
                "url": "https://meet.google.com/abc",
                "title": "Standup",
                "tabId": 42,
            },
        )
        assert resp.status == 404

    async def test_legacy_meeting_ended_returns_404(self, client):
        resp = await client.post("/meeting-ended", json={"tabId": 42})
        assert resp.status == 404


@pytest.mark.asyncio
class TestApiStatusReal:
    """Task 6: ``/api/status`` returns real uptime + recent errors.

    The ``client`` fixture has no daemon wired, so uptime is 0 and
    errors are empty. ``daemon_client`` wires a real Daemon with an
    EventJournal so uptime > 0 and journal errors surface in the
    response.
    """

    async def test_no_daemon_still_returns_placeholder(self, client):
        """Missing daemon yields uptime=0, recent_errors=[]."""
        resp = await client.get(
            "/api/status",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["uptime_seconds"] == 0
        assert data["recent_errors"] == []

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


@pytest.mark.asyncio
class TestApiIndexRename:
    """POST /api/index/rename — update EventIndex path for Phase 4 plugin."""

    async def test_api_index_rename_updates_index(self, daemon_client):
        """Success path: POST updates path, preserves org."""
        client, daemon = daemon_client
        daemon.event_index.add(
            "evt-abc",
            pathlib.Path("Clients/D/Meetings/2026-04-14 - old.md"),
            "disbursecloud",
        )

        resp = await client.post(
            "/api/index/rename",
            json={
                "event_id": "evt-abc",
                "old_path": "Clients/D/Meetings/2026-04-14 - old.md",
                "new_path": "Clients/D/Meetings/2026-04-14 - new.md",
            },
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )

        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"

        entry = daemon.event_index.lookup("evt-abc")
        assert entry is not None
        assert str(entry.path) == "Clients/D/Meetings/2026-04-14 - new.md"
        # org is preserved by EventIndex.rename.
        assert entry.org == "disbursecloud"

    async def test_api_index_rename_requires_bearer(self, daemon_client):
        """Missing Authorization header returns 401."""
        client, _ = daemon_client
        resp = await client.post(
            "/api/index/rename",
            json={
                "event_id": "evt-abc",
                "new_path": "Clients/D/Meetings/new.md",
            },
        )
        assert resp.status == 401

    async def test_api_index_rename_missing_fields_returns_400(self, daemon_client):
        """Empty body or missing event_id / new_path returns 400."""
        client, _ = daemon_client

        # Empty body
        resp = await client.post(
            "/api/index/rename",
            json={},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

        # Missing new_path
        resp = await client.post(
            "/api/index/rename",
            json={"event_id": "evt-abc"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

        # Missing event_id
        resp = await client.post(
            "/api/index/rename",
            json={"new_path": "Clients/D/Meetings/new.md"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

    async def test_api_index_rename_absolute_path_returns_400(self, daemon_client):
        """POSIX-absolute and Windows-drive paths are rejected with 400."""
        client, _ = daemon_client

        # POSIX absolute
        resp = await client.post(
            "/api/index/rename",
            json={
                "event_id": "evt-abc",
                "new_path": "/Clients/D/Meetings/new.md",
            },
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400
        data = await resp.json()
        assert "vault-relative" in data["error"]

        # Windows drive letter
        resp = await client.post(
            "/api/index/rename",
            json={
                "event_id": "evt-abc",
                "new_path": "C:/Users/tim/vault/Clients/D/Meetings/new.md",
            },
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400
        data = await resp.json()
        assert "vault-relative" in data["error"]

    async def test_api_index_rename_journals_event(self, daemon_client):
        """Successful rename emits an ``index_rename`` journal entry."""
        client, daemon = daemon_client
        daemon.event_index.add(
            "evt-xyz",
            pathlib.Path("Clients/D/Meetings/old.md"),
            "disbursecloud",
        )

        resp = await client.post(
            "/api/index/rename",
            json={
                "event_id": "evt-xyz",
                "new_path": "Clients/D/Meetings/renamed.md",
            },
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200

        entries = daemon.event_journal.tail(limit=50)
        rename_entries = [e for e in entries if e.get("event") == "index_rename"]
        assert len(rename_entries) == 1
        entry = rename_entries[0]
        assert entry["level"] == "info"
        assert entry["payload"] == {
            "event_id": "evt-xyz",
            "new_path": "Clients/D/Meetings/renamed.md",
        }

    async def test_api_index_rename_non_string_fields_returns_400(self, daemon_client):
        """Truthy non-string values reach the isinstance guard, not PurePosixPath."""
        client, _ = daemon_client

        # new_path as int
        resp = await client.post(
            "/api/index/rename",
            json={"event_id": "evt-abc", "new_path": 42},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400
        data = await resp.json()
        assert "must be strings" in data["error"]

        # new_path as list
        resp = await client.post(
            "/api/index/rename",
            json={"event_id": "evt-abc", "new_path": [1, 2]},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

        # event_id as dict
        resp = await client.post(
            "/api/index/rename",
            json={"event_id": {"x": 1}, "new_path": "Clients/D/new.md"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

    async def test_api_index_rename_unknown_event_id_is_noop(self, daemon_client):
        """Unknown event_id returns 200 with no side effects (matches index semantics)."""
        client, daemon = daemon_client
        # Don't seed the index — 'nope' is unknown.
        resp = await client.post(
            "/api/index/rename",
            json={"event_id": "nope", "new_path": "Clients/D/new.md"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        assert daemon.event_index.lookup("nope") is None

        # No index_rename journal entry should be emitted for the no-op.
        entries = daemon.event_journal.tail(limit=50)
        rename_entries = [e for e in entries if e.get("event") == "index_rename"]
        assert rename_entries == []


@pytest.mark.asyncio
class TestBroadcastConcurrency:
    """broadcast() must survive concurrent ws_clients mutation."""

    async def test_broadcast_survives_concurrent_client_removal(self):
        """ws_clients mutation during broadcast await must not raise.

        Regression test for a bug where ``broadcast`` iterated the live
        ``ws_clients`` set and awaited ``send_str`` inside the loop; a
        client connect/disconnect mid-send would mutate the set and the
        next iteration would raise ``RuntimeError: Set changed size
        during iteration``, dropping the broadcast.
        """
        clients: set = set()
        removed_other = [False]

        class _FakeWS:
            def __init__(self, name: str, is_remover: bool = False) -> None:
                self.name = name
                self.closed = False
                self._is_remover = is_remover

            async def send_str(self, msg: str) -> None:
                if self._is_remover and not removed_other[0]:
                    # Remove another client during our send, mutating
                    # the set while ``broadcast`` iterates it.
                    other = next(
                        (c for c in clients if c is not self), None
                    )
                    if other is not None:
                        clients.discard(other)
                        removed_other[0] = True

        ws_a = _FakeWS("a", is_remover=True)
        ws_b = _FakeWS("b")
        clients.add(ws_a)
        clients.add(ws_b)

        app = {_WS_CLIENTS_KEY: clients}
        # Must not raise RuntimeError: Set changed size during iteration.
        await broadcast(app, {"event": "test", "data": 1})
        # Sanity check: the removal actually happened during the sweep.
        assert removed_other[0]


@pytest.mark.asyncio
class TestApiNonDictBody:
    """JSON API handlers must return 400 on non-dict bodies, not 500.

    Representative test covering ``/api/index/rename`` — the fix
    (``isinstance(body, dict)`` guard after ``await request.json()``)
    is applied systematically to all seven JSON-body handlers.
    """

    async def test_api_index_rename_non_dict_body_returns_400(self, daemon_client):
        """Non-dict JSON body (string, number, list) returns 400, not 500."""
        client, _ = daemon_client
        for bad_body in ["oops", 42, [1, 2, 3]]:
            resp = await client.post(
                "/api/index/rename",
                json=bad_body,
                headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            )
            assert resp.status == 400, (
                f"Expected 400 for body={bad_body!r}, got {resp.status}"
            )
            data = await resp.json()
            assert data["error"] == "request body must be a JSON object"


@pytest.mark.asyncio
class TestCorsMiddleware:
    """CORS headers for the Obsidian plugin's app:// origin.

    The plugin runs in an Electron/Chromium context and issues
    cross-origin ``fetch`` requests with an ``Authorization`` header.
    Chromium sends preflight OPTIONS for those. Without CORS
    middleware, the daemon 401s the preflight (no Bearer) and the
    plugin sees ``Failed to fetch`` with no handler ever invoked.
    """

    async def test_options_preflight_returns_200_without_auth(self, client):
        """OPTIONS must succeed WITHOUT a Bearer token so preflight passes."""
        resp = await client.options("/api/status")
        assert resp.status == 200

    async def test_options_preflight_has_cors_allow_headers(self, client):
        """Preflight response must advertise the allowed methods + headers."""
        resp = await client.options("/api/status")
        assert resp.headers["Access-Control-Allow-Origin"] == "*"
        assert "Authorization" in resp.headers["Access-Control-Allow-Headers"]
        assert "GET" in resp.headers["Access-Control-Allow-Methods"]

    async def test_api_response_carries_cors_origin_header(self, client):
        """Actual /api/* responses must include Access-Control-Allow-Origin."""
        resp = await client.get(
            "/api/status",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        assert resp.headers["Access-Control-Allow-Origin"] == "*"


@pytest.mark.asyncio
class TestApiRecordStartBackend:
    """POST /api/record/start accepts an optional ``backend`` field that
    flows end-to-end into ``RecordingMetadata.llm_backend``, so the user
    can pick Claude vs Ollama from the Meetings panel's Start modal
    without going through the Signal popup (Scenario 2).
    """

    def _make_client(self, aiohttp_client):
        from recap.daemon.server import create_app
        mock_recorder = MagicMock()
        mock_recorder.is_recording = False
        started: dict = {}
        async def _start(org, metadata=None, *, detected=False, backend=None):
            started["org"] = org
            started["backend"] = backend
            started["metadata"] = metadata
            return pathlib.Path("/tmp/rec.flac")
        mock_recorder.start = _start
        app = create_app(auth_token=AUTH_TOKEN, recorder=mock_recorder)
        return aiohttp_client(app), started

    async def test_omitted_backend_passes_none_to_recorder(
        self, aiohttp_client,
    ):
        client_coro, started = self._make_client(aiohttp_client)
        client = await client_coro
        resp = await client.post(
            "/api/record/start",
            json={"org": "acme"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        assert started["org"] == "acme"
        assert started["backend"] is None

    async def test_ollama_backend_flows_through(self, aiohttp_client):
        client_coro, started = self._make_client(aiohttp_client)
        client = await client_coro
        resp = await client.post(
            "/api/record/start",
            json={"org": "acme", "backend": "ollama"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        assert started["backend"] == "ollama"

    async def test_unknown_backend_returns_400(self, aiohttp_client):
        client_coro, started = self._make_client(aiohttp_client)
        client = await client_coro
        resp = await client.post(
            "/api/record/start",
            json={"org": "acme", "backend": "gpt4"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400
        # Recorder must NOT have been invoked when the body is invalid.
        assert "org" not in started


@pytest.mark.asyncio
class TestApiConfigOrgsShape:
    """GET /api/config/orgs returns org names, each org's default backend,
    and the full list of supported backends so the Start modal can pick
    a sensible default and offer all options."""

    async def test_returns_orgs_default_backends_and_backend_list(
        self, aiohttp_client, tmp_path,
    ):
        from recap.daemon.server import create_app
        cfg = make_daemon_config(tmp_path)
        app = create_app(auth_token=AUTH_TOKEN, config=cfg)
        client = await aiohttp_client(app)
        resp = await client.get(
            "/api/config/orgs",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        # Response must include: orgs (list of {name, default_backend})
        # and a ``backends`` list naming the supported analysis backends.
        assert "orgs" in data and isinstance(data["orgs"], list)
        assert "backends" in data
        assert set(data["backends"]) >= {"claude", "ollama"}
        for org in data["orgs"]:
            assert "name" in org
            assert "default_backend" in org


@pytest.mark.asyncio
class TestApiStatusManagedFlag:
    """``/api/status`` exposes ``managed`` and ``can_restart``.

    The plugin reads ``can_restart`` to decide whether its Restart
    Daemon button is actionable. The daemon only advertises
    ``can_restart: true`` when launched under the ``recap.launcher``
    wrapper (``RECAP_MANAGED=1``); standalone daemons cannot be
    restarted because nothing would respawn them.
    """

    async def test_unmanaged_daemon_reports_cannot_restart(
        self, daemon_client, monkeypatch,
    ):
        monkeypatch.delenv("RECAP_MANAGED", raising=False)
        client, daemon = daemon_client
        # ``Daemon.managed`` is captured at construction; reset it here
        # so the fixture's pre-existing daemon reflects the unset env.
        daemon.managed = False
        resp = await client.get(
            "/api/status",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["managed"] is False
        assert data["can_restart"] is False

    async def test_managed_daemon_reports_can_restart(
        self, daemon_client, monkeypatch,
    ):
        monkeypatch.setenv("RECAP_MANAGED", "1")
        client, daemon = daemon_client
        daemon.managed = True
        resp = await client.get(
            "/api/status",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["managed"] is True
        assert data["can_restart"] is True


@pytest.mark.asyncio
class TestApiAdminShutdown:
    """``POST /api/admin/shutdown`` triggers a graceful shutdown.

    ``{"restart": true}`` sets ``daemon.restart_requested`` before
    requesting shutdown so the ``__main__`` exit handler can translate
    it into ``EXIT_RESTART_REQUESTED`` for the launcher. Without the
    body (or with ``restart: false``) the daemon simply stops.
    """

    async def test_requires_auth(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post("/api/admin/shutdown")
        assert resp.status == 401

    async def test_shutdown_without_restart_flag(self, daemon_client):
        client, daemon = daemon_client
        resp = await client.post(
            "/api/admin/shutdown",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "shutdown_requested"
        assert data["restart"] is False
        assert daemon.restart_requested is False

    async def test_shutdown_with_restart_true_sets_flag(self, daemon_client):
        client, daemon = daemon_client
        # Restart is only honored in managed mode; simulate the launcher
        # having set ``RECAP_MANAGED=1`` before the daemon booted.
        daemon.managed = True
        resp = await client.post(
            "/api/admin/shutdown",
            json={"restart": True},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "shutdown_requested"
        assert data["restart"] is True
        assert daemon.restart_requested is True

    async def test_restart_requires_managed_mode(
        self, daemon_client, monkeypatch,
    ):
        """Restart is refused on an unmanaged daemon.

        Accepting it anyway would shut the daemon down with no process
        to bring it back -- worse UX than refusing the call. The plugin
        already greys the button out based on ``can_restart``; this is
        the server-side enforcement behind that UI gate."""
        monkeypatch.delenv("RECAP_MANAGED", raising=False)
        client, daemon = daemon_client
        daemon.managed = False
        resp = await client.post(
            "/api/admin/shutdown",
            json={"restart": True},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 409
        data = await resp.json()
        assert "not managed" in data["error"].lower()
        assert daemon.restart_requested is False

    async def test_rejects_non_dict_body(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post(
            "/api/admin/shutdown",
            data="not-json",
            headers={
                "Authorization": f"Bearer {AUTH_TOKEN}",
                "Content-Type": "application/json",
            },
        )
        assert resp.status == 400


@pytest.mark.asyncio
class TestApiMeetingSpeakersGet:
    """GET /api/meetings/{stem}/speakers — returns speaker list + participants (#28)."""

    async def test_returns_401_without_auth(self, daemon_client):
        client, _ = daemon_client
        resp = await client.get("/api/meetings/some-stem/speakers")
        assert resp.status == 401

    async def test_returns_400_invalid_stem(self, daemon_client):
        """Path-traversal attempt is rejected via _STEM_RE."""
        client, _ = daemon_client
        # aiohttp decodes %2F to /, which may or may not match the route.
        # What we REALLY want to verify is that the regex validator rejects
        # bad stems. Test with an explicitly-bad stem that still matches the route:
        resp = await client.get(
            "/api/meetings/foo$bar/speakers",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

    async def test_returns_404_for_missing_recording(self, daemon_client):
        client, _ = daemon_client
        resp = await client.get(
            "/api/meetings/nonexistent/speakers",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 404

    async def test_returns_404_when_transcript_missing(self, daemon_client):
        client, daemon = daemon_client
        (daemon.config.recordings_path / "rec.flac").touch()
        resp = await client.get(
            "/api/meetings/rec/speakers",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 404

    async def test_returns_distinct_speakers_in_order(self, daemon_client):
        client, daemon = daemon_client
        audio = daemon.config.recordings_path / "rec.flac"
        audio.touch()
        from recap.artifacts import save_transcript
        from recap.models import TranscriptResult, Utterance
        save_transcript(audio, TranscriptResult(
            utterances=[
                Utterance(speaker_id="SPEAKER_00", speaker="Alice",
                          start=0, end=1, text="hi"),
                Utterance(speaker_id="SPEAKER_01", speaker="Bob",
                          start=1, end=2, text="hey"),
                Utterance(speaker_id="SPEAKER_00", speaker="Alice",
                          start=2, end=3, text="again"),
            ],
            raw_text="...", language="en",
        ))
        resp = await client.get(
            "/api/meetings/rec/speakers",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["speakers"] == [
            {"speaker_id": "SPEAKER_00", "display": "Alice"},
            {"speaker_id": "SPEAKER_01", "display": "Bob"},
        ]
        assert data["participants"] == []  # no sidecar in this test

    async def test_backfills_legacy_transcript_on_the_fly(self, daemon_client):
        """Pre-#28 transcript with only `speaker` field still produces correct output."""
        client, daemon = daemon_client
        audio = daemon.config.recordings_path / "rec.flac"
        audio.touch()
        from recap.artifacts import transcript_path
        legacy = {
            "utterances": [
                {"speaker": "SPEAKER_00", "start": 0, "end": 1, "text": "hi"},
            ],
            "raw_text": "hi", "language": "en",
        }
        transcript_path(audio).write_text(json.dumps(legacy))

        resp = await client.get(
            "/api/meetings/rec/speakers",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["speakers"] == [{"speaker_id": "SPEAKER_00", "display": "SPEAKER_00"}]

    async def test_returns_empty_list_for_zero_utterances(self, daemon_client):
        client, daemon = daemon_client
        audio = daemon.config.recordings_path / "rec.flac"
        audio.touch()
        from recap.artifacts import save_transcript
        from recap.models import TranscriptResult
        save_transcript(audio, TranscriptResult(
            utterances=[], raw_text="", language="en",
        ))
        resp = await client.get(
            "/api/meetings/rec/speakers",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["speakers"] == []
        assert data["participants"] == []

    async def test_participants_from_sidecar_with_emails(self, daemon_client):
        """Response includes participants list with emails from sidecar."""
        client, daemon = daemon_client
        audio = daemon.config.recordings_path / "rec.flac"
        audio.touch()
        from recap.artifacts import save_transcript, write_recording_metadata
        from recap.artifacts import RecordingMetadata
        from recap.models import (
            TranscriptResult, Utterance, Participant,
        )
        save_transcript(audio, TranscriptResult(
            utterances=[Utterance(speaker_id="SPEAKER_00", speaker="SPEAKER_00",
                                  start=0, end=1, text="x")],
            raw_text="x", language="en",
        ))
        rm = RecordingMetadata(
            org="test", note_path="", title="T", date="2026-04-24",
            participants=[
                Participant(name="Alice", email="alice@x.com"),
                Participant(name="Bob", email=None),
            ],
            platform="manual",
        )
        write_recording_metadata(audio, rm)

        resp = await client.get(
            "/api/meetings/rec/speakers",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["participants"] == [
            {"name": "Alice", "email": "alice@x.com"},
            {"name": "Bob", "email": None},
        ]

    async def test_participants_empty_when_sidecar_missing(self, daemon_client):
        """No RecordingMetadata sidecar → participants: []. Older/manual recordings."""
        client, daemon = daemon_client
        audio = daemon.config.recordings_path / "rec.flac"
        audio.touch()
        from recap.artifacts import save_transcript
        from recap.models import TranscriptResult, Utterance
        save_transcript(audio, TranscriptResult(
            utterances=[Utterance(speaker_id="SPEAKER_00", speaker="Alice",
                                  start=0, end=1, text="hi")],
            raw_text="hi", language="en",
        ))
        # No write_recording_metadata call.
        resp = await client.get(
            "/api/meetings/rec/speakers",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["participants"] == []


@pytest_asyncio.fixture
async def speakers_post_client(aiohttp_client, tmp_path):
    """Return ``(client, daemon, trigger_calls)`` for POST /api/meetings/speakers.

    Wires:
      - A real :class:`Daemon` with a real ``config.yaml`` on disk so
        ``_apply_contact_mutations`` can round-trip the file and
        ``daemon.refresh_config()`` can pick up the new state.
      - A pipeline trigger that records calls into ``trigger_calls`` so
        tests can assert ``(rec_path, org, "analyze")`` was dispatched.
    """
    from recap.daemon.server import create_app
    from recap.daemon.service import Daemon
    from tests.conftest import MINIMAL_API_CONFIG_YAML

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

    trigger_calls: list[tuple] = []

    async def _trigger(rec_path, org, from_stage):
        trigger_calls.append((rec_path, org, from_stage))

    app = create_app(auth_token=AUTH_TOKEN, pipeline_trigger=_trigger)
    app["daemon"] = daemon
    client = await aiohttp_client(app)
    return client, daemon, trigger_calls


def _seed_recording_with_transcript(
    daemon, stem: str = "rec",
) -> pathlib.Path:
    """Seed a .flac + .transcript.json so ``validate_from_stage('analyze')`` passes."""
    from recap.artifacts import save_transcript
    from recap.models import TranscriptResult, Utterance

    audio = daemon.config.recordings_path / f"{stem}.flac"
    audio.touch()
    save_transcript(
        audio,
        TranscriptResult(
            utterances=[
                Utterance(
                    speaker_id="SPEAKER_00", speaker="SPEAKER_00",
                    start=0, end=1, text="hi",
                ),
            ],
            raw_text="hi", language="en",
        ),
    )
    return audio


@pytest.mark.asyncio
class TestApiMeetingSpeakersPost:
    """POST /api/meetings/speakers — stem, legacy recording_path,
    contact_mutations, and People stub creation (#28 Task 14)."""

    async def test_returns_401_without_auth(self, speakers_post_client):
        client, _, _ = speakers_post_client
        resp = await client.post("/api/meetings/speakers", json={})
        assert resp.status == 401

    async def test_400_missing_both_stem_and_recording_path(
        self, speakers_post_client,
    ):
        client, _, _ = speakers_post_client
        resp = await client.post(
            "/api/meetings/speakers",
            json={"mapping": {"SPEAKER_00": "Alice"}},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400
        body = await resp.json()
        assert "stem" in body["error"] or "recording_path" in body["error"]

    async def test_400_missing_mapping(self, speakers_post_client):
        client, daemon, _ = speakers_post_client
        _seed_recording_with_transcript(daemon)
        resp = await client.post(
            "/api/meetings/speakers",
            json={"stem": "rec"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400
        body = await resp.json()
        assert "mapping" in body["error"]

    async def test_404_stem_unresolved(self, speakers_post_client):
        client, _, _ = speakers_post_client
        resp = await client.post(
            "/api/meetings/speakers",
            json={"stem": "nonexistent", "mapping": {"SPEAKER_00": "Alice"}},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 404

    async def test_200_with_stem_writes_speakers_json(
        self, speakers_post_client,
    ):
        """Stem path: daemon resolves + writes .speakers.json + triggers reprocess."""
        client, daemon, trigger_calls = speakers_post_client
        audio = _seed_recording_with_transcript(daemon)

        resp = await client.post(
            "/api/meetings/speakers",
            json={
                "stem": "rec",
                "mapping": {"SPEAKER_00": "Alice"},
                "org": "alpha",
            },
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["status"] == "processing"

        # .speakers.json written next to the audio file with the mapping.
        speakers_json = audio.with_suffix(".speakers.json")
        assert speakers_json.exists()
        assert json.loads(speakers_json.read_text()) == {"SPEAKER_00": "Alice"}

        # Pipeline reprocess triggered from analyze stage.
        await asyncio.sleep(0)  # let the create_task run
        assert len(trigger_calls) == 1
        rec_path, org, from_stage = trigger_calls[0]
        assert rec_path == audio
        assert org == "alpha"
        assert from_stage == "analyze"

    async def test_200_with_legacy_recording_path(self, speakers_post_client):
        """Old clients passing a full recording_path still work."""
        client, daemon, trigger_calls = speakers_post_client
        audio = _seed_recording_with_transcript(daemon)

        resp = await client.post(
            "/api/meetings/speakers",
            json={
                "recording_path": str(audio),
                "mapping": {"SPEAKER_00": "Bob"},
                "org": "alpha",
            },
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        speakers_json = audio.with_suffix(".speakers.json")
        assert json.loads(speakers_json.read_text()) == {"SPEAKER_00": "Bob"}

        await asyncio.sleep(0)
        assert len(trigger_calls) == 1
        assert trigger_calls[0][0] == audio
        assert trigger_calls[0][2] == "analyze"

    async def test_200_with_contact_mutations_applies_and_creates_stub(
        self, speakers_post_client,
    ):
        """create mutation lands in config.yaml AND a People stub is written."""
        import yaml

        client, daemon, trigger_calls = speakers_post_client
        _seed_recording_with_transcript(daemon)

        resp = await client.post(
            "/api/meetings/speakers",
            json={
                "stem": "rec",
                "mapping": {"SPEAKER_00": "Alice"},
                "org": "alpha",
                "contact_mutations": [
                    {
                        "action": "create",
                        "name": "Alice",
                        "display_name": "Alice",
                        "email": "alice@example.com",
                    },
                ],
            },
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200

        # known-contacts now contains Alice on disk.
        doc = yaml.safe_load(daemon.config_path.read_text())
        contacts = doc["known-contacts"]
        assert any(
            c.get("name") == "Alice" and c.get("email") == "alice@example.com"
            for c in contacts
        )

        # daemon.refresh_config() picked up the new contact.
        assert any(
            kc.name == "Alice" for kc in daemon.config.known_contacts
        )

        # People stub written under the alpha org's subfolder.
        stub_path = (
            daemon.config.vault_path / "Clients" / "Alpha"
            / "People" / "Alice.md"
        )
        assert stub_path.exists()

        await asyncio.sleep(0)
        assert len(trigger_calls) == 1

    async def test_400_on_invalid_contact_mutation_shape(
        self, speakers_post_client,
    ):
        """contact_mutations with unknown action raises ValueError -> 400."""
        client, daemon, _ = speakers_post_client
        _seed_recording_with_transcript(daemon)
        resp = await client.post(
            "/api/meetings/speakers",
            json={
                "stem": "rec",
                "mapping": {"SPEAKER_00": "Alice"},
                "contact_mutations": [{"action": "nonexistent_action"}],
                "org": "alpha",
            },
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400
        body = await resp.json()
        assert "contact mutation" in body.get("error", "").lower()

    async def test_400_on_stub_creation_unknown_org(
        self, speakers_post_client,
    ):
        """Stub creation with unknown org raises ValueError -> 400.

        Important: contacts have already been committed at this point.
        Retry is safe because both mutation and stub creation are
        idempotent.
        """
        client, daemon, _ = speakers_post_client
        _seed_recording_with_transcript(daemon)
        resp = await client.post(
            "/api/meetings/speakers",
            json={
                "stem": "rec",
                "mapping": {"SPEAKER_00": "Alice"},
                "contact_mutations": [
                    {
                        "action": "create",
                        "name": "Alice",
                        "display_name": "Alice",
                    },
                ],
                "org": "nonexistent-org",  # fails at _ensure_people_stub
            },
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400
        body = await resp.json()
        assert "stub creation" in body.get("error", "").lower()
        # Contacts were committed BEFORE stub creation failed.
        # Verify via live config (daemon.refresh_config() ran).
        assert any(c.name == "Alice" for c in daemon.config.known_contacts)

    async def test_400_on_add_alias_target_not_found(
        self, speakers_post_client,
    ):
        """add_alias targeting a non-existent contact raises ValueError -> 400."""
        client, daemon, _ = speakers_post_client
        _seed_recording_with_transcript(daemon)
        resp = await client.post(
            "/api/meetings/speakers",
            json={
                "stem": "rec",
                "mapping": {"SPEAKER_00": "Alice"},
                "contact_mutations": [
                    {"action": "add_alias", "name": "Ghost", "alias": "G."},
                ],
                "org": "alpha",
            },
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400


# ---------------------------------------------------------------------
# Helpers for TestApiAttachEvent (#33 Task 5)
# ---------------------------------------------------------------------


def _seed_unscheduled_for_attach(
    daemon, *, stem: str, event_id: str, note_path: str, body: str = "# Source body",
):
    """Seed an audio + sidecar + unscheduled note for the daemon_client fixture.

    Mirrors ``tests/test_attach.py::_seed_unscheduled_recording`` but uses the
    ``daemon_client`` fixture's org slug ``"d"`` / subfolder ``"Clients/D"``.
    """
    from recap.artifacts import RecordingMetadata, write_recording_metadata
    from recap.models import Participant
    import yaml

    audio = daemon.config.recordings_path / f"{stem}.flac"
    audio.touch()
    md = RecordingMetadata(
        org="d", note_path=note_path, title="Teams call",
        date="2026-04-24", participants=[Participant(name="Alice")],
        platform="manual",
    )
    md.event_id = event_id
    write_recording_metadata(audio, md)

    vault = daemon.config.vault_path
    (vault / note_path).parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "date": "2026-04-24",
        "time": "14:30-15:15",
        "title": "Teams call",
        "event-id": event_id,
        "org": "d",
        "org-subfolder": "Clients/D",
        "participants": ["[[Alice]]"],
        "companies": [],
        "duration": "45:00",
        "recording": f"{stem}.flac",
        "tags": ["meeting/d", "unscheduled"],
        "pipeline-status": "complete",
    }
    content = "---\n" + yaml.dump(fm, sort_keys=False) + "---\n\n" + body
    (vault / note_path).write_text(content, encoding="utf-8")
    daemon.event_index.add(event_id, pathlib.Path(note_path), "d")
    return audio


def _seed_calendar_stub_for_attach(
    daemon, *, event_id: str, title: str, stub_body: str = "## Agenda\n\n",
    extra_fm: dict | None = None,
):
    """Seed a calendar stub note under Clients/D/Meetings."""
    import yaml

    vault = daemon.config.vault_path
    stub_rel = pathlib.Path(
        "Clients/D/Meetings",
    ) / f"2026-04-24 - {title.lower().replace(' ', '-')}.md"
    full = vault / stub_rel
    full.parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "date": "2026-04-24",
        "time": "14:00-15:00",
        "title": title,
        "event-id": event_id,
        "calendar-source": "google",
        "meeting-link": "https://meet.google.com/xyz",
        "org": "d",
        "org-subfolder": "Clients/D",
        "participants": [],
        "pipeline-status": "pending",
    }
    if extra_fm:
        fm.update(extra_fm)
    content = "---\n" + yaml.dump(fm, sort_keys=False) + "---\n\n" + stub_body
    full.write_text(content, encoding="utf-8")
    daemon.event_index.add(event_id, stub_rel, "d")
    return full


@pytest.mark.asyncio
class TestApiAttachEvent:
    """POST /api/recordings/{stem}/attach-event endpoint (#33 Task 5)."""

    async def test_401_without_auth(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post(
            "/api/recordings/rec/attach-event", json={"event_id": "E1"},
        )
        assert resp.status == 401

    async def test_400_invalid_stem(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post(
            "/api/recordings/foo$bar/attach-event",
            json={"event_id": "E1"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

    async def test_400_missing_event_id(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post(
            "/api/recordings/rec/attach-event", json={},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

    async def test_400_synthetic_event_id(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post(
            "/api/recordings/rec/attach-event",
            json={"event_id": "unscheduled:abc"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400
        data = await resp.json()
        assert data["error"] == "target_event_must_be_real_calendar_event"

    async def test_404_stem_unresolved(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post(
            "/api/recordings/ghost/attach-event",
            json={"event_id": "E1"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 404

    async def test_409_on_recording_conflict(self, daemon_client):
        """Seed unscheduled + calendar stub with different existing recording.

        Asserts 409 + body.error == 'recording_conflict' + structured fields.
        """
        client, daemon = daemon_client
        # Source: unscheduled recording with rec-new.flac.
        _seed_unscheduled_for_attach(
            daemon,
            stem="rec-new",
            event_id="unscheduled:abc",
            note_path="Clients/D/Meetings/2026-04-24 1430 - Teams call.md",
            body="# new body",
        )
        # Target stub: already has a different recording filename.
        _seed_calendar_stub_for_attach(
            daemon,
            event_id="E1",
            title="Sprint Planning",
            extra_fm={"recording": "other-rec.flac", "pipeline-status": "complete"},
        )

        resp = await client.post(
            "/api/recordings/rec-new/attach-event",
            json={"event_id": "E1"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 409
        data = await resp.json()
        assert data["error"] == "recording_conflict"
        assert data["existing_recording"] == "other-rec.flac"
        assert "note_path" in data
        # Vault-relative posix path (no leading slash, no backslashes).
        assert "\\" not in data["note_path"]
        assert data["note_path"].endswith(".md")

    async def test_200_happy_path(self, daemon_client):
        """Happy-path bind via HTTP: seed + POST + verify 200 + side-effects.

        Uses a stem matching ``_STEM_RE`` (no spaces) so the route's stem
        validator passes; the orchestrator itself supports any filename
        ``resolve_recording_path`` can find.
        """
        client, daemon = daemon_client
        stem = "2026-04-24-1430-teams-call"
        unscheduled_rel = (
            "Clients/D/Meetings/2026-04-24 1430 - Teams call.md"
        )
        audio = _seed_unscheduled_for_attach(
            daemon,
            stem=stem,
            event_id="unscheduled:abc",
            note_path=unscheduled_rel,
            body="# Meeting Summary\n\nPipeline output.",
        )
        stub = _seed_calendar_stub_for_attach(
            daemon,
            event_id="E1",
            title="Sprint Planning",
        )

        resp = await client.post(
            f"/api/recordings/{stem}/attach-event",
            json={"event_id": "E1"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["status"] == "ok"
        assert body["noop"] is False
        # note_path is the stub's vault-relative path in posix form.
        assert body["note_path"].endswith(".md")
        assert "\\" not in body["note_path"]

        # Side effects: stub merged, unscheduled gone, sidecar rebound.
        merged = stub.read_text(encoding="utf-8")
        assert "Pipeline output" in merged
        assert "event-id: E1" in merged
        unscheduled_abs = daemon.config.vault_path / unscheduled_rel
        assert not unscheduled_abs.exists()
        from recap.artifacts import load_recording_metadata
        loaded = load_recording_metadata(audio)
        assert loaded is not None
        assert loaded.event_id == "E1"

    async def test_200_replace_overrides_existing_recording(self, daemon_client):
        """With replace=True, the endpoint succeeds even when the target stub
        already references a different recording. Pins the wire contract for
        the conflict-resolution flow."""
        import yaml

        client, daemon = daemon_client
        _seed_unscheduled_for_attach(
            daemon, stem="rec-new", event_id="unscheduled:abc",
            note_path="Clients/D/Meetings/u.md", body="# New body",
        )
        # Calendar stub already carries a different recording.
        vault = daemon.config.vault_path
        stub_rel = pathlib.Path("Clients/D/Meetings/2026-04-24 - sprint.md")
        fm = {
            "date": "2026-04-24", "time": "14:00-15:00", "title": "Sprint",
            "event-id": "E1", "calendar-source": "google",
            "meeting-link": "", "org": "d", "org-subfolder": "Clients/D",
            "recording": "other-rec.flac",
            "pipeline-status": "complete",
        }
        (vault / stub_rel).write_text(
            "---\n" + yaml.dump(fm, sort_keys=False) + "---\n\n## Agenda\n\n",
            encoding="utf-8",
        )
        daemon.event_index.add("E1", stub_rel, "d")

        resp = await client.post(
            "/api/recordings/rec-new/attach-event",
            json={"event_id": "E1", "replace": True},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"
        assert data["noop"] is False
        # New recording overwrote old.
        content = (vault / stub_rel).read_text(encoding="utf-8")
        assert "rec-new.flac" in content
        assert "other-rec.flac" not in content

    async def test_400_non_bool_replace(self, daemon_client):
        """replace must be a boolean, not a truthy string."""
        client, _ = daemon_client
        resp = await client.post(
            "/api/recordings/rec/attach-event",
            json={"event_id": "E1", "replace": "true"},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400
        data = await resp.json()
        assert data["error"] == "replace must be a boolean"

    async def test_400_malformed_json(self, daemon_client):
        """Body that fails JSON parsing returns 400."""
        client, _ = daemon_client
        resp = await client.post(
            "/api/recordings/rec/attach-event",
            data=b"{not json",
            headers={
                "Authorization": f"Bearer {AUTH_TOKEN}",
                "Content-Type": "application/json",
            },
        )
        assert resp.status == 400
        data = await resp.json()
        assert data["error"] == "invalid JSON body"

    async def test_400_non_dict_body(self, daemon_client):
        """Body that parses but isn't an object returns 400."""
        client, _ = daemon_client
        resp = await client.post(
            "/api/recordings/rec/attach-event",
            json=["not", "an", "object"],
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400
        data = await resp.json()
        assert data["error"] == "body must be an object"

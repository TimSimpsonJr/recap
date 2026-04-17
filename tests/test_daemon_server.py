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

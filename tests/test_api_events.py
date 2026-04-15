"""Tests for GET /api/events — journal backfill endpoint (Phase 4 Task 1)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from recap.daemon.server import create_app
from recap.daemon.service import Daemon
from tests.conftest import make_daemon_config

AUTH_TOKEN = "test-secret-token-abc123"


@pytest_asyncio.fixture
async def daemon_client(aiohttp_client, tmp_path):
    """Return (client, daemon) with an app wired to a real Daemon.

    Mirrors the fixture in ``tests/test_daemon_server.py``; kept local
    so this module stands on its own while still exercising a real
    ``EventJournal`` on disk.
    """
    cfg = make_daemon_config(tmp_path)
    daemon = Daemon(cfg)
    daemon.started_at = (
        datetime.now(timezone.utc).astimezone() - timedelta(seconds=5)
    )
    app = create_app(auth_token=AUTH_TOKEN)
    app["daemon"] = daemon
    client = await aiohttp_client(app)
    return client, daemon


@pytest.mark.asyncio
class TestApiEvents:
    """GET /api/events — journal backfill for plugin notification history."""

    async def test_returns_empty_list_when_no_journal_entries(self, daemon_client):
        client, _ = daemon_client
        resp = await client.get(
            "/api/events",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data == {"entries": []}

    async def test_returns_entries_ascending(self, daemon_client):
        client, daemon = daemon_client
        daemon.event_journal.append("info", "e1", "m1")
        daemon.event_journal.append("info", "e2", "m2")
        daemon.event_journal.append("info", "e3", "m3")

        resp = await client.get(
            "/api/events",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        entries = data["entries"]
        assert [e["message"] for e in entries] == ["m1", "m2", "m3"]
        # Ascending by ts
        timestamps = [e["ts"] for e in entries]
        assert timestamps == sorted(timestamps)

    async def test_limit_caps_results(self, daemon_client):
        client, daemon = daemon_client
        for i in range(10):
            daemon.event_journal.append("info", "e", f"m{i}")

        resp = await client.get(
            "/api/events?limit=3",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        entries = data["entries"]
        assert [e["message"] for e in entries] == ["m7", "m8", "m9"]

    async def test_since_filters_strictly_after(self, daemon_client):
        client, daemon = daemon_client
        daemon.event_journal.append("info", "e1", "m1")
        daemon.event_journal.append("info", "middle", "m-middle")

        # Capture the middle timestamp — ts of the most recent entry.
        middle_ts = daemon.event_journal.tail(limit=1)[0]["ts"]

        # Sleep long enough to ensure a strictly-greater microsecond.
        time.sleep(0.01)

        daemon.event_journal.append("info", "e3", "m3")
        daemon.event_journal.append("info", "e4", "m4")

        resp = await client.get(
            f"/api/events?since={middle_ts}",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        messages = [e["message"] for e in data["entries"]]
        assert messages == ["m3", "m4"]

    async def test_malformed_since_returns_400(self, daemon_client):
        client, _ = daemon_client
        resp = await client.get(
            "/api/events?since=not-a-timestamp",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

    async def test_malformed_limit_returns_400(self, daemon_client):
        client, _ = daemon_client
        resp = await client.get(
            "/api/events?limit=not-a-number",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

    async def test_limit_out_of_range_is_clamped(self, daemon_client):
        client, daemon = daemon_client
        daemon.event_journal.append("info", "e", "m")

        # Above max — clamp to _MAX_EVENTS_LIMIT.
        resp = await client.get(
            "/api/events?limit=9999",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200

        # Below min (0) — clamp to 1.
        resp = await client.get(
            "/api/events?limit=0",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200

    async def test_requires_bearer(self, daemon_client):
        client, _ = daemon_client
        resp = await client.get("/api/events")
        assert resp.status == 401

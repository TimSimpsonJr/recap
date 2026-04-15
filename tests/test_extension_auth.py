"""Extension auth contract (Phase 6 Task 5).

Consolidates the finalized post-Phase-4 protocol into one place:

  1. /api/meeting-* requires Bearer auth.
  2. /bootstrap/token serves only while PairingWindow is open.
  3. /bootstrap/token enforces loopback-only (defense-in-depth).
  4. A 401 on any /api/* path means "re-pair", not "retry".

This file is the surface-area audit; per-endpoint behavior tests
live in test_daemon_server.py and test_pairing.py.
"""
from __future__ import annotations

import pytest

from tests.conftest import AUTH_TOKEN


@pytest.mark.asyncio
class TestMeetingApiBearer:
    """Contract: /api/meeting-detected and /api/meeting-ended both
    require a Bearer header that exactly matches the daemon auth token.
    """

    async def test_meeting_detected_no_auth_returns_401(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post(
            "/api/meeting-detected",
            json={"platform": "meet", "url": "https://meet.google.com/x", "title": "x"},
        )
        assert resp.status == 401

    async def test_meeting_detected_wrong_bearer_returns_401(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post(
            "/api/meeting-detected",
            headers={"Authorization": "Bearer not-the-real-token"},
            json={"platform": "meet", "url": "https://meet.google.com/x", "title": "x"},
        )
        assert resp.status == 401

    async def test_meeting_ended_no_auth_returns_401(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post("/api/meeting-ended", json={"tabId": 1})
        assert resp.status == 401


@pytest.mark.asyncio
class TestBootstrapTokenWindow:
    """Contract: /bootstrap/token returns 200 only during an open
    PairingWindow; before/after the window it returns 404.
    """

    async def test_returns_404_before_window_opens(self, daemon_client):
        client, daemon = daemon_client
        # Pairing window is closed by default.
        resp = await client.get("/bootstrap/token")
        assert resp.status == 404

    async def test_returns_token_during_open_window(self, daemon_client):
        client, daemon = daemon_client
        daemon.pairing.open()
        resp = await client.get("/bootstrap/token")
        assert resp.status == 200
        body = await resp.json()
        assert body["token"] == AUTH_TOKEN

    async def test_window_is_one_shot(self, daemon_client):
        client, daemon = daemon_client
        daemon.pairing.open()
        resp1 = await client.get("/bootstrap/token")
        assert resp1.status == 200
        resp2 = await client.get("/bootstrap/token")
        assert resp2.status == 404


@pytest.mark.asyncio
class TestBootstrapLoopbackOnly:
    """Contract: /bootstrap/token rejects non-loopback peers even when
    the PairingWindow is open. The handler reads the peer IP via
    ``server._extract_peer_ip``; we patch that to force a non-loopback
    address and assert the route returns 403 from the actual handler
    code path. (Phase 3 already covers this in
    ``tests/test_pairing.py::TestBootstrapTokenRoute::test_rejects_non_loopback``;
    Task 5 re-runs the same real-behavior check inside the
    consolidated extension-auth surface so the contract is auditable
    in one file.)
    """

    async def test_rejects_non_loopback_peer(
        self, daemon_client, monkeypatch,
    ):
        from recap.daemon import server as server_mod

        client, daemon = daemon_client
        daemon.pairing.open()
        # raising=True so a future rename of _extract_peer_ip turns this
        # silent monkeypatch into an AttributeError instead of a no-op.
        monkeypatch.setattr(
            server_mod, "_extract_peer_ip",
            lambda _request: "10.0.0.5", raising=True,
        )

        resp = await client.get("/bootstrap/token")
        assert resp.status == 403
        # The window stays open so a real loopback caller can still
        # complete the pair after the spoofed peer is rejected.
        assert daemon.pairing.is_open is True

    async def test_loopback_peer_succeeds_when_window_open(
        self, daemon_client, monkeypatch,
    ):
        from recap.daemon import server as server_mod

        client, daemon = daemon_client
        daemon.pairing.open()
        # Force the peer to look like a loopback IP regardless of the
        # transport ``aiohttp.test_utils`` reports. raising=True catches
        # silent drift if _extract_peer_ip is ever renamed.
        monkeypatch.setattr(
            server_mod, "_extract_peer_ip",
            lambda _request: "127.0.0.1", raising=True,
        )

        resp = await client.get("/bootstrap/token")
        assert resp.status == 200


@pytest.mark.asyncio
class TestPostPairingApiAccess:
    """Contract: after a successful pairing, the same token works on
    /api/* endpoints -- i.e. the bootstrap token IS the daemon auth
    token, not a one-shot exchange voucher.
    """

    async def test_paired_token_works_on_status(self, daemon_client):
        client, daemon = daemon_client
        daemon.pairing.open()
        boot = await client.get("/bootstrap/token")
        token = (await boot.json())["token"]
        resp = await client.get(
            "/api/status", headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status == 200

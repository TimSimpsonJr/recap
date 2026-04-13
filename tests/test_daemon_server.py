"""Tests for the daemon HTTP server."""

import pytest
import pytest_asyncio
from unittest.mock import MagicMock

from recap.daemon.server import create_app

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

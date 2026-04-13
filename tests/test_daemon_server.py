"""Tests for the daemon HTTP server."""

import pytest
import pytest_asyncio

from recap.daemon.server import create_app

AUTH_TOKEN = "test-secret-token-abc123"


@pytest_asyncio.fixture
async def client(aiohttp_client):
    """Create a test client for the daemon app."""
    app = create_app(auth_token=AUTH_TOKEN)
    return await aiohttp_client(app)


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

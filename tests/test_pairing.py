"""Tests for the pairing window and /bootstrap/token route (design §0.5)."""
from __future__ import annotations

import pytest
import pytest_asyncio

from recap.daemon.pairing import PairingWindow
from recap.daemon.server import create_app
from recap.daemon.service import Daemon
from tests.conftest import make_daemon_config


# ----------------------------------------------------------------------
# PairingWindow unit tests
# ----------------------------------------------------------------------


class _StubJournal:
    """Minimal EventJournal stand-in that captures appends for assertions."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str, str, dict | None]] = []

    def append(self, level, event, message, *, payload=None):
        self.entries.append((level, event, message, payload))


class TestPairingWindowState:
    def test_initial_state_closed(self):
        j = _StubJournal()
        w = PairingWindow(journal=j)
        assert w.is_open is False
        assert w.current_token is None
        assert j.entries == []

    def test_open_enables_endpoint_and_journals(self):
        j = _StubJournal()
        w = PairingWindow(journal=j)
        w.open()
        assert w.is_open
        assert w.current_token is not None
        assert len(w.current_token) > 16  # token_urlsafe(32) is ~43 chars
        assert any(e[1] == "pairing_opened" for e in j.entries)

    def test_open_is_idempotent(self):
        """Double-open while already open is a no-op; token stays stable."""
        j = _StubJournal()
        w = PairingWindow(journal=j)
        w.open()
        first_token = w.current_token
        w.open()
        assert w.current_token == first_token
        # Only one pairing_opened event should have been journaled.
        opens = [e for e in j.entries if e[1] == "pairing_opened"]
        assert len(opens) == 1


class TestPairingWindowConsume:
    def test_consume_token_once_only(self):
        j = _StubJournal()
        w = PairingWindow(journal=j)
        w.open()
        token = w.consume(requester_ip="127.0.0.1")
        assert token is not None
        assert w.is_open is False  # one-shot
        assert w.current_token is None
        assert any(e[1] == "pairing_token_issued" for e in j.entries)
        # Second consume fails with RuntimeError (window closed).
        with pytest.raises(RuntimeError):
            w.consume(requester_ip="127.0.0.1")

    def test_consume_when_closed_raises(self):
        j = _StubJournal()
        w = PairingWindow(journal=j)
        with pytest.raises(RuntimeError, match="closed"):
            w.consume(requester_ip="127.0.0.1")

    def test_consume_from_ipv6_loopback_allowed(self):
        j = _StubJournal()
        w = PairingWindow(journal=j)
        w.open()
        token = w.consume(requester_ip="::1")
        assert token is not None

    def test_consume_from_non_loopback_fails_and_journals(self):
        j = _StubJournal()
        w = PairingWindow(journal=j)
        w.open()
        with pytest.raises(PermissionError):
            w.consume(requester_ip="10.0.0.5")
        assert any(e[1] == "pairing_failed_non_loopback" for e in j.entries)
        # Window stays open for the legitimate consumer.
        assert w.is_open
        # A subsequent loopback consume still succeeds.
        token = w.consume(requester_ip="127.0.0.1")
        assert token is not None


class TestPairingWindowTimeout:
    def test_timeout_closes_and_journals(self, monkeypatch):
        j = _StubJournal()
        clock = {"t": 0.0}
        monkeypatch.setattr("recap.daemon.pairing._now", lambda: clock["t"])
        w = PairingWindow(journal=j, timeout_seconds=60)
        w.open()
        assert w.is_open
        # Advance past the timeout and poke.
        clock["t"] = 61.0
        w.check_timeout()
        assert w.is_open is False
        assert w.current_token is None
        assert any(e[1] == "pairing_closed_timeout" for e in j.entries)

    def test_check_timeout_noop_when_closed(self, monkeypatch):
        j = _StubJournal()
        clock = {"t": 0.0}
        monkeypatch.setattr("recap.daemon.pairing._now", lambda: clock["t"])
        w = PairingWindow(journal=j, timeout_seconds=60)
        # Never opened -- check_timeout is a no-op and journals nothing.
        w.check_timeout()
        assert w.is_open is False
        assert j.entries == []

    def test_check_timeout_noop_before_expiry(self, monkeypatch):
        j = _StubJournal()
        clock = {"t": 0.0}
        monkeypatch.setattr("recap.daemon.pairing._now", lambda: clock["t"])
        w = PairingWindow(journal=j, timeout_seconds=60)
        w.open()
        clock["t"] = 30.0
        w.check_timeout()
        assert w.is_open
        # No timeout event yet.
        assert not any(e[1] == "pairing_closed_timeout" for e in j.entries)


# ----------------------------------------------------------------------
# /bootstrap/token route tests
# ----------------------------------------------------------------------


AUTH_TOKEN = "test-daemon-auth-token-xyz"


@pytest_asyncio.fixture
async def bootstrap_client(aiohttp_client, tmp_path):
    """aiohttp client backed by a real Daemon so /bootstrap/token sees pairing."""
    cfg = make_daemon_config(tmp_path)
    daemon = Daemon(cfg)
    app = create_app(auth_token=AUTH_TOKEN)
    app["daemon"] = daemon
    client = await aiohttp_client(app)
    return client, daemon


@pytest.mark.asyncio
class TestBootstrapTokenRoute:
    async def test_returns_404_when_window_closed(self, bootstrap_client):
        """Window closed -> the route 404s (no token to hand out)."""
        client, daemon = bootstrap_client
        assert daemon.pairing.is_open is False
        resp = await client.get("/bootstrap/token")
        assert resp.status == 404

    async def test_returns_token_when_window_open_and_loopback(
        self, bootstrap_client,
    ):
        """Window open + loopback peer -> 200 with token; window closes."""
        client, daemon = bootstrap_client
        daemon.pairing.open()
        token_before = daemon.pairing.current_token
        assert token_before is not None

        resp = await client.get("/bootstrap/token")
        assert resp.status == 200
        data = await resp.json()
        assert "token" in data
        # Route hands out the daemon auth_token so the extension can
        # authenticate against /api/* with the same Bearer middleware.
        assert data["token"] == AUTH_TOKEN
        # Window closed after first successful consume.
        assert daemon.pairing.is_open is False

    async def test_second_call_after_consume_returns_404(self, bootstrap_client):
        """One-shot: after the first success, subsequent calls 404."""
        client, daemon = bootstrap_client
        daemon.pairing.open()
        resp1 = await client.get("/bootstrap/token")
        assert resp1.status == 200
        resp2 = await client.get("/bootstrap/token")
        assert resp2.status == 404

    async def test_rejects_non_loopback(self, bootstrap_client, monkeypatch):
        """Non-loopback peer -> 403; window stays open for loopback retry."""
        client, daemon = bootstrap_client
        daemon.pairing.open()

        # Force the route to see a non-loopback peer by patching the
        # extractor used in server._bootstrap_token.
        from recap.daemon import server as server_mod
        monkeypatch.setattr(
            server_mod, "_extract_peer_ip", lambda _request: "10.0.0.5",
        )

        resp = await client.get("/bootstrap/token")
        assert resp.status == 403
        # Window stays open; loopback caller can still succeed.
        assert daemon.pairing.is_open is True

    async def test_no_auth_required(self, bootstrap_client):
        """/bootstrap/token is public -- no Bearer required.

        The security gate is the ``pairing.is_open`` flag plus the
        loopback check, not the auth middleware.
        """
        client, daemon = bootstrap_client
        daemon.pairing.open()
        # Explicitly do NOT send Authorization header.
        resp = await client.get("/bootstrap/token")
        assert resp.status == 200

"""Tests for the async Signal-call detection popup.

The popup must be awaitable and must not block the caller's event loop
while the tkinter dialog is up (the detector needs to keep polling).
"""
from __future__ import annotations

import asyncio

import pytest

from recap.daemon.recorder import signal_popup as popup_module
from recap.daemon.recorder.signal_popup import show_signal_popup


@pytest.mark.asyncio
async def test_show_signal_popup_is_async_and_non_blocking(monkeypatch):
    """Async popup yields to the event loop while the dialog is up."""
    # Stub the tkinter dialog to return immediately with a known result.
    def _fake_blocking(*args, **kwargs):
        return {"backend": "ollama", "org": "d"}

    monkeypatch.setattr(popup_module, "_blocking_dialog", _fake_blocking)

    poll_hits = []

    async def _other_coroutine():
        # Simulate the detector poll loop running concurrently.
        for _ in range(3):
            poll_hits.append(True)
            await asyncio.sleep(0)

    result, _ = await asyncio.gather(
        show_signal_popup(org_slug="d", available_backends=["claude", "ollama"]),
        _other_coroutine(),
    )
    assert result == {"backend": "ollama", "org": "d"}
    assert len(poll_hits) == 3  # other coroutine ran during the await


@pytest.mark.asyncio
async def test_show_signal_popup_returns_none_on_cancel(monkeypatch):
    monkeypatch.setattr(
        popup_module, "_blocking_dialog", lambda *a, **kw: None,
    )
    result = await show_signal_popup(
        org_slug="d", available_backends=["claude"],
    )
    assert result is None


@pytest.mark.asyncio
async def test_show_signal_popup_forwards_arguments(monkeypatch):
    """The async wrapper should forward its kwargs to the blocking dialog."""
    captured: dict = {}

    def _fake_blocking(org_slug, available_backends):
        captured["org_slug"] = org_slug
        captured["available_backends"] = list(available_backends)
        return {"backend": "claude", "org": org_slug}

    monkeypatch.setattr(popup_module, "_blocking_dialog", _fake_blocking)

    result = await show_signal_popup(
        org_slug="personal", available_backends=["claude", "ollama"],
    )
    assert captured["org_slug"] == "personal"
    assert captured["available_backends"] == ["claude", "ollama"]
    assert result == {"backend": "claude", "org": "personal"}

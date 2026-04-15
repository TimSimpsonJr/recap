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
    """Popup runs on executor thread; event loop keeps ticking during the block."""
    import threading
    import time

    evt_started = threading.Event()
    evt_done = threading.Event()

    def _blocking(*args, **kwargs):
        evt_started.set()
        time.sleep(0.05)  # real thread sleep — blocks this worker thread
        evt_done.set()
        return {"backend": "ollama", "org": "d"}

    monkeypatch.setattr(popup_module, "_blocking_dialog", _blocking)

    poll_hits = []

    async def _poll_while_popup_up():
        # Wait until the executor thread has actually started the block.
        while not evt_started.is_set():
            await asyncio.sleep(0.001)
        # Keep ticking while the block is pending.
        while not evt_done.is_set():
            poll_hits.append(True)
            await asyncio.sleep(0.005)

    result, _ = await asyncio.gather(
        show_signal_popup(org_slug="d", available_backends=["claude", "ollama"]),
        _poll_while_popup_up(),
    )
    assert result == {"backend": "ollama", "org": "d"}
    # Event loop ticked multiple times while the dialog was blocking.
    # A synchronous implementation would fail: evt_started and evt_done
    # fire back-to-back within one thread before the coroutine can yield.
    assert len(poll_hits) >= 2, (
        f"Expected multiple poll ticks during the blocking dialog; "
        f"got {len(poll_hits)}"
    )


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

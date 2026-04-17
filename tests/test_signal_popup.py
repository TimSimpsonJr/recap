"""Tests for the Signal-call detection popup.

Phase 7 rewrite: the popup now requires a dedicated ThreadPoolExecutor
supplied by the Daemon, tracks outstanding futures for shutdown, and
registers/deregisters its own hwnd with ``detection.exclude_hwnd`` so
self-detection races are impossible.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import threading

import pytest

from recap.daemon.recorder import signal_popup as popup_module
from recap.daemon.recorder.signal_popup import show_signal_popup


@pytest.fixture(autouse=True)
def reset_shutdown_flag():
    """Ensure the sticky shutdown flag is clear before and after each test."""
    if hasattr(popup_module, "_shutdown_requested"):
        popup_module._shutdown_requested.clear()
    # Also clear the outstanding-futures set between tests so one test's
    # leaked future doesn't bleed into another's wait_for_shutdown check.
    if hasattr(popup_module, "_outstanding_futures"):
        with popup_module._outstanding_lock:
            popup_module._outstanding_futures.clear()
    yield
    if hasattr(popup_module, "_shutdown_requested"):
        popup_module._shutdown_requested.clear()
    if hasattr(popup_module, "_outstanding_futures"):
        with popup_module._outstanding_lock:
            popup_module._outstanding_futures.clear()


# ----------------------------------------------------------------------
# Preserved tests (behavior carried over from the pre-rewrite suite).
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_show_signal_popup_is_async_and_non_blocking(monkeypatch):
    """Popup runs on executor thread; event loop keeps ticking during the block."""
    import time

    evt_started = threading.Event()
    evt_done = threading.Event()

    def _blocking(*args, **kwargs):
        evt_started.set()
        time.sleep(0.05)  # real thread sleep - blocks this worker thread
        evt_done.set()
        return {"backend": "ollama", "org": "d"}

    monkeypatch.setattr(popup_module, "_blocking_dialog", _blocking)

    poll_hits = []

    async def _poll_while_popup_up():
        while not evt_started.is_set():
            await asyncio.sleep(0.001)
        while not evt_done.is_set():
            poll_hits.append(True)
            await asyncio.sleep(0.005)

    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="test-popup"
    )
    try:
        result, _ = await asyncio.gather(
            show_signal_popup(
                org_slug="d",
                available_backends=["claude", "ollama"],
                executor=executor,
            ),
            _poll_while_popup_up(),
        )
    finally:
        executor.shutdown(wait=True)

    assert result == {"backend": "ollama", "org": "d"}
    assert len(poll_hits) >= 2, (
        f"Expected multiple poll ticks during the blocking dialog; "
        f"got {len(poll_hits)}"
    )


@pytest.mark.asyncio
async def test_show_signal_popup_returns_none_on_cancel(monkeypatch):
    monkeypatch.setattr(
        popup_module, "_blocking_dialog", lambda *a, **kw: None,
    )
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        result = await show_signal_popup(
            org_slug="d",
            available_backends=["claude"],
            executor=executor,
        )
    finally:
        executor.shutdown(wait=True)
    assert result is None


# ----------------------------------------------------------------------
# Task 13 new/rewritten tests.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_show_signal_popup_requires_executor_keyword():
    """Calling without ``executor=`` must raise TypeError."""
    with pytest.raises(TypeError):
        await show_signal_popup(
            org_slug="d", available_backends=["claude"],
        )


@pytest.mark.asyncio
async def test_show_signal_popup_uses_provided_executor(monkeypatch):
    """The future we await must have come from the executor we supplied."""
    sentinel = {"backend": "claude", "org": "d"}
    thread_ids: list[int] = []

    def _blocking(org_slug, available_backends):
        thread_ids.append(threading.get_ident())
        return sentinel

    monkeypatch.setattr(popup_module, "_blocking_dialog", _blocking)

    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="test-exec-verify"
    )
    # Submit a marker task to capture the executor's worker thread id.
    marker_future = executor.submit(lambda: threading.get_ident())
    executor_thread_id = marker_future.result(timeout=2.0)

    try:
        result = await show_signal_popup(
            org_slug="d",
            available_backends=["claude"],
            executor=executor,
        )
    finally:
        executor.shutdown(wait=True)

    assert result == sentinel
    assert thread_ids, "blocking dialog was never invoked"
    assert thread_ids[0] == executor_thread_id, (
        "dialog ran on a thread that is not the provided executor's worker; "
        "the default executor was likely used instead"
    )


def test_blocking_dialog_registers_and_deregisters_hwnd(monkeypatch):
    """hwnd is added to the exclusion set before mainloop, removed after destroy."""
    calls: list[tuple[str, int]] = []
    sentinel_hwnd = 0xDEADBEEF

    class FakeRoot:
        def __init__(self):
            self._destroyed = False

        def title(self, *a, **k):
            pass

        def resizable(self, *a, **k):
            pass

        def attributes(self, *a, **k):
            pass

        def protocol(self, *a, **k):
            pass

        def winfo_screenwidth(self):
            return 1920

        def winfo_screenheight(self):
            return 1080

        def geometry(self, *a, **k):
            pass

        def update_idletasks(self):
            pass

        def winfo_id(self):
            return sentinel_hwnd

        def after(self, *a, **k):
            pass

        def quit(self):
            pass

        def mainloop(self):
            calls.append(("mainloop", sentinel_hwnd))

        def destroy(self):
            calls.append(("destroy", sentinel_hwnd))
            self._destroyed = True

    # Stub out tkinter module lookups so _blocking_dialog doesn't touch real Tk.
    class _StubWidget:
        def __init__(self, *a, **k):
            pass

        def pack(self, *a, **k):
            pass

        def current(self, *a, **k):
            pass

        def get(self):
            return ""

        def set(self, *a, **k):
            pass

    import sys
    import types

    fake_tk = types.ModuleType("tkinter")
    fake_tk.Tk = lambda: FakeRoot()
    fake_tk.Label = _StubWidget
    fake_tk.Button = _StubWidget
    fake_tk.Frame = _StubWidget
    fake_tk.StringVar = lambda *a, **k: types.SimpleNamespace(
        get=lambda: "", set=lambda v: None,
    )
    fake_ttk = types.ModuleType("tkinter.ttk")
    fake_ttk.Combobox = _StubWidget
    fake_ttk.Frame = _StubWidget
    fake_ttk.Label = _StubWidget
    fake_ttk.Button = _StubWidget
    fake_tk.ttk = fake_ttk

    monkeypatch.setitem(sys.modules, "tkinter", fake_tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", fake_ttk)

    def _record_exclude(hwnd):
        calls.append(("exclude_hwnd", hwnd))

    def _record_include(hwnd):
        calls.append(("include_hwnd", hwnd))

    from recap.daemon.recorder import detection

    monkeypatch.setattr(detection, "exclude_hwnd", _record_exclude)
    monkeypatch.setattr(detection, "include_hwnd", _record_include)
    monkeypatch.setattr(popup_module.detection, "exclude_hwnd", _record_exclude)
    monkeypatch.setattr(popup_module.detection, "include_hwnd", _record_include)

    popup_module._blocking_dialog("d", ["claude"])

    # Ordering: exclude must come before mainloop; include must come after destroy.
    names = [c[0] for c in calls]
    assert "exclude_hwnd" in names
    assert "mainloop" in names
    assert "destroy" in names
    assert "include_hwnd" in names
    assert names.index("exclude_hwnd") < names.index("mainloop")
    assert names.index("destroy") < names.index("include_hwnd")
    # hwnd is the same both times.
    exclude_call = next(c for c in calls if c[0] == "exclude_hwnd")
    include_call = next(c for c in calls if c[0] == "include_hwnd")
    assert exclude_call[1] == sentinel_hwnd
    assert include_call[1] == sentinel_hwnd


def test_request_shutdown_sets_event():
    """``request_shutdown()`` sets the sticky flag."""
    assert not popup_module._shutdown_requested.is_set()
    popup_module.request_shutdown()
    assert popup_module._shutdown_requested.is_set()


def test_blocking_dialog_returns_none_on_shutdown_signal(monkeypatch):
    """mainloop that observes shutdown returns None from _blocking_dialog."""

    class FakeRoot:
        def title(self, *a, **k):
            pass

        def resizable(self, *a, **k):
            pass

        def attributes(self, *a, **k):
            pass

        def protocol(self, *a, **k):
            pass

        def winfo_screenwidth(self):
            return 1920

        def winfo_screenheight(self):
            return 1080

        def geometry(self, *a, **k):
            pass

        def update_idletasks(self):
            pass

        def winfo_id(self):
            return 12345

        def after(self, *a, **k):
            pass

        def quit(self):
            pass

        def mainloop(self):
            # Simulate a shutdown request arriving via after-callback.
            popup_module.request_shutdown()

        def destroy(self):
            pass

    class _StubWidget:
        def __init__(self, *a, **k):
            pass

        def pack(self, *a, **k):
            pass

        def current(self, *a, **k):
            pass

        def get(self):
            return ""

        def set(self, *a, **k):
            pass

    import sys
    import types

    fake_tk = types.ModuleType("tkinter")
    fake_tk.Tk = lambda: FakeRoot()
    fake_tk.Label = _StubWidget
    fake_tk.Button = _StubWidget
    fake_tk.Frame = _StubWidget
    fake_tk.StringVar = lambda *a, **k: types.SimpleNamespace(
        get=lambda: "", set=lambda v: None,
    )
    fake_ttk = types.ModuleType("tkinter.ttk")
    fake_ttk.Combobox = _StubWidget
    fake_ttk.Frame = _StubWidget
    fake_ttk.Label = _StubWidget
    fake_ttk.Button = _StubWidget
    fake_tk.ttk = fake_ttk
    monkeypatch.setitem(sys.modules, "tkinter", fake_tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", fake_ttk)
    monkeypatch.setattr(popup_module.detection, "exclude_hwnd", lambda h: None)
    monkeypatch.setattr(popup_module.detection, "include_hwnd", lambda h: None)

    result = popup_module._blocking_dialog("d", ["claude"])
    assert result is None


def test_blocking_dialog_short_circuits_when_shutdown_already_requested(monkeypatch):
    """Queued popups never invoke tk.Tk once shutdown has been requested."""
    popup_module.request_shutdown()

    called = {"tk_tk": False}

    import sys
    import types

    def _tk():
        called["tk_tk"] = True
        raise AssertionError("tk.Tk must not be called after shutdown")

    fake_tk = types.SimpleNamespace(Tk=_tk)
    fake_ttk = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "tkinter", fake_tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", fake_ttk)

    result = popup_module._blocking_dialog("d", ["claude"])
    assert result is None
    assert called["tk_tk"] is False


def test_wait_for_shutdown_empty_returns_true_immediately():
    """With no outstanding futures, ``wait_for_shutdown`` short-circuits."""
    import time

    t0 = time.monotonic()
    assert popup_module.wait_for_shutdown(timeout=5.0) is True
    elapsed = time.monotonic() - t0
    assert elapsed < 0.1, f"wait_for_shutdown took {elapsed}s, expected near-zero"


def test_wait_for_shutdown_waits_for_all_outstanding():
    """A pending future prevents ``wait_for_shutdown`` from reporting success."""
    done_fut: concurrent.futures.Future = concurrent.futures.Future()
    pending_fut: concurrent.futures.Future = concurrent.futures.Future()
    popup_module._register_future(done_fut)
    popup_module._register_future(pending_fut)
    done_fut.set_result(None)

    try:
        result = popup_module.wait_for_shutdown(timeout=0.1)
    finally:
        # Leave pending_fut unregistered: manually discard to avoid bleed
        # between tests (the autouse fixture also clears).
        popup_module._unregister_future(done_fut)
        popup_module._unregister_future(pending_fut)

    assert result is False


def test_cancelled_queued_future_is_removed_from_set():
    """Cancelling a registered future and firing the done-callback drops it."""
    fut: concurrent.futures.Future = concurrent.futures.Future()
    popup_module._register_future(fut)
    with popup_module._outstanding_lock:
        assert fut in popup_module._outstanding_futures

    cancelled = fut.cancel()
    assert cancelled is True
    # Manually invoke the done-callback (the real one is attached by
    # show_signal_popup; here we mimic what add_done_callback would do).
    popup_module._unregister_future(fut)

    with popup_module._outstanding_lock:
        assert fut not in popup_module._outstanding_futures

"""Native Windows dialog for Signal call detection.

Rewritten in Phase 7 to fix tkinter threading + shutdown + self-detection
issues. See docs/plans/2026-04-16-phase7-design.md §4 for rationale.

Key guarantees:

- All tkinter state is created and destroyed on a single dedicated worker
  thread (the ``ThreadPoolExecutor`` owned by the :class:`Daemon`). The
  default ``loop.run_in_executor(None, ...)`` pool would hop threads and
  trigger ``Tcl_AsyncDelete: async handler deleted by the wrong thread``
  when a ``tk.StringVar`` finalized on a worker that didn't create it.
- ``tk.StringVar`` is avoided entirely; we read the chosen combobox value
  with ``ttk.Combobox.get()`` so the widget owns its Tcl variable
  lifecycle.
- A sticky :data:`_shutdown_requested` flag short-circuits queued popups
  during daemon shutdown; any running popup polls the flag via
  ``root.after`` and quits the mainloop cleanly.
- Each popup registers its hwnd with :func:`detection.exclude_hwnd` after
  ``root.update_idletasks()`` and deregisters it after ``root.destroy()``,
  so the detector cannot race and see its own dialog as a Signal window.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from typing import Any

from recap.daemon.recorder import detection

logger = logging.getLogger("recap.daemon.recorder.signal_popup")

# Display label <-> backend value mapping. Labels are what the user sees,
# values are what goes into ``RecordingMetadata.llm_backend``.
_BACKEND_LABELS: dict[str, str] = {
    "claude": "Claude",
    "ollama": "Local only",
}


def _label_for_backend(value: str) -> str:
    return _BACKEND_LABELS.get(value, value)


# ----------------------------------------------------------------------
# Sticky shutdown + outstanding-futures tracking
# ----------------------------------------------------------------------

_shutdown_requested = threading.Event()
"""Process-lifetime flag. Set once by :func:`request_shutdown`; never cleared by
popup code. Queued popups short-circuit at entry; running popups poll it
via ``root.after`` and quit their mainloop."""

_outstanding_futures: set[concurrent.futures.Future] = set()
_outstanding_lock = threading.Lock()


def request_shutdown() -> None:
    """Signal popups to bail out. Sticky - never cleared by popup code."""
    _shutdown_requested.set()


def _register_future(fut: concurrent.futures.Future) -> None:
    with _outstanding_lock:
        _outstanding_futures.add(fut)


def _unregister_future(fut: concurrent.futures.Future) -> None:
    """Done-callback: runs on executor or caller thread. GIL-protected discard."""
    with _outstanding_lock:
        _outstanding_futures.discard(fut)


def wait_for_shutdown(timeout: float = 5.0) -> bool:
    """Wait for all outstanding popup executor workers to finish.

    Returns ``True`` if all tracked futures completed within ``timeout``;
    ``False`` if at least one is still running. ``True`` is returned
    immediately when no futures are registered.
    """
    with _outstanding_lock:
        pending = list(_outstanding_futures)
    if not pending:
        return True
    done, not_done = concurrent.futures.wait(pending, timeout=timeout)
    return len(not_done) == 0


# ----------------------------------------------------------------------
# Blocking dialog (runs on the popup executor thread)
# ----------------------------------------------------------------------


def _blocking_dialog(
    org_slug: str,
    available_backends: list[str],
) -> dict[str, str] | None:
    """Show the blocking tkinter dialog and return the user's choice.

    Args:
        org_slug: The slug of the org this recording will be saved to
            (displayed as a read-only label, not editable).
        available_backends: Ordered list of backend values the user can
            choose from (e.g. ``["claude", "ollama"]``).

    Returns:
        ``{"org": org_slug, "backend": <chosen-backend-value>}`` if the
        user clicks Record, ``None`` if they click Skip / close the
        window / a tkinter error is raised / shutdown is requested.
    """
    # Queued-popup short-circuit: if the daemon is already shutting down
    # by the time this task starts executing, bail out before touching Tk.
    if _shutdown_requested.is_set():
        return None

    result: dict[str, Any] = {"value": None}
    popup_hwnd: int | None = None

    try:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
        root.title("Signal call detected")
        root.resizable(False, False)
        root.attributes("-topmost", True)

        backend_values = list(available_backends) or ["claude"]
        default_backend = backend_values[0]
        label_values = [_label_for_backend(v) for v in backend_values]

        def _on_skip() -> None:
            result["value"] = None
            root.quit()

        def _on_record() -> None:
            chosen_label = pipeline_combo.get()
            try:
                idx = label_values.index(chosen_label)
                backend = backend_values[idx]
            except ValueError:
                backend = backend_values[0] if backend_values else "claude"
            result["value"] = {"org": org_slug, "backend": backend}
            root.quit()

        root.protocol("WM_DELETE_WINDOW", _on_skip)

        # Center on screen.
        width, height = 320, 200
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2
        root.geometry(f"{width}x{height}+{x}+{y}")

        frame = ttk.Frame(root, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Record this call?", font=("", 11, "bold")).pack(
            pady=(0, 12),
        )
        ttk.Label(frame, text=f"Org: {org_slug}").pack(anchor="w", pady=(0, 8))

        ttk.Label(frame, text="Pipeline:").pack(anchor="w")
        # No tk.StringVar -- the Combobox owns its Tcl variable lifecycle.
        pipeline_combo = ttk.Combobox(
            frame,
            values=label_values,
            state="readonly",
            width=30,
        )
        # Seed the default selection by label.
        pipeline_combo.set(_label_for_backend(default_backend))
        pipeline_combo.pack(fill="x", pady=(0, 12))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x")

        ttk.Button(btn_frame, text="Skip", command=_on_skip).pack(
            side="left", expand=True, fill="x", padx=(0, 4),
        )
        ttk.Button(btn_frame, text="Record", command=_on_record).pack(
            side="right", expand=True, fill="x", padx=(4, 0),
        )

        # Materialize the native window so winfo_id() returns a real hwnd,
        # THEN exclude it from detection before mainloop starts.
        root.update_idletasks()
        popup_hwnd = int(root.winfo_id())
        detection.exclude_hwnd(popup_hwnd)

        try:
            # Poll the sticky shutdown flag so Daemon.stop() can quit a
            # mainloop that's waiting on user input.
            def _check_shutdown() -> None:
                if _shutdown_requested.is_set():
                    result["value"] = None
                    try:
                        root.quit()
                    except Exception:
                        pass
                else:
                    root.after(100, _check_shutdown)

            root.after(100, _check_shutdown)

            try:
                root.mainloop()
            finally:
                try:
                    root.destroy()
                except Exception:
                    pass
        finally:
            if popup_hwnd is not None:
                try:
                    detection.include_hwnd(popup_hwnd)
                except Exception:
                    logger.exception(
                        "Failed to deregister popup hwnd from detection",
                    )
    except Exception:
        logger.exception("Signal popup failed")
        # If we already registered the hwnd before the failure, make sure
        # it's released. ``exclude_hwnd`` + ``include_hwnd`` are set ops,
        # so include on an unknown hwnd is a cheap no-op.
        if popup_hwnd is not None:
            try:
                detection.include_hwnd(popup_hwnd)
            except Exception:
                pass
        return None

    return result["value"]


# ----------------------------------------------------------------------
# Public async API
# ----------------------------------------------------------------------


async def show_signal_popup(
    *,
    org_slug: str,
    available_backends: list[str],
    executor: concurrent.futures.ThreadPoolExecutor,
) -> dict[str, str] | None:
    """Submit the blocking dialog to the popup executor and await the result.

    The ``executor`` kwarg is mandatory: it must be the single-worker
    ``ThreadPoolExecutor`` owned by the :class:`Daemon` so all tkinter
    state lives and dies on one thread.

    Args:
        org_slug: The org slug to display to the user. The popup does
            not offer an org picker; the caller decides upstream which
            org this call will be recorded against.
        available_backends: Ordered list of backend values the user can
            choose from (e.g. ``["claude", "ollama"]``).
        executor: Dedicated ``ThreadPoolExecutor`` for popup work. Owned
            by the caller (Daemon); callers must not shut it down while a
            popup is outstanding.

    Returns:
        ``{"org": org_slug, "backend": <chosen-backend-value>}`` if the
        user clicks Record, or ``None`` if they click Skip / close /
        shutdown fires / a tkinter error is raised.
    """
    cf_future = executor.submit(
        _blocking_dialog, org_slug, list(available_backends),
    )
    _register_future(cf_future)
    cf_future.add_done_callback(_unregister_future)
    return await asyncio.wrap_future(cf_future)

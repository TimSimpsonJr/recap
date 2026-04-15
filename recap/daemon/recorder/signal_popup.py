"""Native Windows dialog for Signal call detection.

Shows a small topmost tkinter dialog asking the user whether to record
a detected Signal call, with a pipeline backend dropdown. The org is
chosen upstream (from ``DetectionAppConfig.default_org``) and passed in
for display so the user always sees where the recording will land.

Phase 3: the public ``show_signal_popup`` is now an ``async`` coroutine
that offloads the blocking tkinter ``mainloop`` onto a thread via
``loop.run_in_executor``. This lets the detector's polling loop keep
ticking while the user decides whether to record.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("recap.daemon.recorder.signal_popup")

# Display label <-> backend value mapping. Labels are what the user sees,
# values are what goes into ``RecordingMetadata.llm_backend``.
_BACKEND_LABELS: dict[str, str] = {
    "claude": "Claude",
    "ollama": "Local only",
}


def _label_for_backend(value: str) -> str:
    return _BACKEND_LABELS.get(value, value)


def _blocking_dialog(
    org_slug: str,
    available_backends: list[str],
) -> dict[str, str] | None:
    """Show the blocking tkinter dialog and return the user's choice.

    Runs tkinter's mainloop synchronously. The async wrapper
    (:func:`show_signal_popup`) dispatches this to a worker thread via
    ``loop.run_in_executor`` so the caller's event loop is not blocked.

    Args:
        org_slug: The slug of the org this recording will be saved to
            (displayed as a read-only label, not editable).
        available_backends: Ordered list of backend values the user can
            choose from (e.g. ``["claude", "ollama"]``).

    Returns:
        ``{"org": org_slug, "backend": <chosen-backend-value>}`` if the
        user clicks Record, or ``None`` if they click Skip / close the
        window / a tkinter error is raised.
    """
    result: dict[str, Any] = {"value": None}

    try:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
        root.title("Signal call detected")
        root.resizable(False, False)
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", lambda: _on_skip(root, result))

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

        # Org display (read-only) so the user can confirm where it lands.
        ttk.Label(frame, text=f"Org: {org_slug}").pack(anchor="w", pady=(0, 8))

        # Pipeline dropdown.
        ttk.Label(frame, text="Pipeline:").pack(anchor="w")
        backend_values = list(available_backends) or ["claude"]
        default_backend = backend_values[0]
        label_values = [_label_for_backend(v) for v in backend_values]
        pipeline_var = tk.StringVar(value=_label_for_backend(default_backend))
        pipeline_combo = ttk.Combobox(
            frame,
            textvariable=pipeline_var,
            values=label_values,
            state="readonly",
            width=30,
        )
        pipeline_combo.pack(fill="x", pady=(0, 12))

        # Buttons.
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x")

        ttk.Button(
            btn_frame,
            text="Skip",
            command=lambda: _on_skip(root, result),
        ).pack(side="left", expand=True, fill="x", padx=(0, 4))

        ttk.Button(
            btn_frame,
            text="Record",
            command=lambda: _on_record(
                root, result, org_slug, pipeline_var, backend_values, label_values,
            ),
        ).pack(side="right", expand=True, fill="x", padx=(4, 0))

        root.mainloop()
    except Exception:
        logger.exception("Signal popup failed")
        result["value"] = None

    return result["value"]


def _on_skip(root: Any, result: dict) -> None:
    result["value"] = None
    root.destroy()


def _on_record(
    root: Any,
    result: dict,
    org_slug: str,
    pipeline_var: Any,
    backend_values: list[str],
    label_values: list[str],
) -> None:
    chosen_label = pipeline_var.get()
    try:
        idx = label_values.index(chosen_label)
        backend = backend_values[idx]
    except ValueError:
        backend = backend_values[0] if backend_values else "claude"
    result["value"] = {"org": org_slug, "backend": backend}
    root.destroy()


async def show_signal_popup(
    *,
    org_slug: str,
    available_backends: list[str],
) -> dict[str, str] | None:
    """Async wrapper around the blocking tkinter dialog.

    Runs :func:`_blocking_dialog` in a thread via
    ``loop.run_in_executor`` so the detector's poll loop (and any other
    async work on the same event loop) continues ticking while the user
    decides whether to record.

    Args:
        org_slug: The org slug to display to the user. The popup does
            not offer an org picker; the caller decides upstream which
            org this call will be recorded against.
        available_backends: Ordered list of backend values the user can
            choose from (e.g. ``["claude", "ollama"]``).

    Returns:
        ``{"org": org_slug, "backend": <chosen-backend-value>}`` if the
        user clicks Record, or ``None`` if they click Skip / close.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _blocking_dialog, org_slug, list(available_backends),
    )

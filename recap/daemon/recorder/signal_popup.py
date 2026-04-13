"""Native Windows dialog for Signal call detection.

Shows a small topmost tkinter dialog asking the user whether to record
a detected Signal call, with org and pipeline backend dropdowns.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger("recap.daemon.recorder.signal_popup")

_BACKEND_LABELS = ["Claude", "Local only"]
_BACKEND_VALUES = {"Claude": "claude", "Local only": "ollama"}


def show_signal_popup(
    orgs: list[str],
    defaults: dict[str, str],
) -> dict[str, str] | None:
    """Show a blocking dialog for Signal call detection.

    Args:
        orgs: List of org names to populate the dropdown.
        defaults: Dict with ``"org"`` and ``"backend"`` keys for initial
            dropdown selections.

    Returns:
        ``{"org": selected_org, "backend": backend_value}`` if the user
        clicks Record, or ``None`` if they click Skip or close the window.
    """
    result: dict[str, Any] = {"value": None}

    def _run_dialog() -> None:
        try:
            import tkinter as tk
            from tkinter import ttk

            root = tk.Tk()
            root.title("Signal call detected")
            root.resizable(False, False)
            root.attributes("-topmost", True)
            root.protocol("WM_DELETE_WINDOW", lambda: _on_skip(root, result))

            # Center on screen
            width, height = 320, 200
            screen_w = root.winfo_screenwidth()
            screen_h = root.winfo_screenheight()
            x = (screen_w - width) // 2
            y = (screen_h - height) // 2
            root.geometry(f"{width}x{height}+{x}+{y}")

            frame = ttk.Frame(root, padding=16)
            frame.pack(fill="both", expand=True)

            ttk.Label(frame, text="Record this call?", font=("", 11, "bold")).pack(
                pady=(0, 12)
            )

            # Org dropdown
            ttk.Label(frame, text="Org:").pack(anchor="w")
            org_var = tk.StringVar(value=defaults.get("org", orgs[0] if orgs else ""))
            org_combo = ttk.Combobox(
                frame,
                textvariable=org_var,
                values=orgs,
                state="readonly",
                width=30,
            )
            org_combo.pack(fill="x", pady=(0, 8))

            # Pipeline dropdown
            ttk.Label(frame, text="Pipeline:").pack(anchor="w")
            default_backend = defaults.get("backend", "claude")
            default_label = next(
                (lbl for lbl, val in _BACKEND_VALUES.items() if val == default_backend),
                _BACKEND_LABELS[0],
            )
            pipeline_var = tk.StringVar(value=default_label)
            pipeline_combo = ttk.Combobox(
                frame,
                textvariable=pipeline_var,
                values=_BACKEND_LABELS,
                state="readonly",
                width=30,
            )
            pipeline_combo.pack(fill="x", pady=(0, 12))

            # Buttons
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
                    root, result, org_var, pipeline_var
                ),
            ).pack(side="right", expand=True, fill="x", padx=(4, 0))

            root.mainloop()
        except Exception:
            logger.exception("Signal popup failed")
            result["value"] = None

    def _on_skip(root: Any, result: dict) -> None:
        result["value"] = None
        root.destroy()

    def _on_record(
        root: Any,
        result: dict,
        org_var: Any,
        pipeline_var: Any,
    ) -> None:
        result["value"] = {
            "org": org_var.get(),
            "backend": _BACKEND_VALUES.get(pipeline_var.get(), "claude"),
        }
        root.destroy()

    thread = threading.Thread(target=_run_dialog, daemon=True)
    thread.start()
    thread.join()

    return result["value"]

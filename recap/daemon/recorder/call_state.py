"""UIA-based call-state + participant extraction helpers.

Shared between detector confirmation (Phase 7 §3, Task 11) and enrichment
(Teams participant extraction, existing behavior).
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _walk_depth_limited(
    control: Any,
    matcher: Callable[[Any], bool],
    *,
    max_depth: int = 15,
) -> Any | None:
    """Depth-bounded UIA tree walk.

    Returns the first control for which ``matcher`` returns True. If the
    matcher returns False for a node, the walker recurses into that node's
    children. Exceptions during traversal are logged at debug level and
    treated as "no match in this subtree".
    """

    def _walk(c: Any, depth: int) -> Any | None:
        if depth > max_depth:
            return None
        try:
            if matcher(c):
                return c
            for child in c.GetChildren():
                found = _walk(child, depth + 1)
                if found is not None:
                    return found
        except Exception:
            logger.debug("UIA walk error at depth %d", depth, exc_info=True)
        return None

    return _walk(control, 0)


def _walk_for_participants(
    control: object,
    names: list[str],
    depth: int = 0,
    max_depth: int = 15,
) -> None:
    """Recursively walk the UIA tree looking for participant list items.

    When a ListItemControl with a non-empty Name is found, the name is
    appended and the walker does NOT descend into that list item (Teams
    roster items don't contain nested participants).
    """
    if depth > max_depth:
        return

    try:
        # Look for ListItem controls — Teams roster uses these for participants
        if getattr(control, "ControlTypeName", None) == "ListItemControl":
            name = getattr(control, "Name", "")
            if name and name.strip():
                names.append(name.strip())
                return  # don't recurse into the list item

        # control is typed as `object` at the function boundary; uiautomation
        # controls expose GetChildren() at runtime. Trust the runtime here.
        for child in control.GetChildren():  # type: ignore[union-attr]
            _walk_for_participants(child, names, depth + 1, max_depth)

    except Exception:
        logger.debug("UIA walk error at depth %d", depth, exc_info=True)


def extract_teams_participants(hwnd: int) -> list[str] | None:
    """Extract participant names from a Teams window via UI Automation.

    Returns a list of display names, or None if extraction fails.
    This function is intentionally defensive — it must never crash.
    """
    try:
        # uiautomation is a Windows-only untyped library; imported lazily so
        # tests without the package can still import this module.
        import uiautomation as auto  # type: ignore[import-untyped]

        control = auto.ControlFromHandle(hwnd)
        if not control:
            logger.debug("UIA: no control for hwnd %s", hwnd)
            return None

        names: list[str] = []
        # Teams renders participants in list items within the roster pane.
        # Walk the tree looking for ListItem controls with a Name property.
        for attempt in range(2):  # retry once for WebView2 inconsistency
            _walk_for_participants(control, names)
            if names:
                break
            if attempt == 0:
                logger.debug("UIA: no participants on first pass, retrying")

        if not names:
            logger.debug("UIA: no participant names found for hwnd %s", hwnd)
            return None

        return names

    except Exception:
        logger.debug("UIA extraction failed for hwnd %s", hwnd, exc_info=True)
        return None


def _is_teams_call_active(control: Any) -> bool:
    """Return True if a Teams window shows an in-call Leave/Hang up/End call button."""

    def is_leave_button(c: Any) -> bool:
        ct = getattr(c, "ControlTypeName", None)
        name = getattr(c, "Name", "") or ""
        return (
            ct == "ButtonControl"
            and name.strip().lower() in {"leave", "hang up", "end call"}
        )

    return _walk_depth_limited(control, is_leave_button) is not None


def _is_zoom_call_active(control: Any) -> bool:
    """Return True if a Zoom window exposes in-call controls (mute/video/leave)."""

    def is_zoom_control(c: Any) -> bool:
        ct = getattr(c, "ControlTypeName", None)
        name = (getattr(c, "Name", "") or "").lower()
        return ct == "ButtonControl" and any(
            t in name
            for t in ("mute", "unmute", "start video", "stop video", "leave meeting")
        )

    return _walk_depth_limited(control, is_zoom_control) is not None


# Per-platform call-state checkers. Signal is intentionally omitted
# (§3.6 per-platform policy — regex-only).
_CALL_STATE_CHECKERS: dict[str, Callable[[Any], bool]] = {
    "teams": _is_teams_call_active,
    "zoom": _is_zoom_call_active,
}


def is_call_active(hwnd: int, platform: str) -> bool:
    """Return True if the window at hwnd is an active call for the given platform.

    Task 10 ships with an empty ``_CALL_STATE_CHECKERS`` dict, so this always
    returns True (regex-trust fallback). Task 11 populates the dict with
    Teams + Zoom checkers.
    """
    checker = _CALL_STATE_CHECKERS.get(platform)
    if checker is None:
        logger.debug(
            "call_state_check platform=%s hwnd=%d result=true "
            "reason=no_checker_for_platform",
            platform, hwnd,
        )
        return True
    try:
        import uiautomation as auto  # type: ignore[import-untyped]

        control = auto.ControlFromHandle(hwnd)
        if control is None:
            # UIA could not resolve a control tree for this hwnd. Treat as
            # unconfirmed — returning True here would re-open the regex-only
            # false-positive class Phase 7 eliminated. The broader Exception
            # path below remains a best-effort fallback for transient UIA
            # runtime errors.
            logger.debug(
                "call_state_check platform=%s hwnd=%d result=false "
                "reason=uia_control_not_found",
                platform, hwnd,
            )
            return False
        result = checker(control)
        logger.debug(
            "call_state_check platform=%s hwnd=%d result=%s reason=%s",
            platform, hwnd,
            "true" if result else "false",
            "checker_confirmed" if result else "checker_declined",
        )
        return result
    except Exception:
        logger.debug(
            "UIA call-state check failed for %s hwnd=%s",
            platform,
            hwnd,
            exc_info=True,
        )
        logger.debug(
            "call_state_check platform=%s hwnd=%d result=true "
            "reason=uia_exception_fallback",
            platform, hwnd,
        )
        return True


def has_call_state_checker(platform: str) -> bool:
    """Return True if a UIA call-state checker is registered for the platform."""
    return platform in _CALL_STATE_CHECKERS

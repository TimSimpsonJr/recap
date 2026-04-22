"""UIA-based call-state + participant extraction helpers.

Shared between detector confirmation (Phase 7 §3, Task 11) and enrichment
(Teams participant extraction, existing behavior).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Windows identity helpers (thin wrappers kept separate so tests can patch
# them without importing pywin32 or psutil).
# ---------------------------------------------------------------------------


def _GetClassName(hwnd: int) -> str:
    """Return the window class name for ``hwnd``. Raises on failure.

    Thin wrapper over ``win32gui.GetClassName`` so tests can monkeypatch
    this symbol on the module without stubbing the whole pywin32 surface.
    """
    import win32gui  # type: ignore[import-untyped]
    return win32gui.GetClassName(hwnd)


def _GetProcessNameForHwnd(hwnd: int) -> str:
    """Return the owning process name for ``hwnd`` (e.g. ``ms-teams.exe``).

    Raises on failure. Thin wrapper over win32process + psutil so tests
    can monkeypatch this symbol directly.
    """
    import psutil
    import win32process  # type: ignore[import-untyped]
    _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
    return psutil.Process(pid).name()


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


_TEAMS_LEAVE_NAMES: set[str] = {"leave", "hang up", "end call"}
_TEAMS_WALK_BUTTON_CAP = 20
_TEAMS_WALK_MAX_DEPTH = 15


def _is_teams_call_active(control: Any) -> bool:
    """Return True if a Teams window shows an in-call Leave/Hang up/End call button.

    Also collects the first ~20 ButtonControl names seen during the walk so
    that when the check returns False a diagnostic log line records what
    Teams actually exposed. Refs #30.
    """
    buttons_seen: list[str] = []

    def _walk(c: Any, depth: int) -> bool:
        if depth > _TEAMS_WALK_MAX_DEPTH:
            return False
        try:
            ct = getattr(c, "ControlTypeName", None)
            name = getattr(c, "Name", "") or ""
            if ct == "ButtonControl":
                stripped = name.strip()
                # Skip empty / whitespace-only names so icon-only buttons
                # cannot crowd out informative labels in buttons_seen.
                if stripped and len(buttons_seen) < _TEAMS_WALK_BUTTON_CAP:
                    buttons_seen.append(name)
                if stripped.lower() in _TEAMS_LEAVE_NAMES:
                    return True
            for child in c.GetChildren():
                if _walk(child, depth + 1):
                    return True
        except Exception:
            logger.debug("UIA walk error at depth %d", depth, exc_info=True)
        return False

    if _walk(control, 0):
        return True

    logger.debug("teams_call_state_walk buttons_seen=%r", buttons_seen)
    return False


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


# ---------------------------------------------------------------------------
# Round-2 diagnostic helpers for issue #30. These do not participate in the
# detection decision path -- they emit one debug log line each when a Teams
# checker declines, so the next log capture can disambiguate "wrong subtree"
# from "UIA cannot see the control at all."
# ---------------------------------------------------------------------------


def _gather_uia_tree_shape(
    control: Any,
    max_depth: int = 15,
) -> dict[int, dict[str, int]]:
    """Return ``{depth: {ControlTypeName: count}}`` for the subtree under
    ``control`` up to ``max_depth`` (inclusive). Mirrors the depth
    semantics of ``_walk_depth_limited`` (``if depth > max_depth``).

    Exceptions raised while descending any subtree are logged at debug
    and treated as "stop descending here" -- the rest of the tree is
    still counted. This mirrors ``_walk_depth_limited``'s behavior so
    the diagnostic reflects what the existing walker would actually see.
    """
    shape: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def _walk(c: Any, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            ct = getattr(c, "ControlTypeName", "Unknown") or "Unknown"
            shape[depth][ct] += 1
            for child in c.GetChildren():
                _walk(child, depth + 1)
        except Exception:
            logger.debug("UIA tree-shape walk error at depth %d", depth, exc_info=True)

    _walk(control, 0)
    return {k: dict(v) for k, v in shape.items()}


def _get_window_identity(hwnd: int) -> tuple[str, str]:
    """Return ``(class_name, process_name)`` for ``hwnd``.

    Returns ``("", "")`` if either lookup fails so a diagnostic log call
    cannot crash the detection poll.
    """
    try:
        cls = _GetClassName(hwnd)
    except Exception:
        logger.debug("GetClassName failed for hwnd=%s", hwnd, exc_info=True)
        return ("", "")
    try:
        proc = _GetProcessNameForHwnd(hwnd)
    except Exception:
        logger.debug("GetProcessNameForHwnd failed for hwnd=%s", hwnd, exc_info=True)
        return (cls, "")
    return (cls, proc)


# Canonical (case-sensitive) names passed to UIA property search. UIA's
# Name property match is case-sensitive, so we query each variant
# explicitly rather than lowercasing.
_TEAMS_LEAVE_CANONICAL_NAMES: tuple[str, ...] = ("Leave", "Hang up", "End call")

# Tight per-name search timeout so a declined Teams window cannot stall
# the 3-second detection poll. 3 names x 0.1s = worst-case ~0.3s.
_LEAVE_FINDALL_MAX_SEARCH_SECONDS = 0.1


def _find_leave_buttons_via_uia_search(control: Any) -> tuple[list[str], str]:
    """Return ``(names, path)`` where ``names`` is the subset of
    ``_TEAMS_LEAVE_CANONICAL_NAMES`` that UIA's property-based descendant
    search confirms exist under ``control``, and ``path`` is one of:

    - ``"uia_property"``   -- the property search actually ran. ``names``
      is a trustworthy answer, whether empty or not.
    - ``"no_uia_search_api"`` -- the control does not expose the
      constructor-style search method; we did not run a search. ``names``
      is always ``[]``. No silent fallback to tree walking, because that
      would be indistinguishable from the existing checker.
    - ``"uia_property_error"`` -- the search method raised before
      producing a result. ``names`` is always ``[]``.

    The path field is what makes the round-2 log line interpretable:
    ``found=true path=uia_property`` is the only signal that tells us
    property search reaches controls the walker missed. Refs #30.
    """
    search_method = getattr(control, "ButtonControl", None)
    if not callable(search_method):
        return ([], "no_uia_search_api")

    found: list[str] = []
    seen: set[str] = set()
    try:
        for canonical in _TEAMS_LEAVE_CANONICAL_NAMES:
            try:
                candidate = search_method(
                    searchDepth=0xFFFFFFFF,
                    Name=canonical,
                )
            except Exception:
                logger.debug(
                    "uia property search failed constructing candidate for %r",
                    canonical, exc_info=True,
                )
                return ([], "uia_property_error")
            exists_fn = getattr(candidate, "Exists", None)
            if not callable(exists_fn):
                # The search method exists but candidate does not look
                # like a uiautomation control. Treat as unavailable.
                return ([], "no_uia_search_api")
            try:
                present = exists_fn(
                    maxSearchSeconds=_LEAVE_FINDALL_MAX_SEARCH_SECONDS,
                )
            except Exception:
                logger.debug(
                    "uia Exists failed for %r", canonical, exc_info=True,
                )
                return ([], "uia_property_error")
            if present and canonical not in seen:
                seen.add(canonical)
                found.append(canonical)
    except Exception:
        logger.debug("uia property search path failed", exc_info=True)
        return ([], "uia_property_error")
    return (found, "uia_property")


# ---------------------------------------------------------------------------
# Per-hwnd deduplication so the round-2 diagnostics emit one snapshot per
# Teams window per daemon session, not every poll. Repeated emission would
# both spam the log and (via repeated property searches) distort the
# detection cadence the diagnostic is trying to measure.
# ---------------------------------------------------------------------------

_DIAGNOSED_TEAMS_HWNDS: set[int] = set()


def _reset_diagnosed_hwnds() -> None:
    """Test-only helper: clear the per-hwnd diagnostic dedupe set."""
    _DIAGNOSED_TEAMS_HWNDS.clear()


def _emit_teams_round2_diagnostics(hwnd: int, control: Any) -> None:
    """Emit the three round-2 diagnostic log lines for a Teams hwnd when
    the existing checker declined. At most once per hwnd per daemon
    session. Refs #30.
    """
    if hwnd in _DIAGNOSED_TEAMS_HWNDS:
        return
    _DIAGNOSED_TEAMS_HWNDS.add(hwnd)

    shape = _gather_uia_tree_shape(control, max_depth=15)
    cls, proc = _get_window_identity(hwnd)
    leave_names, leave_path = _find_leave_buttons_via_uia_search(control)
    logger.debug("uia_tree_shape hwnd=%d depth_counts=%r", hwnd, shape)
    logger.debug(
        "teams_window_identity hwnd=%d class=%r process=%r",
        hwnd, cls, proc,
    )
    logger.debug(
        "teams_leave_button_findall hwnd=%d path=%s found=%s names=%r",
        hwnd, leave_path, "true" if leave_names else "false", leave_names,
    )


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
        # Round-2 diagnostics for issue #30: when a teams checker
        # declines, emit the tree shape, window identity, and
        # property-based descendant search so the next capture can
        # pinpoint which subtree the existing walker is missing.
        if platform == "teams" and not result:
            _emit_teams_round2_diagnostics(hwnd, control)
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

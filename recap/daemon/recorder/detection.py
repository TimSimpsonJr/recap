"""Meeting window detection via Win32 API."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from recap.daemon.recorder import call_state

try:
    import win32gui  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - depends on Windows runtime
    win32gui = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# Hwnds that failed confirmation and should be skipped on subsequent scans.
# Task 14 will add helpers to mutate this set with TTL semantics.
_EXCLUDED_HWNDS: set[int] = set()


def exclude_hwnd(hwnd: int) -> None:
    """Register an hwnd that MUST NOT be detected as a meeting window.

    Used by the signal popup to exclude its own dialog hwnd so the
    detector cannot race and see the popup as a Signal call. Task 14
    will layer TTL semantics on top of this set-membership base.
    """
    _EXCLUDED_HWNDS.add(hwnd)


def include_hwnd(hwnd: int) -> None:
    """Remove ``hwnd`` from the exclusion set. Idempotent."""
    _EXCLUDED_HWNDS.discard(hwnd)


# Patterns for matching active meeting windows by platform.
# Teams: match titles with text before "| Microsoft Teams" (active call/meeting).
# The bare "Microsoft Teams" title (no prefix) is the idle main window.
MEETING_PATTERNS: dict[str, re.Pattern[str]] = {
    "teams": re.compile(r".+\|.*Microsoft Teams"),
    "zoom": re.compile(r"Zoom (Meeting|Webinar)"),
    "signal": re.compile(r"\bSignal\b"),
}


@dataclass
class MeetingWindow:
    """A detected meeting window."""

    hwnd: int
    title: str
    platform: str


def _enumerate_windows() -> list[tuple[int, str]]:
    """Return (hwnd, title) for all visible windows with non-empty titles."""
    if win32gui is None:
        raise RuntimeError(
            "win32gui is required for meeting window detection on Windows.",
        )
    results: list[tuple[int, str]] = []

    def _callback(hwnd: int, _: object) -> None:
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                results.append((hwnd, title))

    win32gui.EnumWindows(_callback, None)
    return results


def detect_meeting_windows(
    enabled_platforms: set[str] | None = None,
) -> list[MeetingWindow]:
    """Detect active meeting windows across configured platforms.

    Args:
        enabled_platforms: If provided, only check these platform keys.
            Defaults to all platforms in MEETING_PATTERNS.

    Returns:
        List of MeetingWindow for each detected active meeting.
    """
    windows = _enumerate_windows()
    platforms = enabled_platforms if enabled_platforms is not None else set(MEETING_PATTERNS)
    meetings: list[MeetingWindow] = []

    teams_pattern = MEETING_PATTERNS["teams"]
    teams_substring_count = 0
    teams_regex_matched_count = 0

    for hwnd, title in windows:
        has_teams_substring = "teams" in title.lower()
        teams_regex_match = bool(teams_pattern.search(title))
        if has_teams_substring:
            teams_substring_count += 1
        if teams_regex_match:
            teams_regex_matched_count += 1
        # Diagnostic for issue #30: a Teams-looking window that the regex
        # rejected is the signature of the regex being the broken gate.
        if has_teams_substring and not teams_regex_match:
            logger.debug(
                "enumerated_teams_candidate hwnd=%d regex_matched=false title=%r",
                hwnd, title,
            )

        if hwnd in _EXCLUDED_HWNDS:
            continue
        for platform in platforms:
            pattern = MEETING_PATTERNS.get(platform)
            if pattern and pattern.search(title):
                active = call_state.is_call_active(hwnd, platform)
                if not active:
                    logger.debug(
                        "detection_gate platform=%s hwnd=%d "
                        "title_matched=true call_state_active=false "
                        "outcome=filtered reason=call_state_inactive title=%r",
                        platform, hwnd, title,
                    )
                    continue
                logger.debug(
                    "detection_gate platform=%s hwnd=%d "
                    "title_matched=true call_state_active=true "
                    "outcome=detected title=%r",
                    platform, hwnd, title,
                )
                meetings.append(MeetingWindow(hwnd=hwnd, title=title, platform=platform))
                break  # one match per window is enough

    logger.debug(
        "window_enumeration total=%d teams_substring_count=%d teams_regex_matched_count=%d",
        len(windows), teams_substring_count, teams_regex_matched_count,
    )

    return meetings


def is_window_alive(hwnd: int) -> bool:
    """Hard Windows signal: the window still exists and is visible."""
    if win32gui is None:
        return True
    try:
        return win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd)
    except Exception:
        return True

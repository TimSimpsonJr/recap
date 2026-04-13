"""Meeting window detection via Win32 API."""
from __future__ import annotations

import re
from dataclasses import dataclass

import win32gui  # type: ignore[import-untyped]


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

    for hwnd, title in windows:
        for platform in platforms:
            pattern = MEETING_PATTERNS.get(platform)
            if pattern and pattern.search(title):
                meetings.append(MeetingWindow(hwnd=hwnd, title=title, platform=platform))
                break  # one match per window is enough

    return meetings

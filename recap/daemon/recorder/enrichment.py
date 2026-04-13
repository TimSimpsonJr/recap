"""Teams metadata enrichment via Windows UI Automation.

Extracts participant names from Teams using the accessibility tree,
and matches them against known contacts for canonical naming.
"""
from __future__ import annotations

import logging
import re

from recap.daemon.config import KnownContact

logger = logging.getLogger(__name__)


def match_known_contacts(
    display_names: list[str],
    contacts: list[KnownContact],
) -> list[str]:
    """Match display names against known contacts (case-insensitive).

    Returns canonical names for matches, original display names otherwise.
    """
    # Build a lookup keyed on lowercased display_name
    lookup: dict[str, str] = {
        c.display_name.lower(): c.name for c in contacts
    }
    return [
        lookup.get(dn.lower(), dn)
        for dn in display_names
    ]


# ---------------------------------------------------------------------------
# Title parsing
# ---------------------------------------------------------------------------

# Suffixes that platforms append to window titles.
_TITLE_SUFFIXES = [
    re.compile(r"\s*\|\s*Microsoft Teams\s*$", re.IGNORECASE),
]


def _parse_title(title: str, platform: str) -> str:
    """Strip platform-specific suffixes from a window title."""
    for pattern in _TITLE_SUFFIXES:
        title = pattern.sub("", title)
    return title.strip()


# ---------------------------------------------------------------------------
# UIA extraction (best-effort, Teams-only)
# ---------------------------------------------------------------------------


def extract_teams_participants(hwnd: int) -> list[str] | None:
    """Extract participant names from a Teams window via UI Automation.

    Returns a list of display names, or None if extraction fails.
    This function is intentionally defensive — it must never crash.
    """
    try:
        import uiautomation as auto  # type: ignore[import-untyped]

        control = auto.ControlFromHandle(hwnd)
        if not control:
            logger.debug("UIA: no control for hwnd %s", hwnd)
            return None

        names: list[str] = []
        # Teams renders participants in list items within the roster pane.
        # Walk the tree looking for ListItem controls with a Name property.
        for attempt in range(2):  # retry once for WebView2 inconsistency
            list_items = control.GetChildren()
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


def _walk_for_participants(
    control: object,
    names: list[str],
    depth: int = 0,
    max_depth: int = 15,
) -> None:
    """Recursively walk the UIA tree looking for participant list items."""
    if depth > max_depth:
        return

    try:
        import uiautomation as auto  # type: ignore[import-untyped]

        # Look for ListItem controls — Teams roster uses these for participants
        if getattr(control, "ControlTypeName", None) == "ListItemControl":
            name = getattr(control, "Name", "")
            if name and name.strip():
                names.append(name.strip())
                return  # don't recurse into the list item

        for child in control.GetChildren():  # type: ignore[union-attr]
            _walk_for_participants(child, names, depth + 1, max_depth)

    except Exception:
        logger.debug("UIA walk error at depth %d", depth, exc_info=True)


# ---------------------------------------------------------------------------
# Public enrichment entry point
# ---------------------------------------------------------------------------


def enrich_meeting_metadata(
    hwnd: int,
    title: str,
    platform: str,
    known_contacts: list[KnownContact],
) -> dict:
    """Enrich meeting metadata with participant info and parsed title.

    For Teams meetings, attempts UIA extraction of participants.
    For all platforms, parses the window title to strip platform suffixes.
    Never raises — returns best-effort results.
    """
    parsed_title = _parse_title(title, platform)
    participants: list[str] = []

    if platform == "teams":
        try:
            raw = extract_teams_participants(hwnd)
            if raw:
                participants = match_known_contacts(raw, known_contacts)
        except Exception:
            logger.debug("Teams enrichment failed", exc_info=True)

    return {
        "title": parsed_title,
        "participants": participants,
        "platform": platform,
    }

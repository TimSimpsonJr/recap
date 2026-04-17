"""Teams metadata enrichment via Windows UI Automation.

Extracts participant names from Teams using the accessibility tree,
and matches them against known contacts for canonical naming.
"""
from __future__ import annotations

import logging
import re

from recap.daemon.config import KnownContact
from recap.daemon.recorder.call_state import extract_teams_participants

__all__ = [
    "match_known_contacts",
    "extract_teams_participants",
    "enrich_meeting_metadata",
]

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

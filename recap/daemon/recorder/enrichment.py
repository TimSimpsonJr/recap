"""Teams metadata enrichment via Windows UI Automation.

Extracts participant names from Teams using the accessibility tree,
and matches them against known contacts for canonical naming.
"""
from __future__ import annotations

import logging
import re

from recap.daemon.config import KnownContact
from recap.daemon.recorder.call_state import extract_teams_participants
from recap.identity import _normalize
from recap.models import Participant

__all__ = [
    "match_known_contacts",
    "extract_teams_participants",
    "enrich_meeting_metadata",
]

logger = logging.getLogger(__name__)


def match_known_contacts(
    observed: list[Participant],
    contacts: list[KnownContact],
) -> list[Participant]:
    """Canonicalize observed participants against known_contacts.

    Precedence:
      1. Email match (case-insensitive exact) -- strongest dedup signal
      2. Normalized name match against name / display_name / aliases
      3. Passthrough (no match)

    Returns Participant objects with canonical name (and preserved email).
    Empty fields are skipped when building the lookup index.
    """
    by_email: dict[str, KnownContact] = {}
    for c in contacts:
        if c.email:
            by_email[c.email.casefold()] = c

    by_name: dict[str, KnownContact] = {}
    for c in contacts:
        if c.name:
            key = _normalize(c.name)
            if key:
                by_name[key] = c
        if c.display_name:
            key = _normalize(c.display_name)
            if key:
                by_name[key] = c
        for alias in c.aliases:
            if alias:
                key = _normalize(alias)
                if key:
                    by_name[key] = c

    out: list[Participant] = []
    for p in observed:
        match: KnownContact | None = None
        if p.email:
            match = by_email.get(p.email.casefold())
        if match is None:
            key = _normalize(p.name)
            if key:
                match = by_name.get(key)
        if match is not None:
            out.append(Participant(name=match.name, email=p.email or match.email))
        else:
            out.append(p)
    return out


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
                as_participants = [Participant(name=n) for n in raw]
                matched = match_known_contacts(as_participants, known_contacts)
                participants = [p.name for p in matched]
        except Exception:
            logger.debug("Teams enrichment failed", exc_info=True)

    return {
        "title": parsed_title,
        "participants": participants,
        "platform": platform,
    }

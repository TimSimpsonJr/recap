"""Shared identity helpers used across pipeline and daemon paths.

Scope:
- _normalize: lowercase + whitespace + punctuation normalization used by
  match_known_contacts (enrichment) AND client-side resolution.
- _is_eligible_person_label: daemon-level eligibility filter used by
  first-pass auto-relabel AND reprocess participant union.

Client-side (plugin) has a stricter version with Company-collision and
multi-person-form guards that require vault scan context.
"""
from __future__ import annotations

import re

_SPEAKER_ID_RE = re.compile(r"^SPEAKER_\d+$")
_UNKNOWN_RE = re.compile(r"^(UNKNOWN|Unknown Speaker.*)$", re.IGNORECASE)
_PARENTHETICAL_RE = re.compile(r"\([^)]+\)")
_MULTI_WS_RE = re.compile(r"\s+")
_STRIP_PUNCT_RE = re.compile(r"[.,]")


def _normalize(text: str) -> str:
    """casefold + strip + collapse whitespace + strip . and ,.

    Used by match_known_contacts and must match the plugin-side
    normalize() exactly (see obsidian-recap/src/correction/normalize.ts).
    """
    s = text.strip()
    if not s:
        return ""
    s = _STRIP_PUNCT_RE.sub("", s)
    s = _MULTI_WS_RE.sub(" ", s)
    return s.casefold().strip()


def _is_eligible_person_label(label: str) -> bool:
    """Daemon-level eligibility: rejects SPEAKER_XX, UNKNOWN*,
    parenthetical-containing, empty/whitespace. Accepts plain names
    and initials. Plugin adds Company-collision and multi-person guards."""
    s = label.strip()
    if not s:
        return False
    if _SPEAKER_ID_RE.match(s):
        return False
    if _UNKNOWN_RE.match(s):
        return False
    if _PARENTHETICAL_RE.search(s):
        return False
    return True

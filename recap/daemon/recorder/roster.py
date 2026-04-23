"""Per-recording participant accumulator.

Owned by MeetingDetector. Fed by Teams UIA (one-shot at detection),
Zoom UIA (periodic during recording), and browser DOM extraction
(periodic HTTP push via /api/meeting-participants-updated).

Thread-safety: NONE. All callers run on the daemon's single asyncio
event loop. Introducing threads requires adding locks here.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

__all__ = ["ParticipantRoster"]


class ParticipantRoster:
    """Ordered-dedupe participant accumulator scoped to one recording.

    Shaped for future additive behavior: ``merge()`` returns whether
    the roster changed in a user-visible way (new name OR upgraded
    display form), so a later WebSocket ``participants_updated``
    broadcast can attach without redesign.

    Known limitation: cross-source name variants (``"Alice S."`` vs
    ``"Alice Smith"``) are NOT reconciled beyond casefold. Use
    ``match_known_contacts`` at the ingress boundary to normalize
    before merging.
    """

    def __init__(self) -> None:
        # key=casefold, value=display. dict preserves insertion order
        # (Py3.7+), so updating an existing key does not reorder.
        self._names: dict[str, str] = {}
        self._last_merge_per_source: dict[str, datetime] = {}

    def merge(
        self,
        source: str,
        names: Sequence[str],
        observed_at: datetime,
    ) -> bool:
        """Merge names from a source. Return True if the roster changed.

        A "change" is either a new name or a display-form upgrade on an
        existing casefold key. ``observed_at`` must be timezone-aware so
        timestamps stay usable downstream.
        """
        if observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        changed = False
        for raw in names:
            name = raw.strip()
            if not name:
                continue
            key = name.casefold()
            existing = self._names.get(key)
            if existing is None or existing != name:
                self._names[key] = name
                changed = True
        self._last_merge_per_source[source] = observed_at
        return changed

    def current(self) -> list[str]:
        """Current ordered deduped roster. Safe to call any time."""
        return list(self._names.values())

    def finalize(self) -> list[str]:
        """Final roster at Recorder.stop() time.

        Same as ``current()`` in v1. Separate method so future
        finalization logic (e.g. diarization reconciliation) can
        hook here without callers changing.
        """
        return self.current()

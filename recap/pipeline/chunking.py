"""Windowing + stitching utilities for chunked Parakeet inference.

See ``docs/plans/2026-04-20-parakeet-chunked-inference-design.md`` for
scope, OOM policy, and overlap semantics.
"""
from __future__ import annotations

from recap.models import Utterance


def plan_windows(
    duration_s: float,
    window_s: float,
    overlap_s: float,
) -> list[tuple[float, float]]:
    """Return ``(start, end)`` windows covering ``[0, duration_s]``.

    Windows are ``window_s`` long with ``overlap_s`` of overlap between
    adjacent windows. The final window is truncated at ``duration_s``.
    A file shorter than a single window produces exactly one window
    spanning the whole file.

    Raises:
        ValueError: if ``window_s <= 0``, ``overlap_s < 0``,
            ``overlap_s >= window_s``, or ``duration_s <= 0``.
    """
    if duration_s <= 0:
        raise ValueError(f"duration_s must be > 0, got {duration_s}")
    if window_s <= 0:
        raise ValueError(f"window_s must be > 0, got {window_s}")
    if overlap_s < 0 or overlap_s >= window_s:
        raise ValueError(
            f"overlap_s must be in [0, window_s), got {overlap_s} vs {window_s}"
        )

    if duration_s <= window_s:
        return [(0.0, duration_s)]

    step = window_s - overlap_s
    windows: list[tuple[float, float]] = []
    start = 0.0
    while start < duration_s:
        end = min(start + window_s, duration_s)
        windows.append((start, end))
        if end >= duration_s:
            break
        start += step
    return windows


def offset_utterances(
    utterances: list[Utterance],
    window_start_s: float,
) -> list[Utterance]:
    """Return a new list of utterances with timestamps shifted by ``window_start_s``.

    Each returned utterance is a fresh instance so the caller's per-window
    list is never mutated.
    """
    return [
        Utterance(
            speaker=u.speaker,
            start=u.start + window_start_s,
            end=u.end + window_start_s,
            text=u.text,
        )
        for u in utterances
    ]

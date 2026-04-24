"""Windowing + stitching utilities for chunked Parakeet inference.

See ``docs/plans/2026-04-20-parakeet-chunked-inference-design.md`` for
scope, OOM policy, and overlap semantics.
"""
from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

from recap.models import Utterance

_FFMPEG_SLICE_TIMEOUT_S = 60


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
            speaker_id=u.speaker_id,
            speaker=u.speaker,
            start=u.start + window_start_s,
            end=u.end + window_start_s,
            text=u.text,
        )
        for u in utterances
    ]


def merge_overlapping_windows(
    prior: list[Utterance],
    later: list[Utterance],
    overlap_start_s: float,
    overlap_end_s: float,
) -> list[Utterance]:
    """Concatenate two adjacent windows' utterance lists, deduping the overlap.

    Two-stage dedup:

    1. Center-timestamp ownership: ``prior`` owns the overlap zone. Any
       utterance in ``later`` whose midpoint ``(start + end) / 2`` lies
       inside ``[overlap_start_s, overlap_end_s]`` is dropped. The rule is
       positional, not content-based, so it tolerates the timestamp jitter
       that real ASR produces across overlapping windows.
    2. Adjacent same-start collapse: after sorting, any pair of adjacent
       utterances sharing a ``start`` represents the same acoustic moment
       split between two windows (prior's audio ran out mid-utterance and
       later's view continued past the boundary). Keep whichever reaches
       furthest — the longest ``end`` is the most complete version.

    The result is sorted by ``start`` ascending so that a long ``later``
    utterance whose audio straddles the boundary (center outside overlap,
    start inside overlap) cannot create a non-monotonic stitched output.

    Both inputs are assumed to already be offset into the same absolute
    time base.
    """
    later_filtered: list[Utterance] = []
    for u in later:
        center = (u.start + u.end) / 2.0
        if overlap_start_s <= center <= overlap_end_s:
            continue
        later_filtered.append(u)

    merged = list(prior) + later_filtered
    merged.sort(key=lambda u: u.start)

    if not merged:
        return merged
    collapsed: list[Utterance] = [merged[0]]
    for u in merged[1:]:
        if u.start == collapsed[-1].start:
            if u.end > collapsed[-1].end:
                collapsed[-1] = u
        else:
            collapsed.append(u)
    return collapsed


def slice_window_to_temp(
    source: Path,
    start_s: float,
    duration_s: float,
    temp_dir: Path,
) -> Path:
    """Extract ``[start_s, start_s + duration_s]`` of *source* into a temp .wav.

    Uses ffmpeg with ``-c:a pcm_s16le`` (matches the mono sidecar format
    Parakeet already consumes). Creates ``temp_dir`` if it doesn't exist.
    Returns the temp path. The caller is responsible for deletion; a
    stage-level ``finally`` should remove ``temp_dir`` in bulk.

    Raises:
        RuntimeError: ffmpeg exited non-zero or timed out.
    """
    temp_dir.mkdir(parents=True, exist_ok=True)
    out_path = temp_dir / f"window-{uuid.uuid4().hex}.wav"

    cmd = [
        "ffmpeg",
        "-v", "error",
        "-y",
        "-ss", f"{start_s}",
        "-t", f"{duration_s}",
        "-i", str(source),
        "-c:a", "pcm_s16le",
        "-ac", "1",
        str(out_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_FFMPEG_SLICE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"ffmpeg slice timed out after {_FFMPEG_SLICE_TIMEOUT_S}s"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg slice failed: {result.stderr}")
    return out_path

"""Unit tests for the chunking module (window planning + stitching)."""
from __future__ import annotations

import pytest

from recap.models import Utterance
from recap.pipeline.chunking import (
    merge_overlapping_windows,
    offset_utterances,
    plan_windows,
)


def test_plan_windows_single_window_shorter_than_size():
    # 90s audio, 120s window, 10s overlap -> one window spanning the whole file
    assert plan_windows(duration_s=90.0, window_s=120.0, overlap_s=10.0) == [
        (0.0, 90.0),
    ]


def test_plan_windows_exact_multiple():
    # 240s audio, 120s window, 10s overlap -> 3 windows with overlap
    assert plan_windows(duration_s=240.0, window_s=120.0, overlap_s=10.0) == [
        (0.0, 120.0),
        (110.0, 230.0),
        (220.0, 240.0),
    ]


def test_plan_windows_long_file_boundary_handling():
    # 2220s audio (37 min), 120s window, 10s overlap
    windows = plan_windows(duration_s=2220.0, window_s=120.0, overlap_s=10.0)
    # Starts: 0, 110, 220, ..., increments of (window_s - overlap_s) = 110s
    assert windows[0] == (0.0, 120.0)
    assert windows[1] == (110.0, 230.0)
    assert windows[-1][1] == pytest.approx(2220.0)
    # No window exceeds duration
    assert all(end <= 2220.0 for _, end in windows)
    # Every start (except 0) is previous_start + 110s
    for i in range(1, len(windows)):
        assert windows[i][0] == pytest.approx(windows[i - 1][0] + 110.0)


def test_plan_windows_rejects_invalid_params():
    with pytest.raises(ValueError):
        plan_windows(duration_s=100.0, window_s=0.0, overlap_s=10.0)
    with pytest.raises(ValueError):
        plan_windows(duration_s=100.0, window_s=10.0, overlap_s=10.0)
    with pytest.raises(ValueError):
        plan_windows(duration_s=-5.0, window_s=120.0, overlap_s=10.0)


def test_offset_utterances_shifts_timestamps():
    window_utts = [
        Utterance(speaker="UNKNOWN", start=0.5, end=2.0, text="hello"),
        Utterance(speaker="UNKNOWN", start=5.0, end=7.5, text="world"),
    ]
    result = offset_utterances(window_utts, window_start_s=110.0)
    assert result == [
        Utterance(speaker="UNKNOWN", start=110.5, end=112.0, text="hello"),
        Utterance(speaker="UNKNOWN", start=115.0, end=117.5, text="world"),
    ]


def test_offset_utterances_empty_input():
    assert offset_utterances([], window_start_s=500.0) == []


def test_merge_drops_duplicate_in_overlap_zone():
    # Window 1 covers [0, 120], window 2 covers [110, 230]. Overlap: [110, 120].
    # Utterance "overlap-a" has center at 115 -> belongs to window 1.
    # Utterance "overlap-b" has center at 118 -> belongs to window 1.
    # Window 2's duplicates of these two should be dropped.
    w1 = [
        Utterance(speaker="UNKNOWN", start=5.0, end=10.0, text="early"),
        Utterance(speaker="UNKNOWN", start=113.0, end=117.0, text="overlap-a"),
        Utterance(speaker="UNKNOWN", start=116.0, end=120.0, text="overlap-b"),
    ]
    w2 = [
        Utterance(speaker="UNKNOWN", start=113.0, end=117.0, text="overlap-a"),
        Utterance(speaker="UNKNOWN", start=116.0, end=120.0, text="overlap-b"),
        Utterance(speaker="UNKNOWN", start=125.0, end=130.0, text="late"),
    ]
    merged = merge_overlapping_windows(
        prior=w1,
        later=w2,
        overlap_start_s=110.0,
        overlap_end_s=120.0,
    )
    texts = [u.text for u in merged]
    assert texts == ["early", "overlap-a", "overlap-b", "late"]


def test_merge_keeps_later_side_when_center_falls_in_later_window():
    # For center-in-overlap-goes-to-prior behavior, verify prior keeps its own
    # even when later is empty.
    w1 = [Utterance("UNKNOWN", 115.0, 118.0, "only-in-prior")]
    w2: list[Utterance] = []
    merged = merge_overlapping_windows(
        prior=w1, later=w2, overlap_start_s=110.0, overlap_end_s=120.0,
    )
    assert [u.text for u in merged] == ["only-in-prior"]


def test_merge_empty_later_returns_prior():
    w1 = [Utterance("UNKNOWN", 0.0, 5.0, "a")]
    assert merge_overlapping_windows(w1, [], 0.0, 10.0) == w1


def test_merge_result_is_monotonic():
    w1 = [
        Utterance("UNKNOWN", 0.0, 5.0, "a"),
        Utterance("UNKNOWN", 113.0, 118.0, "b"),
    ]
    w2 = [
        Utterance("UNKNOWN", 113.0, 118.0, "b"),
        Utterance("UNKNOWN", 125.0, 130.0, "c"),
    ]
    merged = merge_overlapping_windows(w1, w2, 110.0, 120.0)
    for i in range(1, len(merged)):
        assert merged[i].start >= merged[i - 1].start

"""Unit tests for the chunking module (window planning + stitching)."""
from __future__ import annotations

import pytest

from recap.models import Utterance
from recap.pipeline.chunking import offset_utterances, plan_windows


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

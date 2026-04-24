"""Unit tests for the chunking module (window planning + stitching)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from recap.models import Utterance
from recap.pipeline.chunking import (
    merge_overlapping_windows,
    offset_utterances,
    plan_windows,
    slice_window_to_temp,
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
        Utterance(speaker_id="UNKNOWN", speaker="UNKNOWN", start=0.5, end=2.0, text="hello"),
        Utterance(speaker_id="UNKNOWN", speaker="UNKNOWN", start=5.0, end=7.5, text="world"),
    ]
    result = offset_utterances(window_utts, window_start_s=110.0)
    assert result == [
        Utterance(speaker_id="UNKNOWN", speaker="UNKNOWN", start=110.5, end=112.0, text="hello"),
        Utterance(speaker_id="UNKNOWN", speaker="UNKNOWN", start=115.0, end=117.5, text="world"),
    ]


def test_offset_utterances_empty_input():
    assert offset_utterances([], window_start_s=500.0) == []


def test_merge_drops_duplicate_in_overlap_zone():
    # Window 1 covers [0, 120], window 2 covers [110, 230]. Overlap: [110, 120].
    # Utterance "overlap-a" has center at 115 -> belongs to window 1.
    # Utterance "overlap-b" has center at 118 -> belongs to window 1.
    # Window 2's duplicates of these two should be dropped.
    w1 = [
        Utterance(speaker_id="UNKNOWN", speaker="UNKNOWN", start=5.0, end=10.0, text="early"),
        Utterance(speaker_id="UNKNOWN", speaker="UNKNOWN", start=113.0, end=117.0, text="overlap-a"),
        Utterance(speaker_id="UNKNOWN", speaker="UNKNOWN", start=116.0, end=120.0, text="overlap-b"),
    ]
    w2 = [
        Utterance(speaker_id="UNKNOWN", speaker="UNKNOWN", start=113.0, end=117.0, text="overlap-a"),
        Utterance(speaker_id="UNKNOWN", speaker="UNKNOWN", start=116.0, end=120.0, text="overlap-b"),
        Utterance(speaker_id="UNKNOWN", speaker="UNKNOWN", start=125.0, end=130.0, text="late"),
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
    w1 = [Utterance("UNKNOWN", "UNKNOWN",115.0, 118.0, "only-in-prior")]
    w2: list[Utterance] = []
    merged = merge_overlapping_windows(
        prior=w1, later=w2, overlap_start_s=110.0, overlap_end_s=120.0,
    )
    assert [u.text for u in merged] == ["only-in-prior"]


def test_merge_empty_later_returns_prior():
    w1 = [Utterance("UNKNOWN", "UNKNOWN",0.0, 5.0, "a")]
    assert merge_overlapping_windows(w1, [], 0.0, 10.0) == w1


def test_merge_result_is_monotonic():
    w1 = [
        Utterance("UNKNOWN", "UNKNOWN",0.0, 5.0, "a"),
        Utterance("UNKNOWN", "UNKNOWN",113.0, 118.0, "b"),
    ]
    w2 = [
        Utterance("UNKNOWN", "UNKNOWN",113.0, 118.0, "b"),
        Utterance("UNKNOWN", "UNKNOWN",125.0, 130.0, "c"),
    ]
    merged = merge_overlapping_windows(w1, w2, 110.0, 120.0)
    for i in range(1, len(merged)):
        assert merged[i].start >= merged[i - 1].start


def test_merge_drops_later_overlap_despite_timestamp_jitter():
    """Real Parakeet output jitters timestamps for the same phrase across
    overlapping windows. The dedup rule must drop later's overlap utterance
    based on center position alone, not exact (start, end, text) match."""
    w1 = [
        Utterance("UNKNOWN", "UNKNOWN",113.0, 117.0, "hello world"),
    ]
    w2 = [
        # Same phrase, jittered endpoints — NOT an exact-key match of w1's.
        Utterance("UNKNOWN", "UNKNOWN",113.4, 117.3, "hello world"),
        Utterance("UNKNOWN", "UNKNOWN",125.0, 130.0, "late"),
    ]
    merged = merge_overlapping_windows(w1, w2, 110.0, 120.0)
    # The jittered duplicate must be dropped; only prior's version survives.
    texts = [u.text for u in merged]
    assert texts == ["hello world", "late"]
    # Prior's timestamps (not later's jittered ones) are the authoritative
    # record for the overlap zone.
    assert merged[0].start == 113.0
    assert merged[0].end == 117.0


def test_merge_collapses_same_start_across_window_boundary():
    """When prior's truncated boundary utterance and later's complete
    version share a ``start`` (same acoustic moment, different truncations
    because each window's audio ended differently), keep the longer one.

    This case was observed on real Parakeet output: the same utterance
    got a ``start`` of 1547.52s from both windows — one truncated by the
    prior window's audio boundary, the other complete. The positional
    rule alone leaves both because the long one's center lies past the
    overlap zone; adjacent-same-start collapse catches it.
    """
    prior = [
        # Center=1548.6, in overlap [1540, 1550]. KEPT by positional rule.
        Utterance("UNKNOWN", "UNKNOWN",1547.52, 1549.68,
                  "So now we need to, you know, that."),
    ]
    later = [
        # Same start, longer end. Center=1551.32, PAST overlap → KEPT.
        Utterance("UNKNOWN", "UNKNOWN",1547.52, 1555.12,
                  "So now we need to, you know, that's something we're working on."),
    ]
    merged = merge_overlapping_windows(prior, later, 1540.0, 1550.0)
    assert len(merged) == 1, (
        "Same-start duplicates must collapse; kept "
        f"{[(u.start, u.end, u.text) for u in merged]}"
    )
    assert merged[0].end == 1555.12
    assert "something we're working on" in merged[0].text


def test_merge_output_monotonic_when_later_utterance_straddles_boundary():
    """A long ``later`` utterance whose center is past the overlap zone but
    whose start falls inside it must not break the monotonicity invariant."""
    w1 = [
        # Prior's last utterance — center in overlap, start near overlap end.
        Utterance("UNKNOWN", "UNKNOWN",118.0, 120.5, "tail"),
    ]
    w2 = [
        # Jittered duplicate of "tail" — center in overlap → dropped.
        Utterance("UNKNOWN", "UNKNOWN",117.5, 120.8, "tail"),
        # Long new utterance that starts inside the overlap zone but whose
        # center (121.0) is past overlap_end_s=120.0 → kept in later.
        Utterance("UNKNOWN", "UNKNOWN",117.0, 125.0, "new thing"),
    ]
    merged = merge_overlapping_windows(w1, w2, 110.0, 120.0)
    starts = [u.start for u in merged]
    assert starts == sorted(starts), f"Non-monotonic starts: {starts}"
    # Both prior's "tail" and later's "new thing" survive; the jittered
    # duplicate of "tail" does not.
    texts = [u.text for u in merged]
    assert "tail" in texts
    assert "new thing" in texts
    assert texts.count("tail") == 1


def test_slice_window_invokes_ffmpeg_with_correct_args(monkeypatch, tmp_path):
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        # Pretend ffmpeg produced a file
        Path(cmd[-1]).write_bytes(b"RIFF")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("recap.pipeline.chunking.subprocess.run", fake_run)

    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF")
    out = slice_window_to_temp(
        source=source,
        start_s=10.0,
        duration_s=120.0,
        temp_dir=tmp_path / "chunks",
    )

    assert out.exists()
    assert out.parent == tmp_path / "chunks"
    assert out.suffix == ".wav"
    assert "-ss" in captured["cmd"]
    assert "10.0" in captured["cmd"]
    assert "-t" in captured["cmd"]
    assert "120.0" in captured["cmd"]
    assert "pcm_s16le" in captured["cmd"]


def test_slice_window_raises_on_ffmpeg_failure(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="bad input")

    monkeypatch.setattr("recap.pipeline.chunking.subprocess.run", fake_run)

    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF")
    with pytest.raises(RuntimeError, match="ffmpeg"):
        slice_window_to_temp(source, 0.0, 10.0, tmp_path / "chunks")

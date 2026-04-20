# Parakeet chunked inference — implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the whole-file Parakeet call in `recap/pipeline/transcribe.py:64` with chunked inference that fits on a 12 GiB GPU for recordings up to ~4 hours, so the preserved 37-min `.flac` replays to completion without CUDA OOM.

**Architecture:** Two paths, gated by a time-boxed spike. Path A uses NeMo's built-in buffered inference helpers. Path B (committed fallback) slices `.mono.wav` with ffmpeg into per-window temp files, calls `model.transcribe([str(temp_wav)])` per window (same file-path surface we use today), and stitches `TranscriptResult`s with deterministic overlap dedup. Host memory stays O(window), not O(file).

**Tech stack:** Python 3.12, NeMo ASR (Parakeet-TDT-0.6b-v2), ffmpeg (already a pipeline dependency), pytest, `uv` for dependency management.

**Design reference:** `docs/plans/2026-04-20-parakeet-chunked-inference-design.md`. Read it before starting — decisions on scope, OOM policy, and validation are pinned there.

**Branch:** `obsidian-pivot`. No new worktree (already on a feature branch; worktree skill skips creation).

---

## Task 1: Path A spike (time-boxed probe)

**Goal:** Determine whether NeMo's buffered inference helpers support Parakeet-TDT-0.6b-v2 with bounded VRAM and usable timestamps, within 2 hours of active work.

**Files:**
- Create: `scripts/spike_parakeet_chunked.py` (throwaway — deleted after Task 1 regardless of outcome)

**Step 1: Write the spike script**

```python
"""Throwaway spike: does NeMo's buffered inference support Parakeet-TDT?

Delete this file after Task 1. Decision is captured in the Task 1 handoff
note below the script.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

AUDIO = Path(
    r"C:/Users/tim/recap-test-data/recordings/"
    r"2026-04-20-155927-disbursecloud.mono.wav"
)

def main() -> int:
    if not AUDIO.exists():
        print(f"Missing preserved mono audio: {AUDIO}", file=sys.stderr)
        return 2

    import torch
    import nemo.collections.asr as nemo_asr

    # Try the TDT-compatible buffered helper first. If this import fails
    # or the class doesn't exist, Path A is already disqualified.
    try:
        from nemo.collections.asr.parts.utils.streaming_utils import (
            FrameBatchASR,  # classic CTC helper; check for TDT analog
        )
    except ImportError as exc:
        print(f"FAIL: streaming_utils import: {exc}")
        return 1

    print("Loading Parakeet-TDT...")
    model = nemo_asr.models.ASRModel.from_pretrained(
        "nvidia/parakeet-tdt-0.6b-v2"
    ).to("cuda")

    torch.cuda.reset_peak_memory_stats()
    start = time.time()
    try:
        # TODO: wire the actual helper here. If the FrameBatchASR API
        # doesn't accept TDT models, check for:
        #   - FrameBatchMultiTaskAED
        #   - any class in nemo.collections.asr.parts.submodules.tdt_*
        #   - buffered_transcribe_audio utility
        # If none work, STOP the spike and pick Path B.
        raise NotImplementedError(
            "Spike: pick the helper that supports Parakeet-TDT here"
        )
    except Exception as exc:
        elapsed = time.time() - start
        peak = torch.cuda.max_memory_allocated() / (1024**3)
        print(f"FAIL after {elapsed:.1f}s, peak {peak:.2f} GiB: {exc}")
        return 1

    elapsed = time.time() - start
    peak = torch.cuda.max_memory_allocated() / (1024**3)
    print(f"OK in {elapsed:.1f}s, peak VRAM {peak:.2f} GiB")
    print(f"Utterance count: see stdout; first 3:")
    # Print first 3 segments with timestamps to verify shape.
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Step 2: Run the spike**

Run: `uv run python scripts/spike_parakeet_chunked.py`

Watch: peak VRAM, completion time, first few timestamps, whether any helper class accepts the TDT model.

**Step 3: Evaluate against exit criteria (design doc section "Spike exit criteria")**

Path A proceeds only if ALL four criteria hold:

1. Runs without whole-file VRAM blowup (peak < 6 GiB target; hard fail at > 10 GiB).
2. Timestamps map into `{speaker, start, end, text}` for `Utterance`.
3. No obvious overlap duplication or timestamp non-monotonicity.
4. Fits in `transcribe.py` without importing any live-streaming module.

Hard stop: **2 hours**. If not clearly green by then, switch to Path B.

**Step 4: Record decision**

Append to `docs/plans/2026-04-20-parakeet-chunked-inference-implementation.md` under a new "## Task 1 outcome" section:

```markdown
## Task 1 outcome

**Decision:** [Path A | Path B]
**Reason:** [1-2 sentences]
**Peak VRAM observed:** [X GiB on 120s window]
**Helper used (if A):** [class name or "N/A"]
```

Commit the outcome note before starting Task 2 — future-you needs this context.

**Step 5: Delete the spike script**

```bash
rm scripts/spike_parakeet_chunked.py
git add -A scripts/ docs/plans/2026-04-20-parakeet-chunked-inference-implementation.md
git commit -m "chore(pipeline): Task 1 spike outcome — [A|B] selected"
```

---

## Branching on Task 1 outcome

- **If Path A was selected:** go to Task 2A (skip all Task 2B.*).
- **If Path B was selected:** go to Task 2B.1 (skip Task 2A).

---

## Task 2A: Implement Path A (NeMo buffered helper)

**Only if Task 1 selected Path A.** Skip to Task 3 if Path B.

**Files:**
- Modify: `recap/pipeline/transcribe.py` (replace body of `transcribe()` around line 64)
- Modify: `tests/test_pipeline_transcribe.py` (extend existing tests if Path A changes observable behaviour)

**Step 1: Write the failing test**

Add to `tests/test_pipeline_transcribe.py`:

```python
def test_transcribe_uses_chunked_helper_for_long_audio(monkeypatch, tmp_path):
    """Parakeet-TDT chunked path is used; whole-file transcribe is not called."""
    # Create a dummy audio file (content ignored — we mock the model)
    audio = tmp_path / "long.wav"
    audio.write_bytes(b"\x00" * 16)

    calls = {"chunked": 0, "whole": 0}

    class FakeModel:
        def to(self, _device): return self
        def transcribe(self, _paths, **_kwargs):
            calls["whole"] += 1
            raise AssertionError("whole-file transcribe must not be called")

    # Fake the buffered helper that Task 1 settled on.
    class FakeBufferedHelper:
        def __init__(self, *_args, **_kwargs): pass
        def transcribe(self, _audio_path):
            calls["chunked"] += 1
            return _fake_stitched_hypothesis()

    # Patch model loader + helper constructor at the transcribe module.
    monkeypatch.setattr("recap.pipeline.transcribe._load_model", lambda *a, **k: FakeModel())
    # TODO: adjust to the actual helper-import path chosen in Task 1.
    monkeypatch.setattr(
        "recap.pipeline.transcribe._BufferedHelper", FakeBufferedHelper, raising=False,
    )

    from recap.pipeline.transcribe import transcribe
    result = transcribe(audio_path=audio, device="cpu")

    assert calls["chunked"] == 1
    assert calls["whole"] == 0
    assert all(u.end >= u.start for u in result.utterances)
```

Add a helper `_fake_stitched_hypothesis()` returning an object shaped like the helper's real output.

**Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_pipeline_transcribe.py::test_transcribe_uses_chunked_helper_for_long_audio -v`

Expected: FAIL — helper class doesn't exist yet / current code calls whole-file transcribe.

**Step 3: Implement minimal Path A in `transcribe.py`**

Replace the body of `transcribe()` around line 64 so it:
1. Loads Parakeet-TDT the same way.
2. Instantiates the buffered helper chosen in Task 1.
3. Calls the helper with `str(audio_path)`.
4. Converts the helper's output into `list[Utterance]` using the same `{start, end, text}` extraction shape as the current code (see `transcribe.py:77-85`).

Keep the function signature, docstring, and `save_transcript` behaviour unchanged (transcript contract invariant).

**Step 4: Run the new test + existing transcribe tests**

Run: `uv run pytest tests/test_pipeline_transcribe.py -v`

Expected: all pass, including previously-green tests.

**Step 5: Run the full suite for regression check**

Run: `uv run pytest`

Expected: 686+ passed, coverage >= 70%.

**Step 6: Commit**

```bash
git add recap/pipeline/transcribe.py tests/test_pipeline_transcribe.py
git commit -m "feat(pipeline): chunked Parakeet inference via NeMo buffered helper"
```

Then jump to Task 3 (diarize audit). Skip all Task 2B.*.

---

## Task 2B.1: Window planner

**Only if Task 1 selected Path B.**

**Goal:** Pure function that returns the list of `(start_s, end_s)` windows for a given total duration, window size, and overlap.

**Files:**
- Create: `recap/pipeline/chunking.py`
- Create: `tests/test_pipeline_chunking.py`

**Step 1: Write the failing tests**

```python
"""Unit tests for the chunking module (window planning + stitching)."""
from __future__ import annotations

import pytest

from recap.pipeline.chunking import plan_windows


def test_plan_windows_single_window_shorter_than_size():
    # 90s audio, 120s window, 10s overlap -> one window spanning the whole file
    assert plan_windows(duration_s=90.0, window_s=120.0, overlap_s=10.0) == [
        (0.0, 90.0),
    ]


def test_plan_windows_exact_multiple():
    # 240s audio, 120s window, 10s overlap -> 2 windows with overlap
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
```

**Step 2: Run — expect failures (module doesn't exist)**

Run: `uv run pytest tests/test_pipeline_chunking.py -v`

Expected: `ModuleNotFoundError: No module named 'recap.pipeline.chunking'`.

**Step 3: Implement `plan_windows`**

Create `recap/pipeline/chunking.py`:

```python
"""Windowing + stitching utilities for chunked Parakeet inference.

See ``docs/plans/2026-04-20-parakeet-chunked-inference-design.md`` for
scope, OOM policy, and overlap semantics.
"""
from __future__ import annotations


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
```

**Step 4: Run tests — expect pass**

Run: `uv run pytest tests/test_pipeline_chunking.py -v`

Expected: 4 passed.

**Step 5: Commit**

```bash
git add recap/pipeline/chunking.py tests/test_pipeline_chunking.py
git commit -m "feat(pipeline): plan_windows for chunked inference"
```

---

## Task 2B.2: Utterance offset helper

**Goal:** Pure function that takes per-window utterances (timestamps relative to window start) and returns utterances with timestamps in the original audio's time base.

**Files:**
- Modify: `recap/pipeline/chunking.py`
- Modify: `tests/test_pipeline_chunking.py`

**Step 1: Write the failing test**

Add to `tests/test_pipeline_chunking.py`:

```python
from recap.models import Utterance
from recap.pipeline.chunking import offset_utterances


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
```

**Step 2: Run — expect ImportError**

Run: `uv run pytest tests/test_pipeline_chunking.py::test_offset_utterances_shifts_timestamps -v`

Expected: FAIL, `ImportError: cannot import name 'offset_utterances'`.

**Step 3: Implement**

Append to `recap/pipeline/chunking.py`:

```python
from recap.models import Utterance


def offset_utterances(
    utterances: list[Utterance],
    window_start_s: float,
) -> list[Utterance]:
    """Return a new list of utterances with timestamps shifted by ``window_start_s``.

    Each utterance is immutable; this function constructs fresh instances
    so the caller's per-window list is never mutated.
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
```

**Step 4: Run — expect pass**

Run: `uv run pytest tests/test_pipeline_chunking.py -v`

Expected: 6 passed.

**Step 5: Commit**

```bash
git add recap/pipeline/chunking.py tests/test_pipeline_chunking.py
git commit -m "feat(pipeline): offset_utterances for chunked stitching"
```

---

## Task 2B.3: Overlap dedup

**Goal:** Pure function that merges two already-offset utterance lists (from adjacent windows) using the center-timestamp rule: in the overlap zone, each utterance is assigned to the window holding its center, and its duplicate in the other window is dropped.

**Files:**
- Modify: `recap/pipeline/chunking.py`
- Modify: `tests/test_pipeline_chunking.py`

**Step 1: Write the failing tests**

```python
from recap.pipeline.chunking import merge_overlapping_windows


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
    # Same overlap zone, but overlap-c's center is at 119.5 -> still in window 1
    # because the rule is "the window that holds its midpoint". To exercise
    # the other side, use an utterance whose center is at 120.5 (just past
    # the overlap zone, belongs to window 2 exclusively — not dedup-territory).
    # For center-in-overlap-goes-to-prior behavior, verify prior keeps its own.
    w1 = [Utterance("UNKNOWN", 115.0, 118.0, "only-in-prior")]
    w2 = []
    merged = merge_overlapping_windows(
        prior=w1, later=w2, overlap_start_s=110.0, overlap_end_s=120.0,
    )
    assert [u.text for u in merged] == ["only-in-prior"]


def test_merge_empty_later_returns_prior():
    w1 = [Utterance("UNKNOWN", 0.0, 5.0, "a")]
    assert merge_overlapping_windows(w1, [], 0.0, 10.0) == w1


def test_merge_result_is_monotonic():
    w1 = [Utterance("UNKNOWN", 0.0, 5.0, "a"), Utterance("UNKNOWN", 113.0, 118.0, "b")]
    w2 = [Utterance("UNKNOWN", 113.0, 118.0, "b"), Utterance("UNKNOWN", 125.0, 130.0, "c")]
    merged = merge_overlapping_windows(w1, w2, 110.0, 120.0)
    for i in range(1, len(merged)):
        assert merged[i].start >= merged[i - 1].start
```

**Step 2: Run — expect ImportError**

**Step 3: Implement**

```python
def merge_overlapping_windows(
    prior: list[Utterance],
    later: list[Utterance],
    overlap_start_s: float,
    overlap_end_s: float,
) -> list[Utterance]:
    """Concatenate two adjacent windows' utterance lists, deduping the overlap.

    The center-timestamp rule: an utterance whose ``(start + end) / 2`` lies
    inside ``[overlap_start_s, overlap_end_s]`` is kept in the ``prior``
    window; its duplicate in ``later`` (same start, end, text) is dropped.

    Assumes each list is already individually sorted by ``start`` ascending
    and offset into the same absolute time base.
    """
    prior_overlap_keys: set[tuple[float, float, str]] = set()
    for u in prior:
        center = (u.start + u.end) / 2.0
        if overlap_start_s <= center <= overlap_end_s:
            prior_overlap_keys.add((u.start, u.end, u.text))

    later_filtered = [
        u for u in later
        if (u.start, u.end, u.text) not in prior_overlap_keys
    ]
    return list(prior) + later_filtered
```

**Step 4: Run — expect pass**

**Step 5: Commit**

```bash
git add recap/pipeline/chunking.py tests/test_pipeline_chunking.py
git commit -m "feat(pipeline): deterministic overlap dedup via center-timestamp rule"
```

---

## Task 2B.4: ffmpeg window slicer

**Goal:** Extract `[start_s, end_s]` of a source audio file into a temp `.wav` file via ffmpeg. Returns the temp path. Raises `RuntimeError` on ffmpeg failure (mirrors `audio_convert.py` style).

**Files:**
- Modify: `recap/pipeline/chunking.py`
- Modify: `tests/test_pipeline_chunking.py`

**Step 1: Write the failing test**

```python
import subprocess
from pathlib import Path

from recap.pipeline.chunking import slice_window_to_temp


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
```

**Step 2: Run — expect ImportError**

**Step 3: Implement**

Append to `recap/pipeline/chunking.py`:

```python
import subprocess
import uuid
from pathlib import Path

_FFMPEG_SLICE_TIMEOUT_S = 60


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
```

**Step 4: Run — expect pass**

**Step 5: Commit**

```bash
git add recap/pipeline/chunking.py tests/test_pipeline_chunking.py
git commit -m "feat(pipeline): ffmpeg window slicer for chunked inference"
```

---

## Task 2B.5: Wire chunking into `transcribe()`

**Goal:** Replace the single `model.transcribe([path])` call with a windowed loop that slices → transcribes each window → stitches → cleans up temp files. Preserve the function signature and the save_transcript contract.

**Files:**
- Modify: `recap/pipeline/transcribe.py`
- Modify: `tests/test_pipeline_transcribe.py`

**Step 1: Read existing transcribe tests to understand fixtures**

Run: `uv run cat tests/test_pipeline_transcribe.py` (or `Read` tool). Note the existing mock pattern for `_load_model` and the fake Hypothesis shape.

**Step 2: Write the failing test**

Add to `tests/test_pipeline_transcribe.py`:

```python
def test_transcribe_slices_into_windows_and_stitches(monkeypatch, tmp_path):
    """Long audio: each window is transcribed once; whole-file call is absent."""
    audio = tmp_path / "long.wav"
    audio.write_bytes(b"RIFF")

    transcribe_calls: list[str] = []

    class FakeHypothesis:
        def __init__(self, text, segments):
            self.text = text
            self.timestamp = {"segment": segments}

    class FakeModel:
        def to(self, _device): return self
        def transcribe(self, paths, **_kwargs):
            # One path per call (windowed). Capture for assertion.
            transcribe_calls.extend(paths)
            # Return one segment per window with per-window-relative timestamps.
            return [FakeHypothesis(
                text=f"content-{len(transcribe_calls)}",
                segments=[{"start": 1.0, "end": 5.0, "segment": f"content-{len(transcribe_calls)}"}],
            )]

    monkeypatch.setattr("recap.pipeline.transcribe._load_model", lambda *a, **k: FakeModel())
    # Force duration to 300s so the planner produces 3 windows @ 120s / 10s overlap.
    monkeypatch.setattr("recap.pipeline.transcribe._probe_duration_s", lambda _p: 300.0)
    # Stub the ffmpeg slicer so no real ffmpeg runs.
    def fake_slice(source, start_s, duration_s, temp_dir):
        temp_dir.mkdir(parents=True, exist_ok=True)
        p = temp_dir / f"win-{start_s}.wav"
        p.write_bytes(b"RIFF")
        return p
    monkeypatch.setattr("recap.pipeline.transcribe.slice_window_to_temp", fake_slice)

    from recap.pipeline.transcribe import transcribe
    result = transcribe(audio_path=audio, device="cpu")

    # 300s with 120/10 plan -> windows at [0,120], [110,230], [220,300] -> 3 calls.
    assert len(transcribe_calls) == 3
    # Timestamps must be monotonically non-decreasing across windows.
    starts = [u.start for u in result.utterances]
    assert starts == sorted(starts)
    # Each utterance's timestamp is in the original audio's time base.
    assert result.utterances[0].start == 1.0
    assert result.utterances[1].start == 111.0  # 110 + 1.0
    assert result.utterances[2].start == 221.0  # 220 + 1.0


def test_transcribe_cleans_temp_files_on_failure(monkeypatch, tmp_path):
    """ffmpeg temp files must not leak when a window OOMs."""
    audio = tmp_path / "long.wav"
    audio.write_bytes(b"RIFF")

    created: list[Path] = []

    def fake_slice(source, start_s, duration_s, temp_dir):
        temp_dir.mkdir(parents=True, exist_ok=True)
        p = temp_dir / f"win-{start_s}.wav"
        p.write_bytes(b"RIFF")
        created.append(p)
        return p

    class OOMModel:
        def to(self, _device): return self
        def transcribe(self, _paths, **_kwargs):
            raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr("recap.pipeline.transcribe._load_model", lambda *a, **k: OOMModel())
    monkeypatch.setattr("recap.pipeline.transcribe._probe_duration_s", lambda _p: 300.0)
    monkeypatch.setattr("recap.pipeline.transcribe.slice_window_to_temp", fake_slice)

    from recap.pipeline.transcribe import transcribe
    with pytest.raises(RuntimeError, match="out of memory"):
        transcribe(audio_path=audio, device="cpu")

    # After failure, no temp files remain.
    for p in created:
        assert not p.exists(), f"temp file leaked: {p}"
```

**Step 3: Run — expect fail**

**Step 4: Implement chunked transcribe**

Replace the body of `transcribe()` in `recap/pipeline/transcribe.py`. Keep the docstring. New body (sketch):

```python
import shutil
import subprocess
import tempfile
from pathlib import Path

from recap.pipeline.chunking import (
    merge_overlapping_windows,
    offset_utterances,
    plan_windows,
    slice_window_to_temp,
)

_WINDOW_SIZE_S = 120.0
_OVERLAP_S = 10.0


def _probe_duration_s(audio_path: Path) -> float:
    """Return the audio duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return float(result.stdout.strip())


def _hypothesis_to_utterances(hyp) -> list[Utterance]:
    timestamp = getattr(hyp, "timestamp", None)
    if isinstance(timestamp, dict):
        segments = timestamp.get("segment", [])
    else:
        segments = []
    return [
        Utterance(
            speaker="UNKNOWN",
            start=seg["start"],
            end=seg["end"],
            text=seg["segment"],
        )
        for seg in segments
    ]


def transcribe(
    audio_path: Path,
    model_name: str = "nvidia/parakeet-tdt-0.6b-v2",
    device: str = "cuda",
    save_transcript: Path | None = None,
) -> TranscriptResult:
    """Transcribe with chunked inference. See design doc for details."""
    duration_s = _probe_duration_s(audio_path)
    windows = plan_windows(duration_s, _WINDOW_SIZE_S, _OVERLAP_S)

    temp_dir = Path(tempfile.mkdtemp(prefix="recap-chunks-"))
    model = _load_model(model_name, device)
    stitched: list[Utterance] = []
    try:
        for i, (start_s, end_s) in enumerate(windows):
            chunk_path = slice_window_to_temp(
                source=audio_path,
                start_s=start_s,
                duration_s=end_s - start_s,
                temp_dir=temp_dir,
            )
            try:
                results = model.transcribe([str(chunk_path)], timestamps=True)
                hyp = results[0]
                window_utts = _hypothesis_to_utterances(hyp)
                offset = offset_utterances(window_utts, start_s)
                if stitched and i > 0:
                    prior_window_end = windows[i - 1][1]
                    overlap_start = start_s
                    overlap_end = min(prior_window_end, end_s)
                    stitched = merge_overlapping_windows(
                        stitched, offset, overlap_start, overlap_end,
                    )
                else:
                    stitched = list(offset)
            finally:
                chunk_path.unlink(missing_ok=True)

        raw_text = " ".join(u.text for u in stitched)
        result = TranscriptResult(
            utterances=stitched, raw_text=raw_text, language="en",
        )
        if save_transcript is not None:
            _save_transcript_json(save_transcript, result)
        return result
    finally:
        _unload_model(model)
        shutil.rmtree(temp_dir, ignore_errors=True)
```

Move the transcript JSON-writing code into a `_save_transcript_json` helper (DRY). Keep the existing `_load_model` / `_unload_model` unchanged.

**Step 5: Run the new + existing transcribe tests**

Run: `uv run pytest tests/test_pipeline_transcribe.py -v`

Expected: all pass. If an older test breaks because it mocked `model.transcribe` once-per-whole-file, update the mock to match the per-window pattern (one call per window).

**Step 6: Run the full suite**

Run: `uv run pytest`

Expected: 686+ passed, coverage >= 70%.

**Step 7: Commit**

```bash
git add recap/pipeline/transcribe.py tests/test_pipeline_transcribe.py
git commit -m "feat(pipeline): chunked Parakeet transcribe with ffmpeg slicing"
```

---

## Task 3: Diarize audit

**Goal:** One measurement — is Sortformer's whole-file call on the preserved 37-min `.mono.wav` a hidden OOM waiting to happen?

**Files:**
- Create (throwaway): `scripts/audit_diarize_vram.py`
- Modify: commit message of the final commit (or append a note to the handoff)

**Step 1: Write the audit script**

```python
"""Throwaway audit: peak VRAM for Sortformer on the preserved 37-min file.

Delete after recording the result in the commit message / handoff.
"""
from __future__ import annotations

import sys
from pathlib import Path

AUDIO = Path(
    r"C:/Users/tim/recap-test-data/recordings/"
    r"2026-04-20-155927-disbursecloud.mono.wav"
)


def main() -> int:
    if not AUDIO.exists():
        print(f"Missing: {AUDIO}", file=sys.stderr)
        return 2
    import torch
    from nemo.collections.asr.models import SortformerEncLabelModel

    model = SortformerEncLabelModel.from_pretrained(
        "nvidia/diar_streaming_sortformer_4spk-v2.1",
    ).to("cuda")
    torch.cuda.reset_peak_memory_stats()
    try:
        model.diarize(str(AUDIO))
    except Exception as exc:
        peak = torch.cuda.max_memory_allocated() / (1024**3)
        print(f"FAIL after peak {peak:.2f} GiB: {exc}")
        return 1
    peak = torch.cuda.max_memory_allocated() / (1024**3)
    print(f"OK peak VRAM: {peak:.2f} GiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Step 2: Run**

Run: `uv run python scripts/audit_diarize_vram.py`

**Step 3: Record the outcome**

- **If peak > 6 GiB:** create `docs/handoffs/2026-04-20-sortformer-chunking-followup.md` with the measured number and a note that Sortformer needs the same treatment. Do NOT start that work in this session.
- **If peak <= 6 GiB:** note the peak in the final commit message. No follow-up needed.

**Step 4: Delete the audit script**

```bash
rm scripts/audit_diarize_vram.py
git add -A scripts/
```

---

## Task 4: Manual replay against the preserved `.flac`

**Goal:** End-to-end confidence that the new transcribe path handles real 37-min audio without OOM and produces a plausible transcript.

**Files:**
- No code changes. This is verification.

**Step 1: Prepare a stub metadata JSON**

```bash
mkdir -p /tmp/recap-replay
cat > /tmp/recap-replay/metadata.json <<'EOF'
{
  "title": "Replay — 2026-04-20 155927",
  "date": "2026-04-20",
  "participants": [{"name": "Tim"}],
  "platform": "zoho_meet"
}
EOF
```

**Step 2: Confirm the preserved artifacts**

Run:
```bash
ls -lh /c/Users/tim/recap-test-data/recordings/2026-04-20-155927-disbursecloud.flac
ls -lh /c/Users/tim/recap-test-data/recordings/2026-04-20-155927-disbursecloud.mono.wav
```

Expected: both files exist, `.flac` is ~82 MB, `.mono.wav` is ~200 MB.

**Step 3: Run the replay**

Run:
```bash
uv run python -m recap.cli process \
  /c/Users/tim/recap-test-data/recordings/2026-04-20-155927-disbursecloud.flac \
  /tmp/recap-replay/metadata.json \
  --vault /c/Users/tim/recap-test-vault \
  --org Disbursecloud \
  --user Tim \
  --from transcribe \
  --device cuda
```

**Step 4: Verify replay success criteria** (design doc section "Replay success criteria")

1. Exit code 0.
2. No `CUDA out of memory` in the log.
3. No `Stage '<name>' hit OOM; skipping retry` warning (because there was no OOM).
4. Transcript JSON is written next to the .flac. Spot-check: read 3 regions (start, middle, end), each has readable text.
5. `jq '.utterances | map(.start) | (. == sort)' <transcript>.json` returns `true`.
6. No obvious duplicate text at the 120s, 240s, 360s... boundaries.

**Step 5: Record result**

Add a "## Task 4 outcome" section to this implementation plan capturing:
- Wall time for the transcribe stage.
- Peak VRAM (observed during the run via `nvidia-smi -l 1 | tee /tmp/vram.log` in another shell).
- Any anomalies.

---

## Task 5: Handoff update + final commit

**Files:**
- Modify: `docs/handoffs/2026-04-20-parakeet-chunked-inference.md` — replace "## The real fix: chunked Parakeet inference" section with a terse "done, commit X, replay Y" note.
- Commit all outstanding `docs/` changes.

**Step 1: Update handoff**

Edit the handoff doc to reflect completion. Keep the independent cleanup items (FLAC duration, scheduler idempotency). Add a one-line pointer to the new Sortformer-chunking follow-up handoff if Task 3 produced one.

**Step 2: Final commit**

```bash
git add docs/handoffs/2026-04-20-parakeet-chunked-inference.md \
        docs/plans/2026-04-20-parakeet-chunked-inference-implementation.md
git commit -m "docs(pipeline): close out chunked Parakeet inference work"
```

**Step 3: Run full suite one more time**

Run: `uv run pytest`

Expected: all green.

---

## Success summary

When all tasks complete:

- `recap/pipeline/transcribe.py` no longer calls whole-file `model.transcribe` on long audio.
- Unit tests cover windowing math, timestamp offset, overlap dedup, ffmpeg slicing, and orchestration.
- The preserved 37-min `.flac` replays to completion.
- Sortformer has an explicit data point: either fine at current audio lengths or a follow-up handoff exists.
- OOM safety (commit `1aa86f7`) is still in place as belt-and-braces.

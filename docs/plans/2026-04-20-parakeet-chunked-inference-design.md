# Parakeet chunked inference — design

**Date:** 2026-04-20
**Branch:** `obsidian-pivot`
**Related:** `docs/handoffs/2026-04-20-parakeet-chunked-inference.md` (problem statement), commit `1aa86f7` (OOM safety patch)

## Problem

`recap/pipeline/transcribe.py:64` calls `model.transcribe([str(audio_path)], timestamps=True)` on the full audio file. Parakeet-TDT-0.6b-v2 allocates attention over the entire mel sequence, so a 37-min recording demanded 46 GiB of VRAM on a 12 GiB card. Today's safety patch (`is_oom_error` in `_run_with_retry`) prevents the retry-storm that crashed the host, but it does not fix the underlying capacity limit: any meeting over ~10 min still fails on this GPU.

## Scope

**In scope:** Replace the whole-file call in `transcribe.py` with chunked inference that fits on a 12 GiB GPU for recordings up to ~4 hours (the pipeline's configured `max_duration_hours`).

**Out of scope (explicit):**
- Sortformer / diarize chunking — audited during this pass, redesigned only if the replay proves it is the next blocker.
- Live streaming transcription (`recap/daemon/streaming/transcriber.py`) — stays deferred per Phase 7.
- Adaptive per-window halving on OOM — documented as a future fallback if fixed-size chunking proves insufficient in practice; not implemented now.
- Whole-pipeline OOM resilience sweep (analyze, export, convert).

## Approach: A with strict spike gate, B as committed fallback

### Path A — NeMo buffered inference (preferred)

Use `nemo.collections.asr.parts.utils.streaming_utils` (`FrameBatchASR` or the TDT-equivalent helper if one exists) to run Parakeet over overlapping windows inside a single model call. NeMo handles encoder chunking and timestamp stitching internally.

Smallest production diff: the change is largely replacing the `model.transcribe([path])` call with the helper's API, keeping the rest of `transcribe.py` intact.

### Path B — manual slice-and-stitch (fallback)

If the spike fails, slice the mono audio with ffmpeg into per-window temp files, call `model.transcribe([str(temp_wav)])` per window (same file-path surface as today), and stitch results ourselves.

**Initial parameters (tunable):**
- **Window size:** 120 seconds. Math: the failed run allocated ~1.25 GiB per minute of audio → 120s ≈ 2.5 GiB peak, leaves 9 GiB for diarize + OS/other apps.
- **Overlap:** 10 seconds. Long enough to cover most inter-sentence pauses without doubling compute; short enough that dedup is cheap.
- **Overlap dedup rule:** deterministic — in the overlap zone between window N and N+1, keep utterances whose center timestamp lies in the window that holds its midpoint. Drop the duplicate from the other side.
- **Audio slicing:** ffmpeg (already a pipeline dependency — see `recap/pipeline/audio_convert.py`) extracts each window from `.mono.wav` to a temp `.wav` file with `-ss <start> -t <duration> -c:a pcm_s16le`. Host memory stays O(window), not O(file); this keeps the ~4-hour recording claim honest.
- **Temp-file lifecycle:** each window's temp file is deleted immediately after its `model.transcribe()` call returns. Cleanup also runs in a stage-level `finally` so a mid-stage failure doesn't leak temp files. Temp files land in the OS temp dir under a per-run subdirectory for easy bulk cleanup.

### Path C — streaming module (explicitly rejected)

Folding into `recap/daemon/streaming/transcriber.py` would couple this capacity fix with the Phase 7 live-streaming concerns (real-time latency, incremental output, UI push). Keep separate.

## Spike exit criteria (A → B gate)

The NeMo-helper spike is time-boxed to **one focused session (~2 hours of active work)**. Path A proceeds only if the spike demonstrates all of:

1. Parakeet-TDT-0.6b-v2 runs through the helper without whole-file VRAM blowup on the preserved 37-min `.flac`.
2. Returned timestamps map into `TranscriptResult.utterances` with the same `{speaker, start, end, text}` shape we produce today.
3. No obvious overlap duplication or timestamp non-monotonicity in the stitched output.
4. The helper fits inside `transcribe.py` without importing any live-streaming module.

If any of these are shaky or the helpers turn out to be CTC-only, fall through to Path B without further investigation. Path B is built entirely on the file-path `model.transcribe([path])` surface we already use in production, so the fallback carries no new unverified NeMo dependencies.

## Transcript contract (invariant across A and B)

- Output is still a `TranscriptResult` with the same `utterances`, `raw_text`, `language` fields.
- No partial transcript is persisted on failure. `save_transcript` writes only on success.
- `utterances` are sorted by `start` ascending. `end >= start` for every utterance. No two utterances share both endpoints.
- Overlap dedup is deterministic: given the same inputs and parameters, the output is byte-identical across runs.
- `raw_text` is the space-joined concatenation of `utterances[*].text` in order.

## OOM policy (per-window)

Unchanged from the safety patch: if any window's inference raises OOM, the stage fails immediately. No halving, no retry, no partial save. The windowing exists to prevent OOM in the first place; a window-level OOM means sizing was wrong, which is a design error, not a runtime fallback.

## Validation

**Unit tests** (TDD for the windowing/stitching code):
- Window slicing produces correct offsets on exact-multiple, partial-last, and single-window inputs.
- Per-window timestamps are offset correctly in the stitched output.
- Overlap dedup keeps the expected side and produces monotonic timestamps.
- Empty window (silence) produces no utterances without error.
- Raw-text concatenation matches the utterance order.

NeMo is mocked at the function boundary; tests use a fake `transcribe_fn` that returns canned per-window results.

**Manual replay** (end-to-end confidence):
- Replay `C:/Users/tim/recap-test-data/recordings/2026-04-20-155927-disbursecloud.flac` via the pipeline's `--from transcribe` entry point (see `recap/cli.py`).

**Replay success criteria:**
1. Transcribe stage completes without CUDA OOM.
2. No retry is attempted (log shows the OOM-suppression path did not fire — because there was no OOM).
3. Produced transcript is plausibly complete on spot-check (a few minutes of readable text at beginning, middle, end).
4. Timestamps are monotonic; no visible duplicate text at window boundaries.

No CI GPU gating. No `@pytest.mark.gpu` lane.

## Diarize audit (scope-bound)

While implementing, run one exploratory measurement:
- Load `diar_streaming_sortformer_4spk-v2.1` and call `model.diarize(str(preserved_mono_wav))` against the preserved 37-min file, observing peak VRAM via `nvidia-smi` or `torch.cuda.max_memory_allocated()`.
- **If peak VRAM exceeds ~6 GiB** (leaving no headroom for other GPU apps): file a follow-up task for Sortformer chunking with the same strategy.
- **If peak VRAM fits comfortably:** close the audit with a note in the commit message. No redesign.

This is a measurement, not a redesign. One data point, then done.

## Implementation order

The writing-plans skill will expand this into a TDD plan, but the broad sequence is:

1. Spike path A: minimal probe in a throwaway script, verify exit criteria.
2. If A: implement Path A in `transcribe.py` + unit tests for whatever stitching surface remains.
3. If B: implement slicing / stitching / dedup with unit tests; wire into `transcribe.py`.
4. Diarize audit measurement.
5. Manual replay against preserved `.flac`.
6. Commit + handoff.

## Future enhancements (not this pass)

- **Adaptive window downsizing** — if fixed-size chunking proves brittle on real hardware, implement halve-and-retry per window (the OOM classifier already exists; we'd just need to gate it on a per-window retry counter).
- **Sortformer chunking** — if the diarize audit surfaces the same capacity problem.
- **Config-exposed window parameters** — move `window_size_s` / `overlap_s` into `config.yaml → pipeline:` if tuning ever becomes user-facing. Hardcoded constants for now.

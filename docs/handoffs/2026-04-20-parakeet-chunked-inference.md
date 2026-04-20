# Handoff — Parakeet chunked inference (capacity fix)

**Date:** 2026-04-20
**Branch:** `obsidian-pivot`
**Previous handoff:** `docs/handoffs/2026-04-20-meeting-detection-test.md`

## What happened today

Meeting detection test (Scenario 1 step 2) **PASSED**:

- User joined a Zoho-Meet call at 15:59:27 via `https://meeting.tranzpay.io/wrmd-wpv-qjd`.
- Browser extension matched the URL (platform `zoho_meet`), POSTed `/api/meeting-detected`.
- Detector consumed the 16:00 Zoho calendar arm (`ARMED → DETECTED → RECORDING`), used `org=disbursecloud`.
- Recorder wrote `2026-04-20-155927-disbursecloud.flac` (82 MB, ~37 min) until meeting-ended at 16:36:35.

Step 3 (pipeline) **crashed the host**:

- `audio_convert.ensure_mono_for_ml` completed (`.mono.wav` sidecar survived on disk).
- `transcribe` raised `CUDA out of memory. Tried to allocate 46.19 GiB` on a 12 GiB GPU.
- `_run_with_retry` slept 30s and re-attempted the same whole-file allocation.
- Log cuts off mid-retry with no shutdown messages → hard Windows crash (WDDM/CUDA driver hang + pagefile thrash).

## What was fixed this session (safety patch)

Commit: *see next commit on `obsidian-pivot`*.

- `recap/errors.py` — new `is_oom_error(error)` helper matches `MemoryError`, `"cuda out of memory"`, and bare `"out of memory"`.
- `recap/pipeline/__init__.py` — `_run_with_retry` short-circuits `should_retry = False` when `is_oom_error(first_error)` is true. Logs `Stage '<name>' hit OOM; skipping retry to avoid host stress: ...`. Applies to every stage via the shared wrapper (transcribe, diarize, analyze, export, convert).
- `tests/test_pipeline_retry.py` — 4 new tests: transcribe OOM non-retry, diarize OOM non-retry, non-OOM transient still retries, stage-agnostic OOM rule.

Full suite: 686 passed, 75% coverage.

**What this does NOT fix:** the root capacity problem. `transcribe.py:52` still calls `model.transcribe([str(audio_path)], timestamps=True)` on the whole file. Long recordings still fail — they just fail once now instead of retrying into the same wall.

## The real fix: chunked Parakeet inference — DONE

Path B (ffmpeg slice + per-window `model.transcribe` + deterministic stitching) landed on `obsidian-pivot`. Design: `docs/plans/2026-04-20-parakeet-chunked-inference-design.md`. Implementation plan + per-task outcomes: `docs/plans/2026-04-20-parakeet-chunked-inference-implementation.md`.

**Shipped:**
- `recap/pipeline/chunking.py` — `plan_windows`, `offset_utterances`, `merge_overlapping_windows` (positional overlap dedup + adjacent-same-start collapse), `slice_window_to_temp`.
- `recap/pipeline/transcribe.py` — chunked windowed loop at 120s / 10s overlap; ffprobe duration, per-window ffmpeg slice, stitched output. Two-layer try/finally guarantees temp dir + model are each cleaned up even if the other acquisition fails.

**Replay against preserved `.flac`:** exit code 0, peak VRAM 7.12 GiB on a 12 GiB GPU (down from the 46 GiB demand that crashed the host), 400 utterances, monotonic timestamps, zero detectable boundary duplicates after the same-start collapse fix. Full pipeline wall time 3m 10s.

**Sortformer audit (the "diarize parity" open question):** whole-file `model.diarize(mono.wav)` peaks at **2.17 GiB** on the same 37-min recording. Well under threshold; no chunking follow-up needed at current audio lengths.

**OOM safety patch (commit `1aa86f7`) stays in place** as belt-and-braces: the chunked path should never OOM in practice, and if it does (corrupted audio, hardware anomaly), `_run_with_retry` will fail fast rather than retry-storm.

## Independent cleanup items (surfaced but not fixed)

1. **FLAC `Duration: N/A` in STREAMINFO.** Every recording in `recap-test-data/recordings/` (cleanly stopped or crashed) reports `Duration: N/A` via `ffprobe`. `AudioCapture.stop()` does call `self._encoder.finish()` at `audio.py:968`, so this is a pyflac streaming-encoder limitation, not a graceful-shutdown issue. Non-blocking for the pipeline today, but `_get_audio_duration` in `pipeline/__init__.py` falls back to `0` which may confuse downstream stages. Fix candidates: post-process with `ffmpeg -c copy` to rewrite the header, or switch to a pyflac mode that patches STREAMINFO.
2. **Scheduler idempotency bug** (`Cannot arm from armed`). `recap/daemon/calendar/scheduler.py:168` re-arms on every 15-min sync; `detector.arm_for_event` blindly calls `state_machine.arm()` which only allows `IDLE`. Fix: skip arming when `_armed_event["event_id"]` already matches, or make `arm_for_event` idempotent. Cosmetic noise only — not on the critical path.

## Quick restart recipe

1. `cd C:/Users/tim/OneDrive/Documents/Projects/recap`
2. `uv run python -m recap.launcher config.yaml`
3. Verify daemon `/api/status` returns `state: idle`.
4. For pipeline work, skip the live-meeting step and replay against the surviving .flac:
   ```
   uv run python -m recap.pipeline --audio C:/Users/tim/recap-test-data/recordings/2026-04-20-155927-disbursecloud.flac --from transcribe
   ```
   (confirm the actual CLI entry point — this is the intent, not necessarily the exact invocation).

## Session state at handoff

- Safety patch commit on `obsidian-pivot` (this session).
- `git status` still shows unrelated uncommitted changes from earlier today (launcher + daemon refactors) — not this session's work, don't roll them in.
- Local tests: 686 passing.

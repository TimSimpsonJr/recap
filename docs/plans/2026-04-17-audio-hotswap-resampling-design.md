# Audio Capture: Rate Resampling + Hot-Swap Recovery

**Status:** Design approved 2026-04-17. Ready for implementation planning.
**Parent:** Phase 7 audio stabilization. Supersedes the fail-fast `AudioDeviceError` on rate mismatch landed in commit 2760111.
**Reviewer:** Codex (external) — signed off §1-§5.

## Problem

Today the recorder:

- Opens mic + loopback WASAPI streams at a single device-native rate resolved at `start()`.
- Raises `AudioDeviceError` if mic and loopback report different native rates — a legitimate production condition (user's default output is 44.1 kHz, mic is 48 kHz).
- Assumes both sources advance in a shared frame cadence; the drain loop polls buffer sizes and interleaves what arrives.
- Has no reopen logic. If the default input or output device changes mid-recording (user plugs/unplugs a headset, Windows swaps to Bluetooth, driver stalls), PyAudio keeps reading from the stale handle, or the callback stops receiving frames entirely — no detection, no recovery, no journal warning.

The user's machine hit case (1) on the first Ollama smoke test (mic=48 kHz, loopback=44.1 kHz). More importantly, they have multiple input devices and switch between them during meetings; the current architecture silently corrupts or stops the recording when this happens.

## Goals

1. Record gracefully when mic and loopback have different native sample rates.
2. Detect mid-recording device changes (default-device swap OR hard failure like unplug) and reopen affected streams without killing the recording.
3. Preserve high-quality archive audio — pipeline models handle their own resampling.
4. Keep `AudioCapture`'s public API unchanged so existing callers don't break.

## Non-Goals

- Configurable output sample rate. Production is 48 kHz, full stop.
- Perfect mid-swap continuity. Silence-padding during the ~500 ms reopen gap is acceptable.
- Recovery from both sources dead — that's a fatal recording condition, user retries.
- WASAPI `IMMNotificationClient` native event API. Polling + stream-status watchdog covers the same cases without COM complexity. Defer.

## Design

### §1. Public contract (unchanged surface)

- `AudioCapture(output_path, sample_rate=48000, channels=2)` keeps the same signature for backward compatibility.
- Production path (`start()` called): always uses a fixed 48 kHz output timeline regardless of the `sample_rate` kwarg. `self._sample_rate` is overwritten to `48000` in `start()`, so the FLAC encoder and `on_chunk(bytes, sample_rate)` callback both see the real output rate. If `start()` is called with a value other than `48000`, log a one-shot warning noting the override; do not raise.
- Test helper path (`_test_feed_mock_frames`): does not go through `start()`. `self._sample_rate` stays at whatever `__init__` received, so existing synthetic-feed tests keep working unmodified.
- `sample_rate` property returns `self._sample_rate` — which is `48000` after `start()`.
- Any tests asserting default `sample_rate == 16000` should be reinterpreted as "pre-start constructor state" tests, not production-capture tests.
- `on_chunk(bytes, sample_rate)` in production always emits `48000`.

### §2. `_SourceStream` private class

A private class inside `audio.py`. Two instances per `AudioCapture`: one for mic, one for loopback. `AudioCapture`'s constructor and external behavior are preserved; this is an "A-lite" refactor that does not split files or export the class.

**Owns:**

- One `PyAudioWPatch` stream (open or closed).
- One `soxr.ResampleStream` instance (stateful, rebuilt only on input rate change).
- Raw inbound byte buffer (written by the PyAudio callback).
- Resampled 48 kHz PCM buffer (the internal stage that converts callback bytes into 48 kHz frames).
- Stable device identity — prefer WASAPI endpoint ID or device GUID if PyAudioWPatch exposes one; fall back to `name + hostApi + maxInputChannels` (indexes get reassigned after hot-plug).
- Two separate identity fields: the currently-bound stream's identity, and the latest observed default identity.
- Health state: `HEALTHY`, `RECONNECTING`, `DEGRADED`, `STOPPED`. `DEGRADED` is **non-terminal** — subsequent `attempt_reopen_if_due()` calls can restore it to `HEALTHY`.
- Reconnect metadata: last-status-ok-time, reconnect-attempt-count, backoff timer.

**Two-stage internal pipeline:**

1. PyAudio callback appends raw bytes to the raw inbound buffer (callback-thread work, must be minimal).
2. A per-source resample step converts raw bytes into 48 kHz PCM in the resampled buffer (runs on the drain thread or in `read_frames` — decided in implementation plan).
3. `read_frames(n)` drains `n` frames from the resampled buffer, silence-pads on underflow.

**Public methods:**

- `start()` — open stream + build initial resampler.
- `stop()` — transition to `STOPPED` before tearing down internals (avoids reopen races during shutdown).
- `attempt_reopen_if_due()` — advisory; quickly decides whether anything needs doing and only does reopen work when necessary. Called by the drain loop on the health tick.
- `read_frames(target_frames: int) -> bytes` — returns `target_frames` worth of 48 kHz mono int16 bytes. If the source is reconnecting or degraded, returns silence bytes of the same length. Never blocks.
- `is_degraded() -> bool`.

**Resampler lifecycle:**

- Built on `start()` with the device's native rate.
- Reused across chunks (stateful — this is why we chose soxr over batch resample).
- Torn down and rebuilt only when a reopen lands on a device with a different native rate. Output rate stays 48000 throughout the source's lifetime.

**Reopen backoff:** 250 ms → 500 ms → 1 s → 2 s, bounded by a 5 s wall-clock window total. After the window, source flips to `DEGRADED`, emits one journal warning, keeps feeding silence. If health returns, flips back to `HEALTHY` and emits a one-shot "recovered" warning. State-transition-edge-triggered — no per-tick log spam.

**Callback-thread work is minimal:** `_mark_unhealthy()` only sets a flag, stores a timestamp, and maybe captures the most recent status bits under the per-source lock. No device enumeration, no reopen, no logging from the callback thread.

### §3. Detection: polling + stream watchdog converging on one reopen path

Two detection signals, one `attempt_reopen_if_due()` entry point:

- **Slow path — polling.** Drain loop calls `source.attempt_reopen_if_due()` on each source when `time.monotonic() >= next_health_check_at`, then sets `next_health_check_at = time.monotonic() + 1.0`. The source internally polls `PyAudioWPatch.get_default_wasapi_device(d_in=True)` / `get_default_wasapi_loopback()` and compares the returned device identity against its currently-bound identity. Silent default-device changes (user flips default in Windows settings while the old stream still produces valid frames) are caught here — this is the main reason polling exists at all. The health tick should prefer the new default even if the old stream is still producing valid frames.
- **Fast path — stream status.** PyAudio callback sees a bad status → `_mark_unhealthy()` sets an internal dirty flag + status-bad timestamp. Thread-safe via per-source lock.

Both paths converge on `attempt_reopen_if_due()`, which handles: "is a reopen needed?", "are we past the backoff window for the next attempt?", and "execute the reopen (tear down old stream, open new on current default, rebuild resampler if rate changed, restore state)".

Journal/log emission on state-transition edges happens **inside `_SourceStream`**, preserving the source-owns-source-lifecycle boundary. The drain loop never logs about source-level events.

### §4. Wall-clock drain loop

The drain thread produces frames at 48 kHz regardless of whether either source is currently delivering. It is the authoritative clock for the FLAC timeline.

**Per tick (fixed cadence, 1024 frames = ~21.33 ms):**

1. `mic_bytes = mic_source.read_frames(1024)` → 2048 bytes of 48 kHz mono int16 (or silence).
2. `lb_bytes = loopback_source.read_frames(1024)` → same.
3. If `time.monotonic() >= next_health_check_at`: call `attempt_reopen_if_due()` on each source, then update `next_health_check_at`.
4. Interleave into stereo int16 `[mic0, lb0, mic1, lb1, ...]` (same logic as today's `_interleave_and_encode`).
5. Update `current_rms` from the interleaved buffer.
6. Feed the interleaved buffer to the pyFLAC encoder.
7. Invoke `on_chunk((mic + lb) / 2, 48000)` for streaming consumers (int32 widen to avoid overflow, then narrow to int16).

**Timing:** `start_time = time.monotonic()` at `start()`. Target emit time per tick is `start_time + (tick_index * 1024 / 48000)`. Sleep `max(0, target - now)` between ticks. Catch-up runs back-to-back without spamming health checks (driven by monotonic time, not tick count).

**Stop behavior:** `AudioCapture.stop()` flips `_recording` False. The drain loop exits the main while, then runs **one final partial tick**: drains up to the max available resampled frames across sources, silence-pads the shorter one so the final stereo frame count stays aligned, feeds the encoder, fires a final `on_chunk`. Captures the last ~21 ms of a meeting instead of truncating it. Then closes streams, resamplers, encoder, output file. `source.stop()` transitions each to `STOPPED` before teardown.

**Cross-thread fatal state:** `AudioCapture` holds `self._fatal_error: Exception | None = None` and `self._fatal_event: threading.Event`. When the drain thread detects `mic.is_degraded() and loopback.is_degraded()` simultaneously, it sets `_fatal_error = AudioCaptureBothSourcesFailedError(...)`, sets `_fatal_event`, and **exits the drain loop cleanly** (no raise — background-thread exceptions silently die otherwise). `fatal_error` property is sticky: set once, stays set until the next `start()`. Recorder adds a new async monitor `_monitor_capture_health` (sibling of `_monitor_silence` and `_monitor_duration`) that polls `audio_capture._fatal_event.is_set()` every ~500 ms; on trip, calls `recorder.stop()` and journals the error. Single-source degraded is silent in the recording path — the surviving source keeps writing; the DEGRADED-entry journal warning fired inside `_SourceStream` is the only user-facing signal.

### §5. Testing strategy

**Fake fixture:** `FakeSourceStream` exposing **only** the methods `AudioCapture` actually calls in production (`start`, `stop`, `attempt_reopen_if_due`, `read_frames`, `is_degraded`, state property). Scripted behavior injected per test: e.g., `FakeSourceStream(script=[("healthy", b"\x00"*2048), ("degraded", None), ("healthy", b"\x01"*2048)])`. Tests replace `time.sleep` with a monotonic mock, drive the drain loop a fixed number of ticks, assert observable outcomes.

**Soxr wrapper tested separately:** a thin `_SoxrResamplerWrapper` around `soxr.ResampleStream` gets its own tests — feed N frames at 44100 Hz, expect approximately M = N * 48000/44100 frames at 48000 Hz out, tolerate small boundary variance. Test no-discontinuity/no-explosion across chunk boundaries and on rate change (rebuild resampler). Avoid exact sample-for-sample waveform assertions unless `soxr` exposes an explicit flush contract.

**Key unit tests:**

- `test_both_sources_healthy_interleaves_at_48khz` — happy path.
- `test_mic_rate_mismatch_resamples_not_raises` — mic 44100 + loopback 48000 → both resample to 48000, no `AudioDeviceError`.
- `test_mic_silent_pads_while_loopback_runs` — simulate mic DEGRADED, verify encoder still gets stereo frames with silent left channel.
- `test_both_degraded_sets_fatal_event` — both DEGRADED → `fatal_error` sticky, `fatal_event` fires, drain exits cleanly (no raise in background thread).
- `test_device_identity_change_triggers_reopen` — assert observable behavior: source transitions through RECONNECTING, resampler is recreated (if rate differs), identity updates, healthy output resumes. **Do not** couple to internal `_do_reopen` method name.
- `test_reopen_backoff_respects_window` — successive failures don't bust the 5 s window.
- `test_final_partial_tick_on_stop_flushes_remainder` — stop mid-buffer, final tick flushes remainder with silence-pad on shorter source.
- `test_edge_triggered_warnings_fire_once_per_transition` — assert logged warnings (`caplog`), not journal entries, unless the journal seam is explicitly threaded through.

**Integration test (opt-in, skipped in CI):** `tests/integration/test_audio_hotswap.py` guarded by `@pytest.mark.hardware` (register the marker in `pyproject.toml` to suppress warnings). Records for 10 s while the user manually switches audio devices. Verification hook for the hardware case this design targets.

**Tests to remove:**

- `test_audio_capture_start_uses_matched_device_rate` — obsolete (we no longer require matched rates).
- `test_audio_capture_start_raises_on_device_rate_mismatch` — obsolete (we no longer raise).

**Tests that survive unchanged:**

- `test_audio_capture_does_not_pass_channels_to_encoder` — still valid as encoder kwarg guard.
- `test_audio_capture_invokes_on_chunk_after_interleave` — still valid (synthetic-feed path unchanged).
- `test_audio_capture_on_chunk_swallows_exceptions` — still valid.
- `test_audio_capture_on_chunk_default_is_none` — still valid.

## Dependencies

- **New:** `soxr` Python package (binding to libsoxr). ~500 KB. Stateful streaming resampler. Platform: Windows/Linux/macOS; ships prebuilt wheels for CPython 3.9-3.12.
- **Already transitive:** numpy (unchanged).
- Removed from scope: scipy (considered and rejected for this use — batch-only).

## Rollout

- Single commit or small stack on `obsidian-pivot` branch. No feature flag — the `AudioDeviceError` failure on rate mismatch is a bug, not a feature, and users would have to opt in to get a working recorder.
- Manual hardware smoke test before merge: (1) record with matched 48/48 rates, (2) record with 44.1/48 mismatch, (3) record while switching default input mid-session, (4) record while unplugging the active input mid-session.
- Phase 7 final integration pass scenarios 1-3 re-tested post-merge.

## Out of scope / deferred

- `IMMNotificationClient` native event detection. Polling covers the silent default-change case; callback status covers hard failure. Add only if the 1 s poll cadence proves insufficient in practice.
- Configurable output rate. `48000` is hardcoded. If a future pipeline model needs a different input rate, the pipeline handles it; the recorder does not.
- In-process downmix to mono for ML at capture time. The existing `ensure_mono_for_ml` helper in the pipeline stays authoritative for that transformation; the recorder's job is archive-quality stereo at 48 kHz.

# Multi-output audio capture — design

**Date:** 2026-04-21
**Status:** Approved (brainstorming)
**Scope:** `recap/daemon/recorder/audio.py`, sidecar schema in `recap/artifacts.py`, note export in `recap/vault.py`
**Trigger:** 2026-04-21 Zoho Meet recording captured only the user's voice (22 minutes, 39 utterances all tagged SPEAKER_00). Per-channel ffprobe showed channel 2 at `-inf dB` RMS — the default WASAPI loopback delivered zero bytes for the entire session because the meeting audio was routed to AirPods via Zoho's in-call device picker.

---

## Context

`AudioCapture` opens two WASAPI streams today:

1. A microphone stream via `find_microphone_device()` → `get_default_wasapi_device(d_in=True)`.
2. A loopback stream via `find_loopback_device()` → `get_default_wasapi_loopback()`.

Both streams feed into a stereo int16 FLAC at 48 kHz, with channel layout `[mic_sample, loopback_sample]` per frame. `_SourceStream` (one per kind) owns resampling, reconnect logic, and a private buffer. `_combine_frames` drains both buffers at interleave time, pads any short buffer with zeros, and hands the result to the FLAC encoder.

The architectural problem is in the loopback binding: `get_default_wasapi_loopback()` hooks whatever the Windows default *render* endpoint is at call time. Modern meeting apps (Zoho Meet, Teams, Meet) expose their own output-device picker in the call UI. When the user selects AirPods, the app routes its audio stream to the AirPods endpoint directly, bypassing the default output. The loopback attached to the default sees nothing — its `_on_audio_callback` receives no data, the loopback buffer stays empty, and `_combine_frames` pads channel 1 with zeros for the whole recording.

The `ensure_mono_for_ml` pre-processor averages channels 0 and 1 before handing audio to Parakeet. When channel 1 is zeros, mono = mic / 2. Transcription sees only the user's voice, diarization assigns all utterances to SPEAKER_00, the note records a monologue.

No existing log line surfaces which device was bound or whether the loopback buffer ever received bytes. The 2026-04-21 debugging session had to reach for per-channel `astats` in ffmpeg to confirm the diagnosis.

---

## Goals

- Capture system audio regardless of which render endpoint the meeting app routes to.
- Preserve the stereo FLAC output contract (channel 0 = mic, channel 1 = system audio).
- Leave the downstream ML pipeline unchanged (`ensure_mono_for_ml`, Parakeet, Sortformer, analyze).
- Extend the export path so recorder-side warnings surface in the note (frontmatter + body banner).
- Bound steady-state resource cost to actually-useful devices; evict obviously-dead endpoints.
- Provide enough observability that the 2026-04-21 debugging session would have been a single log glance.

## Non-goals

- Per-process (app-scoped) loopback capture. Browser-based meetings don't have a clean process boundary (tab audio runs in child renderers, attribution needs platform-specific handling per app). Defer until a real need forces it.
- Dynamically following a single "active" output. Heuristic-driven state machine, fragile across device changes, fails when two outputs legitimately have audio at once.
- Microphone input generalization. Today's failure was output-side only; generalizing the input path would double the blast radius of this change.
- Live "is audio being captured right now" indicator in the plugin. Separate product feature.
- User-configurable thresholds in `config.yaml`. Field-test the defaults first; promote to config if evidence demands.

---

## Architecture

`AudioCapture` stops holding a singular loopback and starts managing a set of them, keyed by stable device identity:

```
AudioCapture
├── _mic_source: _SourceStream                     # unchanged (default input)
├── _loopback_sources: dict[DeviceIdentity, _LoopbackEntry]   # N endpoints, dynamic membership
└── _last_membership_tick: float                    # wall-clock gate for the slower checks
```

`_LoopbackEntry` is the new policy object. It wraps a `_SourceStream` with lifecycle metadata that the recorder (not the stream) cares about:

```python
@dataclass
class _LoopbackEntry:
    stream: _SourceStream
    state: Literal["probation", "active"]
    opened_at: float                 # monotonic, for wall-clock probation expiry
    last_active_at: float | None
    device_name: str                 # cached for telemetry (not used for routing)
    missing_since: float | None      # debounce for device-disappearance
```

Key architectural choice: `_SourceStream` remains about "one audio source" — it owns buffer, resampler, identity, and reconnect state. Policy about whether the recorder wants to *keep* that stream (probation, eviction, debounce) lives on `_LoopbackEntry`. Three orthogonal concerns stay separated:

- **Health** — owned by `_SourceStream` (is this stream reachable and streaming data?).
- **Membership** — owned by `AudioCapture._tick_membership()` (does this endpoint still exist in WASAPI's enumeration?).
- **Signal usefulness** — owned by `_drain_and_mix()` (is this stream contributing audio above the RMS threshold right now?).

No new threads. Device enumeration and probation-expiry checks piggyback on the existing drain thread with a wall-clock gate. The drain thread remains the sole owner of `_loopback_sources`, eliminating cross-thread lock acrobatics.

Mic path is deliberately unchanged. `_mic_source` stays singular, default-bound, with its existing hot-plug-reconnect behavior. Generalizing input capture is a separate design problem.

---

## Stream lifecycle

### States

```
PROBATION  → opened, never produced signal above the RMS threshold yet
ACTIVE     → has produced at least one chunk with RMS above the threshold
REMOVED    → terminal; entry dropped from _loopback_sources
```

### Transitions

| From | To | Trigger |
| --- | --- | --- |
| (creation) | PROBATION | Enumeration at recording start, or hot-plug add |
| PROBATION | ACTIVE | First chunk where per-stream RMS > `_LOOPBACK_ACTIVE_RMS_DBFS` |
| PROBATION | REMOVED | Wall-clock `_LOOPBACK_PROBATION_S` elapsed with no signal seen |
| PROBATION or ACTIVE | REMOVED | Device absent from enumeration for `_LOOPBACK_DEVICE_GRACE_S` (debounced) |
| PROBATION or ACTIVE | REMOVED | `stream.is_terminal` becomes true |
| PROBATION or ACTIVE | REMOVED | Recording stops |

### Non-transitions (by design)

- **ACTIVE → PROBATION never happens.** Once an endpoint has carried signal, the recorder trusts it for the rest of the session. An ACTIVE stream that falls silent (the other party stops talking for five minutes) stays open; the RMS-thresholded active-count in the mix math naturally excludes it from this chunk's mix without eviction.
- **Silence alone never evicts.** A stream being silent for a long time is normal meeting behavior, not a fault.

### Transition firing points

- `PROBATION → ACTIVE`: inside `_drain_and_mix`, the moment per-stream chunk RMS crosses the threshold. Single info line: `loopback %s promoted to ACTIVE (elapsed=%.1fs)`.
- Probation expiry, device-gone debounce, and `is_terminal` pickup: inside `_tick_membership`, the slower-cadence helper running on the drain thread.

### Terminal failure surface

`_SourceStream` gains a single read-only public property:

```python
@property
def is_terminal(self) -> bool:
    """True when the source has exhausted its reconnect budget and should
    not be kept alive. Never flips back to False once set."""
```

`_SourceStream` flips this when its existing reconnect loop gives up (a small addition: a retry counter with a hard cap). `_LoopbackEntry` never peeks at `_state`, `_reconnect_attempts`, or any other private state — `is_terminal` is the only coupling. This keeps the three concerns (health / membership / signal) cleanly separated.

---

## Mix math

Replaces `_combine_frames` with `_drain_and_mix`. Runs once per drain tick; produces one `mic_samples` array (channel 0), one `system_mix` array (channel 1), and one `mono_chunk_bytes` for the streaming-consumer callback.

### Per-chunk algorithm

```python
# Mic path — unchanged.
mic_data = drain(self._mic_buffer, bytes_needed)
mic_samples = numpy.frombuffer(mic_data, dtype=int16)[:chunk_frames]

# Loopback path: per-stream drain, RMS gate on unpadded samples, int32 accumulate.
system_sum_i32 = numpy.zeros(chunk_frames, dtype=int32)
active_count = 0

for key, entry in self._loopback_sources.items():
    stream_bytes = entry.stream.drain_resampled(bytes_needed)

    # CRITICAL: measure RMS before padding. A short buffer that gets zero-padded
    # produces a depressed RMS that can misclassify a legitimately active stream
    # as inactive. Measure on the real samples only.
    real_samples = numpy.frombuffer(stream_bytes, dtype=int16)
    if len(real_samples) > 0:
        rms_linear = numpy.sqrt(numpy.mean(real_samples.astype(float64) ** 2))
    else:
        rms_linear = 0.0

    # Pad for alignment after measuring.
    if len(stream_bytes) < bytes_needed:
        stream_bytes += b"\x00" * (bytes_needed - len(stream_bytes))
    stream_samples = numpy.frombuffer(stream_bytes, dtype=int16)[:chunk_frames]

    if rms_linear > _LOOPBACK_ACTIVE_RMS_LINEAR:
        system_sum_i32 += stream_samples.astype(int32)
        active_count += 1

        if entry.state == "probation":
            entry.state = "active"
            entry.last_active_at = monotonic()
            logger.info("loopback %s promoted to ACTIVE (elapsed=%.1fs)",
                        entry.device_name, monotonic() - entry.opened_at)
        else:
            entry.last_active_at = monotonic()

# Narrow to int16 with saturation (safety net — divide-by-count makes clipping unlikely).
if active_count > 0:
    system_mix_i32 = system_sum_i32 // active_count
    system_mix = numpy.clip(system_mix_i32, -32768, 32767).astype(int16)
else:
    system_mix = numpy.zeros(chunk_frames, dtype=int16)

# Mono for streaming consumers — same (mic + system) / 2 contract as today.
mono_i32 = (mic_samples.astype(int32) + system_mix.astype(int32)) // 2
mono_chunk_bytes = numpy.clip(mono_i32, -32768, 32767).astype(int16).tobytes()
```

### Threshold

`_LOOPBACK_ACTIVE_RMS_DBFS = -40.0` → `_LOOPBACK_ACTIVE_RMS_LINEAR = 10 ** (-40/20) * 32768 ≈ 327.68` (int16 amplitude units, computed once at module load).

Rationale:

- Typical WASAPI driver/electrical noise on an idle loopback endpoint sits at −70 to −80 dBFS → safely rejected.
- Conversational speech sits at −20 to −15 dBFS → comfortably promoted.
- Quiet speech from a distant speaker on a compressing codec sits around −30 to −35 dBFS → still promoted with margin.
- False negatives (missing quiet real speech, wrongly evicting a legitimate device during probation) are much worse for transcription quality than false positives (briefly including a noise-only stream in the divide-by-count). Err toward inclusion.

The threshold is a **mix-normalization and promotion** signal only. "Below threshold" means "does not contribute to this chunk's active-count," never "broken" or "candidate for removal." Health remains `_SourceStream`'s concern, membership remains `_tick_membership`'s.

### Periodic telemetry

Every ~5 seconds the drain loop emits a DEBUG line gated behind `RECAP_AUDIO_DEBUG=1`:

```
loopback_sources: [AirPods(ACTIVE, -25 dB, contributing=True),
                   Speakers(PROBATION, -inf dB, contributing=False),
                   HDMI(PROBATION, -inf dB, contributing=False)]
```

State + latest-chunk RMS + this-chunk contributing flag per stream, in one line. This is the observability the 2026-04-21 debugging session was missing.

---

## Membership watcher

`_tick_membership(now)` runs from inside the drain loop with a wall-clock gate:

```python
if now - self._last_membership_tick > _LOOPBACK_MEMBERSHIP_TICK_S:
    self._tick_membership(now)
    self._last_membership_tick = now
```

`_LOOPBACK_MEMBERSHIP_TICK_S = 3.0`. Drain iterations themselves continue at their native fast cadence; only the slower membership work gates on wall-clock.

### What the tick does

1. **Enumerate current WASAPI render endpoints** via PyAudioWPatch's loopback-device generator. Each enumerated endpoint gets a stable key: native endpoint ID/GUID when present, else `(name, hostApi, maxInputChannels)`. Same identity tuple that `_SourceStream._compute_identity` already builds — the existing hot-plug-index-reshuffle protection carries through unchanged.

2. **Diff against current `_loopback_sources` keys:**
   - `adds` (enumerated but not current) → open a new `_SourceStream` with `kind="loopback"` bound to that specific endpoint (explicit `bind_to` contract — see below), wrap in `_LoopbackEntry(state=PROBATION, opened_at=now, device_name=info["name"])`, insert. One info line per open: `loopback opened: %s (identity=%s, native_rate=%d)`.
   - `adds` is a set difference, so duplicate keys cannot appear.

3. **Debounced disappearance check** (Section refinement — immediate eviction was too brittle for Bluetooth):
   - For each key in `current_keys` that is absent from the enumeration:
     - If `entry.missing_since is None`: set `entry.missing_since = now`. Do NOT evict.
     - Else if `now - entry.missing_since > _LOOPBACK_DEVICE_GRACE_S`: stop the stream, drop from dict, emit info line `loopback removed: %s (device disappeared)`.
   - For each key that was missing last tick but is present now: clear `entry.missing_since = None`.

4. **Check `is_terminal` on every entry's stream.** If true, stop and drop with a warning-level log line (terminal failures are not expected steady-state).

5. **Probation expiry check.** For each PROBATION entry where `now - entry.opened_at > _LOOPBACK_PROBATION_S`: stop the stream, drop from dict, emit one info line — `dropping unused loopback endpoint %s after %.0fs without signal`. This is expected behavior, not a fault.

6. **Emit the debug telemetry line** (DEBUG level, gated behind `RECAP_AUDIO_DEBUG=1`).

### Initial population at `start()`

Call `_tick_membership(monotonic())` once before entering the drain loop. Reuses the same add path as hot-plug, so there's only one enumeration code path under test. If enumeration returns zero render endpoints (machine has no enabled output devices — extremely unusual), recording proceeds with mic-only and a `no-system-audio-captured` warning is queued (see Failure modes).

### Explicit per-endpoint binding contract on `_SourceStream`

The existing `_SourceStream(kind="loopback")` is default-following — on open and on reopen, it calls `get_default_wasapi_loopback()`. That behavior is incompatible with multi-output capture: a reconnect would silently collapse two different endpoint streams into both following the default. The design requires loopback streams to be bound to a **specific** endpoint for their entire lifetime.

Contract change:

```python
class _SourceStream:
    def __init__(self, *, kind: str, output_rate: int,
                 bind_to: DeviceIdentity | None = None) -> None:
        ...
```

- When `kind == "loopback"` and `bind_to is not None`: open and reopen target that specific endpoint identity. If the identity is no longer in WASAPI's enumeration, mark `is_terminal` and stop trying.
- When `kind == "loopback"` and `bind_to is None`: preserve today's default-following behavior for any other caller. In practice `AudioCapture` is the only caller and will always pass `bind_to`.
- `kind == "mic"` is unchanged.

### Enumeration failure handling

If the WASAPI enumeration call itself raises (transient error, driver hiccup), the tick catches, logs one debug line (`_tick_membership: enumeration failed, skipping this tick`), and returns without changing any stream state. Next tick retries in 3 seconds. A missed enumeration is not a signal to tear anything down.

### Resource cost

Each `_SourceStream` owns a PyAudio stream + callback thread, a soxr resampler, two byte buffers. Call it ~5–10 MB + 1 thread per stream. Typical Windows machines have 2–4 render endpoints (speakers, headphones, HDMI, Bluetooth when connected). Peak cost bounded at ~50 MB + ~4 threads in the pathological case. No artificial cap.

---

## Failure modes and user-visible state

Three distinct scenarios, each with its own warning code, journal event, and note rendering. The coverage criterion is **ACTIVE-based**, not dict-emptiness — a `_loopback_sources` dict containing only PROBATION entries is effectively no coverage.

### Scenario A — Zero loopback endpoints at recording start

Pathological case (machine has no enabled render devices at all). Warning code `no-system-audio-captured`.

- Journal event (level: warning): `audio_capture_no_loopback_at_start`.
- Sidecar write at recording start: `audio_warnings.append("no-system-audio-captured")`.
- Recording proceeds mic-only.

### Scenario B — No endpoint ever became ACTIVE within its probation window

The 2026-04-21 case. Enumeration succeeded (laptop speakers, HDMI, etc. were present), streams opened, but none ever produced signal above threshold — because the meeting app was routed to a non-enumerated endpoint like AirPods, or the AirPods endpoint was present but the meeting produced no audible activity during probation. Warning code `no-system-audio-captured`.

- Journal event fired once, the moment the last PROBATION expiry leaves `_loopback_sources` with zero currently-ACTIVE entries AND no entry has ever been ACTIVE: `audio_capture_no_system_audio`. Details include enumerated device names seen.
- Sidecar write: `audio_warnings` gets `no-system-audio-captured` (no duplicates); `system_audio_devices_seen` gets the union of device names enumerated during the recording.
- Recording proceeds mic-only. Hot-plug of a new device during the remainder is still processed normally (PROBATION → ACTIVE possible).

### Scenario C — All ACTIVE streams become REMOVED mid-recording

Rare: all previously-working loopbacks disappeared (simultaneous Bluetooth drop, unplug, driver crash). Warning code `system-audio-interrupted`.

- Triggered when the count of ACTIVE entries transitions from non-zero to zero, and at least one entry has ever been ACTIVE.
- Journal event: `audio_capture_all_loopbacks_lost`.
- Sidecar write: `audio_warnings.append("system-audio-interrupted")` (single code regardless of how many interruptions occur in one session).
- Recording proceeds mic-only. Membership watcher keeps ticking; if a device comes back, it enters PROBATION and can be promoted to ACTIVE normally. The `system-audio-interrupted` warning persists on the note — the user still needs to know audio was lost for part of the recording.

### Per-stream churn stays quiet

One device going PROBATION → REMOVED while others are ACTIVE is expected steady-state behavior (Bluetooth sleeps, USB unplugs). Per-stream events stay at info/debug level. Only *total loss of coverage* warrants a user-visible warning.

### Sidecar persistence contract

`RecordingMetadata` (in `recap/artifacts.py`) gets two new optional fields:

```python
audio_warnings: list[str] = field(default_factory=list)
system_audio_devices_seen: list[str] = field(default_factory=list)
```

The recorder writes these into the sidecar JSON via `write_recording_metadata()` as warnings occur. Pipeline export reads them. Fields are optional and default to empty — existing sidecars without them deserialize cleanly.

### Note rendering

`vault.build_canonical_frontmatter` adds a conditional `audio-warnings:` key (only when the list is non-empty):

```yaml
audio-warnings:
  - no-system-audio-captured
```

`vault.upsert_note` appends (or merges into existing content below the marker) a body callout:

```markdown
> [!warning] System audio was not captured during this recording.
> Only the microphone channel has speech. If you expected other
> participants' voices, verify the meeting app's output device is
> one that was active on this machine.
> Active outputs seen during recording: Laptop Speakers, HDMI Audio.
```

Banner text differs by code:

- `no-system-audio-captured`: "System audio was not captured..." (as above).
- `system-audio-interrupted`: "System audio dropped out during this recording. Some portions of the transcript may be one-sided. Active outputs seen during recording: ..."

Wording is careful — "no system audio observed" rather than "capture failed." True silence and misrouting are indistinguishable at the waveform level; the banner must not falsely accuse the recorder when the other party simply didn't speak.

### Explicitly not in this scope

- **No abort-on-failure.** A monologue mic-only recording is better than a lost recording. Mic is always kept.
- **No real-time UI indicator.** Separate product feature.
- **No per-stream eviction warnings** except at debug level.

### Plumbing

All three journal events flow through the existing `EventJournal` and the existing WS `journal_entry` channel. Plugin code is unchanged — the notification history renderer is generic. The body banner is rendered natively by Obsidian's `> [!warning]` callout syntax.

---

## Testing strategy

Three tiers: fast unit tests against mocked streams (the bulk of coverage), small integration tests through the existing `_test_feed_mock_frames` path (extended for multi-stream), and a manual validation checklist for real hardware.

### Tier 1: unit tests (no PyAudio, no threads)

**`tests/test_audio_multi_loopback_mix.py`** — exercises `_drain_and_mix` in isolation.

- Single active stream at normal level → output channel-1 equals that stream's samples (no halving).
- Two active streams at equal level → output equals their average.
- One active + one silent-below-threshold → output equals the active stream (silent excluded from active_count).
- All streams below threshold → channel-1 is exact zeros, no divide-by-zero.
- Stream returns a short buffer → RMS measured on unpadded samples; padding-zeros afterward does not depress the activity decision. (Regression test.)
- Loud simultaneous peaks in two streams → saturation clip engages; no int16 overflow wraparound.
- Per-stream RMS above threshold updates `last_active_at` and flips state to ACTIVE; below-threshold chunk leaves state alone.

**`tests/test_audio_loopback_lifecycle.py`** — exercises `_LoopbackEntry` state machine and `_tick_membership()` with a fake enumerator and fake `monotonic()`.

- PROBATION → ACTIVE on first signal, not before.
- Probation expiry: wall-clock exceeds `_LOOPBACK_PROBATION_S` with no signal → REMOVED, single info log line (caplog assertion).
- ACTIVE is sticky: arbitrary silence after promotion does not revert to PROBATION and does not evict.
- Single missed enumeration does NOT evict — `missing_since` is set, cleared on next tick's presence.
- Two consecutive misses past `_LOOPBACK_DEVICE_GRACE_S` → REMOVED.
- Hot-plug add during recording: new endpoint appears → new PROBATION entry.
- `stream.is_terminal == True` → entry evicted regardless of state.
- Enumeration failure (raises) → tick skipped, no stream changes, single debug log line.

**`tests/test_audio_warning_persistence.py`** — sidecar contract.

- Scenario B trigger writes `no-system-audio-captured` into `RecordingMetadata.audio_warnings` and lists enumerated device names in `system_audio_devices_seen`.
- Scenario C trigger (ACTIVE count transitions to zero after having been non-zero) writes `system-audio-interrupted`.
- Multiple interruptions during a recording don't duplicate the `system-audio-interrupted` code.
- Warnings survive an atomic sidecar write/read roundtrip through `write_recording_metadata` / `load_recording_metadata`.

**`tests/test_pipeline_audio_warnings.py`** — note export.

- Frontmatter includes `audio-warnings: [no-system-audio-captured]` when the sidecar has it.
- Body includes the `> [!warning]` banner with the correct text per code.
- Sidecar with no warnings → no frontmatter field, no banner (existing behavior preserved).
- **Upsert case:** merging pipeline output carrying warnings into an existing note (created by calendar sync) preserves the new frontmatter key and inserts the body banner under the marker correctly.

### Tier 2: integration tests — multi-stream end-to-end through drain

Extend the existing `_test_feed_mock_frames(mic_frame, system_frame)` with a sibling `_test_feed_mock_frames_multi(mic_frame, loopback_frames_by_key)`. Exercises the full drain → RMS → state transition → mix → interleave → FLAC-encode path with mocked per-stream buffers. No PyAudio, no threads.

**AirPods scenario end-to-end test.** Three loopback streams — "Laptop Speakers," "HDMI," "AirPods" — all opened. Feed zero bytes to Speakers and HDMI, feed speech to AirPods. Assertions: AirPods promotes to ACTIVE after first chunk; Speakers and HDMI stay PROBATION; after `_LOOPBACK_PROBATION_S` simulated wall-clock Speakers and HDMI evict; channel-1 of the encoded FLAC matches AirPods content exactly across the whole session. This is the regression test for today's failure mode.

**End-to-end seam test across the sidecar → pipeline → note chain.** `tests/test_audio_warning_e2e.py`: write a real sidecar JSON with `audio_warnings` and `system_audio_devices_seen` populated, drive the pipeline export path with fixture inputs, assert the final note on disk has the expected frontmatter key and body callout with the correct wording per code. Validates the warning survives the full recorder-sidecar → pipeline-input → note-write chain, not just each component in isolation.

### Tier 3: manual validation on real hardware

Checklist the user runs after implementation lands. Not automatable.

1. **Baseline.** Join a Zoho meeting with laptop speakers as default output, don't change routing. Verify both voices appear in the transcript and no `audio-warnings` frontmatter.
2. **AirPods routing — the reported bug.** Join a Zoho meeting, switch output to AirPods via Zoho's in-call device picker. Verify both voices appear in the transcript and no `audio-warnings` frontmatter.
3. **Bluetooth disconnect mid-call.** Start recording with AirPods, disconnect AirPods mid-call, wait 10s past the grace period, reconnect. Verify: transcript has speech from before disconnect, is mic-only during the gap, speech resumes after reconnect. `system-audio-interrupted` warning appears on the note.
4. **Warning wording / UX — not a capture-failure test.** Join a meeting where the other party is muted the entire time. True silence and misrouting are waveform-indistinguishable, so this case is a **UX validation** of the `no-system-audio-captured` banner: the wording should read as "no system audio was observed" rather than as an accusation that the recorder broke. Read the banner as the user would.
5. **Hot-plug add.** Start recording with default speakers, plug in a USB headset mid-call, switch the meeting app to the USB headset, continue. Verify the USB headset's audio is captured in the post-switch portion.
6. **Log hygiene under `RECAP_AUDIO_DEBUG=1`.** Verify the debug line appears at the expected cadence with state + RMS + contributing flag per stream.

---

## Migration and what stays unchanged

### FLAC output contract — unchanged

Every byte of the FLAC still conforms to today's spec: stereo int16 at 48 kHz, channel 0 = mic, channel 1 = system audio, sample-interleaved `[mic0, sys0, mic1, sys1, ...]`. The only semantic shift is *how* channel 1 was constructed — today it's a single loopback's raw samples, tomorrow it's the RMS-gated divide-by-active-count mix of N loopbacks. Readers (ffmpeg, the pipeline, ad-hoc ffprobe, any future consumer) see the same format. Existing recordings on disk remain fully replayable without any migration.

### ML pipeline stages — unchanged

`audio_convert.ensure_mono_for_ml` averages channels 0 and 1 into the `.mono.wav` that Parakeet and Sortformer consume. Chunked Parakeet transcribe (feat/parakeet-chunking, landed 2026-04-20), diarize, analyze — all unchanged. No pipeline work for this change to land.

### Note export — extended

`vault.build_canonical_frontmatter` and `vault.upsert_note` learn about the two new `RecordingMetadata` fields. When `audio_warnings` is non-empty, frontmatter gets the `audio-warnings:` key and the body gets the appropriate `> [!warning]` callout. When empty, both are absent — existing behavior preserved. Frontmatter merging follows the same "pipeline is authoritative for pipeline-owned keys" rule as other fields.

### `RecordingMetadata` schema — backward-compatible extension

```python
# Additions to RecordingMetadata in recap/artifacts.py:
audio_warnings: list[str] = field(default_factory=list)
system_audio_devices_seen: list[str] = field(default_factory=list)
```

Both fields are optional with `default_factory=list`. Existing sidecars without them deserialize with empty defaults — no on-disk migration needed. Fields appear in frontmatter only when non-empty.

### `_SourceStream` — two additive changes, no removals

- New `bind_to: DeviceIdentity | None = None` constructor parameter. For `kind="loopback"`, when provided, open and reopen target that specific endpoint instead of the default. Default value preserves today's behavior for any other caller.
- New `is_terminal: bool` read-only property exposing reconnect-budget-exhaustion.

### `AudioCapture` — internal restructuring, public interface preserved

Private field rename: `_loopback_source: _SourceStream | None` → `_loopback_sources: dict[DeviceIdentity, _LoopbackEntry]`. The single shared `_loopback_buffer: bytes` goes away — each `_SourceStream` owns its own buffer, exposed via the new `drain_resampled()` method. `_loopback_callback` becomes per-stream and lives on the stream itself. Public interface (`start`, `stop`, `output_path`, `sample_rate`, `is_recording`, `current_rms`, `on_chunk`) — unchanged.

### `find_loopback_device()` — retained

Kept as a public utility. The multi-output recorder uses a separate internal enumerator. `find_loopback_device()` remains available for default-loopback diagnostics or health-check use (no current in-tree consumer depends on it beyond the recorder, which is moving off it).

Note: `startup._check_audio_devices` only verifies PyAudio can enumerate *any* devices (`get_device_count() > 0`); it does not depend on the default loopback being present. No change needed there.

### Daemon config — no new keys

The four tunables stay as module-level constants in `recap/daemon/recorder/audio.py`:

| Constant | Default | Purpose |
| --- | --- | --- |
| `_LOOPBACK_PROBATION_S` | `60.0` | Wall-clock budget for a new endpoint to produce signal before eviction |
| `_LOOPBACK_ACTIVE_RMS_DBFS` | `-40.0` | RMS threshold (dBFS) for "signal-bearing" determination |
| `_LOOPBACK_MEMBERSHIP_TICK_S` | `3.0` | How often `_tick_membership` runs its slower checks |
| `_LOOPBACK_DEVICE_GRACE_S` | `6.0` | Debounce window for device-disappearance before eviction |

Promote to YAML only if field testing demonstrates per-user tuning is needed.

### Plugin — no code changes

The three new journal event types flow through the existing `EventJournal` and the existing WS `journal_entry` channel. Plugin notification history renders them without any view or code changes — the renderer is generic. Body banner is rendered natively by Obsidian's `> [!warning]` callout syntax.

### Upgrade path

Zero user action. User updates the daemon, restarts via the Restart button (daemon-restart handshake landed earlier 2026-04-21), next meeting benefits from multi-output capture. Old recordings replay through the pipeline the same way. A user who recorded a meeting on the old daemon with the wrong routing still gets a monologue; their next recording on the new daemon gets proper coverage.

---

## Summary of changes by file

| File | Change kind | Summary |
| --- | --- | --- |
| `recap/daemon/recorder/audio.py` | Restructure | New `_LoopbackEntry`, multi-stream `_loopback_sources` dict, `_drain_and_mix`, `_tick_membership`, per-endpoint `bind_to` contract on `_SourceStream`, `is_terminal` property, `drain_resampled` method |
| `recap/artifacts.py` | Additive schema | `RecordingMetadata.audio_warnings`, `system_audio_devices_seen` |
| `recap/vault.py` | Additive | `build_canonical_frontmatter` learns `audio-warnings:` key; `upsert_note` learns `> [!warning]` body callout rendering |
| `recap/pipeline/__init__.py` | Thread-through | Pass `audio_warnings` / `system_audio_devices_seen` from sidecar into export path |
| `recap/daemon/eventjournal.py` or equivalent | Additive | Three new event types: `audio_capture_no_loopback_at_start`, `audio_capture_no_system_audio`, `audio_capture_all_loopbacks_lost` |
| `tests/test_audio_multi_loopback_mix.py` | New | Unit tests for `_drain_and_mix` |
| `tests/test_audio_loopback_lifecycle.py` | New | Unit tests for `_LoopbackEntry` state machine and `_tick_membership` |
| `tests/test_audio_warning_persistence.py` | New | Sidecar persistence tests |
| `tests/test_pipeline_audio_warnings.py` | New | Note-export rendering tests, including upsert path |
| `tests/test_audio_warning_e2e.py` | New | Cross-seam end-to-end test |

No plugin code changes. No pipeline ML-stage changes. No config schema changes.

---

## Appendix A — Alternatives considered and rejected

### A.1 Per-process (app-scoped) loopback

Using Windows' `PROCESS_LOOPBACK` API (Windows 10 2004+) to capture audio from the meeting app's process directly, regardless of output routing. Surgical — no cross-app contamination — but browser-based meetings (Zoho, Meet) run their audio in child renderer processes, not the main browser process. Identifying "the meeting renderer" requires per-app handling, tab-to-process mapping, and platform-specific edge cases. Rejected as scope-creep against a concrete, well-understood bug.

### A.2 Dynamically follow the "active" output

Detect which output endpoint currently has signal and swap loopback binding at runtime. Single-stream architecture, follows routing. But: heuristic around "active" is load-bearing, fragile on device changes, loses audio during swaps, and handles the two-simultaneous-outputs case poorly. Rejected for complexity-per-value.

### A.3 Alternative mix strategies

- **Fixed divide-by-N** where N = total enumerated endpoints: simpler than active-count, but every idle endpoint costs 6 dB of level on active streams (-14 dB penalty for a machine with 5 outputs and only AirPods carrying signal). Enough to hurt ASR. Rejected.
- **Soft peak limiter**: preserves dynamic range perfectly in multi-source edge cases, but introduces DSP state and tuning. Overkill for speech ASR where Parakeet tolerates a lot. Rejected for over-engineering.

### A.4 COM `IMMNotificationClient` for device change detection

Responds immediately to plug/unplug instead of polling every 3 seconds. Rejected because polling latency is not the bottleneck in a meeting-length recording, and COM threading introduces cross-thread-lock complexity that the drain-thread-owns-everything model deliberately avoids.

### A.5 Re-evicting ACTIVE streams after prolonged silence

Alternative lifecycle option C: an ACTIVE stream that stays silent for Q seconds returns to PROBATION and eventually evicts. Tuning Q is load-bearing and the failure mode is real — a speaker who goes silent for 10 minutes isn't gone, they're just listening. Rejected because "silent for a while" is normal meeting behavior; "should be dropped" is not.

---

## Appendix B — Answered design questions

| Q | Resolution |
| --- | --- |
| Q1: Scope of "all audio output" | Capture and mix all active render endpoints, with dynamic add/remove during recording |
| Q2: Mix math | int32 sum, RMS-thresholded active count, divide by count, narrow with saturation |
| Q3: Stream lifecycle | PROBATION on open, ACTIVE on first real signal, REMOVED only on device-gone / terminal failure / stop. ACTIVE is sticky; no silence-based eviction |
| Section 1 refinement | Minimum-surface change: mic stays singular, `_SourceStream` remains the primitive, complexity isolated to loopback membership + mixing |
| Section 2 refinement | Probation state lives on `_LoopbackEntry`, not `_SourceStream`; membership/health/signal-usefulness kept separate |
| Section 3 refinement | RMS measured on unpadded samples (measure before pad); threshold is mix-normalization signal only, not a health signal |
| Section 4 refinement | Explicit `_SourceStream.bind_to` contract (loopbacks no longer follow default); debounced device disappearance |
| Section 5 refinement | Persist warnings in sidecar (not just journal); trigger on ACTIVE coverage (not dict-emptiness); distinct codes for "never captured" vs "captured then lost" |
| Section 6 refinement | End-to-end seam test from sidecar to note; Scenario 4 is warning-wording UX validation, not capture-failure proof; upsert path in note export tests |
| Section 7 refinement | Export path is extended (not unchanged); `find_loopback_device()` health-check mention softened (startup does not depend on it) |

# Phase 7 — ML Stack Refresh + Detection/Popup Reliability (Design)

**Status:** approved design; ready for implementation plan
**Parent:** `docs/plans/2026-04-14-fix-everything-design.md` (Final Integration Pass section)
**Companion:** `docs/plans/2026-04-16-phase7-ml-stack-refresh.md` (initial phase rationale, captured before detailed design)
**Discovered via:** 2026-04-16 manual Final Integration Pass walkthrough on real hardware
**Design method:** brainstorming skill with external review at every section (every sub-decision reviewed by Codex against the live codebase before moving on)

---

## §1 — Problem, scope, and principles

### §1.1 — Observed problem

On 2026-04-16 the `obsidian-pivot` branch claimed all automated gates green: 573 pytests passing, 71.43% coverage, all 8 Review Blockers from the parent design verified, clean `obsidian-recap` build. When the daemon was actually started against a real vault for the first time (via `uv run python -m recap.daemon config.yaml` after `uv sync --extra dev --extra daemon --extra ml`), startup cascaded through five distinct failures:

1. `parakeet_stream.load_model` — `AttributeError`. parakeet-stream 0.6.0 rewrote its API from free functions to classes; `load_model` no longer exists.
2. `pyflac.StreamEncoder(..., channels=...)` — `TypeError`. pyflac 3.0 dropped the `channels` kwarg; channels are inferred from the data passed via `.process()`.
3. `pyarrow.PyExtensionType` — `AttributeError` via NeMo's transitive dependency on `datasets 2.14.4`. pyarrow 21+ removed the symbol; `datasets` fixed its usage in 2.15+.
4. Meeting detection fired on idle Teams Desktop (Chat tab) within 500 ms of startup. Regex `.+\|.*Microsoft Teams` matches every modern Teams tab title.
5. Signal popup crash — `Tcl_AsyncDelete: async handler deleted by the wrong thread` — because `loop.run_in_executor(None, _blocking_dialog, ...)` doesn't guarantee thread-affinity for tkinter Variable finalization.

### §1.2 — Root cause of the test-suite blind spot

Every failure above is in a code path the pytest suite does not exercise, because every ML/system library boundary is mocked:

- `recap.pipeline.transcribe.transcribe` mocked in pipeline tests
- `recap.analyze.subprocess.run` mocked in analyze tests
- `recap.daemon.streaming.transcriber._load_model` mocked in streaming tests
- `pyflac.StreamEncoder` not exercised (AudioCapture tests use mocks)
- tkinter not exercised (popup tests mock the blocking dialog)

Library APIs can drift underneath mocks and CI stays green. The 573/71.43%/blocker-pass baseline is meaningful for plumbing correctness but tells us nothing about whether the libraries underneath the plumbing still have the APIs we call. Phase 7 closes that gap.

### §1.3 — Scope (Medium)

Four deliverables:

1. Reconcile three drifted libraries with the current code:
   - `parakeet-stream 0.6` — remove the dependency entirely; live streaming transcription deferred to Phase 8.
   - `pyflac 3.0` — remove the `channels` kwarg from the encoder call.
   - `pyarrow ≥ 21` via `datasets 2.14` — pin `datasets>=2.16,<3` (fallback: `pyarrow<21`).
2. Refactor meeting detection from "window-title regex alone" to "window-title regex + UIA call-state confirmation" for Teams and Zoom. Signal stays regex-only; safety comes from §4's popup fix.
3. Fix the tkinter popup's threading crash and the detection recursion where the popup window self-matches the Signal regex.
4. Add an integration test tier that loads real libraries and exercises the call shapes. Gated via `@pytest.mark.integration`; excluded from default `pytest -q`; split into CPU-safe contract smoke (any Windows dev box with the `daemon` and `ml` extras) and GPU-required model tests (requires CUDA).

Phase framing: **Phase 7 fixes batch ML + daemon reliability. Live streaming transcript is deferred to Phase 8 due to discovered API mismatch between parakeet-stream 0.6's audio-source-owned paradigm and our bytes-in recorder architecture.**

### §1.4 — Out of scope

- Replacing parakeet-stream with direct NeMo calls for live streaming (Phase 8).
- True call-state detection APIs (Teams Graph Presence, Zoom SDK, Windows accessibility-based call-active heuristics). Window-title + UIA is the ceiling given the external gates (personal Teams API-limited, no Zoom SDK account, Signal has no API).
- Replacing tkinter with Qt/plyer/Obsidian-modal UI (Phase 8).
- NeMo major-version upgrade (2.5 → 2.x latest).
- Packaging/installer work (Phase 9 already designed).
- CI integration of the `-m integration` tier (no GPU runner configured; runs locally only).
- Performance optimization of UIA walks beyond the "add LRU cache if polls exceed 500 ms" contingency in §3.4.

### §1.5 — Design principles

- **TDD throughout.** Every fix starts as a failing test. This is the discipline that was missing; Phase 7's output should be a suite that would have caught these bugs.
- **One boundary per commit.** Library fixes commit independently so each can be reverted if a downstream issue surfaces.
- **Accept the external gates.** We don't spend time attacking ceilings imposed by third-party APIs we can't access.
- **Preserve the Medium scope line.** If a sub-problem balloons beyond its estimate, flag it as a Phase 8 candidate rather than expanding Phase 7.
- **Stub, don't delete, the streaming subsystem.** Preserves the future seam where Phase 8's real implementation will slot in.
- **Honest shutdown story.** If the primary popup-close signal fails, the daemon hangs at interpreter exit and the user must force-kill. This is a genuine limitation, not a clean fallback — documented explicitly as a Phase 8 candidate.

### §1.6 — Blast radius (total Phase 7)

Five categories of change:

- **Library refresh surface:** 5 source files (`streaming/transcriber.py`, `streaming/diarizer.py`, `pipeline/transcribe.py`, `pipeline/diarize.py`, `recorder/audio.py`) + `pyproject.toml` + `uv.lock`. (Not all of these are edited: the pipeline files gain NeMo imports back once the datasets pin lands.)
- **New module:** `recap/daemon/recorder/call_state.py`.
- **Detection refactor:** `detection.py` (regex stays, adds exclusion set + `is_window_alive`), `detector.py` (stop-path split + tracked-meetings prune + poll-task seal), `enrichment.py` (re-export).
- **Popup rework:** `signal_popup.py` (executor-based lifecycle + Combobox + self-exclusion), `service.py` (executor ownership), `__main__.py` (executor plumbing), `LiveTranscriptView.ts` (UX copy for deferred live transcript).
- **Test infrastructure:** `tests/integration/` package, `tests/conftest.py` (hoisted `make_silent_flac`), updates to 7 existing test files, 1 new test file (`test_call_state.py`).

Roughly 21 files modified + 6 new files across 16 logical commits.

---

## §2 — Library refreshes

Three library bundles. Each is independent; each can fail verification without blocking the others.

### §2.1 — parakeet-stream: remove + stub (Phase 8 deferral)

**Root cause.** parakeet-stream 0.6.0 exposes `Parakeet`, `StreamingTranscriber`, `LiveTranscriber` — all of which either take a complete audio object (`Union[str, Path, ndarray, Tensor]`) or own their own `sounddevice`-based mic loop. None accepts bytes arriving in chunks from an external source. Our [recap/daemon/recorder/audio.py:157](../../recap/daemon/recorder/audio.py) already owns the audio loop (PyAudioWPatch WASAPI loopback + mic interleaved). The two architectures don't compose.

The `Recorder` class at [recap/daemon/recorder/recorder.py:260](../../recap/daemon/recorder/recorder.py) currently relies on `StreamingTranscriber.start()`, `.feed_audio(chunk, sample_rate)`, `.stop()`, `.on_segment`, and `.stop()` possibly returning `None`. The batch fallback at [recap/pipeline/__init__.py:357](../../recap/pipeline/__init__.py) already correctly uses `streaming_transcript` only when it has real speaker-labeled utterances — otherwise the pipeline routes through batch `transcribe` + `diarize`. With the stubs returning no segments, scenarios 1 + 2 work via batch automatically. **No pipeline code changes needed.**

**Actions:**

#### (a) Remove parakeet-stream from dependencies

At [pyproject.toml:29-33](../../pyproject.toml) `[project.optional-dependencies].ml` — delete `"parakeet-stream>=0.1",` line.

#### (b) `StreamingTranscriber` no-op facade

At [recap/daemon/streaming/transcriber.py:12](../../recap/daemon/streaming/transcriber.py):

- Public attributes preserved (`is_running`, `segments`, `had_errors`, `on_segment`, `get_transcript_result`). Recorder-compatible by design.
- `start()`: logs at INFO level: `"Live streaming transcription deferred; see Phase 7 plan for context."` Sets `self._had_errors = True`. Returns. Never raises.
- `feed_audio(audio_data, sample_rate=16000)`: no-op (early-return on `_had_errors`, unchanged from current guard).
- `stop()`: returns `None`.
- Drop `_load_model()` and the `import parakeet_stream` lazy import entirely.

The log message does not reference a filename (filename breadcrumbs rot; the daemon log is ephemeral anyway).

#### (c) `StreamingDiarizer` no-op facade

At [recap/daemon/streaming/diarizer.py:16](../../recap/daemon/streaming/diarizer.py) — same pattern.

#### (d) UX copy in plugin

At [obsidian-recap/src/views/LiveTranscriptView.ts:40-45](../../obsidian-recap/src/views/LiveTranscriptView.ts) — both state strings updated:

- Recording: `"⏺ Recording — transcript will appear in the meeting note after the pipeline completes."`
- Idle: `"Live transcript is not available in this version. Recorded meetings will show the full transcript in the note after the pipeline completes."`

No time promise. WebSocket listener at [main.ts:323](../../obsidian-recap/src/main.ts) stays unchanged — harmless with no `transcript_segment` events emitted.

**Test additions (discriminative against current broken implementation):**

- `test_streaming_transcriber_start_logs_deferred_message` (`tests/test_streaming_transcriber.py`) — uses `caplog` at INFO level, asserts at least one record contains the literal string `"Live streaming transcription deferred"`. Current code produces `"Failed to load streaming model..."` at WARNING — different text and level. FAILS today.
- `test_streaming_transcriber_no_load_model_method` — asserts `not hasattr(StreamingTranscriber, '_load_model')`. FAILS today.
- Same pair for diarizer at `tests/test_streaming_diarizer.py`.

**Existing tests deleted in same commits:**

- [tests/test_streaming_transcriber.py:49-53](../../tests/test_streaming_transcriber.py) — `test_start_with_failed_model_sets_error`. Uses `patch.object(transcriber, "_load_model", side_effect=Exception(...))`. Would fail with `AttributeError` once `_load_model` is removed.
- [tests/test_streaming_diarizer.py:44-48](../../tests/test_streaming_diarizer.py) — same pattern. Same fate.

Deletions land in the same commit as the stub refactor, so the suite never has a window of failing-then-missing tests.

### §2.2 — pyflac 3.0 — single-line fix

**Root cause.** pyflac 3.0 dropped the `channels` kwarg from `StreamEncoder.__init__`. Current signature:

```
StreamEncoder(sample_rate, write_callback, seek_callback=None, tell_callback=None,
              metadata_callback=None, compression_level=5, blocksize=0,
              streamable_subset=True, verify=False, limit_min_bitrate=False)
```

Channel count is inferred from the data passed via `.process()`.

**Action.** At [recap/daemon/recorder/audio.py:312-316](../../recap/daemon/recorder/audio.py) — remove `channels=self._channels,` line. Existing `_write_callback` at [audio.py:182](../../recap/daemon/recorder/audio.py) already has the 4-arg signature pyflac 3.0 expects: `(data: bytes, num_frames: int, num_samples: int, current_frame: int) -> None`.

**Test addition:** `test_audio_capture_does_not_pass_channels_to_encoder` in existing [tests/test_recorder_audio.py](../../tests/test_recorder_audio.py). Patches `pyflac.StreamEncoder` with `MagicMock`, asserts `AudioCapture.start()` call args don't include `channels=`. FAILS today.

### §2.3 — datasets/pyarrow reconciliation — mutually exclusive branches

**Root cause.** `datasets==2.14.4` (current lockfile resolution) imports `pa.PyExtensionType` at module load, which was removed in `pyarrow>=21`. `datasets>=2.15` fixes the usage — but `datasets==2.15.0` has a secondary break on `HfFolder` import from `huggingface_hub`. Versions `2.16.0` and later import cleanly against current pyarrow + huggingface_hub (verified empirically by Codex).

The `datasets` dependency is transitively required by `nemo_toolkit[asr]>=2.0`. NeMo 2.5.0's metadata has `Requires-Dist: datasets` with no version pin, so a direct `datasets` constraint is permissible.

**Preferred branch (primary target):**

At [pyproject.toml:29-33](../../pyproject.toml) `[project.optional-dependencies].ml`:

```
ml = [
    "nemo_toolkit[asr]>=2.0",
    "torch>=2.1",
    "datasets>=2.16,<3",
]
```

No `pyarrow` pin — NeMo's transitive `pyarrow` constraint applies.

**Fallback branch (only if preferred branch fails resolution):**

```
ml = [
    "nemo_toolkit[asr]>=2.0",
    "torch>=2.1",
    "pyarrow<21",
]
```

**No `datasets` pin** — NeMo's transitive `datasets` constraint applies (which resolved to 2.14.4 under current pyarrow 23.0.1). Pinning pyarrow backward lets the existing transitive datasets keep working.

**Only one of these two branches lands in the committed `pyproject.toml`.** They are mutually exclusive constraint sets, not layered.

**Decision process:**

1. Try preferred: `uv sync --extra dev --extra daemon --extra ml --dry-run`
2. If resolver returns clean → apply preferred, re-lock, verify `from nemo.collections import asr` succeeds, commit.
3. If resolver conflict → undo the `datasets` pin, apply fallback (`pyarrow<21`), re-lock, verify the same NeMo import, commit with a message naming the rejected preferred branch.

Commit message prefix:
- Preferred: `chore(deps): pin datasets>=2.16,<3 to fix pyarrow.PyExtensionType import chain`
- Fallback: `chore(deps): pin pyarrow<21 (datasets pin rejected by resolver, see log)`

**Verification gate (both branches):** `uv run python -c "from nemo.collections import asr; print('nemo ok')"` must print `nemo ok`.

**Test addition:** `test_nemo_asr_imports_cleanly` in new `tests/integration/test_contract_smoke.py` (CPU tier). RED today, GREEN after pin lands.

---

## §3 — UIA-confirmed detection refactor

Goal: stop firing on idle Teams tabs. Signal remains regex-only (no UIA checker available for Electron); its safety comes from §4's popup fix.

### §3.1 — New module: `recap/daemon/recorder/call_state.py`

Consolidates UIA-based window inspection. Used by both detection confirmation and the existing participant enrichment.

**Public surface:**

```python
def is_call_active(hwnd: int, platform: str) -> bool:
    """True if the window at hwnd is an active call for the given platform.

    Uses UI Automation to inspect platform-specific UI controls (Teams Leave
    button, Zoom toolbar). Returns True for platforms with no registered
    checker (e.g. signal) — regex match is the only signal. Returns True on
    UIA exception (fallback to regex trust, logged at debug).
    """


def has_call_state_checker(platform: str) -> bool:
    """True if this platform has a UIA checker. For tests/instrumentation."""


def extract_teams_participants(hwnd: int) -> list[str] | None:
    """Moved from enrichment.py. Signature unchanged."""
```

**Internal structure:**

```python
_CALL_STATE_CHECKERS: dict[str, Callable[[Any], bool]] = {
    "teams": _is_teams_call_active,
    "zoom": _is_zoom_call_active,
    # No "signal" entry (see §3.6 per-platform policy).
}

def _is_teams_call_active(control) -> bool:
    """Walk UIA tree for ButtonControl with Name in {Leave, Hang up, End call}."""

def _is_zoom_call_active(control) -> bool:
    """Walk UIA tree for Mute/Stop Video toolbar."""

def _walk_depth_limited(control, matcher, *, max_depth=15):
    """Depth-bounded UIA tree walk. Shared with enrichment's participant walk."""
```

### §3.2 — Privacy principle

**Teams and Zoom:** `call_state.is_call_active(hwnd, platform)` inspects controls as a detection gate. `extract_teams_participants(hwnd)` (Teams only) extracts participant names by design for recordings the user explicitly chose to record. Platform gates ensure no cross-platform content leakage.

**Signal:** no UIA call-state checker (regex-only detection). No UIA enrichment path (existing [enrichment.py:145](../../recap/daemon/recorder/enrichment.py) `if platform == "teams"` gate preserved unchanged). Content-free detection by construction — title string only, no tree walks, no message access. Signal gets the stricter treatment because (a) UIA on Electron is flaky anyway, and (b) Signal is E2E-encrypted; zero-content detection matches user expectation.

### §3.3 — `detection.py` changes

Regex patterns unchanged. `MEETING_PATTERNS` at [detection.py:16-19](../../recap/daemon/recorder/detection.py) stays as the cheap pre-filter.

**Two functions now, not one:**

```python
def detect_meeting_windows(enabled_platforms=None) -> list[MeetingWindow]:
    """Regex match + UIA confirmation. For the detector's START path."""
    windows = _enumerate_windows()
    platforms = enabled_platforms if enabled_platforms is not None else set(MEETING_PATTERNS)
    meetings = []
    for hwnd, title in windows:
        if hwnd in _EXCLUDED_HWNDS:   # §4.4 self-exclusion
            continue
        for platform in platforms:
            pattern = MEETING_PATTERNS.get(platform)
            if pattern and pattern.search(title):
                if not call_state.is_call_active(hwnd, platform):
                    continue
                meetings.append(MeetingWindow(hwnd=hwnd, title=title, platform=platform))
                break
    return meetings


def is_window_alive(hwnd: int) -> bool:
    """True if the hwnd is still enumerable/visible. For the STOP path.

    Does NOT apply regex or UIA — a recording should only stop when
    Windows itself says the window is gone. Transient UIA hiccups
    (e.g. Teams hiding Leave during screen share) must NOT tear
    down an in-progress recording.
    """
    if win32gui is None:
        return True
    try:
        return win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd)
    except Exception:
        return True


_EXCLUDED_HWNDS: set[int] = set()

def exclude_hwnd(hwnd: int) -> None:
    _EXCLUDED_HWNDS.add(hwnd)

def include_hwnd(hwnd: int) -> None:
    _EXCLUDED_HWNDS.discard(hwnd)
```

### §3.4 — `detector.py` changes

Non-trivial: two distinct mechanisms for stop-path and dedupe, plus the poll-task unwind seal.

```python
async def _poll_once(self) -> None:
    # --- Stop-monitoring path: hard signal only ---
    if self._recorder.is_recording and self._recording_hwnd is not None:
        if not is_window_alive(self._recording_hwnd):
            logger.info("Meeting window closed, stopping recording")
            await self._recorder.stop()
            self._recording_hwnd = None
            # Prune runs below at end-of-poll — no special cleanup here.

    # --- Arm timeout + armed-event handling (unchanged) ---

    # --- Detection path ---
    detected = detect_meeting_windows(self.enabled_platforms)
    detected_hwnds: set[int] = set()

    for meeting in detected:
        detected_hwnds.add(meeting.hwnd)

        if meeting.hwnd in self._tracked_meetings:
            continue  # dedupe

        if self._recorder.is_recording:
            continue  # don't start concurrent recordings; UIA flap re-triggers blocked here

        self._tracked_meetings[meeting.hwnd] = meeting
        # ... existing enrich + auto-record / prompt logic ...

    # --- End-of-poll prune with active-recording protection ---
    stale = set(self._tracked_meetings) - detected_hwnds
    if self._recording_hwnd is not None:
        stale.discard(self._recording_hwnd)  # invariant: while recording, hwnd stays tracked
    for hwnd in stale:
        del self._tracked_meetings[hwnd]
```

**Invariants:**
- **Stop path** (`is_window_alive`): hard Windows signal only. Never stops on UIA flap. If a call ends but the Teams app window stays open, the existing silence-timeout mechanism at [silence.py](../../recap/daemon/recorder/silence.py) with `silence-timeout-minutes: 5` handles the soft-stop path.
- **Dedupe refresh** (`end-of-poll prune`): runs against the confirmed-detected set every poll. When UIA drops an hwnd (call ends), prune removes it from tracked, next call in the same hwnd re-triggers normally.
- **Active recording protection**: `_recording_hwnd` is excluded from prune while recording. UIA flap during a call cannot cause the detector to "forget" the active call and re-trigger after the recording stops.

**Stop() hardening** — await the cancelled poll task before draining signal callbacks:

```python
async def stop(self) -> None:
    """Cancel the polling task and drain any pending signal callbacks.

    Order matters: the poll task MUST finish unwinding before we drain
    signal-callback tasks, otherwise the poll task's current synchronous
    chunk can spawn a new callback after the drain snapshot, leaving a
    zombie submission that either runs past shutdown or collides with
    a just-closed popup executor.
    """
    if self._poll_task is not None:
        self._poll_task.cancel()
        try:
            await self._poll_task  # wait for unwind
        except asyncio.CancelledError:
            pass
        self._poll_task = None

    # Now no more _poll_once iterations; _pending_signal_tasks won't grow.
    if self._pending_signal_tasks:
        for task in list(self._pending_signal_tasks):
            task.cancel()
        await asyncio.gather(
            *self._pending_signal_tasks, return_exceptions=True,
        )
        self._pending_signal_tasks.clear()
```

Single change from today's code: insert `try: await self._poll_task / except CancelledError: pass` between `cancel()` and the drain loop.

### §3.5 — `enrichment.py` refactor

At [enrichment.py:62-91](../../recap/daemon/recorder/enrichment.py), `extract_teams_participants` currently lives in `enrichment.py` and uses an inline tree walk. Move the body to `call_state.py`; replace with a re-export:

```python
# enrichment.py
from recap.daemon.recorder.call_state import extract_teams_participants

__all__ = [..., "extract_teams_participants"]
```

Callers of `enrich_meeting_metadata` and `extract_teams_participants` keep importing from `enrichment.py` — no caller churn. Internally, UIA logic lives in `call_state.py` and shares `_walk_depth_limited` with the call-state checkers.

### §3.6 — Per-platform policy

| Platform | Regex | UIA checker | What §3 fixes | What's left for §4 |
|---|---|---|---|---|
| teams | unchanged | `_is_teams_call_active` | Fixes chat/activity tab false-positives | — |
| zoom | unchanged | `_is_zoom_call_active` | Tightens confirmation | — |
| signal | unchanged | **none** | NOT fixed by §3 alone. Regex still matches Signal main window AND our own popup window. | §4 fixes: (a) tkinter threading crash, (b) explicit exclusion of our own popup hwnd from detection |

**Honest framing:**
- After §3: Teams no longer records idle tabs. Signal still produces false-positive popups (but the popup no longer crashes — §4).
- After §4: Signal popup is stable AND doesn't re-trigger detection against itself.

### §3.7 — Test strategy

**New file `tests/test_call_state.py`:**
- `test_is_call_active_returns_true_when_leave_button_present`
- `test_is_call_active_returns_false_when_no_call_controls`
- `test_is_call_active_returns_true_for_unregistered_platform`
- `test_is_call_active_returns_true_on_uia_exception`
- `test_extract_teams_participants_walks_list_items`

Fake UIA tree is a small dataclass mimicking uiautomation's Control interface (`{ControlTypeName, Name, GetChildren()}`). Not a real `uiautomation.Control`.

**Existing `tests/test_detection.py` additions:**
- `test_is_window_alive_returns_false_for_closed_hwnd`
- `test_detect_meeting_windows_excludes_unconfirmed_candidates`
- `test_excluded_hwnds_do_not_match_any_platform` (§4)
- `test_exclude_include_are_symmetric` (§4)

**Existing `tests/test_detector.py` additions:**
- `test_tracked_meeting_pruned_when_dropped_from_detected`
- `test_stop_path_ignores_uia_false_negative`
- `test_recording_hwnd_survives_uia_flap_during_recording`
- `test_no_retrigger_after_recording_stops_if_hwnd_still_tracked`
- `test_stop_waits_for_poll_task_unwind`

Total new tests for §3: 5 in `test_call_state.py` + 4 in `test_detection.py` (2 from §3, 2 from §4) + 5 in `test_detector.py`.

**Performance note:** UIA walks on Teams can take 50-200 ms. Detector polls every 500 ms. **Measure during implementation** via log timing; add an LRU cache in `call_state.py` keyed by `(hwnd, platform)` with short TTL (≤ 2 s) only if polls exceed a 500 ms budget with 3+ candidate windows. Not pre-committed — YAGNI until measured.

---

## §4 — Popup threading fix + self-window exclusion

### §4.1 — Root cause (tkinter)

[signal_popup.py:172-174](../../recap/daemon/recorder/signal_popup.py) uses `loop.run_in_executor(None, _blocking_dialog, ...)`. The default `ThreadPoolExecutor` owns a pool of worker threads with no thread-affinity guarantee. `_blocking_dialog` creates a Tk root, widgets, and `StringVar` instances, runs mainloop. When the callback fires `root.destroy()`, mainloop returns, `_blocking_dialog` returns, the thread becomes idle.

Crash path: Tk `Variable` instances live until GC collects them — by then the worker thread may be doing other work, reused for a different coroutine, or finalization may run on a different thread entirely. `Variable.__del__` tries to call into the Tcl interpreter but the interpreter was torn down when `root.destroy()` ran. `RuntimeError: main thread is not in main loop` / `Tcl_AsyncDelete: async handler deleted by the wrong thread`.

Compounding: (a) thread-affinity drift, (b) Variable lifecycle after root destruction.

### §4.2 — Dedicated single-worker executor + graceful shutdown

**Dedicated executor** pins all popup work to one thread:

```python
# In Daemon (recap/daemon/service.py)
self._popup_executor: ThreadPoolExecutor | None = None

def start(self):
    ...
    self._popup_executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="signal-popup-ui",
    )

async def stop(self):
    ...
    await self._detector.stop()  # awaits poll-task unwind (§3.4)
    signal_popup.request_shutdown()
    if not signal_popup.wait_for_shutdown(timeout=5.0):
        logger.warning(
            "signal popup worker did not finish within 5s; "
            "daemon shutdown is compromised — interpreter exit will hang. "
            "User may need to force-kill the process via Task Manager."
        )
    if self._popup_executor is not None:
        self._popup_executor.shutdown(wait=False)
        self._popup_executor = None
```

**Updated `show_signal_popup`** — required `executor` kwarg (not optional); uses `executor.submit()` directly so we hold the `concurrent.futures.Future` handle:

```python
# signal_popup.py
import asyncio
import concurrent.futures
import threading
from typing import Optional

_shutdown_requested = threading.Event()
_outstanding_futures: set[concurrent.futures.Future] = set()
_outstanding_lock = threading.Lock()


def _register_future(fut):
    with _outstanding_lock:
        _outstanding_futures.add(fut)

def _unregister_future(fut):
    """Done-callback — runs on worker or caller thread. GIL-protected discard."""
    with _outstanding_lock:
        _outstanding_futures.discard(fut)


async def show_signal_popup(
    *,
    org_slug: str,
    available_backends: list[str],
    executor: concurrent.futures.ThreadPoolExecutor,
) -> dict[str, str] | None:
    cf_future = executor.submit(_blocking_dialog, org_slug, list(available_backends))
    _register_future(cf_future)
    cf_future.add_done_callback(_unregister_future)
    return await asyncio.wrap_future(cf_future)


def request_shutdown() -> None:
    """Set sticky shutdown flag. Never cleared by popup code — process-lifetime."""
    _shutdown_requested.set()


def wait_for_shutdown(timeout: float = 5.0) -> bool:
    """Wait for ALL outstanding popup executor workers to finish.

    Returns True iff every cf_future has completed (normal return, exception,
    or cancellation) within `timeout`. Returns False if any worker is still
    blocked — interpreter shutdown will hang on that worker.
    """
    with _outstanding_lock:
        pending = list(_outstanding_futures)
    if not pending:
        return True
    done, not_done = concurrent.futures.wait(pending, timeout=timeout)
    return len(not_done) == 0
```

**Race analysis** (why set-based tracking, not single-slot):

| Scenario | Outstanding set | `wait_for_shutdown()` observes |
|---|---|---|
| cf1 running, cf2 queued; cf2's outer task cancelled; cf2's done-callback fires with cancelled state | `{cf1}` | Waits on cf1 correctly |
| cf1 completes naturally | `{}` | True immediately |
| cf1 wedged in mainloop at shutdown | `{cf1}` | Times out at 5s; returns False |
| Concurrent new popup during shutdown request | cf2 short-circuits via `_shutdown_requested.is_set()`; returns None fast; done-callback fires; `{}` | True |

Single-slot tracking broke the first scenario: cf2's done-callback would clear the slot, but cf1 was still running.

**Thread safety:** `_outstanding_lock` is a `threading.Lock`. `concurrent.futures.wait` is called outside the lock (snapshot `pending` first). `discard` inside `_unregister_future` is already inside the lock. No deadlock risk.

### §4.3 — Variable cleanup: drop `StringVar` entirely

Original cleanup-with-gc.collect ordering was backwards. Cleaner fix: avoid `tk.StringVar`. `ttk.Combobox` manages its own internal Tcl variable; read via `.get()`; the widget owns the Tcl variable's lifecycle. When the combobox is destroyed (as a child of root), the internal variable is finalized on the Tk thread synchronously.

**Rewritten `_blocking_dialog` (structure):**

```python
def _blocking_dialog(org_slug, available_backends) -> dict | None:
    # Sticky shutdown check: queued popups short-circuit.
    if _shutdown_requested.is_set():
        return None

    result: dict[str, Any] = {"value": None}
    try:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
        root.title("Signal call detected")
        root.update_idletasks()
        popup_hwnd = int(root.winfo_id())

        detection.exclude_hwnd(popup_hwnd)
        try:
            try:
                label_values = [_label_for_backend(v) for v in available_backends]
                pipeline_combo = ttk.Combobox(root, values=label_values, state="readonly")
                pipeline_combo.current(0)
                pipeline_combo.pack(...)

                def _on_record():
                    chosen_label = pipeline_combo.get()
                    try:
                        idx = label_values.index(chosen_label)
                        backend = available_backends[idx]
                    except ValueError:
                        backend = available_backends[0] if available_backends else "claude"
                    result["value"] = {"org": org_slug, "backend": backend}
                    root.quit()

                def _on_skip():
                    root.quit()

                # ... buttons ...

                def _check_shutdown():
                    if _shutdown_requested.is_set():
                        root.quit()
                    else:
                        root.after(100, _check_shutdown)

                root.after(100, _check_shutdown)
                root.mainloop()
            finally:
                # Destroy BEFORE dropping exclusion so the window is gone
                # from EnumWindows before the detector can see it again.
                try:
                    root.destroy()
                except Exception:
                    pass
        finally:
            detection.include_hwnd(popup_hwnd)
    except Exception:
        logger.exception("signal popup crashed")
        return None

    return result["value"]
```

**Key properties:**
- **Sticky shutdown check** at entry — queued popups short-circuit without ever calling `tk.Tk()`.
- **No `tk.StringVar`** — `ttk.Combobox` owns its internal variable.
- **`root.quit()` in callbacks** — breaks mainloop but keeps window; `finally` runs `destroy()` cleanly on the Tk thread.
- **Nested try/finally for exclusion ordering** — `root.destroy()` runs BEFORE `include_hwnd()`, so the window is gone from EnumWindows by the time the exclusion is lifted. Outer finally guarantees `include_hwnd` even if destroy raises.
- **`_shutdown_requested` never cleared by popup code.** Sticky through process lifetime. Tests reset via autouse fixture.

### §4.4 — Self-window exclusion

**Problem.** The popup's Tk root has title "Signal call detected" at line 62 of current `signal_popup.py`. That string contains "Signal" → matches `MEETING_PATTERNS["signal"] = r"\bSignal\b"` → detector sees our popup as a Signal candidate. Signal has no UIA checker (§3.6), so the regex match IS the detection. Loop.

**Fix.** Module-level exclusion set in `detection.py`:

```python
_EXCLUDED_HWNDS: set[int] = set()

def exclude_hwnd(hwnd: int) -> None:
    """Register an hwnd that MUST NOT be detected as a meeting."""
    _EXCLUDED_HWNDS.add(hwnd)

def include_hwnd(hwnd: int) -> None:
    _EXCLUDED_HWNDS.discard(hwnd)
```

Consulted inside `detect_meeting_windows` before regex match. Popup's `_blocking_dialog` registers its own hwnd via `winfo_id()` after `update_idletasks()` and deregisters after `root.destroy()` (ordering per §4.3 nested try/finally).

### §4.5 — Testing

Extensions to existing `tests/test_signal_popup.py` (autouse fixture resets `_shutdown_requested` between tests):

```python
@pytest.fixture(autouse=True)
def reset_shutdown_flag():
    from recap.daemon.recorder import signal_popup
    signal_popup._shutdown_requested.clear()
    yield
    signal_popup._shutdown_requested.clear()
```

Tests:
- `test_show_signal_popup_requires_executor_keyword` — TypeError without `executor=`.
- `test_show_signal_popup_uses_provided_executor` — mocks `asyncio.wrap_future`, asserts executor is passed.
- `test_blocking_dialog_registers_and_deregisters_hwnd` — register-then-deregister call order.
- `test_request_shutdown_sets_event` — `_shutdown_requested.is_set()` after call.
- `test_blocking_dialog_returns_none_on_shutdown_signal` — triggers `request_shutdown()` AFTER dialog starts via faked mainloop; asserts None return.
- `test_blocking_dialog_short_circuits_when_shutdown_already_requested` — sets event before entry, asserts `tk.Tk` never called, asserts None return.
- `test_wait_for_shutdown_empty_returns_true_immediately`.
- `test_wait_for_shutdown_waits_for_all_outstanding` — register two fake futures; assert timeout behavior with one complete, one pending.
- `test_cancelled_queued_future_is_removed_from_set` — cancel a registered future, invoke done-callback, assert removal.

**Manual verification** (scenario 5 addition): While popup is open, right-click tray → Quit. Daemon process exits within 5 seconds; no orphan threads.

### §4.6 — Blast radius

| File | Change |
|---|---|
| `signal_popup.py` | Sticky `_shutdown_requested`; required `executor=`; `wait_for_shutdown(timeout)`; outstanding-futures set with done-callback; Combobox over StringVar; nested try/finally for exclusion ordering; self-exclusion hwnd register/deregister |
| `detection.py` | `_EXCLUDED_HWNDS` + helpers; `detect_meeting_windows` honors exclusion |
| `service.py` | Spawn dedicated `ThreadPoolExecutor(max_workers=1)`; shutdown sequence per §4.2 |
| `__main__.py` | Plumb executor into `on_signal_detected` closure |

No detector changes from §4 (all detector changes are in §3).

---

## §5 — Integration test infrastructure

Closes the coverage lie. Existing 573-passing suite is green because every ML boundary is mocked; §5 adds a tier that imports real libraries and exercises call shapes.

### §5.1 — Directory layout

```
tests/
├── conftest.py                       (existing; adds make_silent_flac)
├── integration/
│   ├── __init__.py                   (new, empty)
│   ├── conftest.py                   (new, session-scoped fixtures)
│   ├── test_contract_smoke.py        (new, CPU tier)
│   └── test_ml_pipeline.py           (new, GPU tier)
```

### §5.2 — `pyproject.toml` changes

At `[tool.pytest.ini_options]`:

```toml
testpaths = ["tests"]
addopts = "--cov=recap --cov-fail-under=70 --cov-report=term-missing -m 'not integration'"
markers = [
    "integration: tests that import real ML/system libraries; slow; opt-in via -m integration",
]
```

Default `pytest -q` excludes the tier; explicit `pytest -m integration` opts in.

### §5.3 — Session-scoped fixtures

At new `tests/integration/conftest.py`:

```python
import pytest


@pytest.fixture(scope="session")
def cuda_guard():
    """Skip if CUDA is not available. Lazy torch import (session-scoped to
    allow dependent session-scoped model fixtures).

    Skip propagates correctly — any test transitively depending on this
    fixture skips when CUDA is absent.
    """
    pytest.importorskip("torch")
    import torch
    if not torch.cuda.is_available():
        pytest.skip("CUDA not available")


@pytest.fixture(scope="session")
def parakeet_asr_model(cuda_guard):
    """Load Parakeet ASR once per session."""
    import nemo.collections.asr as nemo_asr
    import torch
    model = nemo_asr.models.ASRModel.from_pretrained("nvidia/parakeet-tdt-0.6b-v2")
    model = model.to("cuda")
    yield model
    del model
    torch.cuda.empty_cache()


@pytest.fixture(scope="session")
def sortformer_diarizer_model(cuda_guard):
    """Load NeMo Sortformer once per session.

    Mirrors the production loader at recap/pipeline/diarize.py:16 — same
    class (SortformerEncLabelModel), same from_pretrained, same .diarize()
    surface. Changes here must track that file.
    """
    from nemo.collections.asr.models import SortformerEncLabelModel
    import torch
    model = SortformerEncLabelModel.from_pretrained(
        "nvidia/diar_streaming_sortformer_4spk-v2.1"
    )
    model = model.to("cuda")
    yield model
    del model
    torch.cuda.empty_cache()
```

### §5.4 — Hoist `make_silent_flac` to `tests/conftest.py`

Existing helper is FFmpeg-based (subprocess, no pyflac import), currently duplicated in `tests/test_e2e_pipeline.py:56` and `tests/test_signal_backend_routing.py:82`. Hoisted:

```python
# tests/conftest.py (addition)
import pathlib
import subprocess

def make_silent_flac(path: pathlib.Path, seconds: int = 2) -> pathlib.Path:
    """Generate a short silent FLAC via ffmpeg."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "anullsrc=channel_layout=mono:sample_rate=16000",
            "-t", str(seconds), str(path),
        ],
        check=True, capture_output=True,
    )
    return path
```

Only stdlib imports; no heavyweight deps added to default test runs. 2 call sites updated to import from conftest; 2 local definitions deleted.

### §5.5 — CPU contract smoke tests

`tests/integration/test_contract_smoke.py`:

```python
import inspect
import pytest

pytestmark = pytest.mark.integration


def test_nemo_asr_imports_cleanly():
    """Catches datasets/pyarrow import chain (RED today; GREEN after §2.3)."""
    from nemo.collections import asr  # noqa: F401


def test_pyflac_streamencoder_has_no_channels_kwarg():
    """Documents pyflac 3.0 API contract. Regression guard."""
    import pyflac
    params = inspect.signature(pyflac.StreamEncoder.__init__).parameters
    assert "channels" not in params


def test_pyflac_write_callback_signature():
    """Documents the 4-arg write_callback shape our code uses."""
    import pyflac
    params = inspect.signature(pyflac.StreamEncoder.__init__).parameters
    assert "write_callback" in params


def test_parakeet_stream_not_installed():
    """parakeet-stream removed in §2.1.

    Uses importlib.metadata (checks the venv), not sys.modules
    (which only reflects what this process has imported).
    """
    from importlib.metadata import PackageNotFoundError, distribution
    with pytest.raises(PackageNotFoundError):
        distribution("parakeet-stream")


def test_uiautomation_control_from_handle_exists():
    """call_state.py depends on uiautomation.ControlFromHandle."""
    import uiautomation
    assert hasattr(uiautomation, "ControlFromHandle")


def test_win32gui_required_apis():
    """detection.py depends on IsWindow, IsWindowVisible, EnumWindows, GetWindowText."""
    import win32gui
    for name in ("IsWindow", "IsWindowVisible", "EnumWindows", "GetWindowText"):
        assert hasattr(win32gui, name)
```

Requires `--extra daemon` (for uiautomation + pywin32) AND `--extra ml` (for NeMo + pyflac). CPU-safe; no GPU required.

### §5.6 — GPU model + end-to-end

`tests/integration/test_ml_pipeline.py`:

```python
import json
import pathlib
from unittest.mock import patch

import pytest

from tests.conftest import make_silent_flac

pytestmark = pytest.mark.integration


def test_parakeet_transcribes_silent_audio_without_error(parakeet_asr_model, tmp_path):
    """Real model processes silent FLAC without raising."""
    audio_path = make_silent_flac(tmp_path / "silent.flac", seconds=2)
    results = parakeet_asr_model.transcribe([str(audio_path)])
    assert len(results) == 1
    assert hasattr(results[0], "text")


def test_sortformer_diarizes_silent_audio_without_error(tmp_path, cuda_guard):
    """Exercises recap.pipeline.diarize.diarize — production path, not a
    reimplementation via fixture. Catches any drift at the diarize() function.
    """
    from recap.pipeline.diarize import diarize
    audio_path = make_silent_flac(tmp_path / "silent.flac", seconds=2)
    result = diarize(audio_path)
    assert isinstance(result, list)


def test_run_pipeline_end_to_end_on_silent_audio(tmp_path, cuda_guard):
    """Full batch pipeline with real Parakeet + Sortformer + stubbed analyze.

    Seeds recording_metadata.note_path explicitly (mirrors scenario 1's
    calendar-first flow) so the assertion targets an exact path without
    coupling to path-resolution internals.

    Would fail on today's obsidian-pivot via the pyarrow/datasets import chain.
    """
    audio_path = make_silent_flac(tmp_path / "test-meeting.flac", seconds=3)
    vault_path = tmp_path / "vault"
    (vault_path / "Test" / "Meetings").mkdir(parents=True)
    seeded_note_path = "Test/Meetings/2026-04-16 - Integration Test.md"

    # ... build RecordingMetadata(..., note_path=seeded_note_path),
    # MeetingMetadata, PipelineRuntimeConfig ...

    stub_analysis = {
        "speaker_mapping": {}, "meeting_type": "other",
        "summary": "integration test stub", "key_points": [],
        "decisions": [], "action_items": [], "follow_ups": None,
        "relationship_notes": None, "people": [], "companies": [],
    }

    with patch("recap.analyze.subprocess.run") as mock_run:
        mock_run.return_value = type("R", (), {
            "returncode": 0,
            "stdout": json.dumps(stub_analysis),
            "stderr": "",
        })()
        from recap.pipeline import run_pipeline
        run_pipeline(
            audio_path=audio_path,
            # ... all other args ...
        )

    note_path = vault_path / seeded_note_path
    assert note_path.exists()
    note_text = note_path.read_text()
    assert "## Summary" in note_text
    assert "pipeline-status: complete" in note_text
    assert "integration test stub" in note_text
```

### §5.7 — README updates

```markdown
### Unit tests (default)

```bash
uv sync --extra dev
uv run pytest -q
```

Fast (<1 min). Integration tier excluded via `-m 'not integration'` in pyproject.

### Integration tests

The integration tier loads real libraries (Parakeet, NeMo, pyflac, uiautomation,
pywin32) and requires the `daemon` and `ml` extras in addition to `dev`:

```bash
uv sync --extra dev --extra daemon --extra ml
```

Then run:

```bash
# CPU-safe contract smoke — runs on any Windows dev box, no GPU required
uv run pytest -m integration --no-cov tests/integration/test_contract_smoke.py

# Full integration tier (CPU + GPU model + end-to-end; requires CUDA)
uv run pytest -m integration --no-cov
```

`--no-cov` is recommended because running only the integration subset would
trip the 70% coverage floor pytest applies globally.

GPU tests automatically skip when CUDA isn't available via `cuda_guard`.
The `daemon` extra is Windows-specific (WASAPI + DPAPI); the integration
tier only runs on Windows.
```

---

## §6 — Rollout order + risk

### §6.1 — Preflight

Validate on the dev box before any code is written:

- [ ] `uv sync --extra dev --extra daemon --extra ml` succeeds.
- [ ] `ffmpeg -version` and `ffprobe -version` both resolve.
- [ ] `uv run python -c "import torch; print(torch.cuda.is_available())"` prints `True`.
- [ ] `claude --version` works without auth prompt.
- [ ] `ollama list` shows `qwen2.5:14b`.
- [ ] > 5 GB free on the disk holding `~\.cache\huggingface\` (first-run model downloads).
- [ ] Dev vault + `config.yaml` still intact from 2026-04-16 setup walkthrough.

### §6.2 — Commit sequence

| # | Commit | Scope | Test tier |
|---|---|---|---|
| 1 | `chore(tests): introduce integration tier infrastructure` | `tests/integration/` package + empty smoke file + `cuda_guard`/model fixtures + pyproject marker + `-m 'not integration'` addopts | None run yet — infrastructure only |
| 2 | `test(integration): CPU contract smoke tests against current library state` | §5.5's six tests including `test_parakeet_stream_not_installed`. Several RED today (NeMo import fails, parakeet-stream still installed). Fixes across commits 3-7 flip to GREEN. | |
| 3 | `chore(deps): pin datasets>=2.16,<3 to fix pyarrow.PyExtensionType import chain` | §2.3 preferred branch. pyproject + uv.lock. Dry-run log in commit body. | Commit 2's NeMo test passes |
| 4 | `fix(recorder): remove channels kwarg from pyflac 3.0 StreamEncoder call` | §2.2. Unit test (RED) → code fix (GREEN). | |
| 5 | `fix(daemon): stub live streaming transcriber (defer to Phase 8)` | §2.1 transcriber + discriminative tests. Deletes old `_load_model`-patching test. | `test_streaming_transcriber.py` green |
| 6 | `fix(daemon): stub live streaming diarizer (defer to Phase 8)` | §2.1 diarizer, same pattern. | `test_streaming_diarizer.py` green |
| 7 | `chore(deps): remove parakeet-stream dependency` | pyproject edit only (test already exists from commit 2). Commit 2's test transitions RED → GREEN. | Full CPU smoke tier green |
| 8 | `fix(plugin): update LiveTranscriptView copy for deferred live transcript` | §2.1(d) both status strings. | Manual visual check |
| 9 | `test(integration): GPU-tier model load + end-to-end pipeline` | §5.6's three tests. | `pytest -m integration --no-cov` on GPU box |
| 10 | `refactor(recorder): extract call_state module` | §3.1 + §3.5. Move `extract_teams_participants`. Empty `_CALL_STATE_CHECKERS`. | Existing enrichment tests green via re-export |
| 11 | `feat(recorder): UIA-confirmed call state for Teams and Zoom detection` | §3.2 + §3.3. `is_call_active` + checkers + `MEETING_PATTERNS` gated. `test_call_state.py` tests. | |
| 12 | `fix(detector): split stop/confirmed pruning + seal poll-task unwind on stop` | §3.4. `is_window_alive` + `_poll_once` rewrite + prune-with-recording-hwnd-protection + `stop()` poll-task await. | `test_detector.py` green |
| 13 | `fix(signal-popup): pin to dedicated executor + drop StringVar + thread-safe shutdown + outstanding-futures tracking` | §4.2 + §4.3. Daemon wiring. | Updated `test_signal_popup.py` green |
| 14 | `feat(detection): exclude daemon-owned popup windows` | §4.4. `_EXCLUDED_HWNDS` + `_blocking_dialog` registration. | |
| 15 | `docs(readme): integration test tier invocation` | §5.7. | |
| 16 | `docs(handoff): unblock Final Integration Pass scenarios after Phase 7` | Update `docs/handoffs/2026-04-15-final-integration-pass.md`. | |

### §6.3 — Risk catalog

| Commit | Risk | Probability | Mitigation |
|---|---|---|---|
| 3 | uv resolver rejects `datasets>=2.16,<3` | Low | Fallback: `pyarrow<21` (documented in §2.3) |
| 3 | datasets 2.16+ breaks NeMo 2.5 internals | Low | CPU smoke catches via `test_nemo_asr_imports_cleanly`; fallback pin available |
| 4 | pyflac 3 inferred channels wrong | Low | Manual scenario 1 check; ffprobe on emitted FLAC |
| 5-6 | Recorder assumes stub behavior we missed | Medium | Existing recorder tests + new stub tests |
| 8 | Obsidian plugin copy doesn't reload | Trivial | Plugin reload / restart Obsidian |
| 11 | Teams UIA tree differs per version | Medium | `is_call_active` falls back to regex-trust on UIA exception |
| 11 | UIA walks exceed 500 ms poll budget | Medium | LRU cache as conditional follow-up (§3.4) |
| 12 | Edge case in prune-with-protection | Medium | `test_detector.py` coverage; manual scenarios |
| 12 | Post-cancel synchronous poll chunk creates late signal-callback task | Low, catastrophic | `await self._poll_task` in `stop()`; `test_stop_waits_for_poll_task_unwind` |
| 13 | Sticky shutdown + queueing race: queued popup clears flag post-shutdown | Addressed | Sticky `_shutdown_requested.is_set()` check at entry; queued popups short-circuit |
| 13 | Outstanding-futures tracking misses workers | Addressed | Set-based tracking (not single-slot); `concurrent.futures.wait` across full set |
| 13 | `request_shutdown` doesn't reach mainloop → worker wedged → interpreter hangs | Low — 100 ms polling | Secondary: `wait_for_shutdown(timeout=5.0)`. **Fallback: daemon process hangs at interpreter exit; user must force-kill via Task Manager.** Phase 8 candidate: replace `ThreadPoolExecutor` with daemon `Thread + Queue`. |
| 14 | Race between popup window creation and `exclude_hwnd` | Low | `root.update_idletasks()` before `winfo_id()`; register before mainloop; nested finally for exclusion order (destroy before include) |

### §6.4 — Rollback strategy

Every commit is independently revertable. Reverts preserve upstream work:

- Library pins (commit 3) revertable via lockfile.
- Detection changes (10-12) revertable as a block if UIA flaky; fall back to regex-only + ship scenarios 3+4+5.
- Popup changes (13-14) revertable as a block; worst case daemon hangs on shutdown but scenarios 3+4+5 still pass.

**"Known good" checkpoint after commit 14** (not commit 9). After commit 9, Scenario 1 is runnable but Scenarios 2 + 5 still depend on the popup work. All 5 scenarios are runnable only after commit 14.

### §6.5 — Manual scenarios

All 5 from `docs/handoffs/2026-04-15-final-integration-pass.md`, run after commit 16:

1. Scenario 1: calendar → recording → pipeline → canonical note. Includes new check: Teams Desktop open on Chat tab does NOT trigger auto-record.
2. Scenario 2: Signal backend choice survives end-to-end. Includes popup stress: daemon quits cleanly within 5s of tray Quit while popup is open.
3. Scenario 3: rename queue on calendar time change.
4. Scenario 4: notification history backfill.
5. Scenario 5: extension auth enforcement. Includes new check: popup open does NOT cause a second detection cycle (self-exclusion).

### §6.6 — Shutdown sequence (final)

```
Daemon.stop()
  ↓
MeetingDetector.stop()
  ├─ _poll_task.cancel()
  ├─ await _poll_task  (§3.4 poll-task seal — no further _poll_once iterations)
  ├─ cancel + gather + clear _pending_signal_tasks
  ↓
signal_popup.request_shutdown()
  (_shutdown_requested set; sticky for process lifetime)
  ↓
signal_popup.wait_for_shutdown(timeout=5.0)
  (waits on ALL outstanding cf_futures via set-based tracking)
  (True = all complete; False = log warning, interpreter exit will hang)
  ↓
popup_executor.shutdown(wait=False)
  (forbids new submits; existing workers continue)
  ↓
(rest of daemon teardown)
```

Every layer has clear invariants at handoff points. No races between layers given the approved design.

---

## §7 — Success criteria

### §7.1 — Automated gates

| # | Gate | Command | Pass condition |
|---|---|---|---|
| 1 | Unit suite | `uv run pytest -q` | All pass; coverage ≥ 70%; count ≥ 573 + ~20 Phase 7 additions |
| 2 | CPU contract smoke | `uv run pytest -m integration --no-cov tests/integration/test_contract_smoke.py` | All 6 pass |
| 3 | GPU + e2e | `uv run pytest -m integration --no-cov` (GPU box) | All 3 pass |
| 4 | Plugin build | `cd obsidian-recap && npm run build` | Clean build, zero tsc errors |
| 5 | Daemon boot | `uv run python -m recap.daemon config.yaml` | (a) No stack traces. (b) `/api/status` returns 200 within 5s. (c) Tray icon visible. (d) No "Auto-recording teams" within 10s with Teams on non-call tab. (e) Ctrl+C/Quit terminates within 5s. |

### §7.2 — Manual scenarios

All 5 checkmarked in the handoff file with Phase 7-specific additions (§6.5 summary above).

### §7.3 — Documentation

- [ ] `docs/handoffs/2026-04-15-final-integration-pass.md` — blocker banner removed; scenarios marked runnable.
- [ ] `docs/plans/2026-04-16-phase7-ml-stack-refresh.md` — updated to "landed" with link to this design doc.
- [ ] `README.md` — integration test invocation section added.
- [ ] `MANIFEST.md` — regenerated to reflect new/modified files.

### §7.4 — Non-criteria (explicitly NOT required)

- Live streaming transcription (Phase 8).
- Call-state detection via platform APIs (external gates).
- Signal call detection (no UIA hooks).
- Tkinter replacement (Phase 8).
- CI integration of `-m integration` (no GPU runner).
- Migration off `parakeet-stream` in pipeline/transcribe.py (already uses NeMo direct).
- UIA walk performance tuning beyond contingent LRU.
- Improved Zoho detection beyond existing extension URL-pattern flow.

### §7.5 — Phase 8 follow-ups captured

| # | Item | Source |
|---|---|---|
| 1 | Rebuild live streaming transcription against NeMo directly | §2.1 deferred |
| 2 | Replace `ThreadPoolExecutor` with daemon `Thread + Queue` if popup shutdown hangs observed | §6.3 conditional |
| 3 | LRU cache in `call_state.py` if UIA walks dominate detector poll latency | §3.4 conditional |

### §7.6 — Merge readiness

`phase-7-ml-stack-refresh` (or chosen branch name) ready to merge into `obsidian-pivot` when:

1. §7.1 automated gates green.
2. §7.2 manual scenarios marked done.
3. §7.3 documentation updated.
4. `MANIFEST.md` regenerated.
5. Phase 8 follow-ups filed.

---

## Appendix — Review record

Every section reviewed against live codebase by Codex (external reviewer) before approval. Substantive P1/P2 findings were folded back in before moving on. A representative trail:

- §1: 3 review rounds. Finalized blast radius broadened to include all NeMo entry points + `uv.lock`; integration tiers split into CPU-safe contract smoke vs. GPU-required model tests; popup fix scope expanded beyond `signal_popup.py` to include `detector.py` and `__main__.py`; detection refactor surface includes `detection.py`.
- §2: 3 rounds. `datasets>=2.16,<3` pin tightened from `>=2.15` after empirical verification; `ConfigPresets.REALTIME` typed correctly as `AudioConfig` not `TranscriberConfig`; pytest marker registration moved from conftest to pyproject; deferred to stub-not-delete for parakeet-stream; test replacement (not supplementation) for `_load_model`-patching tests; mutually-exclusive branches for datasets vs. pyarrow pins.
- §3: 4 rounds. UIA gating split into two functions (detection vs. aliveness) to prevent false-stop on UIA flap; two independent pruning mechanisms for stop-path (hard signal) vs. dedupe (detected set); active-recording `_recording_hwnd` protected from prune; Signal reframed as NOT fixed by §3 alone.
- §4: 6 rounds. Shutdown signal via `threading.Event`; `StringVar` removed entirely in favor of `ttk.Combobox.get()`; executor ownership lifecycle; exclusion ordering (destroy before include) with nested try/finally; sticky `_shutdown_requested` (no clear at dialog entry); `_current_cf_future` widened to set-based outstanding-futures tracking; done-callback-based cleanup (not try/finally after await).
- §5: 5 rounds. `cuda_guard` fixture session-scoped; `SortformerEncLabelModel` (production class); hoisted `make_silent_flac` is FFmpeg-based (lightweight); seeded `recording_metadata.note_path` for e2e; `test_parakeet_stream_not_installed` uses `importlib.metadata`; integration tier requires `daemon + ml` extras (not just `ml`).
- §6: 6 rounds. Preflight uses `uv run python`; commit 7 flips existing test RED→GREEN (doesn't add); ThreadPoolExecutor threads are NOT daemon, fallback is honest (daemon hangs; user force-kill); `concurrent.futures.Future` type tracked correctly (not `asyncio.Task`); set-based outstanding-futures handles cancellation races; poll-task unwind awaited in `MeetingDetector.stop()` before signal-task drain.
- §7: 2 rounds. Gate 5 reframed as behavioral (not log-string match); `MANIFEST.md` is standalone step (not "per CLAUDE.md"); `.reap/genome/constraints.md` update removed (phase-specific state doesn't belong in long-lived constraints).

Final approval: all seven sections signed off.

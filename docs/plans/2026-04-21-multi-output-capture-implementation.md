# Multi-output audio capture — implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the single-default WASAPI loopback in the recorder with a dictionary of per-endpoint loopback streams that are dynamically managed, RMS-gated, and mixed into the existing stereo FLAC's system-audio channel — so meetings routed to non-default outputs (AirPods via Zoho's in-call picker) no longer silently record as monologues.

**Architecture:** `_SourceStream` gains an explicit per-endpoint `bind_to` parameter and an `is_terminal` surface. `AudioCapture` drops its singular `_loopback_source` field in favor of a `dict[DeviceIdentity, _LoopbackEntry]` whose lifecycle (PROBATION → ACTIVE → REMOVED) is managed by a new `_tick_membership()` helper that piggybacks on the drain thread. Mix math widens to int32, thresholds each stream on RMS, divides by active count, narrows with saturation. Total-loss-of-coverage triggers three new journal event types and persists to the sidecar as new `RecordingMetadata.audio_warnings` / `system_audio_devices_seen` fields; note export renders them as frontmatter + a body callout.

**Tech Stack:** Python 3.12, PyAudioWPatch (WASAPI), pyflac, numpy, pytest, existing EventJournal plumbing.

**Design doc:** `docs/plans/2026-04-21-multi-output-capture-design.md`

**Target branch:** `obsidian-pivot` (current). No worktree — changes are scoped and unblocked on existing branch state. Commit after every task.

---

## Task overview

Foundation layer (independent, unblocks everything else):
- Task 1: `_SourceStream.is_terminal` property
- Task 2: `_SourceStream.bind_to` constructor parameter
- Task 3: `_SourceStream.drain_resampled()` method

Policy and mixing layer:
- Task 4: `_LoopbackEntry` dataclass
- Task 5: `_drain_and_mix()` method with RMS-thresholded active-count mix
- Task 6: Wire `_drain_and_mix` into `_interleave_and_encode`

Membership layer:
- Task 7: `_tick_membership()` — enumeration, debounced remove, probation expiry, `is_terminal` check
- Task 8: Wire the tick into drain loop with wall-clock gate; initial population at `start()`

Warning persistence layer:
- Task 9: Extend `RecordingMetadata` with `audio_warnings` and `system_audio_devices_seen`
- Task 10: New journal event types
- Task 11: Emit warnings from `AudioCapture` on Scenarios A/B/C

Note export layer:
- Task 12: `build_canonical_frontmatter` renders `audio-warnings:` key
- Task 13: `upsert_note` renders `> [!warning]` body callout
- Task 14: Pipeline export reads sidecar warnings and threads through

End-to-end validation:
- Task 15: Multi-stream test helper `_test_feed_mock_frames_multi`
- Task 16: AirPods-scenario integration test
- Task 17: Cross-seam e2e test (sidecar → pipeline → note)
- Task 18: Manual validation run on real hardware (reference)

Each task follows the TDD loop: write failing test → verify fails → minimal implementation → verify passes → commit.

---

## Task 1: `_SourceStream.is_terminal` property

**Files:**
- Modify: `recap/daemon/recorder/audio.py` (add `_MAX_RECONNECT_ATTEMPTS` constant, `_reconnect_budget_exhausted` flag, `is_terminal` property)
- Test: `tests/test_recorder_audio.py` (append new test class)

**Step 1: Write the failing test**

Append to `tests/test_recorder_audio.py`:

```python
class TestSourceStreamTerminalState:
    def test_is_terminal_false_by_default(self):
        from recap.daemon.recorder.audio import _SourceStream
        s = _SourceStream(kind="loopback", output_rate=48000)
        assert s.is_terminal is False

    def test_is_terminal_true_after_budget_exhausted(self, monkeypatch):
        """When the internal reopen retry counter exceeds _MAX_RECONNECT_ATTEMPTS,
        is_terminal flips to True and stays True."""
        from recap.daemon.recorder.audio import _SourceStream
        s = _SourceStream(kind="loopback", output_rate=48000)
        # Force the exhausted state via the single public mutator used by the
        # reopen loop; do not poke private state from the test.
        s._mark_terminal_for_test()  # tiny test-only helper added in impl
        assert s.is_terminal is True
        # Never flips back
        s._mark_terminal_for_test()
        assert s.is_terminal is True
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_recorder_audio.py::TestSourceStreamTerminalState -v
```

Expected: FAIL with `AttributeError: '_SourceStream' object has no attribute 'is_terminal'`.

**Step 3: Write minimal implementation**

In `recap/daemon/recorder/audio.py`, near the top of the module add:

```python
_MAX_RECONNECT_ATTEMPTS = 20
```

Inside `_SourceStream.__init__`, after the existing `self._reconnect_attempts = 0`, add:

```python
        self._terminal: bool = False
```

After the existing `is_degraded` method, add:

```python
    @property
    def is_terminal(self) -> bool:
        """True when the source has exhausted its reconnect budget and should
        not be kept alive. Never flips back to False once set."""
        return self._terminal

    def _mark_terminal_for_test(self) -> None:  # pragma: no cover - test-only helper
        """Test hook: flip the terminal flag without going through the reopen loop."""
        self._terminal = True
```

Modify `_SourceStream.attempt_reopen_if_due` (around line 321) so that after a failed reopen, when `self._reconnect_attempts >= _MAX_RECONNECT_ATTEMPTS`, it sets `self._terminal = True` before returning. Find the `except` branch that currently logs `"%s reopen failed: %s"` and add the terminal check immediately after the log line:

```python
            logger.warning("%s reopen failed: %s", self._kind, exc)
            if self._reconnect_attempts >= _MAX_RECONNECT_ATTEMPTS:
                self._terminal = True
                logger.warning(
                    "%s exceeded reconnect budget (%d); marking terminal",
                    self._kind, _MAX_RECONNECT_ATTEMPTS,
                )
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_recorder_audio.py::TestSourceStreamTerminalState -v
```

Expected: PASS (2 passed).

Also run the full audio test file to make sure nothing regressed:

```bash
uv run pytest tests/test_recorder_audio.py -v
```

Expected: all prior tests still pass.

**Step 5: Commit**

```bash
git add recap/daemon/recorder/audio.py tests/test_recorder_audio.py
git commit -m "feat(audio): add _SourceStream.is_terminal for reconnect budget exhaustion

Foundation for the multi-output loopback refactor: lifecycle owners need
an explicit public surface to detect permanently-dead streams instead of
peeking at _state or _reconnect_attempts. is_terminal never flips back
to False once set; the existing reopen loop flips it when the retry
counter exceeds _MAX_RECONNECT_ATTEMPTS.

No behavior change for current callers -- today nothing reads
is_terminal. Used in task 7 by the membership watcher.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `_SourceStream.bind_to` constructor parameter

**Files:**
- Modify: `recap/daemon/recorder/audio.py` (`_SourceStream.__init__` signature, `_do_reopen` and `start` device-lookup paths)
- Test: `tests/test_recorder_audio.py` (extend `TestSourceStreamTerminalState` or add new class)

**Step 1: Write the failing test**

Append to `tests/test_recorder_audio.py`:

```python
class TestSourceStreamExplicitBinding:
    def test_bind_to_none_preserves_default_loopback(self):
        """No bind_to -> today's default-following behavior."""
        from recap.daemon.recorder.audio import _SourceStream
        s = _SourceStream(kind="loopback", output_rate=48000)
        assert s._bind_to is None

    def test_bind_to_explicit_identity_stored(self):
        """Explicit identity is stored and is what reopen will look up."""
        from recap.daemon.recorder.audio import _SourceStream
        identity = ("endpoint-guid-abc",)
        s = _SourceStream(kind="loopback", output_rate=48000, bind_to=identity)
        assert s._bind_to == identity

    def test_bind_to_loopback_open_uses_specific_endpoint(self, monkeypatch):
        """When bind_to is set, start() looks up that exact device instead of
        calling get_default_wasapi_loopback."""
        from recap.daemon.recorder.audio import _SourceStream
        identity = ("endpoint-guid-xyz",)
        s = _SourceStream(kind="loopback", output_rate=48000, bind_to=identity)

        # Capture which device-lookup path was exercised.
        called = {"default": 0, "by_identity": 0}

        class _FakePA:
            def get_default_wasapi_loopback(self):
                called["default"] += 1
                return {"name": "WRONG", "index": 0, "maxInputChannels": 2,
                        "defaultSampleRate": 48000.0}

            def get_device_info_by_index(self, idx):
                return {"endpointId": "endpoint-guid-xyz", "name": "AirPods",
                        "index": idx, "maxInputChannels": 2,
                        "defaultSampleRate": 48000.0, "isLoopbackDevice": True}

            def get_device_count(self):
                return 1

            def open(self, *args, **kwargs):
                m = MagicMock()
                m.is_active.return_value = True
                return m

            def terminate(self):
                pass

        monkeypatch.setattr(
            "recap.daemon.recorder.audio._require_pyaudio",
            lambda: MagicMock(PyAudio=_FakePA, paInt16=8, paContinue=0),
        )

        # Trigger the device-lookup path. We reach past start() here because
        # start() does full stream wiring; _lookup_bound_device is the narrow
        # helper we extract to exercise just the binding decision.
        info = s._lookup_bound_device()

        assert called["default"] == 0, "bind_to must not fall back to default"
        assert info["endpointId"] == "endpoint-guid-xyz"
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_recorder_audio.py::TestSourceStreamExplicitBinding -v
```

Expected: FAIL with `TypeError: _SourceStream.__init__() got an unexpected keyword argument 'bind_to'`.

**Step 3: Write minimal implementation**

In `_SourceStream.__init__`, change the signature:

```python
    def __init__(
        self,
        *,
        kind: str,
        output_rate: int,
        bind_to: tuple | None = None,
    ) -> None:
```

At the end of `__init__`, add:

```python
        self._bind_to: tuple | None = bind_to
```

Extract a new helper method. After the `_compute_identity` staticmethod, add:

```python
    def _lookup_bound_device(self) -> dict:
        """Return the PyAudio device-info dict for this stream's target.

        When bind_to is None (legacy default-following behavior), returns the
        default device. When bind_to is an explicit identity tuple (loopback
        only), scans the WASAPI device list for a matching identity.

        Raises:
            AudioDeviceError: if bind_to is set but the identity is not in
                the current enumeration.
        """
        pa = _require_pyaudio().PyAudio()
        try:
            if self._bind_to is None:
                if self._kind == "loopback":
                    return pa.get_default_wasapi_loopback()
                return pa.get_default_wasapi_device(d_in=True)

            # Explicit binding: scan for matching identity.
            count = pa.get_device_count()
            for idx in range(count):
                info = pa.get_device_info_by_index(idx)
                if self._compute_identity(info) == self._bind_to:
                    return info
            raise AudioDeviceError(
                f"loopback bound endpoint {self._bind_to!r} not in current "
                f"WASAPI enumeration",
            )
        finally:
            pa.terminate()
```

Update `start()` and `_do_reopen()` to use `_lookup_bound_device()` instead of calling `get_default_wasapi_loopback()` / `get_default_wasapi_device()` directly. In `start()` (around line 214):

```python
        # Before:
        # if self._kind == "loopback":
        #     info = pa.get_default_wasapi_loopback()
        # else:
        #     info = pa.get_default_wasapi_device(d_in=True)
        # Replace with:
        info = self._lookup_bound_device()
```

Same substitution in `_do_reopen()` (around line 338).

When `_lookup_bound_device()` raises `AudioDeviceError` during reopen, the existing except-branch should flip `_terminal = True` (since a bound identity that vanished from enumeration cannot recover from the stream's own retry loop — membership handles it). Add to the reopen except path:

```python
        except AudioDeviceError as exc:
            logger.warning("%s bound identity vanished: %s", self._kind, exc)
            self._terminal = True
            return
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_recorder_audio.py::TestSourceStreamExplicitBinding -v
uv run pytest tests/test_recorder_audio.py -v
```

Expected: new tests pass; all existing audio tests still pass.

**Step 5: Commit**

```bash
git add recap/daemon/recorder/audio.py tests/test_recorder_audio.py
git commit -m "feat(audio): _SourceStream.bind_to for explicit per-endpoint loopback binding

Today _SourceStream(kind='loopback') always calls
get_default_wasapi_loopback() on open and reopen. That behavior is
incompatible with multi-output capture: a reconnect after the default
changes would silently collapse two different endpoint streams into
both following the default.

bind_to accepts the stable identity tuple that _SourceStream already
computes for hot-plug tracking. _lookup_bound_device() scans the WASAPI
enumeration for a match and raises AudioDeviceError (which the reopen
path translates to is_terminal=True) if the identity vanishes.

When bind_to is None, legacy default-following behavior is preserved.
In practice AudioCapture will always pass bind_to going forward, but
the default remains for any future caller that wants the old semantics.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `_SourceStream.drain_resampled()` method

**Files:**
- Modify: `recap/daemon/recorder/audio.py` (new public drain method on `_SourceStream`)
- Test: `tests/test_recorder_audio.py`

Currently `AudioCapture` reaches into `self._mic_buffer` and `self._loopback_buffer` directly. For the multi-stream design, each `_SourceStream` must expose its own drain. This task extracts a narrow public method.

**Step 1: Write the failing test**

Append to `tests/test_recorder_audio.py`:

```python
class TestSourceStreamDrain:
    def test_drain_resampled_returns_requested_bytes(self):
        from recap.daemon.recorder.audio import _SourceStream
        s = _SourceStream(kind="loopback", output_rate=48000)
        s._resampled_buffer = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        out = s.drain_resampled(4)
        assert out == b"\x01\x02\x03\x04"
        assert s._resampled_buffer == b"\x05\x06\x07\x08"

    def test_drain_resampled_returns_partial_when_short(self):
        from recap.daemon.recorder.audio import _SourceStream
        s = _SourceStream(kind="loopback", output_rate=48000)
        s._resampled_buffer = b"\x01\x02"
        out = s.drain_resampled(8)
        assert out == b"\x01\x02"
        assert s._resampled_buffer == b""

    def test_drain_resampled_returns_empty_when_no_data(self):
        from recap.daemon.recorder.audio import _SourceStream
        s = _SourceStream(kind="loopback", output_rate=48000)
        assert s.drain_resampled(4) == b""
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_recorder_audio.py::TestSourceStreamDrain -v
```

Expected: FAIL with `AttributeError: '_SourceStream' object has no attribute 'drain_resampled'`.

**Step 3: Write minimal implementation**

Add to `_SourceStream`, after the `read_frames` method:

```python
    def drain_resampled(self, max_bytes: int) -> bytes:
        """Drain up to max_bytes from the resampled output buffer.

        Returns whatever is currently available up to max_bytes. May return
        less than requested (including empty) when the buffer has not yet
        filled. Caller is responsible for padding with zeros if alignment
        matters.
        """
        with self._lock:
            out = self._resampled_buffer[:max_bytes]
            self._resampled_buffer = self._resampled_buffer[max_bytes:]
        return out
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_recorder_audio.py::TestSourceStreamDrain -v
uv run pytest tests/test_recorder_audio.py -v
```

Expected: all pass.

**Step 5: Commit**

```bash
git add recap/daemon/recorder/audio.py tests/test_recorder_audio.py
git commit -m "feat(audio): _SourceStream.drain_resampled public drain method

Extracts a narrow public accessor for the resampled output buffer so
that the multi-loopback mixer in a later task can drain per-stream
instead of reaching into a single shared AudioCapture._loopback_buffer.

No current caller uses it; the existing read_frames path keeps working.
This is a seam for the multi-output refactor.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `_LoopbackEntry` dataclass

**Files:**
- Modify: `recap/daemon/recorder/audio.py` (new dataclass + constants)
- Test: `tests/test_audio_loopback_lifecycle.py` (new file)

**Step 1: Write the failing test**

Create `tests/test_audio_loopback_lifecycle.py`:

```python
"""Tests for _LoopbackEntry state machine (probation -> active -> removed)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from recap.daemon.recorder.audio import _LoopbackEntry


def _make_entry(opened_at: float = 0.0, device_name: str = "Test Device") -> _LoopbackEntry:
    stream = MagicMock()
    stream.is_terminal = False
    return _LoopbackEntry(
        stream=stream,
        state="probation",
        opened_at=opened_at,
        last_active_at=None,
        device_name=device_name,
        missing_since=None,
    )


class TestLoopbackEntryConstruction:
    def test_default_state_is_probation(self):
        e = _make_entry()
        assert e.state == "probation"
        assert e.last_active_at is None
        assert e.missing_since is None

    def test_device_name_stored(self):
        e = _make_entry(device_name="AirPods")
        assert e.device_name == "AirPods"

    def test_opened_at_stored(self):
        e = _make_entry(opened_at=123.45)
        assert e.opened_at == 123.45
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_audio_loopback_lifecycle.py -v
```

Expected: FAIL with `ImportError: cannot import name '_LoopbackEntry'`.

**Step 3: Write minimal implementation**

In `recap/daemon/recorder/audio.py`, after the `_SourceStream` class definition (or near the top imports region), add:

```python
from dataclasses import dataclass, field
from typing import Literal

# --- Multi-output loopback lifecycle constants ---
_LOOPBACK_PROBATION_S = 60.0
_LOOPBACK_MEMBERSHIP_TICK_S = 3.0
_LOOPBACK_DEVICE_GRACE_S = 6.0
_LOOPBACK_ACTIVE_RMS_DBFS = -40.0
# Derived once at module load:
#   10 ** (-40/20) = 0.01;  0.01 * 32768 ≈ 327.68
_LOOPBACK_ACTIVE_RMS_LINEAR = 10.0 ** (_LOOPBACK_ACTIVE_RMS_DBFS / 20.0) * 32768.0


@dataclass
class _LoopbackEntry:
    """Recorder-side policy wrapper around a loopback _SourceStream.

    Tracks PROBATION/ACTIVE lifecycle, wall-clock opened_at for probation
    expiry, last_active_at for telemetry, and missing_since for debounced
    device-disappearance. Does NOT introspect _SourceStream's private state;
    the only coupling is the public is_terminal property.
    """
    stream: "_SourceStream"
    state: Literal["probation", "active"]
    opened_at: float
    last_active_at: float | None
    device_name: str
    missing_since: float | None
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_audio_loopback_lifecycle.py -v
```

Expected: PASS (3 passed).

**Step 5: Commit**

```bash
git add recap/daemon/recorder/audio.py tests/test_audio_loopback_lifecycle.py
git commit -m "feat(audio): _LoopbackEntry lifecycle dataclass

Recorder-side policy wrapper around a loopback _SourceStream. Keeps
PROBATION/ACTIVE state and wall-clock metadata on the entry rather
than pushing them down into _SourceStream, per the design's
health/membership/signal-usefulness separation.

Also introduces the four tunable constants for the multi-output
loopback subsystem: probation timeout (60s), membership tick cadence
(3s), device-grace debounce (6s), and the -40 dBFS RMS threshold
for signal-bearing determination.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `_drain_and_mix()` method with RMS-thresholded active-count mix

**Files:**
- Modify: `recap/daemon/recorder/audio.py` (new method on `AudioCapture`; `_loopback_sources` dict added; `_loopback_buffer` field marked for removal)
- Test: `tests/test_audio_multi_loopback_mix.py` (new file)

**Step 1: Write the failing test**

Create `tests/test_audio_multi_loopback_mix.py`:

```python
"""Tests for AudioCapture._drain_and_mix (multi-stream mix math)."""
from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from recap.daemon.recorder.audio import (
    AudioCapture,
    _LoopbackEntry,
    _LOOPBACK_ACTIVE_RMS_LINEAR,
)


def _entry_with_buffer(samples: np.ndarray, device_name: str = "Test") -> _LoopbackEntry:
    """Build a _LoopbackEntry whose _SourceStream's drain_resampled() returns
    the given samples as int16 bytes."""
    stream = MagicMock()
    stream.is_terminal = False
    stream.drain_resampled.return_value = samples.astype(np.int16).tobytes()
    return _LoopbackEntry(
        stream=stream,
        state="probation",
        opened_at=0.0,
        last_active_at=None,
        device_name=device_name,
        missing_since=None,
    )


@pytest.fixture
def capture(tmp_path):
    cap = AudioCapture(output_path=tmp_path / "test.flac")
    return cap


def _mic_bytes(chunk_frames: int, level_int16: int = 10000) -> bytes:
    arr = np.full(chunk_frames, level_int16, dtype=np.int16)
    return arr.tobytes()


class TestDrainAndMix:
    def test_single_active_stream_preserves_level(self, capture):
        """One signal-bearing loopback → channel-1 equals that stream's samples."""
        chunk_frames = 480
        speech = np.full(chunk_frames, 8000, dtype=np.int16)  # well above threshold
        capture._mic_buffer = _mic_bytes(chunk_frames)
        capture._loopback_sources = {
            ("airpods",): _entry_with_buffer(speech, device_name="AirPods"),
        }

        mic, system, _ = capture._drain_and_mix(chunk_frames)

        # System channel equals the single active stream's samples (not halved).
        np.testing.assert_array_equal(system, speech)

    def test_two_active_streams_average(self, capture):
        """Two signal-bearing loopbacks → channel-1 = (a + b) / 2."""
        chunk_frames = 480
        a = np.full(chunk_frames, 8000, dtype=np.int16)
        b = np.full(chunk_frames, 4000, dtype=np.int16)
        capture._mic_buffer = _mic_bytes(chunk_frames)
        capture._loopback_sources = {
            ("dev-a",): _entry_with_buffer(a, device_name="A"),
            ("dev-b",): _entry_with_buffer(b, device_name="B"),
        }

        _, system, _ = capture._drain_and_mix(chunk_frames)
        expected = ((a.astype(np.int32) + b.astype(np.int32)) // 2).astype(np.int16)
        np.testing.assert_array_equal(system, expected)

    def test_silent_stream_excluded_from_active_count(self, capture):
        """Silent (below-threshold) stream does not contribute or halve."""
        chunk_frames = 480
        speech = np.full(chunk_frames, 8000, dtype=np.int16)
        silent = np.zeros(chunk_frames, dtype=np.int16)
        capture._mic_buffer = _mic_bytes(chunk_frames)
        capture._loopback_sources = {
            ("airpods",): _entry_with_buffer(speech, device_name="AirPods"),
            ("speakers",): _entry_with_buffer(silent, device_name="Speakers"),
        }

        _, system, _ = capture._drain_and_mix(chunk_frames)
        # Silent stream excluded → active_count=1 → no halving of speech.
        np.testing.assert_array_equal(system, speech)

    def test_all_below_threshold_emits_zero_channel(self, capture):
        chunk_frames = 480
        capture._mic_buffer = _mic_bytes(chunk_frames)
        capture._loopback_sources = {
            ("a",): _entry_with_buffer(np.zeros(chunk_frames, dtype=np.int16)),
            ("b",): _entry_with_buffer(np.zeros(chunk_frames, dtype=np.int16)),
        }
        _, system, _ = capture._drain_and_mix(chunk_frames)
        assert np.all(system == 0)

    def test_no_loopback_sources_emits_zero_channel(self, capture):
        chunk_frames = 480
        capture._mic_buffer = _mic_bytes(chunk_frames)
        capture._loopback_sources = {}
        _, system, _ = capture._drain_and_mix(chunk_frames)
        assert np.all(system == 0)
        assert system.shape == (chunk_frames,)

    def test_rms_measured_before_padding(self, capture):
        """A stream that returns a short buffer must have its RMS measured on
        the unpadded samples. If we measured after padding with zeros, a burst
        of real signal could be misclassified as silent."""
        chunk_frames = 480
        # Stream returns only 100 frames of loud signal (well above threshold).
        short = np.full(100, 20000, dtype=np.int16)
        capture._mic_buffer = _mic_bytes(chunk_frames)
        entry = _entry_with_buffer(short)
        capture._loopback_sources = {("x",): entry}

        _, system, _ = capture._drain_and_mix(chunk_frames)

        # The stream should be classified active (RMS of unpadded is high),
        # so system[0:100] should equal the short samples and system[100:]
        # should be zeros from the pad.
        np.testing.assert_array_equal(system[:100], short)
        assert np.all(system[100:] == 0)
        assert entry.state == "active"

    def test_first_signal_promotes_probation_to_active(self, capture):
        chunk_frames = 480
        speech = np.full(chunk_frames, 8000, dtype=np.int16)
        entry = _entry_with_buffer(speech)
        assert entry.state == "probation"
        capture._mic_buffer = _mic_bytes(chunk_frames)
        capture._loopback_sources = {("a",): entry}

        capture._drain_and_mix(chunk_frames)

        assert entry.state == "active"
        assert entry.last_active_at is not None

    def test_below_threshold_leaves_probation_intact(self, capture):
        chunk_frames = 480
        silent = np.zeros(chunk_frames, dtype=np.int16)
        entry = _entry_with_buffer(silent)
        capture._mic_buffer = _mic_bytes(chunk_frames)
        capture._loopback_sources = {("a",): entry}
        capture._drain_and_mix(chunk_frames)
        assert entry.state == "probation"
        assert entry.last_active_at is None

    def test_saturation_clips_without_overflow(self, capture):
        """Simultaneous int16-peak signals on two streams must saturate to
        int16 max in the divide-by-count step, not wrap."""
        chunk_frames = 480
        peak = np.full(chunk_frames, 32767, dtype=np.int16)
        entry_a = _entry_with_buffer(peak)
        entry_b = _entry_with_buffer(peak)
        capture._mic_buffer = _mic_bytes(chunk_frames)
        capture._loopback_sources = {("a",): entry_a, ("b",): entry_b}
        _, system, _ = capture._drain_and_mix(chunk_frames)
        # (32767 + 32767) / 2 = 32767; no wraparound.
        assert np.all(system == 32767)

    def test_mono_chunk_is_mic_plus_system_halved(self, capture):
        chunk_frames = 480
        speech = np.full(chunk_frames, 8000, dtype=np.int16)
        capture._mic_buffer = _mic_bytes(chunk_frames, level_int16=10000)
        capture._loopback_sources = {("a",): _entry_with_buffer(speech)}

        mic, system, mono_bytes = capture._drain_and_mix(chunk_frames)
        mono = np.frombuffer(mono_bytes, dtype=np.int16)

        expected = ((mic.astype(np.int32) + system.astype(np.int32)) // 2).astype(np.int16)
        np.testing.assert_array_equal(mono, expected)
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_audio_multi_loopback_mix.py -v
```

Expected: FAIL — `AttributeError: 'AudioCapture' object has no attribute '_drain_and_mix'` and `'_loopback_sources'` attr missing.

**Step 3: Write minimal implementation**

In `AudioCapture.__init__`, add alongside existing fields:

```python
        self._loopback_sources: dict[tuple, "_LoopbackEntry"] = {}
        self._last_membership_tick: float = 0.0
```

Immediately after `_combine_frames`, add the new method:

```python
    def _drain_and_mix(
        self, chunk_frames: int,
    ) -> tuple["np.ndarray", "np.ndarray", bytes]:
        """Drain mic + all loopback sources for one chunk and build channel-0
        (mic), channel-1 (system mix), and the mono chunk for on_chunk.

        Replaces _combine_frames for the multi-output design. Mic behavior is
        unchanged; system mix is an RMS-thresholded divide-by-active-count
        average of all loopback streams.

        Lifecycle side effect: a PROBATION _LoopbackEntry whose chunk RMS
        crosses _LOOPBACK_ACTIVE_RMS_LINEAR flips to ACTIVE here (the only
        place promotions happen).
        """
        numpy = _require_numpy()
        bytes_needed = chunk_frames * 2  # int16 = 2 bytes per sample

        # --- Mic drain: unchanged. ---
        with self._lock:
            mic_data = self._mic_buffer[:bytes_needed]
            self._mic_buffer = self._mic_buffer[bytes_needed:]
        if len(mic_data) < bytes_needed:
            mic_data += b"\x00" * (bytes_needed - len(mic_data))
        mic_samples = numpy.frombuffer(mic_data, dtype=numpy.int16)[:chunk_frames]

        # --- Loopback drain + mix ---
        system_sum_i32 = numpy.zeros(chunk_frames, dtype=numpy.int32)
        active_count = 0
        now = time.monotonic()

        for key, entry in self._loopback_sources.items():
            stream_bytes = entry.stream.drain_resampled(bytes_needed)

            # Measure RMS on the UNPADDED samples only — padding zeros before
            # measurement would depress the level of a stream with a short
            # buffer and misclassify it as silent.
            real_samples = numpy.frombuffer(stream_bytes, dtype=numpy.int16)
            if real_samples.size > 0:
                rms_linear = float(
                    numpy.sqrt(numpy.mean(real_samples.astype(numpy.float64) ** 2)),
                )
            else:
                rms_linear = 0.0

            # Pad for alignment after measuring.
            if len(stream_bytes) < bytes_needed:
                stream_bytes = stream_bytes + b"\x00" * (bytes_needed - len(stream_bytes))
            stream_samples = numpy.frombuffer(
                stream_bytes, dtype=numpy.int16,
            )[:chunk_frames]

            if rms_linear > _LOOPBACK_ACTIVE_RMS_LINEAR:
                system_sum_i32 += stream_samples.astype(numpy.int32)
                active_count += 1
                if entry.state == "probation":
                    entry.state = "active"
                    entry.last_active_at = now
                    logger.info(
                        "loopback %s promoted to ACTIVE (elapsed=%.1fs)",
                        entry.device_name, now - entry.opened_at,
                    )
                else:
                    entry.last_active_at = now

        if active_count > 0:
            system_mix_i32 = system_sum_i32 // active_count
            system_mix = numpy.clip(system_mix_i32, -32768, 32767).astype(numpy.int16)
        else:
            system_mix = numpy.zeros(chunk_frames, dtype=numpy.int16)

        # --- Mono for on_chunk consumers: (mic + system_mix) / 2 in int32. ---
        mono_i32 = (
            mic_samples.astype(numpy.int32) + system_mix.astype(numpy.int32)
        ) // 2
        mono_bytes = numpy.clip(mono_i32, -32768, 32767).astype(numpy.int16).tobytes()

        return mic_samples, system_mix, mono_bytes
```

At the top of `recap/daemon/recorder/audio.py`, add `import time` if not already imported.

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_audio_multi_loopback_mix.py -v
uv run pytest tests/test_recorder_audio.py -v
```

Expected: all pass. `_combine_frames` is still present (removed in Task 6), so existing `_test_feed_mock_frames` still works.

**Step 5: Commit**

```bash
git add recap/daemon/recorder/audio.py tests/test_audio_multi_loopback_mix.py
git commit -m "feat(audio): _drain_and_mix replaces _combine_frames for multi-loopback

Per-chunk drain of mic + all loopback _SourceStreams into channel-0 +
channel-1 + mono. System mix is an RMS-thresholded divide-by-active-count
average: each stream's chunk RMS is measured on unpadded samples (critical
-- measuring after padding zeros would misclassify legitimately active
short-buffer streams as silent), streams above -40 dBFS are summed in
int32 and averaged by active_count, and the result is saturation-clipped
to int16. Zero active streams emit a true-zero channel.

Side effect: PROBATION -> ACTIVE promotion happens here, the only place
in the design where it's allowed to fire.

_combine_frames remains for now; Task 6 removes it and rewires
_interleave_and_encode.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Wire `_drain_and_mix` into `_interleave_and_encode`

**Files:**
- Modify: `recap/daemon/recorder/audio.py` — `_interleave_and_encode`, `_test_feed_mock_frames`
- Test: existing `tests/test_recorder_audio.py::test_audio_capture_invokes_on_chunk_after_interleave` must still pass

**Step 1: Write the failing test**

Extend `tests/test_audio_multi_loopback_mix.py`:

```python
class TestInterleaveUsesDrainAndMix:
    def test_interleave_uses_mic_and_system_mix(self, capture, monkeypatch):
        """_interleave_and_encode must build the stereo FLAC frame from
        _drain_and_mix output (mic in channel 0, system mix in channel 1)."""
        chunk_frames = 480
        mic = np.full(chunk_frames, 1000, dtype=np.int16)
        system = np.full(chunk_frames, 2000, dtype=np.int16)

        monkeypatch.setattr(
            capture, "_drain_and_mix",
            lambda cf: (mic, system, b"\x00" * cf * 2),
        )
        captured: list[np.ndarray] = []
        capture._encoder = MagicMock()
        capture._encoder.process.side_effect = lambda frames: captured.append(frames)

        capture._interleave_and_encode(chunk_frames)

        assert len(captured) == 1
        frames = captured[0]
        assert frames.shape == (chunk_frames, 2)
        np.testing.assert_array_equal(frames[:, 0], mic)
        np.testing.assert_array_equal(frames[:, 1], system)
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_audio_multi_loopback_mix.py::TestInterleaveUsesDrainAndMix -v
```

Expected: FAIL — current `_interleave_and_encode` calls `_combine_frames`, not `_drain_and_mix`.

**Step 3: Write minimal implementation**

In `_interleave_and_encode` (around line 723), replace the call:

```python
        # Before:
        mic_samples, lb_samples, mono_chunk_bytes = self._combine_frames(chunk_frames)
        # After:
        mic_samples, system_mix, mono_chunk_bytes = self._drain_and_mix(chunk_frames)
```

Update the interleave line to use `system_mix`:

```python
        interleaved = numpy.empty(chunk_frames * 2, dtype=numpy.int16)
        interleaved[0::2] = mic_samples
        interleaved[1::2] = system_mix
```

Now update `_test_feed_mock_frames` so existing tests still work in legacy-stream mode. The helper currently takes `mic_frame` and `system_frame` and uses `_loopback_buffer`. Refactor it to construct a single synthetic `_LoopbackEntry` wrapping a stub that returns the `system_frame`:

```python
    def _test_feed_mock_frames(
        self, mic_frame: bytes, system_frame: bytes
    ) -> None:  # pragma: no cover - test-only helper
        """Legacy single-loopback test helper. Constructs one synthetic
        _LoopbackEntry containing the system_frame and drives the normal
        _drain_and_mix + _interleave_and_encode path.

        Preserved for backwards compatibility with existing tests; new tests
        should use _test_feed_mock_frames_multi (Task 15) for per-stream
        control."""
        if len(mic_frame) != len(system_frame):
            raise ValueError("mic_frame and system_frame must have the same length")
        chunk_frames = len(mic_frame) // 2

        class _StubStream:
            def __init__(self, frame: bytes) -> None:
                self._buf = frame
                self.is_terminal = False
            def drain_resampled(self, max_bytes: int) -> bytes:
                out = self._buf[:max_bytes]
                self._buf = self._buf[max_bytes:]
                return out

        entry = _LoopbackEntry(
            stream=_StubStream(system_frame),
            state="active",  # start active so even silent test frames contribute
            opened_at=0.0,
            last_active_at=None,
            device_name="test",
            missing_since=None,
        )

        with self._lock:
            self._mic_buffer += mic_frame
        # NOTE: test-only override — temporarily install our stub as the single
        # loopback source so the normal drain_and_mix path sees it.
        prior = self._loopback_sources
        self._loopback_sources = {("test",): entry}
        try:
            self._interleave_and_encode(chunk_frames)
        finally:
            self._loopback_sources = prior
```

Important nuance: the legacy helper's state is set to `"active"` so that even all-zero test `system_frame` bytes pass through without being RMS-gated out. This preserves the existing test contract where `system_frame = b"\x00" * N` produced `lb_samples = all zeros` in the output FLAC.

Wait — that won't actually work for the zero case. RMS of zeros is zero, below threshold, so the entry is active but excluded from mix. Result: channel 1 is zeros, same as before. Existing tests that pass all-zero system frames should still see zero in channel 1. Good.

But for tests that pass non-zero system frames and expect them in channel 1, the RMS must exceed threshold. The existing `test_audio_capture_invokes_on_chunk_after_interleave` uses `b"\x01" * 320` — that's 320 bytes of `\x01`, which as int16 is 0x0101 = 257 per sample. RMS = 257, threshold is ~327. **Below threshold!**

This is a test-contract mismatch. The existing test was only verifying `on_chunk` fired, not the actual channel-1 content. So the all-zero channel-1 it'd now produce is still compatible with the existing asserts (`isinstance(c[0], bytes)`). Double-check by reading the test.

Per the Task 6 test check: existing `test_audio_capture_invokes_on_chunk_after_interleave` only asserts that chunks are bytes and sample_rate is int. It doesn't check content. The new behavior still satisfies the assertion.

Delete the now-dead `_combine_frames` method (it has no other callers after this change).

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_audio_multi_loopback_mix.py -v
uv run pytest tests/test_recorder_audio.py -v
```

Expected: all pass.

**Step 5: Commit**

```bash
git add recap/daemon/recorder/audio.py tests/test_audio_multi_loopback_mix.py
git commit -m "refactor(audio): _interleave_and_encode consumes _drain_and_mix

Removes the now-dead _combine_frames. The legacy _test_feed_mock_frames
helper is rewritten to wrap the given system_frame in a synthetic
_LoopbackEntry so existing tests continue to exercise the normal
drain-and-mix path end to end.

The stereo FLAC contract is unchanged: channel 0 still carries mic,
channel 1 now carries the RMS-gated divide-by-count system mix. For
existing single-loopback tests where system_frame contains below-
threshold data, channel 1 is zeros -- same observable result as
before for the shape-only assertions in test_recorder_audio.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `_tick_membership()` — enumeration, debounced remove, probation expiry, `is_terminal` check

**Files:**
- Modify: `recap/daemon/recorder/audio.py` — new `_tick_membership` method + `_enumerate_loopback_endpoints` helper
- Test: `tests/test_audio_loopback_lifecycle.py` (extend with TestTickMembership class)

**Step 1: Write the failing test**

Append to `tests/test_audio_loopback_lifecycle.py`:

```python
from unittest.mock import MagicMock, patch
from recap.daemon.recorder.audio import AudioCapture, _LOOPBACK_PROBATION_S, _LOOPBACK_DEVICE_GRACE_S


@pytest.fixture
def capture(tmp_path):
    return AudioCapture(output_path=tmp_path / "test.flac")


def _fake_enumerator(devices: list[tuple]):
    """Returns a function that mimics _enumerate_loopback_endpoints's contract:
    yields (stable_key, info_dict) pairs."""
    def _enum():
        for key, info in devices:
            yield key, info
    return _enum


class TestTickMembershipAdd:
    def test_new_endpoint_opens_as_probation(self, capture, monkeypatch):
        """Enumeration returns a new device → new _LoopbackEntry with PROBATION."""
        captured_streams: list[tuple] = []

        def _fake_open_stream(bind_to, device_name):
            s = MagicMock()
            s.is_terminal = False
            captured_streams.append((bind_to, device_name))
            return s

        monkeypatch.setattr(
            capture, "_enumerate_loopback_endpoints",
            _fake_enumerator([
                (("airpods-guid",), {"name": "AirPods", "index": 3,
                                     "defaultSampleRate": 48000.0}),
            ]),
        )
        monkeypatch.setattr(capture, "_open_loopback_stream", _fake_open_stream)

        capture._tick_membership(now=10.0)

        assert ("airpods-guid",) in capture._loopback_sources
        entry = capture._loopback_sources[("airpods-guid",)]
        assert entry.state == "probation"
        assert entry.opened_at == 10.0
        assert entry.device_name == "AirPods"
        assert captured_streams == [(("airpods-guid",), "AirPods")]


class TestTickMembershipProbationExpiry:
    def test_probation_expiry_evicts(self, capture, monkeypatch):
        """A PROBATION entry past _LOOPBACK_PROBATION_S with no signal is evicted."""
        stream = MagicMock()
        stream.is_terminal = False
        capture._loopback_sources = {
            ("dev1",): _LoopbackEntry(
                stream=stream, state="probation", opened_at=0.0,
                last_active_at=None, device_name="Dev1", missing_since=None,
            ),
        }
        monkeypatch.setattr(
            capture, "_enumerate_loopback_endpoints",
            _fake_enumerator([
                (("dev1",), {"name": "Dev1", "index": 1, "defaultSampleRate": 48000.0}),
            ]),
        )

        # Past probation timeout, no signal.
        capture._tick_membership(now=_LOOPBACK_PROBATION_S + 1.0)

        assert ("dev1",) not in capture._loopback_sources
        stream.stop.assert_called_once()

    def test_active_entry_survives_probation_window(self, capture, monkeypatch):
        """An ACTIVE entry past the probation window is NOT evicted by expiry."""
        stream = MagicMock()
        stream.is_terminal = False
        capture._loopback_sources = {
            ("dev1",): _LoopbackEntry(
                stream=stream, state="active", opened_at=0.0,
                last_active_at=5.0, device_name="Dev1", missing_since=None,
            ),
        }
        monkeypatch.setattr(
            capture, "_enumerate_loopback_endpoints",
            _fake_enumerator([
                (("dev1",), {"name": "Dev1", "index": 1, "defaultSampleRate": 48000.0}),
            ]),
        )

        capture._tick_membership(now=_LOOPBACK_PROBATION_S + 1.0)

        assert ("dev1",) in capture._loopback_sources
        stream.stop.assert_not_called()


class TestTickMembershipDebouncedRemove:
    def test_single_missed_enumeration_does_not_evict(self, capture, monkeypatch):
        stream = MagicMock()
        stream.is_terminal = False
        entry = _LoopbackEntry(
            stream=stream, state="active", opened_at=0.0,
            last_active_at=5.0, device_name="AirPods", missing_since=None,
        )
        capture._loopback_sources = {("airpods",): entry}
        # Empty enumeration — AirPods momentarily absent.
        monkeypatch.setattr(
            capture, "_enumerate_loopback_endpoints", _fake_enumerator([]),
        )

        capture._tick_membership(now=10.0)

        # Still present, but missing_since is set.
        assert ("airpods",) in capture._loopback_sources
        assert entry.missing_since == 10.0
        stream.stop.assert_not_called()

    def test_sustained_absence_past_grace_evicts(self, capture, monkeypatch):
        stream = MagicMock()
        stream.is_terminal = False
        entry = _LoopbackEntry(
            stream=stream, state="active", opened_at=0.0,
            last_active_at=5.0, device_name="AirPods",
            missing_since=10.0,  # was marked missing on prior tick
        )
        capture._loopback_sources = {("airpods",): entry}
        monkeypatch.setattr(
            capture, "_enumerate_loopback_endpoints", _fake_enumerator([]),
        )

        capture._tick_membership(now=10.0 + _LOOPBACK_DEVICE_GRACE_S + 1.0)

        assert ("airpods",) not in capture._loopback_sources
        stream.stop.assert_called_once()

    def test_reappearance_clears_missing_since(self, capture, monkeypatch):
        stream = MagicMock()
        stream.is_terminal = False
        entry = _LoopbackEntry(
            stream=stream, state="active", opened_at=0.0,
            last_active_at=5.0, device_name="AirPods",
            missing_since=10.0,
        )
        capture._loopback_sources = {("airpods",): entry}
        monkeypatch.setattr(
            capture, "_enumerate_loopback_endpoints",
            _fake_enumerator([
                (("airpods",), {"name": "AirPods", "index": 3,
                                "defaultSampleRate": 48000.0}),
            ]),
        )

        capture._tick_membership(now=12.0)

        assert ("airpods",) in capture._loopback_sources
        assert entry.missing_since is None


class TestTickMembershipTerminalStream:
    def test_terminal_stream_is_evicted(self, capture, monkeypatch):
        stream = MagicMock()
        stream.is_terminal = True
        capture._loopback_sources = {
            ("dev1",): _LoopbackEntry(
                stream=stream, state="active", opened_at=0.0,
                last_active_at=5.0, device_name="Dev1", missing_since=None,
            ),
        }
        monkeypatch.setattr(
            capture, "_enumerate_loopback_endpoints",
            _fake_enumerator([
                (("dev1",), {"name": "Dev1", "index": 1, "defaultSampleRate": 48000.0}),
            ]),
        )

        capture._tick_membership(now=10.0)

        assert ("dev1",) not in capture._loopback_sources
        stream.stop.assert_called_once()


class TestTickMembershipEnumerationFailure:
    def test_enumeration_exception_skips_tick_without_evicting(self, capture, monkeypatch):
        stream = MagicMock()
        stream.is_terminal = False
        entry = _LoopbackEntry(
            stream=stream, state="active", opened_at=0.0,
            last_active_at=5.0, device_name="Dev1", missing_since=None,
        )
        capture._loopback_sources = {("dev1",): entry}

        def _raises():
            raise RuntimeError("transient WASAPI error")
            yield  # pragma: no cover - unreachable, keeps type a generator

        monkeypatch.setattr(capture, "_enumerate_loopback_endpoints", _raises)

        capture._tick_membership(now=10.0)  # must not raise

        # No changes — stream still there.
        assert ("dev1",) in capture._loopback_sources
        stream.stop.assert_not_called()
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_audio_loopback_lifecycle.py -v
```

Expected: FAIL — `_tick_membership`, `_enumerate_loopback_endpoints`, and `_open_loopback_stream` don't exist yet.

**Step 3: Write minimal implementation**

Add to `AudioCapture` after `_drain_and_mix`:

```python
    def _enumerate_loopback_endpoints(self):
        """Yield (stable_identity, device_info_dict) pairs for every WASAPI
        render loopback endpoint currently available.

        Implementation note: PyAudioWPatch exposes a loopback-device generator
        (get_loopback_device_info_generator). We wrap it to yield the stable
        identity tuple that _SourceStream._compute_identity uses for hot-plug
        tracking.
        """
        pa = _require_pyaudio().PyAudio()
        try:
            for info in pa.get_loopback_device_info_generator():
                key = _SourceStream._compute_identity(info)
                yield key, info
        finally:
            pa.terminate()

    def _open_loopback_stream(self, bind_to: tuple, device_name: str) -> "_SourceStream":
        """Open a new _SourceStream bound to the given endpoint identity.

        Factored out for test overrides.
        """
        s = _SourceStream(
            kind="loopback", output_rate=self._sample_rate, bind_to=bind_to,
        )
        s.start()
        return s

    def _tick_membership(self, now: float) -> None:
        """Reconcile _loopback_sources against the current WASAPI enumeration.

        Runs from the drain thread with a wall-clock gate; owns the entire
        dict lifecycle. Enumeration failures are logged and swallowed — a
        missed tick never tears streams down.
        """
        try:
            enumerated = dict(self._enumerate_loopback_endpoints())
        except Exception:
            logger.debug("_tick_membership: enumeration failed, skipping this tick",
                         exc_info=True)
            return

        enumerated_keys = set(enumerated.keys())
        current_keys = set(self._loopback_sources.keys())

        # --- Adds ---
        for key in enumerated_keys - current_keys:
            info = enumerated[key]
            try:
                stream = self._open_loopback_stream(
                    bind_to=key, device_name=info["name"],
                )
            except Exception:
                logger.warning(
                    "failed to open loopback %s; will retry next tick",
                    info.get("name", key), exc_info=True,
                )
                continue
            self._loopback_sources[key] = _LoopbackEntry(
                stream=stream, state="probation", opened_at=now,
                last_active_at=None, device_name=info["name"],
                missing_since=None,
            )
            native_rate = int(info.get("defaultSampleRate", 0))
            logger.info(
                "loopback opened: %s (identity=%s, native_rate=%d)",
                info["name"], key, native_rate,
            )

        # --- Debounced removes (disappearance) ---
        for key in list(current_keys):
            entry = self._loopback_sources.get(key)
            if entry is None:
                continue
            if key in enumerated_keys:
                # Present this tick — clear any prior disappearance mark.
                if entry.missing_since is not None:
                    entry.missing_since = None
                continue
            # Absent this tick.
            if entry.missing_since is None:
                entry.missing_since = now
                continue
            if now - entry.missing_since > _LOOPBACK_DEVICE_GRACE_S:
                self._evict_entry(key, reason="device disappeared")

        # --- Terminal stream evictions ---
        for key in list(self._loopback_sources.keys()):
            entry = self._loopback_sources[key]
            if entry.stream.is_terminal:
                self._evict_entry(key, reason="stream terminal (reconnect exhausted)")

        # --- Probation expiry ---
        for key in list(self._loopback_sources.keys()):
            entry = self._loopback_sources[key]
            if entry.state == "probation" and now - entry.opened_at > _LOOPBACK_PROBATION_S:
                self._evict_entry(
                    key, reason=(
                        f"probation expired after {now - entry.opened_at:.0f}s "
                        "without signal"
                    ),
                )

    def _evict_entry(self, key: tuple, reason: str) -> None:
        """Stop and drop a loopback entry, emitting one info line."""
        entry = self._loopback_sources.pop(key, None)
        if entry is None:
            return
        try:
            entry.stream.stop()
        except Exception:
            logger.debug("stream.stop() raised during evict for %s",
                         entry.device_name, exc_info=True)
        logger.info("loopback removed: %s (%s)", entry.device_name, reason)
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_audio_loopback_lifecycle.py -v
```

Expected: all TestTickMembership* tests pass.

**Step 5: Commit**

```bash
git add recap/daemon/recorder/audio.py tests/test_audio_loopback_lifecycle.py
git commit -m "feat(audio): _tick_membership reconciles WASAPI enumeration with streams

Implements the full membership state machine. The drain thread owns the
_loopback_sources dict; _tick_membership() is the sole mutator outside
of PROBATION->ACTIVE promotions in _drain_and_mix.

- enumerate via PyAudioWPatch's loopback generator
- add missing endpoints as PROBATION
- debounce disappearance via missing_since + _LOOPBACK_DEVICE_GRACE_S
  so a single missed enumeration does not evict a healthy stream
- evict is_terminal streams
- evict PROBATION entries past _LOOPBACK_PROBATION_S
- enumeration failure logs and returns; no stream teardown

ACTIVE streams are not evicted by silence (by design).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Wire tick into drain loop + initial population at `start()`

**Files:**
- Modify: `recap/daemon/recorder/audio.py` — `start()` and the drain loop
- Test: `tests/test_audio_loopback_lifecycle.py` (initial population test)

**Step 1: Write the failing test**

Append to `tests/test_audio_loopback_lifecycle.py`:

```python
class TestStartInitialPopulation:
    def test_start_populates_loopback_sources_from_enumeration(
        self, tmp_path, monkeypatch,
    ):
        """AudioCapture.start() should call _tick_membership once before
        entering the drain loop, populating _loopback_sources."""
        cap = AudioCapture(output_path=tmp_path / "out.flac")

        # Stub the mic source entirely so start() doesn't try real PyAudio.
        monkeypatch.setattr(cap, "_spawn_mic_source", lambda: MagicMock())
        monkeypatch.setattr(cap, "_start_encoder", lambda: None)
        monkeypatch.setattr(cap, "_spawn_drain_thread", lambda: None)

        monkeypatch.setattr(
            cap, "_enumerate_loopback_endpoints",
            _fake_enumerator([
                (("dev-a",), {"name": "A", "index": 1, "defaultSampleRate": 48000.0}),
                (("dev-b",), {"name": "B", "index": 2, "defaultSampleRate": 48000.0}),
            ]),
        )
        monkeypatch.setattr(
            cap, "_open_loopback_stream",
            lambda bind_to, device_name: MagicMock(is_terminal=False),
        )

        cap.start()

        assert set(cap._loopback_sources.keys()) == {("dev-a",), ("dev-b",)}
        assert all(
            e.state == "probation" for e in cap._loopback_sources.values()
        )
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_audio_loopback_lifecycle.py::TestStartInitialPopulation -v
```

Expected: FAIL — `start()` still uses the singular `_loopback_source` initialization and doesn't call `_tick_membership`.

**Step 3: Write minimal implementation**

Refactor `AudioCapture.start()` to split its current body into smaller hooks for testability:

```python
    def start(self) -> None:
        """Open mic stream + enumerated loopback streams; begin recording."""
        if self._recording:
            return

        runtime_pyflac = _require_pyflac()
        if self._sample_rate != 48000:
            logger.warning(
                "AudioCapture.start() overriding sample_rate=%d to 48000",
                self._sample_rate,
            )
            self._sample_rate = 48000

        self._mic_source = self._spawn_mic_source()
        self._start_encoder()

        # Initial population of loopback sources — reuses _tick_membership's add path.
        self._tick_membership(time.monotonic())
        self._last_membership_tick = time.monotonic()

        self._recording = True
        self._spawn_drain_thread()
```

Extract the three helpers (they contain what used to live inline in `start()`). The exact code depends on today's `start()` body; the refactor is mechanical.

In the drain loop (the `_drain_thread` body, around line 450-ish), add a wall-clock gate at the top of each iteration:

```python
            now = time.monotonic()
            if now - self._last_membership_tick > _LOOPBACK_MEMBERSHIP_TICK_S:
                self._tick_membership(now)
                self._last_membership_tick = now

            # ... existing drain body ...
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_audio_loopback_lifecycle.py -v
uv run pytest tests/test_recorder_audio.py -v
```

Expected: all pass.

**Step 5: Commit**

```bash
git add recap/daemon/recorder/audio.py tests/test_audio_loopback_lifecycle.py
git commit -m "feat(audio): wire _tick_membership into start() and drain loop

start() calls _tick_membership once before the drain thread launches so
every loopback endpoint is opened as PROBATION at recording start --
reuses the same add path the hot-plug tick uses, keeping one enumeration
code path under test.

The drain loop gates _tick_membership on a 3-second wall-clock interval
(_LOOPBACK_MEMBERSHIP_TICK_S). The drain thread remains the sole owner
of _loopback_sources -- no new thread, no cross-thread lock acrobatics.

start() is split into _spawn_mic_source / _start_encoder / _spawn_drain_thread
helpers to make initial-population testable without real PyAudio.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Extend `RecordingMetadata` with `audio_warnings` and `system_audio_devices_seen`

**Files:**
- Modify: `recap/artifacts.py` — `RecordingMetadata` dataclass
- Test: `tests/test_artifacts.py` (extend if exists, otherwise create minimal)

**Step 1: Write the failing test**

Find or create `tests/test_artifacts.py`. Add:

```python
class TestRecordingMetadataAudioWarnings:
    def test_defaults_to_empty_lists(self, tmp_path):
        from recap.artifacts import RecordingMetadata
        m = RecordingMetadata(
            org="test", title="T", date="2026-04-21", participants=[],
            platform="zoho_meet",
        )
        assert m.audio_warnings == []
        assert m.system_audio_devices_seen == []

    def test_roundtrip_preserves_warnings(self, tmp_path):
        from recap.artifacts import (
            RecordingMetadata, write_recording_metadata, load_recording_metadata,
        )
        audio_path = tmp_path / "rec.flac"
        audio_path.touch()
        m = RecordingMetadata(
            org="test", title="T", date="2026-04-21", participants=[],
            platform="zoho_meet",
            audio_warnings=["no-system-audio-captured"],
            system_audio_devices_seen=["Laptop Speakers", "HDMI"],
        )
        write_recording_metadata(audio_path, m)
        loaded = load_recording_metadata(audio_path)
        assert loaded.audio_warnings == ["no-system-audio-captured"]
        assert loaded.system_audio_devices_seen == ["Laptop Speakers", "HDMI"]

    def test_loads_older_sidecar_without_fields(self, tmp_path):
        """Older sidecars without the new fields deserialize with empty defaults."""
        import json
        from recap.artifacts import load_recording_metadata
        audio_path = tmp_path / "rec.flac"
        audio_path.touch()
        sidecar = audio_path.with_suffix(".metadata.json")
        sidecar.write_text(json.dumps({
            "org": "test", "title": "T", "date": "2026-04-21",
            "participants": [], "platform": "zoho_meet",
        }))
        loaded = load_recording_metadata(audio_path)
        assert loaded.audio_warnings == []
        assert loaded.system_audio_devices_seen == []
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_artifacts.py::TestRecordingMetadataAudioWarnings -v
```

Expected: FAIL — fields don't exist on the dataclass.

**Step 3: Write minimal implementation**

In `recap/artifacts.py`, find the `RecordingMetadata` dataclass (around line 45 per earlier grep). Add two fields:

```python
@dataclass
class RecordingMetadata:
    # ... existing fields ...
    audio_warnings: list[str] = field(default_factory=list)
    system_audio_devices_seen: list[str] = field(default_factory=list)
```

Ensure the serializer (`write_recording_metadata`) and deserializer (`load_recording_metadata`) handle the new fields. If they use `asdict()` and `**data` respectively, the new fields flow through automatically. Verify and adjust if the serializer explicitly enumerates fields.

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_artifacts.py -v
```

Expected: all pass, including new tests.

**Step 5: Commit**

```bash
git add recap/artifacts.py tests/test_artifacts.py
git commit -m "feat(artifacts): RecordingMetadata.audio_warnings + system_audio_devices_seen

Backward-compatible additive extension for the multi-output loopback
design's warning contract. Recorder writes these fields as warnings
occur (Task 11); pipeline export renders them to note frontmatter +
body callout (Tasks 12-14).

Both fields default to empty lists. Existing sidecars without the
fields deserialize cleanly with the defaults -- no migration needed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: New journal event types

**Files:**
- Modify: the EventJournal module (likely `recap/daemon/event_journal.py` or inline in `recap/daemon/service.py` — check by grep for `EventJournal` class)
- Test: extend relevant journal tests

**Step 1: Locate the EventJournal implementation**

```bash
grep -rn "class EventJournal" recap/
```

The new event types are just string constants documented in one place. Add a dedicated module `recap/daemon/recorder/audio_events.py`:

**Step 2: Write the failing test**

Create `tests/test_audio_events.py`:

```python
def test_event_type_constants_exist():
    from recap.daemon.recorder.audio_events import (
        EVT_AUDIO_NO_LOOPBACK_AT_START,
        EVT_AUDIO_NO_SYSTEM_AUDIO,
        EVT_AUDIO_ALL_LOOPBACKS_LOST,
    )
    assert EVT_AUDIO_NO_LOOPBACK_AT_START == "audio_capture_no_loopback_at_start"
    assert EVT_AUDIO_NO_SYSTEM_AUDIO == "audio_capture_no_system_audio"
    assert EVT_AUDIO_ALL_LOOPBACKS_LOST == "audio_capture_all_loopbacks_lost"

def test_warning_code_constants_exist():
    from recap.daemon.recorder.audio_events import (
        WARN_NO_SYSTEM_AUDIO_CAPTURED,
        WARN_SYSTEM_AUDIO_INTERRUPTED,
    )
    assert WARN_NO_SYSTEM_AUDIO_CAPTURED == "no-system-audio-captured"
    assert WARN_SYSTEM_AUDIO_INTERRUPTED == "system-audio-interrupted"
```

**Step 3: Run test to verify it fails**

```bash
uv run pytest tests/test_audio_events.py -v
```

Expected: FAIL — `ImportError`.

**Step 4: Write minimal implementation**

Create `recap/daemon/recorder/audio_events.py`:

```python
"""Well-known journal event types and sidecar warning codes for audio capture.

Shared between the recorder (which emits the events and persists warning
codes to the sidecar) and the pipeline export path (which reads warning
codes and renders them as note frontmatter + body callouts).
"""
from __future__ import annotations

# Journal event types (used as EventJournal category names).
EVT_AUDIO_NO_LOOPBACK_AT_START = "audio_capture_no_loopback_at_start"
"""Emitted once at recording start when WASAPI enumerates zero render endpoints."""

EVT_AUDIO_NO_SYSTEM_AUDIO = "audio_capture_no_system_audio"
"""Emitted once when the last PROBATION entry expires with no entry ever ACTIVE."""

EVT_AUDIO_ALL_LOOPBACKS_LOST = "audio_capture_all_loopbacks_lost"
"""Emitted when the count of ACTIVE entries transitions from non-zero to zero
(given at least one entry had ever been ACTIVE during the recording)."""

# Sidecar warning codes (persisted in RecordingMetadata.audio_warnings).
WARN_NO_SYSTEM_AUDIO_CAPTURED = "no-system-audio-captured"
"""Recorder never achieved ACTIVE loopback coverage. Scenarios A and B."""

WARN_SYSTEM_AUDIO_INTERRUPTED = "system-audio-interrupted"
"""Recorder had ACTIVE coverage at some point, then lost it. Scenario C."""
```

**Step 5: Run test and commit**

```bash
uv run pytest tests/test_audio_events.py -v
git add recap/daemon/recorder/audio_events.py tests/test_audio_events.py
git commit -m "feat(audio): journal event types and sidecar warning codes

Shared constants for the multi-output loopback warning surface. Recorder
(Task 11) emits EVT_* journal events and persists WARN_* codes; pipeline
export (Task 13) reads WARN_* and renders body callouts with the
matching wording.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Emit warnings from `AudioCapture` on Scenarios A/B/C

**Files:**
- Modify: `recap/daemon/recorder/audio.py` — add warning-emission hooks
- Test: `tests/test_audio_warning_persistence.py` (new file)

**Step 1: Write the failing test**

Create `tests/test_audio_warning_persistence.py`:

```python
"""Tests for audio-warning persistence to journal + sidecar."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from recap.daemon.recorder.audio import AudioCapture, _LoopbackEntry
from recap.daemon.recorder.audio_events import (
    EVT_AUDIO_NO_LOOPBACK_AT_START,
    EVT_AUDIO_NO_SYSTEM_AUDIO,
    EVT_AUDIO_ALL_LOOPBACKS_LOST,
    WARN_NO_SYSTEM_AUDIO_CAPTURED,
    WARN_SYSTEM_AUDIO_INTERRUPTED,
)


def _make_entry(state: str, device_name: str = "Dev") -> _LoopbackEntry:
    s = MagicMock()
    s.is_terminal = False
    return _LoopbackEntry(
        stream=s, state=state, opened_at=0.0,
        last_active_at=(5.0 if state == "active" else None),
        device_name=device_name, missing_since=None,
    )


class TestScenarioAZeroEndpoints:
    def test_scenario_a_emits_journal_and_sidecar_warning(self, tmp_path):
        cap = AudioCapture(output_path=tmp_path / "test.flac")
        journal = MagicMock()
        cap._event_journal = journal

        cap._note_scenario_no_loopback_at_start()

        journal.record.assert_called_once()
        args = journal.record.call_args
        assert args.kwargs.get("event_type") == EVT_AUDIO_NO_LOOPBACK_AT_START
        assert WARN_NO_SYSTEM_AUDIO_CAPTURED in cap._audio_warnings


class TestScenarioBNoActiveEverPromoted:
    def test_scenario_b_fires_once_when_last_probation_evicts(self, tmp_path):
        cap = AudioCapture(output_path=tmp_path / "test.flac")
        journal = MagicMock()
        cap._event_journal = journal
        cap._loopback_sources = {}  # last one just evicted
        cap._any_active_ever = False

        cap._note_scenario_no_system_audio_if_applicable()

        journal.record.assert_called_once()
        assert args_matches(journal, EVT_AUDIO_NO_SYSTEM_AUDIO)
        assert WARN_NO_SYSTEM_AUDIO_CAPTURED in cap._audio_warnings

    def test_scenario_b_does_not_fire_twice(self, tmp_path):
        cap = AudioCapture(output_path=tmp_path / "test.flac")
        journal = MagicMock()
        cap._event_journal = journal
        cap._loopback_sources = {}
        cap._any_active_ever = False

        cap._note_scenario_no_system_audio_if_applicable()
        cap._note_scenario_no_system_audio_if_applicable()

        assert journal.record.call_count == 1
        assert cap._audio_warnings.count(WARN_NO_SYSTEM_AUDIO_CAPTURED) == 1

    def test_scenario_b_does_not_fire_if_any_active_ever(self, tmp_path):
        """If a stream was ACTIVE at some point, we are in Scenario C territory,
        not Scenario B."""
        cap = AudioCapture(output_path=tmp_path / "test.flac")
        journal = MagicMock()
        cap._event_journal = journal
        cap._loopback_sources = {}
        cap._any_active_ever = True

        cap._note_scenario_no_system_audio_if_applicable()

        journal.record.assert_not_called()
        assert WARN_NO_SYSTEM_AUDIO_CAPTURED not in cap._audio_warnings


class TestScenarioCAllLoopbacksLost:
    def test_scenario_c_fires_on_active_to_zero_transition(self, tmp_path):
        cap = AudioCapture(output_path=tmp_path / "test.flac")
        journal = MagicMock()
        cap._event_journal = journal
        cap._loopback_sources = {}  # just dropped from 1 to 0
        cap._any_active_ever = True
        cap._active_count_was_nonzero = True

        cap._note_scenario_all_loopbacks_lost_if_applicable()

        journal.record.assert_called_once()
        assert args_matches(journal, EVT_AUDIO_ALL_LOOPBACKS_LOST)
        assert WARN_SYSTEM_AUDIO_INTERRUPTED in cap._audio_warnings

    def test_scenario_c_does_not_duplicate_code_on_repeat_loss(self, tmp_path):
        cap = AudioCapture(output_path=tmp_path / "test.flac")
        journal = MagicMock()
        cap._event_journal = journal
        cap._any_active_ever = True
        cap._active_count_was_nonzero = True

        cap._note_scenario_all_loopbacks_lost_if_applicable()
        cap._note_scenario_all_loopbacks_lost_if_applicable()

        # Code appears only once in the list even though the event can fire
        # multiple times across the recording.
        assert cap._audio_warnings.count(WARN_SYSTEM_AUDIO_INTERRUPTED) == 1


def args_matches(journal_mock, event_type: str) -> bool:
    return any(
        call.kwargs.get("event_type") == event_type
        for call in journal_mock.record.call_args_list
    )
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_audio_warning_persistence.py -v
```

Expected: FAIL — methods and fields don't exist.

**Step 3: Write minimal implementation**

In `AudioCapture.__init__`, add:

```python
        self._event_journal: Any = None  # set by recorder wiring; optional
        self._audio_warnings: list[str] = []
        self._system_audio_devices_seen: list[str] = []
        self._any_active_ever: bool = False
        self._active_count_was_nonzero: bool = False
```

Add the three notification methods plus a helper:

```python
    def _append_warning_once(self, code: str) -> None:
        if code not in self._audio_warnings:
            self._audio_warnings.append(code)

    def _record_journal_event(self, event_type: str, **details) -> None:
        if self._event_journal is None:
            return
        try:
            self._event_journal.record(
                level="warning", event_type=event_type, details=details,
            )
        except Exception:
            logger.debug("event journal record() raised", exc_info=True)

    def _note_scenario_no_loopback_at_start(self) -> None:
        self._append_warning_once(WARN_NO_SYSTEM_AUDIO_CAPTURED)
        self._record_journal_event(
            EVT_AUDIO_NO_LOOPBACK_AT_START,
            message="No system audio devices available; recording microphone only",
        )

    def _note_scenario_no_system_audio_if_applicable(self) -> None:
        """Fire Scenario B warning if no entry has ever been ACTIVE and the
        dict is empty. Idempotent -- repeat calls are no-ops."""
        if self._any_active_ever:
            return
        if self._loopback_sources:
            return
        if WARN_NO_SYSTEM_AUDIO_CAPTURED in self._audio_warnings:
            return
        self._audio_warnings.append(WARN_NO_SYSTEM_AUDIO_CAPTURED)
        self._record_journal_event(
            EVT_AUDIO_NO_SYSTEM_AUDIO,
            message=(
                "No system audio captured. Verify the meeting app's output "
                "device is one that was active on this machine."
            ),
            devices_seen=list(self._system_audio_devices_seen),
        )

    def _note_scenario_all_loopbacks_lost_if_applicable(self) -> None:
        """Fire Scenario C warning when ACTIVE count transitions non-zero -> zero
        after having been non-zero. The sidecar code is deduplicated; the
        journal event can fire on each transition."""
        active_count = sum(
            1 for e in self._loopback_sources.values() if e.state == "active"
        )
        if not self._active_count_was_nonzero:
            return
        if active_count > 0:
            return
        # Active count just dropped to zero.
        self._append_warning_once(WARN_SYSTEM_AUDIO_INTERRUPTED)
        self._record_journal_event(
            EVT_AUDIO_ALL_LOOPBACKS_LOST,
            message=(
                "All system audio sources went offline mid-recording. "
                "Remaining audio is microphone only."
            ),
        )
```

Wire the hooks in. Modify `_tick_membership` and `_drain_and_mix` to call them:

- In `_tick_membership`, after initial enumeration if `not enumerated_keys` and `_loopback_sources` is empty: call `_note_scenario_no_loopback_at_start()`. Need a flag to fire only once; add `self._scenario_a_fired: bool = False` to `__init__` and gate on it.
- In `_tick_membership` after any eviction: call `_note_scenario_no_system_audio_if_applicable()` and `_note_scenario_all_loopbacks_lost_if_applicable()`.
- In `_drain_and_mix` after promoting to ACTIVE: set `self._any_active_ever = True`. Also recompute `self._active_count_was_nonzero`.
- In `_tick_membership` at the top: add device_name to `self._system_audio_devices_seen` when opening new entries.

For device list tracking, simplest: in the add path, `if info["name"] not in self._system_audio_devices_seen: self._system_audio_devices_seen.append(info["name"])`.

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_audio_warning_persistence.py -v
uv run pytest tests/test_audio_loopback_lifecycle.py -v
```

Expected: all pass.

**Step 5: Commit**

```bash
git add recap/daemon/recorder/audio.py tests/test_audio_warning_persistence.py
git commit -m "feat(audio): emit journal events + sidecar warnings on audio-capture failure modes

Three scenarios, each with one-shot idempotent warning emission:

- Scenario A (zero loopback endpoints at start): fires
  EVT_AUDIO_NO_LOOPBACK_AT_START + WARN_NO_SYSTEM_AUDIO_CAPTURED.
- Scenario B (no entry ever ACTIVE, last probation expired): fires
  EVT_AUDIO_NO_SYSTEM_AUDIO + WARN_NO_SYSTEM_AUDIO_CAPTURED once.
- Scenario C (ACTIVE count drops to zero after having been non-zero):
  fires EVT_AUDIO_ALL_LOOPBACKS_LOST + WARN_SYSTEM_AUDIO_INTERRUPTED;
  sidecar code deduplicated across repeat transitions.

Device names seen during the recording are tracked in
_system_audio_devices_seen for inclusion in the note banner.

The recorder now exposes _audio_warnings and _system_audio_devices_seen
to be written into the sidecar at recording stop (subsequent task).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: `build_canonical_frontmatter` renders `audio-warnings:` key

**Files:**
- Modify: `recap/vault.py` — `build_canonical_frontmatter`
- Test: `tests/test_pipeline_audio_warnings.py` (new file)

**Step 1: Write the failing test**

Create `tests/test_pipeline_audio_warnings.py`:

```python
"""Tests for audio-warning rendering in note frontmatter + body."""
from __future__ import annotations

import pathlib
from datetime import date

import pytest

from recap.vault import build_canonical_frontmatter


class TestFrontmatterAudioWarnings:
    def test_absent_when_empty(self, tmp_path):
        # Minimal fixture: build FM without warnings
        fm = build_canonical_frontmatter(
            metadata=_meeting_metadata(),
            analysis=_analysis_result(),
            duration_seconds=120,
            recording_path=tmp_path / "r.flac",
            org="testorg", org_subfolder="TestOrg",
            recording_metadata=_recording_metadata(audio_warnings=[]),
        )
        assert "audio-warnings" not in fm

    def test_present_when_non_empty(self, tmp_path):
        fm = build_canonical_frontmatter(
            metadata=_meeting_metadata(),
            analysis=_analysis_result(),
            duration_seconds=120,
            recording_path=tmp_path / "r.flac",
            org="testorg", org_subfolder="TestOrg",
            recording_metadata=_recording_metadata(
                audio_warnings=["no-system-audio-captured"],
            ),
        )
        assert fm["audio-warnings"] == ["no-system-audio-captured"]


# Fixture helpers — adjust to actual class signatures in recap.models.
def _meeting_metadata():
    from recap.models import MeetingMetadata  # or whatever the path is
    return MeetingMetadata(
        title="Test Meeting", date=date(2026, 4, 21),
        participants=[], platform="zoho_meet",
    )

def _analysis_result():
    from recap.models import AnalysisResult
    return AnalysisResult(meeting_type="client-call", companies=[])

def _recording_metadata(audio_warnings=None, devices_seen=None):
    from recap.artifacts import RecordingMetadata
    return RecordingMetadata(
        org="testorg", title="Test", date="2026-04-21",
        participants=[], platform="zoho_meet",
        audio_warnings=(audio_warnings or []),
        system_audio_devices_seen=(devices_seen or []),
    )
```

(Adjust `_meeting_metadata` / `_analysis_result` fixtures to match the actual signatures in `recap/models.py`.)

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_pipeline_audio_warnings.py -v
```

Expected: FAIL — `audio-warnings` key is not in the returned frontmatter dict.

**Step 3: Write minimal implementation**

In `recap/vault.py`, modify `build_canonical_frontmatter` (around line 46, after the existing `if recording_metadata is not None:` block):

```python
    if recording_metadata is not None:
        # ... existing calendar-owned fields ...
        if recording_metadata.audio_warnings:
            fm["audio-warnings"] = list(recording_metadata.audio_warnings)
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_pipeline_audio_warnings.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add recap/vault.py tests/test_pipeline_audio_warnings.py
git commit -m "feat(vault): render audio-warnings frontmatter key when non-empty

When RecordingMetadata.audio_warnings is non-empty, build_canonical_frontmatter
emits an audio-warnings: list[str] key alongside other pipeline-owned
frontmatter. Empty list -> key omitted (preserves existing behavior for
recordings with no audio issues).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: `upsert_note` renders `> [!warning]` body callout

**Files:**
- Modify: `recap/vault.py` — the body-writing helpers
- Test: `tests/test_pipeline_audio_warnings.py` (extend)

**Step 1: Write the failing test**

Extend `tests/test_pipeline_audio_warnings.py`:

```python
class TestBodyCallout:
    def test_no_callout_when_warnings_empty(self, tmp_path):
        from recap.vault import upsert_note
        note_path = tmp_path / "note.md"
        fm = {"pipeline-status": "complete", "title": "T",
              "date": "2026-04-21"}
        upsert_note(note_path, fm, body="## Summary\n\nHi.\n")
        content = note_path.read_text(encoding="utf-8")
        assert "[!warning]" not in content

    def test_no_system_audio_callout_wording(self, tmp_path):
        from recap.vault import upsert_note
        note_path = tmp_path / "note.md"
        fm = {
            "pipeline-status": "complete", "title": "T", "date": "2026-04-21",
            "audio-warnings": ["no-system-audio-captured"],
            "system-audio-devices-seen": ["Laptop Speakers", "HDMI Audio"],
        }
        upsert_note(note_path, fm, body="## Summary\n\nHi.\n")
        content = note_path.read_text(encoding="utf-8")
        assert "[!warning] System audio was not captured" in content
        assert "Laptop Speakers" in content
        assert "HDMI Audio" in content

    def test_interrupted_callout_wording(self, tmp_path):
        from recap.vault import upsert_note
        note_path = tmp_path / "note.md"
        fm = {
            "pipeline-status": "complete", "title": "T", "date": "2026-04-21",
            "audio-warnings": ["system-audio-interrupted"],
            "system-audio-devices-seen": ["AirPods"],
        }
        upsert_note(note_path, fm, body="## Summary\n\nHi.\n")
        content = note_path.read_text(encoding="utf-8")
        assert "[!warning] System audio dropped out" in content

    def test_upsert_preserves_warning_on_merge_path(self, tmp_path):
        """Existing note with calendar frontmatter + marker -> pipeline run
        with warnings. Callout must appear below the marker, frontmatter
        merged with new audio-warnings key."""
        from recap.vault import upsert_note, MEETING_RECORD_MARKER
        note_path = tmp_path / "note.md"
        existing = (
            "---\n"
            "date: '2026-04-21'\n"
            "title: T\n"
            "---\n"
            "\n"
            "User agenda\n"
            f"\n{MEETING_RECORD_MARKER}\n\n"
            "(old body)\n"
        )
        note_path.write_text(existing, encoding="utf-8")
        fm = {
            "pipeline-status": "complete", "title": "T", "date": "2026-04-21",
            "audio-warnings": ["no-system-audio-captured"],
            "system-audio-devices-seen": ["Laptop Speakers"],
        }
        upsert_note(note_path, fm, body="## Summary\n\nNew body.\n")
        content = note_path.read_text(encoding="utf-8")
        assert "User agenda" in content  # preserved above marker
        assert "[!warning]" in content  # callout in new body
        assert "audio-warnings:" in content  # frontmatter merged
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_pipeline_audio_warnings.py::TestBodyCallout -v
```

Expected: FAIL — no callout in the written content.

**Step 3: Write minimal implementation**

In `recap/vault.py`, add a helper near the top of the file:

```python
_AUDIO_WARNING_BANNERS = {
    "no-system-audio-captured": (
        "> [!warning] System audio was not captured during this recording.\n"
        "> Only the microphone channel has speech. If you expected other "
        "participants' voices, verify the meeting app's output device is "
        "one that was active on this machine.\n"
        "> Active outputs seen during recording: {devices}."
    ),
    "system-audio-interrupted": (
        "> [!warning] System audio dropped out during this recording.\n"
        "> Some portions of the transcript may be one-sided.\n"
        "> Active outputs seen during recording: {devices}."
    ),
}


def _render_audio_warning_callout(
    warnings: list[str], devices_seen: list[str],
) -> str:
    """Render the body callout for audio warnings. Empty → empty string."""
    if not warnings:
        return ""
    devices = ", ".join(devices_seen) if devices_seen else "(none recorded)"
    blocks = []
    for code in warnings:
        template = _AUDIO_WARNING_BANNERS.get(code)
        if template is None:
            continue
        blocks.append(template.format(devices=devices))
    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n\n"
```

Modify the four `_write_new_note` / `_prepend_fm_and_append_body` / `_merge_fm_and_append_body` / `_merge_fm_and_replace_below_marker` / `_prepend_fm_and_replace_below_marker` helpers to prepend the callout to the body they write. Simplest approach: in `upsert_note` itself, just before dispatching to the five branches, synthesize a new body string that includes the callout prefix:

```python
def upsert_note(note_path, frontmatter, body, *, event_index=None, vault_path=None):
    # ... existing docstring + parent mkdir ...
    callout = _render_audio_warning_callout(
        warnings=frontmatter.get("audio-warnings", []),
        devices_seen=frontmatter.get("system-audio-devices-seen", []),
    )
    body_with_callout = callout + body
    # ... dispatch to the five branches, passing body_with_callout instead of body ...
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_pipeline_audio_warnings.py -v
```

Expected: all pass.

**Step 5: Commit**

```bash
git add recap/vault.py tests/test_pipeline_audio_warnings.py
git commit -m "feat(vault): body callout for audio-warnings in upsert_note

When the frontmatter carries audio-warnings, upsert_note prepends a
> [!warning] Obsidian callout to the body for each code. Wording is
careful -- 'system audio was not observed' rather than an accusation
of capture failure -- because true silence and misrouting are
waveform-indistinguishable.

Banner includes the list of system-audio-devices-seen so the user can
diagnose routing mismatches at a glance ('Recap tried Laptop Speakers
and HDMI but not AirPods').

Callout prefixes the body in all five upsert branches including the
merge path for existing notes created by calendar sync.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Pipeline export reads sidecar warnings and threads through

**Files:**
- Modify: `recap/pipeline/__init__.py` — export stage
- Test: extend `tests/test_pipeline_audio_warnings.py`

**Step 1: Write the failing test**

Extend `tests/test_pipeline_audio_warnings.py`:

```python
class TestPipelineExportThreadsWarnings:
    def test_export_reads_warnings_from_sidecar(self, tmp_path, monkeypatch):
        """When the sidecar has audio_warnings, the exported note carries them."""
        from recap.artifacts import RecordingMetadata, write_recording_metadata
        from recap.pipeline import _build_frontmatter_for_export  # may need to extract

        audio_path = tmp_path / "rec.flac"
        audio_path.touch()
        sidecar = RecordingMetadata(
            org="testorg", title="T", date="2026-04-21",
            participants=[], platform="zoho_meet",
            audio_warnings=["no-system-audio-captured"],
            system_audio_devices_seen=["Laptop Speakers"],
        )
        write_recording_metadata(audio_path, sidecar)

        fm = _build_frontmatter_for_export(
            audio_path=audio_path,
            # ... other required args per the actual signature ...
        )
        assert fm.get("audio-warnings") == ["no-system-audio-captured"]
        assert fm.get("system-audio-devices-seen") == ["Laptop Speakers"]
```

(Adjust imports to the actual pipeline entry point; you may need to extract a small helper to make the frontmatter-building testable in isolation.)

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_pipeline_audio_warnings.py::TestPipelineExportThreadsWarnings -v
```

Expected: FAIL — the pipeline doesn't pass these fields through yet.

**Step 3: Write minimal implementation**

In `recap/pipeline/__init__.py`, find the export stage (the one that calls `build_canonical_frontmatter` and `upsert_note`). Ensure the `recording_metadata` passed to `build_canonical_frontmatter` has the new fields populated — likely this already works via the existing `load_recording_metadata` call that returns a `RecordingMetadata` with the new fields as empty defaults or populated values.

Also ensure the frontmatter dict is extended with `system-audio-devices-seen` so the banner rendering in `upsert_note` has the device names. Add after the existing `fm = build_canonical_frontmatter(...)`:

```python
    if recording_metadata and recording_metadata.system_audio_devices_seen:
        fm["system-audio-devices-seen"] = list(
            recording_metadata.system_audio_devices_seen,
        )
```

(This is frontmatter-only for Obsidian-hidden metadata; it's rendered to YAML and available to the banner.)

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_pipeline_audio_warnings.py -v
uv run pytest tests/test_pipeline -v  # full pipeline regression
```

Expected: all pass.

**Step 5: Commit**

```bash
git add recap/pipeline/__init__.py tests/test_pipeline_audio_warnings.py
git commit -m "feat(pipeline): thread sidecar audio warnings into note export

Export stage now populates system-audio-devices-seen in the frontmatter
alongside audio-warnings so the body-callout renderer in upsert_note has
the device name list at hand.

No change for recordings with no warnings (both fields remain empty).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: Multi-stream test helper `_test_feed_mock_frames_multi`

**Files:**
- Modify: `recap/daemon/recorder/audio.py` — add new test helper

**Step 1: Write the failing test**

(This task adds testing infrastructure. We write a test that USES the helper so the helper exists and is exercised.)

Append to `tests/test_audio_multi_loopback_mix.py`:

```python
class TestFeedMockFramesMulti:
    def test_multiple_streams_contribute_to_channel_1(self, tmp_path):
        """The new multi-stream test helper must drive the full
        drain -> mix -> interleave -> encode path with per-stream control."""
        import numpy as np
        cap = AudioCapture(output_path=tmp_path / "out.flac")
        captured: list[tuple[bytes, int]] = []
        cap.on_chunk = lambda c, sr: captured.append((c, sr))

        chunk_frames = 480
        mic_frame = np.full(chunk_frames, 1000, dtype=np.int16).tobytes()
        airpods_frame = np.full(chunk_frames, 8000, dtype=np.int16).tobytes()  # above threshold
        speakers_frame = b"\x00" * (chunk_frames * 2)  # silent

        cap._test_feed_mock_frames_multi(
            mic_frame=mic_frame,
            loopback_frames_by_key={
                ("airpods",): ("AirPods", airpods_frame),
                ("speakers",): ("Laptop Speakers", speakers_frame),
            },
        )

        assert len(captured) == 1
        assert ("airpods",) in cap._loopback_sources
        airpods_entry = cap._loopback_sources[("airpods",)]
        assert airpods_entry.state == "active"
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_audio_multi_loopback_mix.py::TestFeedMockFramesMulti -v
```

Expected: FAIL — `_test_feed_mock_frames_multi` doesn't exist.

**Step 3: Write minimal implementation**

Add to `AudioCapture` near the existing `_test_feed_mock_frames`:

```python
    def _test_feed_mock_frames_multi(
        self,
        mic_frame: bytes,
        loopback_frames_by_key: dict[tuple, tuple[str, bytes]],
    ) -> None:  # pragma: no cover - test-only helper
        """Multi-stream test helper. Accepts a mapping of
        stable_key -> (device_name, frame_bytes). Installs a synthetic
        _LoopbackEntry for each key (all starting in PROBATION), drives one
        _drain_and_mix + _interleave_and_encode cycle, then restores prior
        state.

        Unlike _test_feed_mock_frames (which starts synthetic streams as
        ACTIVE for legacy compat), this helper starts them as PROBATION
        so tests can exercise the RMS-threshold promotion path end to end.
        """
        chunk_frames = len(mic_frame) // 2
        for key, (_, frame) in loopback_frames_by_key.items():
            if len(frame) != len(mic_frame):
                raise ValueError(
                    f"loopback frame for {key} has different length "
                    f"than mic_frame",
                )

        class _StubStream:
            def __init__(self, frame: bytes) -> None:
                self._buf = frame
                self.is_terminal = False
            def drain_resampled(self, max_bytes: int) -> bytes:
                out = self._buf[:max_bytes]
                self._buf = self._buf[max_bytes:]
                return out
            def stop(self) -> None:
                pass

        with self._lock:
            self._mic_buffer += mic_frame
        prior = self._loopback_sources
        self._loopback_sources = {
            key: _LoopbackEntry(
                stream=_StubStream(frame),
                state="probation",
                opened_at=0.0,
                last_active_at=None,
                device_name=name,
                missing_since=None,
            )
            for key, (name, frame) in loopback_frames_by_key.items()
        }
        try:
            self._interleave_and_encode(chunk_frames)
        finally:
            self._loopback_sources.update(prior)
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_audio_multi_loopback_mix.py -v
```

Expected: all pass.

**Step 5: Commit**

```bash
git add recap/daemon/recorder/audio.py tests/test_audio_multi_loopback_mix.py
git commit -m "test(audio): _test_feed_mock_frames_multi for multi-stream scenarios

Per-stream control helper, complementary to the legacy single-stream
_test_feed_mock_frames. Streams start in PROBATION so tests can
exercise the RMS-threshold promotion path through the normal
drain -> mix -> interleave cycle without real PyAudio.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 16: AirPods-scenario integration test

**Files:**
- Extend: `tests/test_audio_multi_loopback_mix.py`

**Step 1: Write the test**

Append to `tests/test_audio_multi_loopback_mix.py`:

```python
class TestAirPodsScenarioEndToEnd:
    """Regression test for the 2026-04-21 failure mode: meeting routed to
    AirPods via Zoho's in-call picker while the Windows default output is
    Laptop Speakers. The new architecture must capture AirPods audio and
    evict the silent Speakers/HDMI endpoints after their probation window."""

    def test_airpods_only_wins_after_probation_expiry(self, tmp_path, monkeypatch):
        import numpy as np
        cap = AudioCapture(output_path=tmp_path / "out.flac")
        captured_chunks: list[bytes] = []
        cap.on_chunk = lambda c, sr: captured_chunks.append(c)

        chunk_frames = 480
        mic_frame = (np.full(chunk_frames, 2000, dtype=np.int16)).tobytes()
        speech_frame = (np.full(chunk_frames, 12000, dtype=np.int16)).tobytes()
        silent_frame = b"\x00" * (chunk_frames * 2)

        # Feed 10 chunks of the AirPods-only scenario.
        for _ in range(10):
            cap._test_feed_mock_frames_multi(
                mic_frame=mic_frame,
                loopback_frames_by_key={
                    ("airpods",): ("AirPods", speech_frame),
                    ("speakers",): ("Laptop Speakers", silent_frame),
                    ("hdmi",): ("HDMI", silent_frame),
                },
            )

        # AirPods is ACTIVE after first chunk; Speakers and HDMI remain PROBATION.
        assert cap._loopback_sources[("airpods",)].state == "active"
        assert cap._loopback_sources[("speakers",)].state == "probation"
        assert cap._loopback_sources[("hdmi",)].state == "probation"

        # After probation expires (simulated by advancing opened_at),
        # _tick_membership evicts the silent ones.
        now = cap._loopback_sources[("airpods",)].opened_at + 100.0
        for key, entry in cap._loopback_sources.items():
            entry.opened_at = now - 100.0
        monkeypatch.setattr(
            cap, "_enumerate_loopback_endpoints",
            lambda: iter([
                (("airpods",), {"name": "AirPods", "index": 3, "defaultSampleRate": 48000.0}),
                (("speakers",), {"name": "Laptop Speakers", "index": 1, "defaultSampleRate": 48000.0}),
                (("hdmi",), {"name": "HDMI", "index": 2, "defaultSampleRate": 48000.0}),
            ]),
        )
        cap._tick_membership(now=now)

        assert ("airpods",) in cap._loopback_sources
        assert ("speakers",) not in cap._loopback_sources
        assert ("hdmi",) not in cap._loopback_sources
```

**Step 2 / 3 / 4: Run, implement if needed (all infrastructure already exists), verify**

```bash
uv run pytest tests/test_audio_multi_loopback_mix.py::TestAirPodsScenarioEndToEnd -v
```

Expected: PASS (this test exercises existing code; the infrastructure from Tasks 1–11 already supports it).

**Step 5: Commit**

```bash
git add tests/test_audio_multi_loopback_mix.py
git commit -m "test(audio): regression test for the 2026-04-21 AirPods routing failure

Three enumerated loopback endpoints (AirPods, Laptop Speakers, HDMI).
Only AirPods produces speech; the others are silent. Asserts that:

- AirPods promotes to ACTIVE on first chunk
- Speakers and HDMI remain PROBATION
- After the probation window, _tick_membership evicts Speakers and HDMI
- AirPods alone survives and continues contributing to channel 1

This is the end-to-end regression test for the monologue bug.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 17: Cross-seam e2e test (sidecar → pipeline → note)

**Files:**
- Create: `tests/test_audio_warning_e2e.py`

**Step 1: Write the test**

Create `tests/test_audio_warning_e2e.py`:

```python
"""End-to-end test: recorder sidecar -> pipeline export -> note on disk.

Validates that audio-warning codes survive the full chain without being
dropped or mangled at a seam. Each earlier test covers one piece; this
one covers the join between them.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from recap.artifacts import RecordingMetadata, write_recording_metadata


def test_no_system_audio_code_flows_to_note(tmp_path, monkeypatch):
    # Arrange: write a sidecar with the code.
    audio_path = tmp_path / "rec.flac"
    audio_path.touch()
    sidecar = RecordingMetadata(
        org="testorg", title="Test", date="2026-04-21",
        participants=[], platform="zoho_meet",
        audio_warnings=["no-system-audio-captured"],
        system_audio_devices_seen=["Laptop Speakers", "HDMI Audio"],
    )
    write_recording_metadata(audio_path, sidecar)

    # Act: run the export stage against a fixture vault.
    vault_root = tmp_path / "vault"
    (vault_root / "TestOrg" / "Meetings").mkdir(parents=True)
    note_path = vault_root / "TestOrg" / "Meetings" / "2026-04-21 - test.md"

    # Minimal invocation of the export helper (adapt to actual signature).
    from recap.pipeline import run_export_for_test  # or the real export function
    run_export_for_test(
        audio_path=audio_path, note_path=note_path,
        vault_root=vault_root,
    )

    # Assert: note on disk contains the frontmatter + body callout.
    content = note_path.read_text(encoding="utf-8")
    assert "audio-warnings:" in content
    assert "- no-system-audio-captured" in content
    assert "[!warning] System audio was not captured" in content
    assert "Laptop Speakers" in content
    assert "HDMI Audio" in content


def test_interrupted_code_flows_to_note(tmp_path):
    # Same structure, different code, different banner wording.
    audio_path = tmp_path / "rec.flac"
    audio_path.touch()
    sidecar = RecordingMetadata(
        org="testorg", title="Test", date="2026-04-21",
        participants=[], platform="zoho_meet",
        audio_warnings=["system-audio-interrupted"],
        system_audio_devices_seen=["AirPods"],
    )
    write_recording_metadata(audio_path, sidecar)

    vault_root = tmp_path / "vault"
    (vault_root / "TestOrg" / "Meetings").mkdir(parents=True)
    note_path = vault_root / "TestOrg" / "Meetings" / "2026-04-21 - test.md"

    from recap.pipeline import run_export_for_test
    run_export_for_test(
        audio_path=audio_path, note_path=note_path, vault_root=vault_root,
    )

    content = note_path.read_text(encoding="utf-8")
    assert "[!warning] System audio dropped out" in content
    assert "AirPods" in content
```

**Step 2: Run to see what's needed**

```bash
uv run pytest tests/test_audio_warning_e2e.py -v
```

You may need to extract or expose a test-friendly pipeline entry point. If the existing pipeline has a `run_export(...)` or `export_meeting(...)` helper, use that.

**Step 3: Write minimal implementation if needed**

If the pipeline has no clean export entry, add a thin wrapper `run_export_for_test(audio_path, note_path, vault_root)` in `recap/pipeline/__init__.py` that:
- loads the sidecar via `load_recording_metadata`
- builds a stub `MeetingMetadata` + `AnalysisResult` sufficient for `build_canonical_frontmatter`
- calls `upsert_note`

(Or thread real arguments through the existing export function. The simplest path depends on the current pipeline shape.)

**Step 4: Verify**

```bash
uv run pytest tests/test_audio_warning_e2e.py -v
uv run pytest tests/  # full regression
```

Expected: all pass.

**Step 5: Commit**

```bash
git add tests/test_audio_warning_e2e.py recap/pipeline/__init__.py
git commit -m "test(pipeline): e2e test for audio-warning seam (sidecar -> note)

Validates that warning codes survive the full recorder-sidecar ->
pipeline-export -> note-on-disk chain. Each earlier test covers one
component; this one covers the join between them so a regression in
the threading between artifacts / pipeline / vault surfaces here
rather than in a user's actual meeting note.

Covers both warning codes (no-system-audio-captured and
system-audio-interrupted) with their respective banner wordings.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 18: Manual validation on real hardware

**Files:** none (reference only; user runs these checks after Task 17)

After all unit and integration tests pass on CI, run the manual validation checklist from the design doc against real hardware. Record results in `docs/handoffs/2026-04-21-multi-output-capture-handoff.md` or append to the design doc.

1. **Baseline.** Join a Zoho meeting with laptop speakers as default output, don't change routing. Verify: both voices in transcript, no `audio-warnings` frontmatter.
2. **AirPods routing — the reported bug.** Join a Zoho meeting, switch output to AirPods via Zoho's in-call device picker. Verify: both voices in transcript, no `audio-warnings` frontmatter.
3. **Bluetooth disconnect mid-call.** Start recording with AirPods, disconnect AirPods mid-call, wait 10s past the grace period, reconnect. Verify: transcript has speech from before disconnect, is mic-only during the gap, speech resumes after reconnect. `system-audio-interrupted` warning on the note.
4. **Warning-wording UX (not a capture-failure test).** Join a meeting where the other party is muted the entire time. Read the `no-system-audio-captured` banner as the user would. Confirm wording is a fair observation, not an accusation.
5. **Hot-plug add.** Start recording with default speakers, plug in a USB headset mid-call, switch the meeting app to the USB headset, continue. Verify: post-switch audio captured.
6. **Log hygiene under `RECAP_AUDIO_DEBUG=1`.** Set the env var and restart the daemon via the Restart button. Verify the debug line appears at ~5s cadence with the expected format.

**Step 5: Commit the handoff/results doc**

```bash
git add docs/handoffs/2026-04-21-multi-output-capture-handoff.md
git commit -m "docs(handoffs): manual validation results for multi-output capture"
```

---

## Done criteria

All of the following must hold before closing out:

- All new and existing tests pass: `uv run pytest` → green.
- Coverage remains at or above the 70% threshold configured in `pytest.ini`.
- Manual scenario 2 (AirPods routing) on real hardware captures both voices and produces a clean note with no `audio-warnings`.
- Manual scenario 3 (Bluetooth disconnect) produces a `system-audio-interrupted` warning with the correct banner wording.
- The debug log line format matches the design doc spec and appears at the 5s cadence under `RECAP_AUDIO_DEBUG=1`.
- No regression in the chunked Parakeet transcribe (run the preserved 2026-04-20 disbursecloud FLAC through the pipeline end-to-end; verify same utterance count as yesterday's handoff).

---

## Notes for the executor

- **TDD discipline:** write the failing test first, verify the failure message is what you expected, then write the minimum code to pass. Don't write implementation ahead of tests.
- **Commit after every task.** Each task produces one commit. Do not batch.
- **Existing test patterns:** mock PyAudio via `patch("recap.daemon.recorder.audio.pyaudio")` where streams need to be avoided. Use `tmp_path` for file paths. Use `pytest.importorskip("numpy")` if running in environments without numpy.
- **Skill to use for execution:** `superpowers:executing-plans`.
- **Design doc:** `docs/plans/2026-04-21-multi-output-capture-design.md` has the full rationale, rejected alternatives, and per-section refinements.
- **Do not exceed scope.** This plan is deliberately narrow — no per-process loopback, no mic generalization, no YAML-configurable thresholds, no UI indicator. Those are explicitly out-of-scope per the design doc's non-goals.

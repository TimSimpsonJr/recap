# Phase 2: Audio Recording

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Record meetings to FLAC via PyAudioWPatch with dual-channel interleaved audio (mic + system), silence detection, and a state machine for manual start/stop. No meeting detection yet (that's Phase 4).

**Architecture:** The recorder is a state machine (Idle → Recording → Processing) running in the daemon's asyncio loop. Audio capture runs in a separate thread (PyAudioWPatch callback). pyFLAC encodes in real-time. Silence detection monitors audio levels.

**Tech Stack:** PyAudioWPatch, pyFLAC, asyncio

---

### Task 1: Add recording dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add PyAudioWPatch and pyFLAC to daemon dependencies**

```toml
daemon = [
    "aiohttp>=3.9",
    "pystray>=0.19",
    "Pillow>=10.0",
    "keyring>=25.0",
    "plyer>=2.1",
    "authlib>=1.3",
    "pywin32>=306",
    "PyAudioWPatch>=0.2.12",
    "pyflac>=2.2",
]
```

**Step 2: Install and verify**

```bash
uv sync --extra daemon
python -c "import pyaudiowpatch; import pyflac; print('OK')"
```

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add PyAudioWPatch and pyFLAC dependencies"
```

---

### Task 2: Audio capture module

**Files:**
- Create: `recap/daemon/recorder/audio.py`
- Create: `recap/daemon/recorder/__init__.py`
- Test: `tests/test_recorder_audio.py`

**Step 1: Write the failing tests**

Test the audio module's device enumeration and stream configuration logic (not actual recording — that requires hardware).

```python
"""Tests for audio capture module."""
import pytest
from unittest.mock import patch, MagicMock
from recap.daemon.recorder.audio import (
    AudioCapture,
    find_loopback_device,
    find_microphone_device,
    AudioDeviceError,
)


class TestDeviceDiscovery:
    def test_find_loopback_device_returns_device_info(self):
        """Should find a WASAPI loopback device (or skip if no audio hardware)."""
        try:
            device = find_loopback_device()
            assert "index" in device
            assert device["maxInputChannels"] > 0
        except AudioDeviceError:
            pytest.skip("No WASAPI loopback device available")

    def test_find_microphone_returns_device_info(self):
        """Should find a microphone device (or skip if no audio hardware)."""
        try:
            device = find_microphone_device()
            assert "index" in device
            assert device["maxInputChannels"] > 0
        except AudioDeviceError:
            pytest.skip("No microphone device available")


class TestAudioCaptureConfig:
    def test_interleaved_stream_config(self):
        """Verify dual-channel config is set up correctly."""
        capture = AudioCapture(
            output_path="/tmp/test.flac",
            sample_rate=16000,
            channels=2,
        )
        assert capture.channels == 2
        assert capture.sample_rate == 16000
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_recorder_audio.py -v
```

**Step 3: Implement audio capture**

`recap/daemon/recorder/audio.py`:

- `AudioDeviceError(Exception)` — raised when no suitable device found
- `find_loopback_device() -> dict` — enumerate WASAPI loopback devices, return the default one
- `find_microphone_device() -> dict` — enumerate WASAPI input devices, return the default mic
- `AudioCapture` class:
  - `__init__(output_path, sample_rate=16000, channels=2)` — configure but don't start
  - `start()` — open PyAudioWPatch streams for both mic and loopback, interleave into single pyFLAC encoder writing to output_path. Start in a background thread.
  - `stop() -> Path` — stop streams, finalize FLAC file, return path
  - `is_recording -> bool` property
  - `current_levels -> tuple[float, float]` property — RMS levels for silence detection (mic, system)
  - pyFLAC callback flushes to disk continuously (crash resilience)
  - Audio callback interleaves mic and system channels into a single frame buffer

**Step 4: Run tests, commit**

```bash
pytest tests/test_recorder_audio.py -v
git add recap/daemon/recorder/ tests/test_recorder_audio.py
git commit -m "feat: add audio capture with dual-channel WASAPI + FLAC encoding"
```

---

### Task 3: Silence detection

**Files:**
- Create: `recap/daemon/recorder/silence.py`
- Test: `tests/test_recorder_silence.py`

**Step 1: Write the failing tests**

```python
"""Tests for silence detection."""
import time
from recap.daemon.recorder.silence import SilenceDetector


class TestSilenceDetector:
    def test_not_silent_initially(self):
        detector = SilenceDetector(threshold_db=-40, timeout_seconds=5)
        assert detector.is_silent is False
        assert detector.silence_duration == 0

    def test_becomes_silent_after_timeout(self):
        detector = SilenceDetector(threshold_db=-40, timeout_seconds=0.1)
        # Feed silence (very low levels)
        for _ in range(20):
            detector.update(rms_level=0.001)
            time.sleep(0.01)
        assert detector.is_silent is True

    def test_resets_on_audio(self):
        detector = SilenceDetector(threshold_db=-40, timeout_seconds=0.1)
        # Feed silence
        for _ in range(20):
            detector.update(rms_level=0.001)
            time.sleep(0.01)
        assert detector.is_silent is True
        # Feed audio
        detector.update(rms_level=0.5)
        assert detector.is_silent is False
        assert detector.silence_duration == 0

    def test_silence_duration_tracks_seconds(self):
        detector = SilenceDetector(threshold_db=-40, timeout_seconds=300)
        detector.update(rms_level=0.001)
        time.sleep(0.05)
        detector.update(rms_level=0.001)
        assert detector.silence_duration > 0
```

**Step 2: Run, fail, implement**

`SilenceDetector`:
- `__init__(threshold_db, timeout_seconds)` — convert threshold_db to linear RMS
- `update(rms_level: float)` — if below threshold, track start time. If above, reset.
- `is_silent -> bool` — True if silence has lasted longer than timeout
- `silence_duration -> float` — seconds of continuous silence (0 if not silent)

**Step 3: Run tests, commit**

```bash
pytest tests/test_recorder_silence.py -v
git add recap/daemon/recorder/silence.py tests/test_recorder_silence.py
git commit -m "feat: add silence detection for meeting end detection"
```

---

### Task 4: Recording state machine

**Files:**
- Create: `recap/daemon/recorder/state_machine.py`
- Test: `tests/test_recorder_state_machine.py`

**Step 1: Write the failing tests**

```python
"""Tests for recording state machine."""
import pytest
from recap.daemon.recorder.state_machine import (
    RecorderState,
    RecorderStateMachine,
    InvalidTransition,
)


class TestRecorderStateMachine:
    def test_initial_state_is_idle(self):
        sm = RecorderStateMachine()
        assert sm.state == RecorderState.IDLE

    def test_can_start_recording_from_idle(self):
        sm = RecorderStateMachine()
        sm.start_recording(org="disbursecloud")
        assert sm.state == RecorderState.RECORDING
        assert sm.current_org == "disbursecloud"

    def test_cannot_start_recording_when_already_recording(self):
        sm = RecorderStateMachine()
        sm.start_recording(org="disbursecloud")
        with pytest.raises(InvalidTransition):
            sm.start_recording(org="personal")

    def test_can_stop_recording(self):
        sm = RecorderStateMachine()
        sm.start_recording(org="disbursecloud")
        sm.stop_recording()
        assert sm.state == RecorderState.PROCESSING

    def test_processing_completes_to_idle(self):
        sm = RecorderStateMachine()
        sm.start_recording(org="disbursecloud")
        sm.stop_recording()
        sm.processing_complete()
        assert sm.state == RecorderState.IDLE

    def test_state_change_callback(self):
        changes = []
        sm = RecorderStateMachine(
            on_state_change=lambda old, new: changes.append((old, new))
        )
        sm.start_recording(org="disbursecloud")
        sm.stop_recording()
        assert len(changes) == 2
        assert changes[0] == (RecorderState.IDLE, RecorderState.RECORDING)
        assert changes[1] == (RecorderState.RECORDING, RecorderState.PROCESSING)
```

**Step 2: Run, fail, implement**

`RecorderState` enum: `IDLE, ARMED, DETECTED, RECORDING, PROCESSING`

`RecorderStateMachine`:
- `state` property
- `current_org` — which org this recording is for
- `start_recording(org)` — IDLE → RECORDING (or DETECTED → RECORDING)
- `stop_recording()` — RECORDING → PROCESSING
- `processing_complete()` — PROCESSING → IDLE
- `arm(org)` — IDLE → ARMED (for Phase 4)
- `detected(org)` — ARMED → DETECTED or IDLE → DETECTED (for Phase 4)
- `decline()` — DETECTED → IDLE (for Phase 4, Signal popup)
- `on_state_change` callback for tray updates and WebSocket push
- `InvalidTransition` exception for illegal transitions

**Step 3: Run tests, commit**

```bash
pytest tests/test_recorder_state_machine.py -v
git add recap/daemon/recorder/state_machine.py tests/test_recorder_state_machine.py
git commit -m "feat: add recording state machine with transition validation"
```

---

### Task 5: Recorder orchestrator

**Files:**
- Create: `recap/daemon/recorder/recorder.py`
- Test: `tests/test_recorder_orchestrator.py`

**Step 1: Write the failing tests**

```python
"""Tests for recorder orchestrator."""
import pathlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from recap.daemon.recorder.recorder import Recorder


class TestRecorder:
    @pytest.fixture
    def recorder(self, tmp_path):
        return Recorder(
            recordings_path=tmp_path,
            sample_rate=16000,
            channels=2,
            silence_timeout_minutes=5,
            max_duration_hours=4,
        )

    def test_generates_unique_filename(self, recorder):
        path = recorder._generate_recording_path("disbursecloud")
        assert path.suffix == ".flac"
        assert "disbursecloud" in str(path) or path.parent.exists()

    def test_is_recording_false_initially(self, recorder):
        assert recorder.is_recording is False

    def test_recording_path_none_when_idle(self, recorder):
        assert recorder.current_recording_path is None
```

**Step 2: Run, fail, implement**

`Recorder` class:
- `__init__(recordings_path, sample_rate, channels, silence_timeout_minutes, max_duration_hours)`
- `start(org: str) -> Path` — create AudioCapture, SilenceDetector, start recording, start silence monitoring task
- `stop() -> Path` — stop AudioCapture, return FLAC path
- `is_recording -> bool`
- `current_recording_path -> Path | None`
- `_generate_recording_path(org) -> Path` — `{recordings_path}/{date}-{time}-{org}.flac`
- `_silence_monitor()` — async task that periodically checks SilenceDetector, fires callback when silence detected
- `_duration_monitor()` — async task that warns at max_duration - 1hr, stops at max_duration
- Disk space check before starting (warn if < 1GB)

**Step 3: Run tests, commit**

```bash
pytest tests/test_recorder_orchestrator.py -v
git add recap/daemon/recorder/recorder.py tests/test_recorder_orchestrator.py
git commit -m "feat: add recorder orchestrator with silence and duration monitoring"
```

---

### Task 6: Wire recorder to HTTP API and tray

**Files:**
- Modify: `recap/daemon/server.py` — add recording start/stop endpoints
- Modify: `recap/daemon/tray.py` — wire menu items to recorder
- Modify: `recap/daemon/__main__.py` — instantiate recorder, pass to server and tray

**Step 1: Add HTTP endpoints**

- `POST /api/record/start` — body: `{"org": "disbursecloud"}`. Starts recording. Returns 200 with `{"recording_path": "..."}` or 409 if already recording.
- `POST /api/record/stop` — stops recording. Returns 200 with `{"recording_path": "..."}` or 409 if not recording.
- `GET /api/status` — update to include `recording` state from state machine.

**Step 2: Wire tray menu**

- "Start Recording > disbursecloud" calls `recorder.start("disbursecloud")`
- "Stop Recording" calls `recorder.stop()`
- State machine `on_state_change` callback updates tray icon color and status text

**Step 3: Manual end-to-end test**

1. Start daemon: `python -m recap.daemon config.yaml`
2. Verify tray icon appears (green = idle)
3. Right-click → Start Recording → disbursecloud
4. Verify icon turns red, FLAC file appears in recordings path
5. Play some audio on the system
6. Right-click → Stop Recording
7. Verify icon turns green, FLAC file is finalized
8. Verify FLAC plays back correctly in VLC or similar

**Step 4: Commit**

```bash
git add recap/daemon/server.py recap/daemon/tray.py recap/daemon/__main__.py
git commit -m "feat: wire recorder to HTTP API and system tray controls"
```

---

### Task 7: WebSocket state broadcasting

**Files:**
- Modify: `recap/daemon/server.py` — add WebSocket endpoint

**Step 1: Implement WebSocket**

- `WS /api/ws` — clients connect, receive JSON messages on state changes:
  - `{"event": "state_change", "state": "recording", "org": "disbursecloud"}`
  - `{"event": "state_change", "state": "idle"}`
  - `{"event": "silence_warning", "duration_seconds": 300}`
  - `{"event": "recording_stopped", "path": "...", "duration": "45m"}`
- Server maintains a set of connected WebSocket clients
- State machine `on_state_change` broadcasts to all connected clients
- Silence detector warnings broadcast to all connected clients

**Step 2: Test with a simple WebSocket client**

```bash
python -c "
import asyncio
import aiohttp

async def main():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect('http://localhost:9847/api/ws') as ws:
            async for msg in ws:
                print(msg.data)

asyncio.run(main())
"
```

Start daemon, connect client, trigger recording via tray. Verify state change messages appear.

**Step 3: Commit**

```bash
git add recap/daemon/server.py
git commit -m "feat: add WebSocket endpoint for live state broadcasting"
```

---

### Task 8: Orphaned FLAC detection

**Files:**
- Create: `recap/daemon/recorder/recovery.py`
- Test: `tests/test_recorder_recovery.py`

**Step 1: Write the failing tests**

```python
"""Tests for orphaned recording recovery."""
from recap.daemon.recorder.recovery import find_orphaned_recordings


class TestOrphanedRecoveryDetection:
    def test_finds_flac_without_status(self, tmp_path):
        (tmp_path / "2026-04-13-meeting.flac").write_bytes(b"fake flac data")
        orphans = find_orphaned_recordings(tmp_path)
        assert len(orphans) == 1

    def test_ignores_flac_with_completed_status(self, tmp_path):
        (tmp_path / "2026-04-13-meeting.flac").write_bytes(b"fake")
        status_dir = tmp_path / ".recap" / "status"
        status_dir.mkdir(parents=True)
        (status_dir / "2026-04-13-meeting.json").write_text('{"pipeline-status": "complete"}')
        orphans = find_orphaned_recordings(tmp_path)
        assert len(orphans) == 0

    def test_returns_empty_for_clean_directory(self, tmp_path):
        orphans = find_orphaned_recordings(tmp_path)
        assert len(orphans) == 0
```

**Step 2: Run, fail, implement, commit**

`find_orphaned_recordings(recordings_path: Path) -> list[Path]`:
- Scan for `.flac` files
- Check if a corresponding status.json exists and has `pipeline-status: complete`
- Return FLAC paths without completed status

**Step 3: Wire into daemon startup**

In `__main__.py`, after startup validation:
- Call `find_orphaned_recordings()`
- For each orphan: `notify("Recap", f"Incomplete recording found: {path.name}. Process anyway?")`
- Log each orphan

**Step 4: Commit**

```bash
git add recap/daemon/recorder/recovery.py tests/test_recorder_recovery.py recap/daemon/__main__.py
git commit -m "feat: detect orphaned FLAC files on daemon startup"
```

---

### Task 9: Push and verify

**Step 1: Run all tests**

```bash
pytest tests/ -v --ignore=tests/fixtures
```

Note any failures from old pipeline tests (expected — pipeline.py still references removed modules). These will be fixed in Phase 3.

**Step 2: Manual end-to-end recording test**

1. Start daemon
2. Start recording via tray
3. Play a YouTube video or join a test call
4. Wait 30 seconds
5. Stop recording
6. Verify FLAC file exists and plays back with both mic and system audio

**Step 3: Push**

```bash
git push
```

# Phase 7 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reconcile three drifted ML libraries with current code, refactor meeting detection to UIA-confirmed call state, fix the Signal popup threading + self-detection bugs, and add an integration test tier that catches future library drift at CI.

**Architecture:** Python daemon (aiohttp + pystray) + Obsidian plugin + MV3 extension. This plan touches the daemon's streaming subsystem (stubbed), recorder audio (pyflac fix), detection (new UIA module), signal popup (executor + self-exclusion), and adds a `tests/integration/` tier with real-library tests.

**Tech Stack:** Python 3.12 + uv + pytest + NeMo (ASR + Sortformer) + pyflac + tkinter + uiautomation + pywin32. TypeScript (plugin). Windows 11 + CUDA 12.6.

**Design doc:** [`docs/plans/2026-04-16-phase7-design.md`](2026-04-16-phase7-design.md) — read before starting. Contains approved rationale; this plan contains the execution.

---

## Preflight (before Task 1)

Verify the environment once:

```powershell
cd C:\Users\tim\OneDrive\Documents\Projects\recap
uv sync --extra dev --extra daemon --extra ml
uv run python -c "import torch; print('cuda', torch.cuda.is_available())"
ffmpeg -version
ffprobe -version
claude --version
ollama list
```

All six must succeed. `cuda True`, ffmpeg/ffprobe resolve, Claude CLI authenticated, `qwen2.5:14b` listed in ollama.

Branch off:

```bash
git checkout obsidian-pivot
git checkout -b phase-7-ml-stack-refresh
```

---

## Task 1: Integration test tier infrastructure

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_contract_smoke.py`
- Create: `tests/integration/test_ml_pipeline.py`
- Modify: `pyproject.toml:45-47`

**Step 1: Create empty package marker**

Write `tests/integration/__init__.py` as an empty file.

**Step 2: Create integration conftest with session-scoped fixtures**

Write `tests/integration/conftest.py`:
```python
"""Fixtures for the integration tier — real ML libraries, heavy setup.

All fixtures here are session-scoped so model loading happens once per
`pytest -m integration` invocation. Regular `pytest -q` never touches
this file because the tier is excluded by default.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def cuda_guard():
    """Skip if CUDA is not available. Lazy torch import.

    Session-scoped so model fixtures can depend on it without ScopeMismatch.
    """
    pytest.importorskip("torch")
    import torch
    if not torch.cuda.is_available():
        pytest.skip("CUDA not available")


@pytest.fixture(scope="session")
def parakeet_asr_model(cuda_guard):
    """Load Parakeet ASR model once per session."""
    import nemo.collections.asr as nemo_asr
    import torch

    model = nemo_asr.models.ASRModel.from_pretrained("nvidia/parakeet-tdt-0.6b-v2")
    model = model.to("cuda")
    yield model
    del model
    torch.cuda.empty_cache()


@pytest.fixture(scope="session")
def sortformer_diarizer_model(cuda_guard):
    """Load NeMo Sortformer diarization model once per session.

    Mirrors the production loader at recap/pipeline/diarize.py:16 — same
    class (SortformerEncLabelModel), same from_pretrained, same .diarize()
    surface.
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

**Step 3: Create empty test files**

Write `tests/integration/test_contract_smoke.py`:
```python
"""CPU-safe contract smoke tests.

These assert the shape and importability of real libraries we depend on.
Marked `@pytest.mark.integration`; opt-in via `pytest -m integration`.
"""
import pytest

pytestmark = pytest.mark.integration

# Tests added in Task 2.
```

Write `tests/integration/test_ml_pipeline.py`:
```python
"""GPU-required ML pipeline tests.

Load real models and exercise the batch pipeline end-to-end. Skipped
when CUDA is unavailable via the cuda_guard fixture.
"""
import pytest

pytestmark = pytest.mark.integration

# Tests added in Task 9.
```

**Step 4: Update pyproject.toml marker + addopts**

In `pyproject.toml`, replace the `[tool.pytest.ini_options]` block:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--cov=recap --cov-fail-under=70 --cov-report=term-missing"
```

with:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--cov=recap --cov-fail-under=70 --cov-report=term-missing -m 'not integration'"
markers = [
    "integration: tests that import real ML/system libraries; slow; opt-in via -m integration",
]
```

**Step 5: Verify default test run still passes**

```powershell
uv run pytest -q
```

Expected: same as pre-change (573 passing, coverage ≥ 70%). No `PytestUnknownMarkWarning`.

**Step 6: Verify integration tier is discoverable but empty**

```powershell
uv run pytest -m integration --no-cov --collect-only
```

Expected: `no tests ran` or 0 items collected.

**Step 7: Commit**

```bash
git add tests/integration/ pyproject.toml
git commit -m "chore(tests): introduce integration tier infrastructure"
```

---

## Task 2: CPU contract smoke tests (RED state)

**Files:**
- Modify: `tests/integration/test_contract_smoke.py`

**Step 1: Write the six CPU smoke tests**

Replace `tests/integration/test_contract_smoke.py`:
```python
"""CPU-safe contract smoke tests."""
import inspect
import pytest

pytestmark = pytest.mark.integration


def test_nemo_asr_imports_cleanly():
    """Catches datasets/pyarrow import chain. RED today; GREEN after Task 3."""
    from nemo.collections import asr  # noqa: F401


def test_pyflac_streamencoder_has_no_channels_kwarg():
    """Documents pyflac 3.0 API contract."""
    import pyflac
    params = inspect.signature(pyflac.StreamEncoder.__init__).parameters
    assert "channels" not in params


def test_pyflac_write_callback_signature():
    """Documents write_callback parameter exists."""
    import pyflac
    params = inspect.signature(pyflac.StreamEncoder.__init__).parameters
    assert "write_callback" in params


def test_parakeet_stream_not_installed():
    """parakeet-stream removed in Task 7. RED today; GREEN after Task 7."""
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
        assert hasattr(win32gui, name), f"win32gui missing {name}"
```

**Step 2: Observe the RED failures**

```powershell
uv run pytest -m integration --no-cov tests/integration/test_contract_smoke.py -v
```

Expected:
- `test_nemo_asr_imports_cleanly` — FAIL (pyarrow.PyExtensionType)
- `test_parakeet_stream_not_installed` — FAIL (still installed)
- Four others — PASS.

**Step 3: Commit (with intentional REDs)**

```bash
git add tests/integration/test_contract_smoke.py
git commit -m "test(integration): CPU contract smoke tests against current library state

Two tests intentionally RED; transition to GREEN across commits 3 + 7."
```

---

## Task 3: Pin datasets to fix pyarrow.PyExtensionType

**Files:**
- Modify: `pyproject.toml:29-33`
- Regenerated: `uv.lock`

**Step 1: Try preferred branch (dry-run)**

Edit `pyproject.toml` `[project.optional-dependencies].ml` — add `"datasets>=2.16,<3",`:

```toml
ml = [
    "nemo_toolkit[asr]>=2.0",
    "torch>=2.1",
    "parakeet-stream>=0.1",
    "datasets>=2.16,<3",
]
```

```powershell
uv sync --extra dev --extra daemon --extra ml --dry-run
```

**Decision:**
- Clean resolve → proceed to Step 2.
- Resolver conflict → revert the pyproject edit, apply fallback instead: remove the `datasets` pin, add `"pyarrow<21",` in the same extras block. Then run `uv sync --extra dev --extra daemon --extra ml` and skip to Step 3.

**Step 2 (preferred): Apply + re-lock**

```powershell
uv sync --extra dev --extra daemon --extra ml
```

**Step 3: Verify NeMo imports cleanly**

```powershell
uv run python -c "from nemo.collections import asr; print('nemo ok')"
```

Expected: `nemo ok`

**Step 4: Verify contract smoke test passes**

```powershell
uv run pytest -m integration --no-cov tests/integration/test_contract_smoke.py::test_nemo_asr_imports_cleanly -v
```

Expected: PASS.

**Step 5: No regressions**

```powershell
uv run pytest -q
```

**Step 6: Commit (preferred branch)**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(deps): pin datasets>=2.16,<3 to fix pyarrow.PyExtensionType import chain"
```

Or (fallback branch):
```bash
git commit -m "chore(deps): pin pyarrow<21 (datasets pin rejected by resolver)"
```

---

## Task 4: Remove channels kwarg from pyflac StreamEncoder

**Files:**
- Modify: `recap/daemon/recorder/audio.py:312-316`
- Modify: `tests/test_recorder_audio.py`

**Step 1: Add failing test**

In `tests/test_recorder_audio.py`, add:

```python
def test_audio_capture_does_not_pass_channels_to_encoder(tmp_path, monkeypatch):
    """AudioCapture.start() must not pass channels= to pyflac.StreamEncoder."""
    from unittest.mock import MagicMock
    from recap.daemon.recorder.audio import AudioCapture
    import recap.daemon.recorder.audio as audio_mod

    mock_encoder_cls = MagicMock()
    mock_pyflac = MagicMock()
    mock_pyflac.StreamEncoder = mock_encoder_cls

    monkeypatch.setattr(audio_mod, "_require_pyflac", lambda: mock_pyflac)
    monkeypatch.setattr(audio_mod, "_require_pyaudio", lambda: MagicMock())

    capture = AudioCapture(output_path=tmp_path / "x.flac", sample_rate=16000, channels=2)
    try:
        capture.start()
    except Exception:
        pass

    assert mock_encoder_cls.called
    _, kwargs = mock_encoder_cls.call_args
    assert "channels" not in kwargs, f"StreamEncoder called with channels: {kwargs}"
```

**Step 2: Confirm RED**

```powershell
uv run pytest tests/test_recorder_audio.py::test_audio_capture_does_not_pass_channels_to_encoder --no-cov -v
```

Expected: FAIL.

**Step 3: Apply fix**

At `recap/daemon/recorder/audio.py:312-316`, remove the `channels=self._channels,` line. Block changes from:

```python
self._encoder = runtime_pyflac.StreamEncoder(
    write_callback=self._write_callback,
    sample_rate=self._sample_rate,
    channels=self._channels,
)
```

to:

```python
self._encoder = runtime_pyflac.StreamEncoder(
    write_callback=self._write_callback,
    sample_rate=self._sample_rate,
)
```

**Step 4: Confirm GREEN**

```powershell
uv run pytest tests/test_recorder_audio.py::test_audio_capture_does_not_pass_channels_to_encoder --no-cov -v
```

**Step 5: Full suite**

```powershell
uv run pytest -q
```

**Step 6: Commit**

```bash
git add recap/daemon/recorder/audio.py tests/test_recorder_audio.py
git commit -m "fix(recorder): remove channels kwarg from pyflac 3.0 StreamEncoder call"
```

---

## Task 5: Stub StreamingTranscriber

**Files:**
- Modify: `recap/daemon/streaming/transcriber.py` (rewrite)
- Modify: `tests/test_streaming_transcriber.py` (delete one test, add two)

**Step 1: Add failing tests**

In `tests/test_streaming_transcriber.py`, add:

```python
def test_streaming_transcriber_start_logs_deferred_message(caplog):
    """Stub emits 'Live streaming transcription deferred' at INFO level."""
    import logging
    caplog.set_level(logging.INFO, logger="recap.daemon.streaming.transcriber")

    from recap.daemon.streaming.transcriber import StreamingTranscriber
    t = StreamingTranscriber()
    t.start()

    assert any(
        "Live streaming transcription deferred" in r.message
        for r in caplog.records
    )


def test_streaming_transcriber_no_load_model_method():
    """Stub removes _load_model entirely."""
    from recap.daemon.streaming.transcriber import StreamingTranscriber
    assert not hasattr(StreamingTranscriber, "_load_model")
```

**Step 2: Confirm RED**

```powershell
uv run pytest tests/test_streaming_transcriber.py::test_streaming_transcriber_start_logs_deferred_message tests/test_streaming_transcriber.py::test_streaming_transcriber_no_load_model_method --no-cov -v
```

**Step 3: Delete existing `test_start_with_failed_model_sets_error`**

In `tests/test_streaming_transcriber.py`, remove the ~5 lines of the test method that patches `_load_model`. Approx lines 49-53.

**Step 4: Rewrite transcriber as stub**

Replace `recap/daemon/streaming/transcriber.py`:

```python
"""Streaming transcription — deferred to Phase 8.

Phase 7 stubs this subsystem because parakeet-stream 0.6 adopted an
audio-source-owned API that doesn't compose with our bytes-in recorder.
Public surface preserved; batch pipeline is the canonical transcription
path in Phase 7.
"""
from __future__ import annotations

import logging
from typing import Callable

from recap.models import TranscriptResult

logger = logging.getLogger(__name__)


class StreamingTranscriber:
    """No-op facade for live streaming transcription.

    Live streaming transcription is deferred to Phase 8 (see Phase 7
    design doc). Recorder and plugin wiring reference this class;
    start() logs deferral and sets had_errors=True so downstream code
    short-circuits. feed_audio() is a no-op.
    """

    def __init__(
        self,
        model_name: str = "nvidia/parakeet-tdt-0.6b-v2",
        device: str = "cuda",
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._running = False
        self._segments: list[dict] = []
        self._had_errors = False
        self.on_segment: Callable[[dict], None] | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def segments(self) -> list[dict]:
        return list(self._segments)

    @property
    def had_errors(self) -> bool:
        return self._had_errors

    def start(self) -> None:
        logger.info(
            "Live streaming transcription deferred; see Phase 7 plan for context."
        )
        self._had_errors = True

    def feed_audio(self, audio_data: bytes, sample_rate: int = 16000) -> None:
        return

    def stop(self) -> TranscriptResult | None:
        self._running = False
        return None

    def get_transcript_result(self) -> TranscriptResult:
        return TranscriptResult(utterances=[], raw_text="", language="en")
```

**Step 5: Confirm GREEN**

```powershell
uv run pytest tests/test_streaming_transcriber.py --no-cov -v
uv run pytest -q
```

**Step 6: Commit**

```bash
git add recap/daemon/streaming/transcriber.py tests/test_streaming_transcriber.py
git commit -m "fix(daemon): stub live streaming transcriber (defer to Phase 8)"
```

---

## Task 6: Stub StreamingDiarizer

Same pattern as Task 5 against `recap/daemon/streaming/diarizer.py` and `tests/test_streaming_diarizer.py`.

**Files:**
- Modify: `recap/daemon/streaming/diarizer.py` (rewrite as stub)
- Modify: `tests/test_streaming_diarizer.py` (delete one test, add two)

**Steps:**

1. Read current `tests/test_streaming_diarizer.py` to see what attributes are currently tested (e.g. `speaker_segments`, `is_running`, `had_errors`). Stub must preserve all of them.

2. Add two tests:

```python
def test_streaming_diarizer_start_logs_deferred_message(caplog):
    import logging
    caplog.set_level(logging.INFO, logger="recap.daemon.streaming.diarizer")

    from recap.daemon.streaming.diarizer import StreamingDiarizer
    d = StreamingDiarizer()
    d.start()

    assert any(
        "Live streaming diarization deferred" in r.message
        for r in caplog.records
    )


def test_streaming_diarizer_no_load_model_method():
    from recap.daemon.streaming.diarizer import StreamingDiarizer
    assert not hasattr(StreamingDiarizer, "_load_model")
```

3. Confirm RED: `uv run pytest tests/test_streaming_diarizer.py::test_streaming_diarizer_start_logs_deferred_message tests/test_streaming_diarizer.py::test_streaming_diarizer_no_load_model_method --no-cov -v`.

4. Delete `test_start_with_failed_model_sets_error` (~lines 44-48).

5. Rewrite `recap/daemon/streaming/diarizer.py` as a stub. Mirror Task 5's pattern. Log message: `"Live streaming diarization deferred; see Phase 7 plan for context."` Preserve every attribute/method the Recorder accesses on it — read `recap/daemon/recorder/recorder.py` first to list what's used.

6. Confirm GREEN: `uv run pytest tests/test_streaming_diarizer.py --no-cov -v; uv run pytest -q`.

7. Commit:

```bash
git add recap/daemon/streaming/diarizer.py tests/test_streaming_diarizer.py
git commit -m "fix(daemon): stub live streaming diarizer (defer to Phase 8)"
```

---

## Task 7: Remove parakeet-stream dependency

**Files:**
- Modify: `pyproject.toml:29-33`
- Regenerated: `uv.lock`

**Step 1: Remove from ml extras**

Edit `pyproject.toml` `[project.optional-dependencies].ml` — delete the `"parakeet-stream>=0.1",` line.

**Step 2: Re-lock**

```powershell
uv sync --extra dev --extra daemon --extra ml
```

**Step 3: Verify removal via the existing test**

```powershell
uv run pytest -m integration --no-cov tests/integration/test_contract_smoke.py::test_parakeet_stream_not_installed -v
```

Expected: PASS.

**Step 4: Full CPU smoke tier green**

```powershell
uv run pytest -m integration --no-cov tests/integration/test_contract_smoke.py
```

Expected: 6/6 green.

**Step 5: Default suite**

```powershell
uv run pytest -q
```

**Step 6: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(deps): remove parakeet-stream dependency from ml extras"
```

---

## Task 8: Update LiveTranscriptView copy

**Files:**
- Modify: `obsidian-recap/src/views/LiveTranscriptView.ts:40-45`

**Step 1: Read current state**

Inspect lines 38-47 to locate the `updateStatus` switch.

**Step 2: Replace both status strings**

Change to:

```typescript
switch (state) {
    case "recording":
        this.statusEl.setText("⏺ Recording — transcript will appear in the meeting note after the pipeline completes.");
        this.statusEl.addClass("recap-recording");
        break;
    default:
        this.statusEl.setText("Live transcript is not available in this version. Recorded meetings will show the full transcript in the note after the pipeline completes.");
        this.statusEl.removeClass("recap-recording");
}
```

**Step 3: Rebuild plugin**

```powershell
cd obsidian-recap
npm run build
cd ..
```

Expected: clean tsc; `main.js` emitted.

**Step 4: Commit**

```bash
git add obsidian-recap/src/views/LiveTranscriptView.ts obsidian-recap/main.js
git commit -m "fix(plugin): update LiveTranscriptView copy for deferred live transcript"
```

---

## Task 9: GPU integration tier tests

**Files:**
- Modify: `tests/conftest.py` (add `make_silent_flac`)
- Modify: `tests/test_signal_backend_routing.py` (hoist helper)
- Modify: `tests/test_e2e_pipeline.py` (hoist helper)
- Modify: `tests/integration/test_ml_pipeline.py` (add 3 GPU tests)

**Step 1: Hoist helper to `tests/conftest.py`**

Add at top of `tests/conftest.py` (after imports):

```python
def make_silent_flac(path: pathlib.Path, seconds: int = 2) -> pathlib.Path:
    """Generate a short silent FLAC via ffmpeg (stdlib subprocess only)."""
    import subprocess
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=mono:sample_rate=16000",
            "-t", str(seconds),
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path
```

**Step 2: Remove local duplicates from `tests/test_signal_backend_routing.py`**

Near line 82, delete the local `_make_silent_flac` definition. Add `from tests.conftest import make_silent_flac` to imports. Update the three call sites (approx lines 257, 296, 340) from `_make_silent_flac(audio_path)` to `make_silent_flac(audio_path)`.

**Step 3: Same for `tests/test_e2e_pipeline.py`**

Delete local definition near line 56. Add the import. Update two call sites at lines 163 and 329.

**Step 4: Confirm no regressions**

```powershell
uv run pytest tests/test_signal_backend_routing.py tests/test_e2e_pipeline.py --no-cov -v
```

**Step 5: Add GPU-tier tests**

Replace `tests/integration/test_ml_pipeline.py`:

```python
"""GPU-required ML pipeline tests."""
import json
import pathlib
from unittest.mock import patch

import pytest

from tests.conftest import make_silent_flac

pytestmark = pytest.mark.integration


def test_parakeet_transcribes_silent_audio_without_error(parakeet_asr_model, tmp_path):
    """Real Parakeet model processes a silent FLAC without raising."""
    audio_path = make_silent_flac(tmp_path / "silent.flac", seconds=2)
    results = parakeet_asr_model.transcribe([str(audio_path)])
    assert len(results) == 1
    assert hasattr(results[0], "text")


def test_sortformer_diarizes_silent_audio_without_error(tmp_path, cuda_guard):
    """Exercises recap.pipeline.diarize.diarize() — production path."""
    from recap.pipeline.diarize import diarize
    audio_path = make_silent_flac(tmp_path / "silent.flac", seconds=2)
    result = diarize(audio_path)
    assert isinstance(result, list)


def test_run_pipeline_end_to_end_on_silent_audio(tmp_path, cuda_guard):
    """Full batch pipeline with real Parakeet + Sortformer + stubbed analyze."""
    from recap.artifacts import RecordingMetadata, write_recording_metadata
    from recap.models import MeetingMetadata
    from recap.pipeline import PipelineRuntimeConfig, run_pipeline

    audio_path = make_silent_flac(tmp_path / "test-meeting.flac", seconds=3)
    vault_path = tmp_path / "vault"
    (vault_path / "Test" / "Meetings").mkdir(parents=True)
    seeded_note_path = "Test/Meetings/2026-04-16 - Integration Test.md"

    recording_metadata = RecordingMetadata(
        org="test",
        note_path=seeded_note_path,
        title="Integration Test",
        date="2026-04-16",
        participants=[],
        platform="calendar",
    )
    write_recording_metadata(audio_path, recording_metadata)

    meeting_metadata = MeetingMetadata(
        title="Integration Test",
        date="2026-04-16",
        participants=[],
    )

    pipeline_config = PipelineRuntimeConfig(
        transcription_model="nvidia/parakeet-tdt-0.6b-v2",
        diarization_model="nvidia/diar_streaming_sortformer_4spk-v2.1",
        device="cuda",
        llm_backend="claude",
        ollama_model="",
        archive_format="aac",
        archive_bitrate="64k",
        delete_source_after_archive=False,
        auto_retry=False,
        max_retries=0,
        prompt_template_path=None,
        status_dir=vault_path / "_Recap" / ".recap" / "status",
    )

    stub_analysis = {
        "speaker_mapping": {},
        "meeting_type": "other",
        "summary": "integration test stub",
        "key_points": [],
        "decisions": [],
        "action_items": [],
        "follow_ups": None,
        "relationship_notes": None,
        "people": [],
        "companies": [],
    }

    with patch("recap.analyze.subprocess.run") as mock_run:
        mock_run.return_value = type("R", (), {
            "returncode": 0,
            "stdout": json.dumps(stub_analysis),
            "stderr": "",
        })()
        run_pipeline(
            audio_path=audio_path,
            metadata=meeting_metadata,
            config=pipeline_config,
            org_slug="test",
            org_subfolder="Test",
            vault_path=vault_path,
            user_name="Tim",
            recording_metadata=recording_metadata,
        )

    note_path = vault_path / seeded_note_path
    assert note_path.exists()
    note_text = note_path.read_text()
    assert "## Summary" in note_text
    assert "pipeline-status: complete" in note_text
    assert "integration test stub" in note_text
```

**Step 6: Run GPU tier (on GPU box)**

```powershell
uv run pytest -m integration --no-cov tests/integration/test_ml_pipeline.py -v
```

First run downloads ~1.5 GB Parakeet + ~400 MB Sortformer (cached to `~\.cache\huggingface\`). Expected: 3/3 pass.

**Step 7: Commit**

```bash
git add tests/conftest.py tests/test_signal_backend_routing.py tests/test_e2e_pipeline.py tests/integration/test_ml_pipeline.py
git commit -m "test(integration): GPU-tier model load + end-to-end pipeline"
```

---

## Task 10: Extract call_state module

**Design ref:** §3.1, §3.5

**Files:**
- Create: `recap/daemon/recorder/call_state.py`
- Modify: `recap/daemon/recorder/enrichment.py` (re-export)
- Create: `tests/test_call_state.py` (moved tests)
- Modify: `tests/test_enrichment.py` (if exists and references moved functions)

**Steps:**

1. Locate existing `extract_teams_participants` and `_walk_for_participants` in `recap/daemon/recorder/enrichment.py:62-123`.
2. Create `recap/daemon/recorder/call_state.py`:

```python
"""UIA-based call-state + participant extraction helpers.

Shared between detector confirmation (§3) and enrichment (Teams
participant extraction, existing behavior).
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _walk_depth_limited(
    control: Any,
    matcher: Callable[[Any], bool],
    *,
    max_depth: int = 15,
) -> Any | None:
    """Depth-bounded UIA tree walk. Returns first control matching matcher."""
    def _walk(c, depth):
        if depth > max_depth:
            return None
        try:
            if matcher(c):
                return c
            for child in c.GetChildren():
                found = _walk(child, depth + 1)
                if found is not None:
                    return found
        except Exception:
            logger.debug("UIA walk error at depth %d", depth, exc_info=True)
        return None
    return _walk(control, 0)


def extract_teams_participants(hwnd: int) -> list[str] | None:
    """Extract participant names from a Teams window via UI Automation."""
    try:
        import uiautomation as auto  # type: ignore[import-untyped]
        control = auto.ControlFromHandle(hwnd)
        if not control:
            return None

        names: list[str] = []

        def is_list_item(c) -> bool:
            if getattr(c, "ControlTypeName", None) == "ListItemControl":
                name = getattr(c, "Name", "")
                if name and name.strip():
                    names.append(name.strip())
            return False  # always continue walking to find all list items

        _walk_depth_limited(control, is_list_item)

        if not names:
            return None
        return names
    except Exception:
        logger.debug("UIA extraction failed for hwnd %s", hwnd, exc_info=True)
        return None


# Per-platform call-state checkers populated in Task 11.
_CALL_STATE_CHECKERS: dict[str, Callable[[Any], bool]] = {}


def is_call_active(hwnd: int, platform: str) -> bool:
    """True if the window at hwnd is an active call for the given platform.

    Task 10 ships with an empty _CALL_STATE_CHECKERS dict, so this always
    returns True (regex-trust fallback). Task 11 populates the dict with
    Teams + Zoom checkers.
    """
    checker = _CALL_STATE_CHECKERS.get(platform)
    if checker is None:
        return True
    try:
        import uiautomation as auto
        control = auto.ControlFromHandle(hwnd)
        if control is None:
            return True
        return checker(control)
    except Exception:
        logger.debug("UIA call-state check failed for %s hwnd=%s", platform, hwnd, exc_info=True)
        return True


def has_call_state_checker(platform: str) -> bool:
    return platform in _CALL_STATE_CHECKERS
```

3. Replace in `recap/daemon/recorder/enrichment.py` the bodies of `extract_teams_participants` and `_walk_for_participants` with a re-export at the top of the file:

```python
from recap.daemon.recorder.call_state import extract_teams_participants
```

Keep `enrich_meeting_metadata` intact (it uses `extract_teams_participants` internally). Add `"extract_teams_participants"` to `__all__` if present.

4. Move Teams-participant tests from wherever they currently live (`git grep "extract_teams_participants" tests/`) to new `tests/test_call_state.py`. Update imports in the moved tests.

5. Run: `uv run pytest tests/test_enrichment.py tests/test_call_state.py --no-cov -v` — all green.

6. Full suite: `uv run pytest -q`.

7. Commit:

```bash
git add recap/daemon/recorder/call_state.py recap/daemon/recorder/enrichment.py tests/test_call_state.py tests/test_enrichment.py
git commit -m "refactor(recorder): extract call_state module"
```

---

## Task 11: UIA-confirmed call state for Teams + Zoom

**Design ref:** §3.2, §3.3

**Files:**
- Modify: `recap/daemon/recorder/call_state.py` (populate `_CALL_STATE_CHECKERS`)
- Modify: `recap/daemon/recorder/detection.py` (add UIA gate, exclusion set scaffolding, `is_window_alive`)
- Modify: `tests/test_call_state.py` (add 4 tests)
- Modify: `tests/test_detection.py` (add 2 tests)

**Steps:**

1. In `call_state.py`, add checkers and populate dict:

```python
def _is_teams_call_active(control) -> bool:
    def is_leave_button(c) -> bool:
        ct = getattr(c, "ControlTypeName", None)
        name = getattr(c, "Name", "") or ""
        return (
            ct == "ButtonControl"
            and name.strip().lower() in {"leave", "hang up", "end call"}
        )
    return _walk_depth_limited(control, is_leave_button) is not None


def _is_zoom_call_active(control) -> bool:
    def is_zoom_control(c) -> bool:
        ct = getattr(c, "ControlTypeName", None)
        name = (getattr(c, "Name", "") or "").lower()
        return ct == "ButtonControl" and any(
            t in name for t in ("mute", "unmute", "start video", "stop video", "leave meeting")
        )
    return _walk_depth_limited(control, is_zoom_control) is not None


_CALL_STATE_CHECKERS = {
    "teams": _is_teams_call_active,
    "zoom": _is_zoom_call_active,
}
```

2. In `detection.py`, add module-level exclusion set (helpers added in Task 14):

```python
_EXCLUDED_HWNDS: set[int] = set()
```

3. Update `detect_meeting_windows` in `detection.py`:

```python
from recap.daemon.recorder import call_state

def detect_meeting_windows(enabled_platforms=None) -> list[MeetingWindow]:
    windows = _enumerate_windows()
    platforms = enabled_platforms if enabled_platforms is not None else set(MEETING_PATTERNS)
    meetings = []
    for hwnd, title in windows:
        if hwnd in _EXCLUDED_HWNDS:
            continue
        for platform in platforms:
            pattern = MEETING_PATTERNS.get(platform)
            if pattern and pattern.search(title):
                if not call_state.is_call_active(hwnd, platform):
                    continue
                meetings.append(MeetingWindow(hwnd=hwnd, title=title, platform=platform))
                break
    return meetings
```

4. Add `is_window_alive` to `detection.py`:

```python
def is_window_alive(hwnd: int) -> bool:
    """Hard Windows signal: the window still exists and is visible."""
    if win32gui is None:
        return True
    try:
        return win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd)
    except Exception:
        return True
```

5. Add to `tests/test_call_state.py`:

```python
class FakeControl:
    def __init__(self, ControlTypeName="", Name="", children=None):
        self.ControlTypeName = ControlTypeName
        self.Name = Name
        self._children = children or []

    def GetChildren(self):
        return self._children


def test_is_call_active_returns_true_when_leave_button_present():
    from recap.daemon.recorder.call_state import _is_teams_call_active
    leave_btn = FakeControl("ButtonControl", "Leave")
    root = FakeControl(children=[leave_btn])
    assert _is_teams_call_active(root) is True


def test_is_call_active_returns_false_when_no_call_controls():
    from recap.daemon.recorder.call_state import _is_teams_call_active
    chat_btn = FakeControl("ButtonControl", "Chat")
    root = FakeControl(children=[chat_btn])
    assert _is_teams_call_active(root) is False


def test_is_call_active_returns_true_for_unregistered_platform():
    from recap.daemon.recorder.call_state import is_call_active
    assert is_call_active(hwnd=1, platform="signal") is True


def test_is_call_active_returns_true_on_uia_exception(monkeypatch):
    import uiautomation
    from recap.daemon.recorder.call_state import is_call_active
    def raise_it(_): raise RuntimeError("uia broken")
    monkeypatch.setattr(uiautomation, "ControlFromHandle", raise_it)
    assert is_call_active(hwnd=1, platform="teams") is True
```

6. Add to `tests/test_detection.py`:

```python
def test_is_window_alive_returns_false_for_closed_hwnd(monkeypatch):
    import recap.daemon.recorder.detection as det
    monkeypatch.setattr(det.win32gui, "IsWindow", lambda h: False)
    assert det.is_window_alive(999) is False


def test_detect_meeting_windows_excludes_unconfirmed_candidates(monkeypatch):
    import recap.daemon.recorder.detection as det
    monkeypatch.setattr(det, "_enumerate_windows", lambda: [(42, "Standup | Microsoft Teams")])
    monkeypatch.setattr(det.call_state, "is_call_active", lambda h, p: False)
    result = det.detect_meeting_windows({"teams"})
    assert result == []
```

7. Run tests: `uv run pytest tests/test_call_state.py tests/test_detection.py --no-cov -v`.

8. Full suite: `uv run pytest -q`.

9. Commit:

```bash
git add recap/daemon/recorder/call_state.py recap/daemon/recorder/detection.py tests/test_call_state.py tests/test_detection.py
git commit -m "feat(recorder): UIA-confirmed call state for Teams and Zoom detection"
```

---

## Task 12: Split detector stop/dedupe + seal poll-task unwind

**Design ref:** §3.4

**Files:**
- Modify: `recap/daemon/recorder/detector.py:258-398`
- Modify: `tests/test_detector.py` (add 5 tests)

**Steps:**

1. Rewrite `_poll_once` per §3.4. Replace the current stop-monitoring branch + detection loop + existing cleanup with:

```python
async def _poll_once(self) -> None:
    # --- Stop-monitoring path: hard Windows signal only ---
    if self._recorder.is_recording and self._recording_hwnd is not None:
        if not is_window_alive(self._recording_hwnd):
            logger.info("Meeting window closed, stopping recording")
            await self._recorder.stop()
            self._recording_hwnd = None

    # --- Arm timeout check (unchanged) ---
    if self._armed_event is not None:
        deadline = self._armed_event["start_time"] + _ARM_TIMEOUT
        if datetime.now() > deadline:
            logger.info("Arm timeout reached, disarming")
            self.disarm()

    # --- Detection path ---
    detected = detect_meeting_windows(self.enabled_platforms)
    detected_hwnds: set[int] = set()

    for meeting in detected:
        detected_hwnds.add(meeting.hwnd)

        if meeting.hwnd in self._tracked_meetings:
            continue

        if self._recorder.is_recording:
            continue  # don't start concurrent recordings

        self._tracked_meetings[meeting.hwnd] = meeting
        enriched = enrich_meeting_metadata(
            meeting.hwnd,
            meeting.title,
            meeting.platform,
            self._config.known_contacts,
        )
        # ... existing armed/auto-record/prompt logic from current detector.py ...

    # --- End-of-poll prune with active-recording protection ---
    stale = set(self._tracked_meetings) - detected_hwnds
    if self._recording_hwnd is not None:
        stale.discard(self._recording_hwnd)
    for hwnd in stale:
        del self._tracked_meetings[hwnd]
```

Preserve the existing armed/auto-record/prompt behavior inside the for loop — that code isn't changing, only the surrounding structure.

2. Update `stop()` method:

```python
async def stop(self) -> None:
    """Cancel the polling task and drain any pending signal callbacks."""
    if self._poll_task is not None:
        self._poll_task.cancel()
        try:
            await self._poll_task
        except asyncio.CancelledError:
            pass
        self._poll_task = None

    if self._pending_signal_tasks:
        for task in list(self._pending_signal_tasks):
            task.cancel()
        await asyncio.gather(
            *self._pending_signal_tasks, return_exceptions=True,
        )
        self._pending_signal_tasks.clear()
```

3. Ensure `is_window_alive` is imported at the top of `detector.py`:

```python
from recap.daemon.recorder.detection import detect_meeting_windows, is_window_alive
```

4. Add 5 tests to `tests/test_detector.py`. Each uses `AsyncMock` for Recorder and monkeypatches `detect_meeting_windows` / `is_window_alive` as needed. Test names per §3.7:
   - `test_tracked_meeting_pruned_when_dropped_from_detected`
   - `test_stop_path_ignores_uia_false_negative`
   - `test_recording_hwnd_survives_uia_flap_during_recording`
   - `test_no_retrigger_after_recording_stops_if_hwnd_still_tracked`
   - `test_stop_waits_for_poll_task_unwind`

See §3.7 of design doc for specific assertion patterns.

5. Run: `uv run pytest tests/test_detector.py --no-cov -v`.

6. Full suite: `uv run pytest -q`.

7. Commit:

```bash
git add recap/daemon/recorder/detector.py tests/test_detector.py
git commit -m "fix(detector): split stop/confirmed pruning + seal poll-task unwind on stop"
```

---

## Task 13: Signal popup rewrite

**Design ref:** §4.2, §4.3

**Files:**
- Modify: `recap/daemon/recorder/signal_popup.py` (major rewrite)
- Modify: `recap/daemon/service.py` (spawn dedicated executor)
- Modify: `recap/daemon/__main__.py` (plumb executor)
- Modify: `tests/test_signal_popup.py` (autouse fixture + 8 tests)

**Steps:**

1. Add autouse fixture at top of `tests/test_signal_popup.py`:

```python
import pytest

@pytest.fixture(autouse=True)
def reset_shutdown_flag():
    from recap.daemon.recorder import signal_popup
    if hasattr(signal_popup, "_shutdown_requested"):
        signal_popup._shutdown_requested.clear()
    yield
    if hasattr(signal_popup, "_shutdown_requested"):
        signal_popup._shutdown_requested.clear()
```

2. Add the 8 tests from §4.5:
   - `test_show_signal_popup_requires_executor_keyword`
   - `test_show_signal_popup_uses_provided_executor`
   - `test_blocking_dialog_registers_and_deregisters_hwnd`
   - `test_request_shutdown_sets_event`
   - `test_blocking_dialog_returns_none_on_shutdown_signal`
   - `test_blocking_dialog_short_circuits_when_shutdown_already_requested`
   - `test_wait_for_shutdown_empty_returns_true_immediately`
   - `test_wait_for_shutdown_waits_for_all_outstanding`
   - `test_cancelled_queued_future_is_removed_from_set`

Each test's assertion specified in §4.5. Most will FAIL pre-rewrite (module state doesn't exist yet). Run to see the RED baseline.

3. Rewrite `recap/daemon/recorder/signal_popup.py`:

```python
"""Native Windows dialog for Signal call detection.

Rewritten in Phase 7 to fix tkinter threading + shutdown + self-detection
issues. See docs/plans/2026-04-16-phase7-design.md §4 for rationale.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from typing import Any, Optional

from recap.daemon.recorder import detection

logger = logging.getLogger("recap.daemon.recorder.signal_popup")

_BACKEND_LABELS: dict[str, str] = {
    "claude": "Claude",
    "ollama": "Local only",
}


def _label_for_backend(value: str) -> str:
    return _BACKEND_LABELS.get(value, value)


# --- Sticky shutdown + outstanding-futures tracking ---

_shutdown_requested = threading.Event()
_outstanding_futures: set[concurrent.futures.Future] = set()
_outstanding_lock = threading.Lock()


def request_shutdown() -> None:
    """Sticky shutdown flag. Never cleared by popup code — process-lifetime."""
    _shutdown_requested.set()


def _register_future(fut: concurrent.futures.Future) -> None:
    with _outstanding_lock:
        _outstanding_futures.add(fut)


def _unregister_future(fut: concurrent.futures.Future) -> None:
    with _outstanding_lock:
        _outstanding_futures.discard(fut)


def wait_for_shutdown(timeout: float = 5.0) -> bool:
    """Wait for all outstanding popup workers to finish."""
    with _outstanding_lock:
        pending = list(_outstanding_futures)
    if not pending:
        return True
    done, not_done = concurrent.futures.wait(pending, timeout=timeout)
    return len(not_done) == 0


# --- Blocking dialog (runs on the popup executor thread) ---

def _blocking_dialog(
    org_slug: str,
    available_backends: list[str],
) -> dict[str, str] | None:
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

                org_label = tk.Label(root, text=f"Org: {org_slug}")
                org_label.pack(padx=10, pady=5)

                intro = tk.Label(root, text="Record this Signal call?")
                intro.pack(padx=10, pady=5)

                pipeline_combo = ttk.Combobox(root, values=label_values, state="readonly")
                pipeline_combo.current(0)
                pipeline_combo.pack(padx=10, pady=5)

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

                btn_frame = tk.Frame(root)
                btn_frame.pack(padx=10, pady=10)
                tk.Button(btn_frame, text="Record", command=_on_record).pack(side="left", padx=5)
                tk.Button(btn_frame, text="Skip", command=_on_skip).pack(side="left", padx=5)

                def _check_shutdown():
                    if _shutdown_requested.is_set():
                        root.quit()
                    else:
                        root.after(100, _check_shutdown)

                root.after(100, _check_shutdown)
                root.mainloop()
            finally:
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


# --- Public async API ---

async def show_signal_popup(
    *,
    org_slug: str,
    available_backends: list[str],
    executor: concurrent.futures.ThreadPoolExecutor,
) -> dict[str, str] | None:
    """Submit to the popup executor, track cf_future for shutdown, await."""
    cf_future = executor.submit(_blocking_dialog, org_slug, list(available_backends))
    _register_future(cf_future)
    cf_future.add_done_callback(_unregister_future)
    return await asyncio.wrap_future(cf_future)
```

4. Update `recap/daemon/service.py` `Daemon`:
   - Add `self._popup_executor: ThreadPoolExecutor | None = None` to `__init__`.
   - In `start()`:
     ```python
     from concurrent.futures import ThreadPoolExecutor
     self._popup_executor = ThreadPoolExecutor(
         max_workers=1,
         thread_name_prefix="signal-popup-ui",
     )
     ```
   - In `stop()` after `await self._detector.stop()`:
     ```python
     from recap.daemon.recorder import signal_popup
     signal_popup.request_shutdown()
     if not signal_popup.wait_for_shutdown(timeout=5.0):
         logger.warning(
             "signal popup worker did not finish within 5s; daemon shutdown "
             "compromised — user may need to force-kill the process."
         )
     if self._popup_executor is not None:
         self._popup_executor.shutdown(wait=False)
         self._popup_executor = None
     ```

5. Update `recap/daemon/__main__.py:263` — thread `daemon._popup_executor` through to `show_signal_popup(..., executor=daemon._popup_executor)`. The `on_signal_detected` closure should capture `daemon` and pass the executor.

6. Run: `uv run pytest tests/test_signal_popup.py --no-cov -v`.

7. Full suite: `uv run pytest -q`.

8. Commit:

```bash
git add recap/daemon/recorder/signal_popup.py recap/daemon/service.py recap/daemon/__main__.py tests/test_signal_popup.py
git commit -m "fix(signal-popup): dedicated executor + sticky shutdown + outstanding-futures tracking"
```

---

## Task 14: Detection self-exclusion

**Design ref:** §4.4

**Files:**
- Modify: `recap/daemon/recorder/detection.py` (add helpers)
- Modify: `tests/test_detection.py` (add 2 tests)

Note: the `_EXCLUDED_HWNDS` set was added in Task 11; this task only adds the public helpers (callable from signal_popup) and the tests. `signal_popup._blocking_dialog` already calls `detection.exclude_hwnd` / `include_hwnd` from Task 13's rewrite, so those must exist by now — they're added here.

**Steps:**

1. Add to `recap/daemon/recorder/detection.py`:

```python
def exclude_hwnd(hwnd: int) -> None:
    """Register an hwnd that MUST NOT be detected as a meeting."""
    _EXCLUDED_HWNDS.add(hwnd)


def include_hwnd(hwnd: int) -> None:
    """Remove an hwnd from the exclusion set."""
    _EXCLUDED_HWNDS.discard(hwnd)
```

2. Add to `tests/test_detection.py`:

```python
def test_excluded_hwnds_do_not_match_any_platform(monkeypatch):
    import recap.daemon.recorder.detection as det
    monkeypatch.setattr(det, "_enumerate_windows", lambda: [(42, "Signal call detected")])
    det.exclude_hwnd(42)
    try:
        result = det.detect_meeting_windows({"signal"})
    finally:
        det.include_hwnd(42)
    assert result == []


def test_exclude_include_are_symmetric():
    import recap.daemon.recorder.detection as det
    det.exclude_hwnd(123)
    assert 123 in det._EXCLUDED_HWNDS
    det.include_hwnd(123)
    assert 123 not in det._EXCLUDED_HWNDS
```

3. Run: `uv run pytest tests/test_detection.py tests/test_signal_popup.py --no-cov -v`.

4. Full suite: `uv run pytest -q`.

5. Commit:

```bash
git add recap/daemon/recorder/detection.py tests/test_detection.py
git commit -m "feat(detection): exclude daemon-owned popup windows"
```

**Task 14 completes the "known good" checkpoint** — at this point all 5 Final Integration Pass scenarios are runnable. Tasks 15-16 are documentation only.

---

## Task 15: README integration test section

**Files:**
- Modify: `README.md`

**Steps:**

1. Add a "Running tests" section to README.md (content from §5.7 of design doc). Place after the existing "Development Setup" section or similar.

2. Commit:

```bash
git add README.md
git commit -m "docs(readme): integration test tier invocation"
```

---

## Task 16: Update handoff + phase plan + MANIFEST.md

**Files:**
- Modify: `docs/handoffs/2026-04-15-final-integration-pass.md`
- Modify: `docs/plans/2026-04-16-phase7-ml-stack-refresh.md`
- Regenerate: `MANIFEST.md`

**Steps:**

1. In `docs/handoffs/2026-04-15-final-integration-pass.md`:
   - Remove the `⚠️ 2026-04-16 update` blocker banner paragraph.
   - Add to the Automated Gates section: `| Phase 7 library + detection + popup refresh | ALL LANDED (branch phase-7-ml-stack-refresh) |`.

2. In `docs/plans/2026-04-16-phase7-ml-stack-refresh.md`:
   - Change `**Status:** proposed (unbranched)` to `**Status:** landed (branch phase-7-ml-stack-refresh)`.
   - Add at top: `**Detailed design:** docs/plans/2026-04-16-phase7-design.md`.

3. Regenerate `MANIFEST.md`. Walk the repo tree and update Structure + Key Relationships sections to include:
   - `recap/daemon/recorder/call_state.py` (new — UIA helpers + per-platform call-state checkers)
   - `tests/integration/` (new — CPU contract smoke + GPU model + e2e)
   - Updated lines for streaming/transcriber.py and streaming/diarizer.py (now stubs)
   - Updated lines for detector.py (two-path stop/dedupe), signal_popup.py (executor + sticky shutdown), detection.py (UIA gate + exclusion set)

4. Commit:

```bash
git add docs/handoffs/2026-04-15-final-integration-pass.md docs/plans/2026-04-16-phase7-ml-stack-refresh.md MANIFEST.md
git commit -m "docs(handoff): unblock Final Integration Pass scenarios after Phase 7"
```

---

## Post-commit manual verification

Run all 5 scenarios from `docs/handoffs/2026-04-15-final-integration-pass.md` plus Phase 7 additions in §6.5 of design doc.

Phase 7-specific checks:

1. **Teams false-positive gate:** start daemon with Teams Desktop open on a Chat tab. Tail log for 10 seconds. No `Auto-recording` lines must appear.
2. **Popup shutdown stress:** start Signal Desktop; let detector fire popup; while popup is open, right-click tray → Quit. Daemon process gone from Task Manager within 5 seconds.
3. **Popup self-exclusion:** while popup is open, tail daemon log. No repeated Signal detection beyond the one that opened the popup.

Mark each scenario's checkboxes in the handoff as done. Any `[F]` (fail) gets a bug ticket before attempting merge.

---

## Merge readiness checklist

- [ ] All 16 commits on `phase-7-ml-stack-refresh`.
- [ ] `uv run pytest -q` — ≥ 573 + Phase 7 tests; coverage ≥ 70%.
- [ ] `uv run pytest -m integration --no-cov tests/integration/test_contract_smoke.py` — 6/6.
- [ ] `uv run pytest -m integration --no-cov` (GPU box) — 9/9.
- [ ] `cd obsidian-recap && npm run build` — clean.
- [ ] Daemon boot smoke (§7.1 gate 5) — passes.
- [ ] All 5 manual scenarios + 3 Phase 7 additions marked `[x]`.
- [ ] README + handoff + phase plan + MANIFEST.md updated.
- [ ] Phase 8 follow-ups filed (e.g., `docs/plans/future-phases.md` entries).

Merge:

```bash
git checkout obsidian-pivot
git merge --no-ff phase-7-ml-stack-refresh
```

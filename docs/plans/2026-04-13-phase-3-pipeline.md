# Phase 3: Pipeline Adaptation

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rewrite the transcription/diarization pipeline for Parakeet + NeMo, adapt vault.py for the new org structure and Obsidian Tasks format, add FLAC-to-AAC conversion, and wire the pipeline into the daemon so recordings are automatically processed.

**Architecture:** Pipeline stages run sequentially after recording stops. GPU models load/unload between stages to stay within 12GB VRAM. Status is tracked in both status.json and meeting note frontmatter. The pipeline writes vault notes directly to the org subfolder.

**Tech Stack:** NeMo, Parakeet, PyTorch, ffmpeg (for AAC conversion), Claude CLI

---

### Task 1: Add NeMo/Parakeet dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add ML dependency group**

```toml
[project.optional-dependencies]
ml = [
    "nemo_toolkit[asr]>=2.0",
    "torch>=2.1",
]
daemon = [
    # ... existing entries ...
]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

Note: NeMo pulls in PyTorch and many transitive deps. The `[asr]` extra includes Parakeet model support.

**Step 2: Install and verify**

```bash
uv sync --extra ml --extra daemon --extra dev
python -c "
import nemo.collections.asr as nemo_asr
print('NeMo ASR loaded')
import torch
print(f'CUDA available: {torch.cuda.is_available()}')
print(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"none\"}')
"
```

**Step 3: Download models**

```python
# Run once to cache models locally
import nemo.collections.asr as nemo_asr
model = nemo_asr.models.ASRModel.from_pretrained("nvidia/parakeet-tdt-0.6b-v2")
del model

from nemo.collections.asr.models import SortformerEncLabelModel
diar_model = SortformerEncLabelModel.from_pretrained("nvidia/diar_streaming_sortformer_4spk-v2.1")
del diar_model
```

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add NeMo/Parakeet ML dependencies"
```

---

### Task 2: Parakeet transcription module

**Files:**
- Create: `recap/pipeline/transcribe.py`
- Create: `recap/pipeline/__init__.py`
- Test: `tests/test_pipeline_transcribe.py`

**Step 1: Write the failing tests**

```python
"""Tests for Parakeet transcription."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from recap.pipeline.transcribe import transcribe
from recap.models import TranscriptResult


class TestTranscribe:
    def test_returns_transcript_result(self, tmp_path):
        """Mock NeMo model to test output parsing."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = [{
            "text": "Hello world",
            "timestamp": {"segment": [
                {"start": 0.0, "end": 1.5, "text": "Hello"},
                {"start": 1.5, "end": 2.5, "text": "world"},
            ]}
        }]

        with patch("recap.pipeline.transcribe._load_model", return_value=mock_model):
            result = transcribe(
                audio_path=tmp_path / "test.flac",
                model_name="nvidia/parakeet-tdt-0.6b-v2",
                device="cpu",
            )

        assert isinstance(result, TranscriptResult)
        assert "Hello" in result.raw_text

    def test_saves_transcript_json(self, tmp_path):
        mock_model = MagicMock()
        mock_model.transcribe.return_value = [{
            "text": "Test",
            "timestamp": {"segment": [
                {"start": 0.0, "end": 1.0, "text": "Test"},
            ]}
        }]

        save_path = tmp_path / "transcript.json"
        with patch("recap.pipeline.transcribe._load_model", return_value=mock_model):
            transcribe(
                audio_path=tmp_path / "test.flac",
                model_name="nvidia/parakeet-tdt-0.6b-v2",
                device="cpu",
                save_transcript=save_path,
            )

        assert save_path.exists()
        data = json.loads(save_path.read_text())
        assert "utterances" in data

    def test_unloads_model_after_transcription(self, tmp_path):
        mock_model = MagicMock()
        mock_model.transcribe.return_value = [{
            "text": "Test",
            "timestamp": {"segment": [
                {"start": 0.0, "end": 1.0, "text": "Test"},
            ]}
        }]

        with patch("recap.pipeline.transcribe._load_model", return_value=mock_model) as load_mock:
            with patch("recap.pipeline.transcribe._unload_model") as unload_mock:
                transcribe(
                    audio_path=tmp_path / "test.flac",
                    model_name="nvidia/parakeet-tdt-0.6b-v2",
                    device="cpu",
                )
                unload_mock.assert_called_once()
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pipeline_transcribe.py -v
```

**Step 3: Implement transcription module**

`recap/pipeline/transcribe.py`:
- `_load_model(model_name, device) -> ASRModel` — load Parakeet from NeMo
- `_unload_model(model)` — `del model; torch.cuda.empty_cache(); gc.collect()`
- `transcribe(audio_path, model_name, device, save_transcript=None) -> TranscriptResult`:
  1. Load model
  2. Transcribe audio file (returns text + timestamps)
  3. Parse NeMo output into `Utterance` objects (speaker field left as "UNKNOWN" — diarization fills it in)
  4. Build `TranscriptResult`
  5. Optionally save to JSON
  6. Unload model
  7. Return result

Note: utterances at this stage have timestamps and text but no speaker labels. Diarization (Task 3) adds those.

**Step 4: Run tests, commit**

```bash
pytest tests/test_pipeline_transcribe.py -v
git add recap/pipeline/ tests/test_pipeline_transcribe.py
git commit -m "feat: add Parakeet transcription with model load/unload"
```

---

### Task 3: NeMo diarization module

**Files:**
- Create: `recap/pipeline/diarize.py`
- Test: `tests/test_pipeline_diarize.py`

**Step 1: Write the failing tests**

```python
"""Tests for NeMo speaker diarization."""
import pytest
from unittest.mock import patch, MagicMock
from recap.pipeline.diarize import diarize, assign_speakers
from recap.models import TranscriptResult, Utterance


class TestDiarize:
    def test_returns_speaker_segments(self, tmp_path):
        mock_model = MagicMock()
        mock_model.diarize.return_value = [
            {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"},
            {"start": 5.0, "end": 10.0, "speaker": "SPEAKER_01"},
        ]

        with patch("recap.pipeline.diarize._load_diarization_model", return_value=mock_model):
            with patch("recap.pipeline.diarize._unload_model"):
                segments = diarize(
                    audio_path=tmp_path / "test.flac",
                    model_name="nvidia/diar_streaming_sortformer_4spk-v2.1",
                    device="cpu",
                )
        assert len(segments) == 2
        assert segments[0]["speaker"] == "SPEAKER_00"


class TestAssignSpeakers:
    def test_assigns_speakers_by_overlap(self):
        transcript = TranscriptResult(
            utterances=[
                Utterance(speaker="UNKNOWN", start=0.0, end=3.0, text="Hello"),
                Utterance(speaker="UNKNOWN", start=5.0, end=8.0, text="Hi there"),
            ],
            raw_text="Hello Hi there",
            language="en",
        )
        speaker_segments = [
            {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"},
            {"start": 5.0, "end": 10.0, "speaker": "SPEAKER_01"},
        ]

        result = assign_speakers(transcript, speaker_segments)
        assert result.utterances[0].speaker == "SPEAKER_00"
        assert result.utterances[1].speaker == "SPEAKER_01"

    def test_handles_overlapping_segments(self):
        transcript = TranscriptResult(
            utterances=[
                Utterance(speaker="UNKNOWN", start=4.0, end=6.0, text="overlap"),
            ],
            raw_text="overlap",
            language="en",
        )
        speaker_segments = [
            {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"},
            {"start": 5.0, "end": 10.0, "speaker": "SPEAKER_01"},
        ]

        result = assign_speakers(transcript, speaker_segments)
        # Should assign to the speaker with the most overlap
        assert result.utterances[0].speaker in ("SPEAKER_00", "SPEAKER_01")
```

**Step 2: Run, fail, implement**

`recap/pipeline/diarize.py`:
- `_load_diarization_model(model_name, device)` — load NeMo Sortformer
- `_unload_model(model)` — del + cache clear
- `diarize(audio_path, model_name, device) -> list[dict]` — returns speaker segments with start/end/speaker
- `assign_speakers(transcript: TranscriptResult, segments: list[dict]) -> TranscriptResult` — for each utterance, find the speaker segment with the most temporal overlap, assign that speaker label. Returns a new TranscriptResult with speakers filled in.

**Step 3: Run tests, commit**

```bash
pytest tests/test_pipeline_diarize.py -v
git add recap/pipeline/diarize.py tests/test_pipeline_diarize.py
git commit -m "feat: add NeMo diarization with speaker-to-utterance assignment"
```

---

### Task 4: Adapt vault.py for new structure

**Files:**
- Modify: `recap/vault.py`
- Modify: `tests/test_vault.py`

**Step 1: Update tests for new format**

Update existing vault tests to reflect:
- Org subfolder routing (`_Recap/Disbursecloud/Meetings/` instead of `Work/Meetings/`)
- Obsidian Tasks emoji format (`📅`, `⏫`) instead of `#todoist` tags
- No frames/screenshots section
- `pipeline-status` and `pipeline-error` frontmatter fields
- `org` frontmatter field
- `## Meeting Record` append marker
- Append guard (check if marker exists, replace below it on reprocess)

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_vault.py -v
```

**Step 3: Update vault.py**

Key changes:
- `_generate_meeting_markdown()` — remove frames section, add `## Meeting Record` marker before pipeline content
- Action items: map `priority` to emoji (`high` → `⏫`, `normal` → `🔼`, `low` → none), add `📅` for due dates
- Remove all `#todoist` references
- Add `org` to frontmatter
- Add `pipeline-status` and `pipeline-error` to frontmatter
- New function: `write_meeting_note(vault_path, org_config, analysis, transcript, metadata)` that:
  1. Determines target path: `{vault_path}/{org.subfolder}/Meetings/{date} - {title}.md`
  2. If note exists and has `## Meeting Record` marker: replace everything below marker
  3. If note exists without marker: append marker + content
  4. If note doesn't exist: create with frontmatter + content
- People/company stubs: write to `{org.subfolder}/People/` and `{org.subfolder}/Companies/`
- Only create stubs for people/companies that don't already have notes

**Step 4: Run tests, commit**

```bash
pytest tests/test_vault.py -v
git add recap/vault.py tests/test_vault.py
git commit -m "feat: adapt vault writer for org subfolders, Obsidian Tasks, and append guard"
```

---

### Task 5: Adapt analyze.py for pluggable backend

**Files:**
- Modify: `recap/analyze.py`
- Modify: `tests/test_analyze.py`

**Step 1: Update tests**

Add test for backend parameter:

```python
def test_uses_claude_backend_by_default(self, ...):
    # existing test, verify claude --print is called

def test_uses_ollama_backend_when_specified(self, ...):
    # mock subprocess, verify ollama command is called
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout='{"summary": "test"}', returncode=0)
        analyze(transcript, metadata, backend="ollama", ollama_model="llama3")
        assert "ollama" in mock_run.call_args[0][0][0]
```

**Step 2: Implement backend parameter**

Add `backend: str = "claude"` and `ollama_model: str = ""` parameters to `analyze()`. When `backend="ollama"`, call `ollama run {model}` instead of `claude --print`. Same prompt template, same output parsing.

**Step 3: Run tests, commit**

```bash
pytest tests/test_analyze.py -v
git add recap/analyze.py tests/test_analyze.py
git commit -m "feat: add pluggable LLM backend (claude/ollama) to analysis"
```

---

### Task 6: Audio conversion (FLAC to AAC)

**Files:**
- Create: `recap/pipeline/audio_convert.py`
- Test: `tests/test_audio_convert.py`

**Step 1: Write the failing tests**

```python
"""Tests for audio format conversion."""
import subprocess
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from recap.pipeline.audio_convert import convert_flac_to_aac


class TestConvertFlacToAac:
    def test_calls_ffmpeg_with_correct_args(self, tmp_path):
        flac_path = tmp_path / "recording.flac"
        flac_path.write_bytes(b"fake flac")
        expected_output = tmp_path / "recording.m4a"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = convert_flac_to_aac(flac_path)

        assert result == expected_output
        cmd = mock_run.call_args[0][0]
        assert "ffmpeg" in cmd[0]
        assert "-codec:a" in cmd or "-c:a" in cmd

    def test_returns_output_path(self, tmp_path):
        flac_path = tmp_path / "recording.flac"
        flac_path.write_bytes(b"fake flac")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = convert_flac_to_aac(flac_path)

        assert result.suffix == ".m4a"
        assert result.stem == "recording"

    def test_raises_on_ffmpeg_failure(self, tmp_path):
        flac_path = tmp_path / "recording.flac"
        flac_path.write_bytes(b"fake flac")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            with pytest.raises(RuntimeError, match="ffmpeg"):
                convert_flac_to_aac(flac_path)
```

**Step 2: Run, fail, implement**

`convert_flac_to_aac(flac_path: Path, bitrate: str = "64k") -> Path`:
- Output path: same directory, same stem, `.m4a` extension
- Call: `ffmpeg -i input.flac -c:a aac -b:a 64k output.m4a`
- Raise RuntimeError on non-zero exit
- Return output path

**Step 3: Run tests, commit**

```bash
pytest tests/test_audio_convert.py -v
git add recap/pipeline/audio_convert.py tests/test_audio_convert.py
git commit -m "feat: add FLAC to AAC audio conversion via ffmpeg"
```

---

### Task 7: Pipeline orchestrator rewrite

**Files:**
- Modify: `recap/pipeline/pipeline.py` (or rewrite)
- Test: `tests/test_pipeline.py`

**Step 1: Rewrite pipeline orchestrator**

The existing `pipeline.py` references removed modules (frames, todoist). Rewrite it for the new stage sequence:

1. **transcribe** — Parakeet (or skip if streaming transcript provided)
2. **diarize** — NeMo Sortformer (or skip if streaming diarization provided)
3. **analyze** — Claude CLI or Ollama (per-org backend)
4. **export** — write vault note + people/company stubs
5. **convert** — FLAC to AAC (if configured)

Each stage:
- Updates `status.json` with stage name + timestamp
- Updates meeting note frontmatter `pipeline-status`
- On failure: sets `pipeline-status: failed:stagename` and `pipeline-error`, sends notification, auto-retries once
- On second failure: stops, requires manual retry

`run_pipeline(flac_path, org_config, config, streaming_transcript=None)`:
- If `streaming_transcript` is provided and complete, skip transcribe+diarize stages
- Otherwise run full pipeline sequentially
- Track status in both `status.json` and frontmatter

**Step 2: Update tests**

Test the orchestrator with mocked stage functions. Verify:
- Stages run in order
- Status is updated after each stage
- Streaming transcript skips transcribe+diarize
- Failure at any stage triggers retry
- Second failure stops pipeline and reports error
- Frontmatter is updated correctly

**Step 3: Run tests, commit**

```bash
pytest tests/test_pipeline.py -v
git add recap/pipeline/pipeline.py tests/test_pipeline.py
git commit -m "feat: rewrite pipeline orchestrator for Parakeet/NeMo with retry and status tracking"
```

---

### Task 8: Wire pipeline to daemon

**Files:**
- Modify: `recap/daemon/recorder/recorder.py` — trigger pipeline after recording stops
- Modify: `recap/daemon/server.py` — add reprocess endpoint
- Modify: `recap/daemon/__main__.py` — pass config to pipeline

**Step 1: Post-recording pipeline trigger**

When recording stops (state → PROCESSING):
1. Spawn pipeline in a background asyncio task
2. Pipeline runs all stages
3. On completion: state → IDLE, tray notification "Meeting processed — N action items"
4. On failure: state → IDLE, tray notification with error

**Step 2: Add reprocess endpoint**

`POST /api/meetings/reprocess` — body: `{"recording_path": "...", "from_stage": "analyze"}`. Runs pipeline from specified stage.

**Step 3: Manual end-to-end test**

1. Start daemon
2. Start recording via tray
3. Play audio for 30 seconds
4. Stop recording
5. Verify pipeline runs (check logs, status.json)
6. Verify vault note appears in correct org subfolder
7. Verify FLAC converted to AAC (if configured)
8. Verify frontmatter shows `pipeline-status: complete`

**Step 4: Commit**

```bash
git add recap/daemon/recorder/recorder.py recap/daemon/server.py recap/daemon/__main__.py
git commit -m "feat: wire pipeline to daemon — auto-process after recording stops"
```

---

### Task 9: Update prompts

**Files:**
- Modify: `prompts/meeting_analysis.md`

**Step 1: Remove screenshot/video references**

Edit the prompt to remove any references to screenshots, frames, or video. The input is audio-only: a diarized transcript with speaker labels.

**Step 2: Commit**

```bash
git add prompts/meeting_analysis.md
git commit -m "chore: remove screenshot references from analysis prompt (audio-only)"
```

---

### Task 10: Push and verify

**Step 1: Run all tests**

```bash
pytest tests/ -v --ignore=tests/fixtures
```

All tests should pass now. The old pipeline tests that were broken in Phase 0 should be fixed or replaced.

**Step 2: Full integration test**

Record a real meeting (or play a YouTube conversation), let the pipeline process it, verify the vault note is correct.

**Step 3: Push**

```bash
git push
```

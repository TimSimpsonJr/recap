# Phase 8: Real-Time Streaming Transcription

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add real-time transcription + diarization during recording using streaming Parakeet + NeMo Sortformer, feed results to the live transcript view via WebSocket, and skip batch transcription/diarization when streaming succeeded.

**Architecture:** Streaming models run concurrently with the audio capture. Audio is forked: one path writes FLAC to disk, the other feeds the streaming models. Streaming output is pushed over the existing WebSocket. The post-meeting pipeline checks whether streaming completed successfully and skips transcription/diarization if so.

**Tech Stack:** parakeet-stream, NeMo streaming Sortformer, asyncio

---

### Task 1: Add streaming dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add parakeet-stream**

```toml
ml = [
    "nemo_toolkit[asr]>=2.0",
    "torch>=2.1",
    "parakeet-stream>=0.1",
]
```

**Step 2: Install and verify**

```bash
uv sync --extra ml
python -c "import parakeet_stream; print('OK')"
```

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add parakeet-stream dependency for real-time transcription"
```

---

### Task 2: Streaming transcriber

**Files:**
- Create: `recap/daemon/streaming/transcriber.py`
- Create: `recap/daemon/streaming/__init__.py`
- Test: `tests/test_streaming_transcriber.py`

**Step 1: Write the failing tests**

```python
"""Tests for streaming transcriber."""
import pytest
from unittest.mock import MagicMock, patch
from recap.daemon.streaming.transcriber import StreamingTranscriber


class TestStreamingTranscriber:
    def test_initial_state(self):
        transcriber = StreamingTranscriber(model_name="nvidia/parakeet-tdt-0.6b-v2")
        assert transcriber.is_running is False
        assert transcriber.segments == []

    def test_records_segments(self):
        transcriber = StreamingTranscriber(model_name="nvidia/parakeet-tdt-0.6b-v2")
        transcriber._on_segment({"text": "Hello world", "start": 0.0, "end": 1.5})
        assert len(transcriber.segments) == 1
        assert transcriber.segments[0]["text"] == "Hello world"

    def test_has_error_flag(self):
        transcriber = StreamingTranscriber(model_name="nvidia/parakeet-tdt-0.6b-v2")
        assert transcriber.had_errors is False
        transcriber._on_error(Exception("GPU OOM"))
        assert transcriber.had_errors is True

    def test_get_transcript_result(self):
        transcriber = StreamingTranscriber(model_name="nvidia/parakeet-tdt-0.6b-v2")
        transcriber._on_segment({"text": "Hello", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"})
        transcriber._on_segment({"text": "Hi", "start": 1.0, "end": 2.0, "speaker": "SPEAKER_01"})
        result = transcriber.get_transcript_result()
        assert len(result.utterances) == 2
        assert result.utterances[0].speaker == "SPEAKER_00"
```

**Step 2: Run, fail, implement**

`StreamingTranscriber`:
- `__init__(model_name, device="cuda")` — configure but don't load model yet
- `start(audio_callback)` — load model, start processing audio chunks. `audio_callback` is called by the audio capture to provide raw audio frames.
- `stop() -> TranscriptResult | None` — stop processing, unload model. Returns TranscriptResult if no errors, None if errors occurred.
- `segments` — accumulated transcript segments with timestamps
- `had_errors` — True if any errors occurred during streaming
- `on_segment_callback` — called for each new segment (for WebSocket push)
- `_on_segment(segment)` — internal handler, appends to segments list + fires callback
- `_on_error(error)` — sets error flag, logs error
- `get_transcript_result() -> TranscriptResult` — convert accumulated segments to TranscriptResult

Uses `parakeet-stream` for the actual streaming inference.

**Step 3: Run tests, commit**

```bash
pytest tests/test_streaming_transcriber.py -v
git add recap/daemon/streaming/ tests/test_streaming_transcriber.py
git commit -m "feat: add streaming transcriber with Parakeet"
```

---

### Task 3: Streaming diarizer

**Files:**
- Create: `recap/daemon/streaming/diarizer.py`
- Test: `tests/test_streaming_diarizer.py`

**Step 1: Write the failing tests**

```python
"""Tests for streaming diarizer."""
from recap.daemon.streaming.diarizer import StreamingDiarizer


class TestStreamingDiarizer:
    def test_initial_state(self):
        diarizer = StreamingDiarizer(model_name="nvidia/diar_streaming_sortformer_4spk-v2.1")
        assert diarizer.is_running is False
        assert diarizer.had_errors is False

    def test_tracks_speaker_segments(self):
        diarizer = StreamingDiarizer(model_name="nvidia/diar_streaming_sortformer_4spk-v2.1")
        diarizer._on_speaker_segment({"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"})
        diarizer._on_speaker_segment({"start": 5.0, "end": 10.0, "speaker": "SPEAKER_01"})
        assert len(diarizer.speaker_segments) == 2
```

**Step 2: Run, fail, implement**

`StreamingDiarizer`:
- Same pattern as StreamingTranscriber but uses NeMo's streaming Sortformer
- Receives audio chunks, outputs speaker segments with timestamps
- `get_speaker_segments() -> list[dict]`
- `had_errors` flag

Note: the streaming Sortformer model (`nvidia/diar_streaming_sortformer_4spk-v2.1`) is designed for this use case. It processes audio in chunks and assigns speaker labels in near-real-time.

VRAM consideration: both Parakeet (~2GB) and Sortformer (~1-2GB per speaker) need to be loaded concurrently during streaming. For a 2-person call: ~4-6GB. For 4 people: ~6-10GB. This is tight but fits the 12GB 4070 for typical meetings. If VRAM is exceeded, the streaming diarizer should fail gracefully (set `had_errors = True`), and the post-meeting batch diarization (which runs sequentially) handles it.

**Step 3: Run tests, commit**

```bash
pytest tests/test_streaming_diarizer.py -v
git add recap/daemon/streaming/diarizer.py tests/test_streaming_diarizer.py
git commit -m "feat: add streaming diarizer with NeMo Sortformer"
```

---

### Task 4: Wire streaming to audio capture

**Files:**
- Modify: `recap/daemon/recorder/recorder.py`
- Modify: `recap/daemon/recorder/audio.py`

**Step 1: Fork audio stream**

When recording starts:
1. Audio capture writes FLAC to disk (existing behavior)
2. Audio capture ALSO feeds raw frames to the streaming transcriber and diarizer

Add an `on_audio_frame` callback to `AudioCapture` that fires for every audio frame. The recorder passes this to both streaming components.

**Step 2: Start/stop streaming with recording**

In `Recorder.start()`:
- Start audio capture
- Start streaming transcriber (if GPU available)
- Start streaming diarizer (if GPU available)
- If either fails to start: log warning, continue without streaming (FLAC recording is unaffected)

In `Recorder.stop()`:
- Stop audio capture
- Stop streaming transcriber → get TranscriptResult (or None on error)
- Stop streaming diarizer → get speaker segments (or None on error)
- If both succeeded: merge into final TranscriptResult with speaker labels
- Pass streaming result to pipeline (which may skip batch stages)

**Step 3: Commit**

```bash
git add recap/daemon/recorder/
git commit -m "feat: fork audio stream to FLAC recording + streaming models"
```

---

### Task 5: WebSocket transcript push

**Files:**
- Modify: `recap/daemon/server.py`

**Step 1: Push transcript segments over WebSocket**

When the streaming transcriber produces a new segment:
- Broadcast to all WebSocket clients:
```json
{
    "event": "transcript_segment",
    "speaker": "SPEAKER_00",
    "text": "I think we should focus on the Q3 roadmap",
    "start": 142.5,
    "end": 145.2
}
```

The live transcript view in the plugin receives these and calls `appendUtterance()`.

**Step 2: Manual test**

1. Start daemon with streaming enabled
2. Open Obsidian, open live transcript view
3. Start recording
4. Speak or play audio
5. Verify transcript segments appear in real-time

**Step 3: Commit**

```bash
git add recap/daemon/server.py
git commit -m "feat: push streaming transcript segments over WebSocket"
```

---

### Task 6: Skip-batch-if-streaming-succeeded logic

**Files:**
- Modify: `recap/pipeline/pipeline.py`

**Step 1: Implement skip logic**

`run_pipeline()` already accepts `streaming_transcript=None`. When provided:
- Check `streaming_transcript` is a valid `TranscriptResult` with speaker labels
- If valid: skip transcribe + diarize stages, proceed directly to analyze
- If None or incomplete: run full batch pipeline (load/unload models sequentially)
- Log which path was taken

**Step 2: Wire from recorder to pipeline**

In `Recorder`, after stopping:
- If streaming succeeded → pass `streaming_transcript` to pipeline
- If streaming failed → pass `None`, pipeline runs batch stages

**Step 3: Test both paths**

Create tests that verify:
- Pipeline skips transcribe/diarize when streaming result provided
- Pipeline runs all stages when streaming result is None
- Pipeline runs all stages when streaming result has errors

**Step 4: Commit**

```bash
git add recap/pipeline/pipeline.py recap/daemon/recorder/recorder.py tests/
git commit -m "feat: skip batch transcription when streaming succeeded"
```

---

### Task 7: Push and verify

**Step 1: Run all tests**

```bash
pytest tests/ -v --ignore=tests/fixtures
```

**Step 2: Full integration test**

1. Start daemon
2. Open Obsidian with live transcript view
3. Start a test call or play conversation audio
4. Verify live transcript appears in real-time
5. Stop recording
6. Verify pipeline skips transcribe/diarize (check logs)
7. Verify vault note is complete

**Step 3: Stress test VRAM**

Play a 4-person conversation. Monitor GPU memory. If streaming diarizer OOMs, verify:
- FLAC recording continues
- Batch pipeline runs after meeting
- Error is logged, not silent

**Step 4: Push**

```bash
git push
```

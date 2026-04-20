"""Tests for Parakeet chunked transcription."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from recap.models import TranscriptResult
from recap.pipeline.transcribe import transcribe


def _fake_slice(source, start_s, duration_s, temp_dir):
    """Stand-in for slice_window_to_temp that writes a trivial placeholder."""
    temp_dir.mkdir(parents=True, exist_ok=True)
    chunk = temp_dir / f"chunk-{start_s}.wav"
    chunk.write_bytes(b"RIFF")
    return chunk


class TestTranscribe:
    """Exercises the single-window happy path with a mocked NeMo model."""

    def _mock_model(self):
        mock = MagicMock()
        # NeMo transcribe returns a list of hypothesis objects
        mock_hyp = MagicMock()
        mock_hyp.text = "Hello world how are you"
        # NeMo (current) populates hyp.timestamp as a dict when transcribe is
        # called with timestamps=True. The "segment" list holds per-segment
        # dicts keyed by "segment" (text), "start", "end", "start_offset",
        # "end_offset".
        mock_hyp.timestamp = {
            "segment": [
                {
                    "segment": "Hello world",
                    "start": 0.0,
                    "end": 1.5,
                    "start_offset": 0,
                    "end_offset": 19,
                },
                {
                    "segment": "how are you",
                    "start": 1.8,
                    "end": 3.2,
                    "start_offset": 23,
                    "end_offset": 40,
                },
            ]
        }
        mock.transcribe.return_value = [mock_hyp]
        return mock

    def _patch_chunked_internals(self, monkeypatch, duration_s=30.0):
        """Stub _probe_duration_s + slice_window_to_temp so tests don't need
        real ffprobe/ffmpeg. Short duration keeps plan_windows to one window
        and leaves the mock model's utterances intact (no overlap dedup)."""
        monkeypatch.setattr(
            "recap.pipeline.transcribe._probe_duration_s",
            lambda _p: duration_s,
        )
        monkeypatch.setattr(
            "recap.pipeline.transcribe.slice_window_to_temp", _fake_slice,
        )

    def test_returns_transcript_result(self, tmp_path, monkeypatch):
        self._patch_chunked_internals(monkeypatch)
        with patch("recap.pipeline.transcribe._load_model", return_value=self._mock_model()):
            with patch("recap.pipeline.transcribe._unload_model"):
                result = transcribe(
                    audio_path=tmp_path / "test.flac",
                    model_name="nvidia/parakeet-tdt-0.6b-v2",
                    device="cpu",
                )
        assert isinstance(result, TranscriptResult)
        assert len(result.utterances) == 2
        assert result.utterances[0].text == "Hello world"
        assert result.utterances[0].speaker == "UNKNOWN"
        assert result.utterances[0].start == 0.0
        assert result.utterances[0].end == 1.5

    def test_raw_text_is_combined(self, tmp_path, monkeypatch):
        self._patch_chunked_internals(monkeypatch)
        with patch("recap.pipeline.transcribe._load_model", return_value=self._mock_model()):
            with patch("recap.pipeline.transcribe._unload_model"):
                result = transcribe(audio_path=tmp_path / "test.flac", device="cpu")
        assert "Hello world" in result.raw_text
        assert "how are you" in result.raw_text

    def test_saves_transcript_json(self, tmp_path, monkeypatch):
        self._patch_chunked_internals(monkeypatch)
        save_path = tmp_path / "transcript.json"
        with patch("recap.pipeline.transcribe._load_model", return_value=self._mock_model()):
            with patch("recap.pipeline.transcribe._unload_model"):
                transcribe(
                    audio_path=tmp_path / "test.flac",
                    device="cpu",
                    save_transcript=save_path,
                )
        assert save_path.exists()
        data = json.loads(save_path.read_text())
        assert "utterances" in data
        assert len(data["utterances"]) == 2

    def test_unloads_model_after_transcription(self, tmp_path, monkeypatch):
        self._patch_chunked_internals(monkeypatch)
        with patch("recap.pipeline.transcribe._load_model", return_value=self._mock_model()):
            with patch("recap.pipeline.transcribe._unload_model") as unload_mock:
                transcribe(audio_path=tmp_path / "test.flac", device="cpu")
                unload_mock.assert_called_once()

    def test_language_defaults_to_en(self, tmp_path, monkeypatch):
        self._patch_chunked_internals(monkeypatch)
        with patch("recap.pipeline.transcribe._load_model", return_value=self._mock_model()):
            with patch("recap.pipeline.transcribe._unload_model"):
                result = transcribe(audio_path=tmp_path / "test.flac", device="cpu")
        assert result.language == "en"


class _FakeHypothesis:
    """Minimal stand-in for a NeMo Hypothesis (timestamps=True shape)."""

    def __init__(self, text: str, segments: list[dict]):
        self.text = text
        self.timestamp = {"segment": segments}


def test_transcribe_slices_into_windows_and_stitches(monkeypatch, tmp_path):
    """Long audio: each window is transcribed once; whole-file call is absent."""
    audio = tmp_path / "long.wav"
    audio.write_bytes(b"RIFF")

    transcribe_calls: list[str] = []

    class FakeModel:
        def to(self, _device):
            return self

        def transcribe(self, paths, **_kwargs):
            # One path per call (windowed). Capture for assertion.
            transcribe_calls.extend(paths)
            # Utterance sits in the middle of each window, safely outside
            # overlap zones [110, 120] and [220, 230] so the positional
            # dedup rule leaves all three intact.
            return [_FakeHypothesis(
                text=f"content-{len(transcribe_calls)}",
                segments=[{
                    "start": 50.0,
                    "end": 55.0,
                    "segment": f"content-{len(transcribe_calls)}",
                }],
            )]

    monkeypatch.setattr(
        "recap.pipeline.transcribe._load_model", lambda *a, **k: FakeModel(),
    )
    monkeypatch.setattr(
        "recap.pipeline.transcribe._unload_model", lambda _m: None,
    )
    # Force duration to 300s -> plan_windows produces 3 windows
    # at [0, 120], [110, 230], [220, 300] with 10s overlap.
    monkeypatch.setattr(
        "recap.pipeline.transcribe._probe_duration_s", lambda _p: 300.0,
    )
    monkeypatch.setattr(
        "recap.pipeline.transcribe.slice_window_to_temp", _fake_slice,
    )

    result = transcribe(audio_path=audio, device="cpu")

    # One transcribe() call per window.
    assert len(transcribe_calls) == 3
    # All three utterances survive (none lie in overlap zones).
    assert len(result.utterances) == 3
    # Timestamps are monotonically non-decreasing across windows.
    starts = [u.start for u in result.utterances]
    assert starts == sorted(starts)
    # Each utterance carries its absolute time base (window_start + rel_start).
    assert result.utterances[0].start == 50.0
    assert result.utterances[1].start == 160.0  # 110 + 50.0
    assert result.utterances[2].start == 270.0  # 220 + 50.0


def test_transcribe_cleans_temp_files_on_failure(monkeypatch, tmp_path):
    """ffmpeg temp files must not leak when a window's model call raises."""
    audio = tmp_path / "long.wav"
    audio.write_bytes(b"RIFF")

    created: list[Path] = []

    def recording_slice(source, start_s, duration_s, temp_dir):
        p = _fake_slice(source, start_s, duration_s, temp_dir)
        created.append(p)
        return p

    class OOMModel:
        def to(self, _device):
            return self

        def transcribe(self, _paths, **_kwargs):
            raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr(
        "recap.pipeline.transcribe._load_model", lambda *a, **k: OOMModel(),
    )
    monkeypatch.setattr(
        "recap.pipeline.transcribe._unload_model", lambda _m: None,
    )
    monkeypatch.setattr(
        "recap.pipeline.transcribe._probe_duration_s", lambda _p: 300.0,
    )
    monkeypatch.setattr(
        "recap.pipeline.transcribe.slice_window_to_temp", recording_slice,
    )

    with pytest.raises(RuntimeError, match="out of memory"):
        transcribe(audio_path=audio, device="cpu")

    # The per-window unlink + outer shutil.rmtree must collectively leave
    # no temp file on disk. Also verify the parent temp dir is gone.
    for p in created:
        assert not p.exists(), f"temp file leaked: {p}"
        assert not p.parent.exists(), f"temp dir leaked: {p.parent}"


def test_transcribe_no_temp_dir_leak_when_model_load_fails(monkeypatch, tmp_path):
    """If _load_model raises, no recap-chunks-* directory may be left behind.

    The acquisition-and-release pair for the temp dir must be anchored
    AFTER the model load succeeds; otherwise a model init failure (missing
    NeMo, download/auth error, GPU init) leaves an orphan temp dir on disk.
    """
    audio = tmp_path / "long.wav"
    audio.write_bytes(b"RIFF")

    mkdtemp_calls: list[str] = []
    original_mkdtemp = tempfile.mkdtemp

    def tracking_mkdtemp(*args, **kwargs):
        path = original_mkdtemp(*args, **kwargs)
        mkdtemp_calls.append(path)
        return path

    monkeypatch.setattr("tempfile.mkdtemp", tracking_mkdtemp)

    def failing_load(*_a, **_k):
        raise RuntimeError("CUDA init failed")

    monkeypatch.setattr("recap.pipeline.transcribe._load_model", failing_load)
    monkeypatch.setattr("recap.pipeline.transcribe._unload_model", lambda _m: None)
    monkeypatch.setattr(
        "recap.pipeline.transcribe._probe_duration_s", lambda _p: 300.0,
    )
    monkeypatch.setattr(
        "recap.pipeline.transcribe.slice_window_to_temp", _fake_slice,
    )

    with pytest.raises(RuntimeError, match="CUDA init"):
        transcribe(audio_path=audio, device="cpu")

    # Either mkdtemp was never called (deferred past model load) or it was
    # called and the directory is gone. Either is acceptable; a surviving
    # directory is the leak this test guards against.
    for path in mkdtemp_calls:
        assert not Path(path).exists(), f"temp dir leaked: {path}"

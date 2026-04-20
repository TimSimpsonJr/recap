"""Transcription via NVIDIA Parakeet (NeMo) using chunked inference.

Long audio is sliced with ffmpeg into overlapping windows, each window is
transcribed independently so peak VRAM stays bounded, and per-window
utterances are offset into the source time base and stitched with
deterministic overlap dedup. See
``docs/plans/2026-04-20-parakeet-chunked-inference-design.md`` for the
capacity-vs-complexity rationale.
"""
from __future__ import annotations

import gc
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from recap.models import TranscriptResult, Utterance
from recap.pipeline.chunking import (
    merge_overlapping_windows,
    offset_utterances,
    plan_windows,
    slice_window_to_temp,
)

_WINDOW_SIZE_S = 120.0
_OVERLAP_S = 10.0
_FFPROBE_TIMEOUT_S = 30


def _load_model(model_name: str, device: str):
    """Load Parakeet ASR model from NeMo.

    Import is wrapped in try/except so the module is importable
    even without NeMo installed.
    """
    try:
        import nemo.collections.asr as nemo_asr
    except ImportError as exc:
        raise ImportError(
            "NeMo is required for transcription. "
            "Install with: pip install nemo_toolkit[asr]"
        ) from exc

    model = nemo_asr.models.ASRModel.from_pretrained(model_name)
    model = model.to(device)
    return model


def _unload_model(model) -> None:
    """Release model memory and clean up GPU resources."""
    del model
    try:
        import torch

        torch.cuda.empty_cache()
    except ImportError:
        pass
    gc.collect()


def _probe_duration_s(audio_path: Path) -> float:
    """Return the audio duration in seconds via ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=_FFPROBE_TIMEOUT_S,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return float(result.stdout.strip())


def _hypothesis_to_utterances(hyp) -> list[Utterance]:
    """Extract per-segment utterances from a NeMo Hypothesis.

    NeMo (current) populates ``hyp.timestamp`` as a dict when ``transcribe``
    is called with ``timestamps=True``. The ``"segment"`` entry is a list
    of per-segment dicts keyed by ``segment`` (the text), ``start``,
    ``end``, ``start_offset``, ``end_offset``. Silent audio yields an
    empty list, which is fine.
    """
    timestamp = getattr(hyp, "timestamp", None)
    if isinstance(timestamp, dict):
        segments = timestamp.get("segment", [])
    else:
        segments = []
    return [
        Utterance(
            speaker="UNKNOWN",
            start=seg["start"],
            end=seg["end"],
            text=seg["segment"],
        )
        for seg in segments
    ]


def _save_transcript_json(path: Path, result: TranscriptResult) -> None:
    """Persist a TranscriptResult as JSON matching the transcript contract."""
    data = {
        "utterances": [
            {
                "speaker": u.speaker,
                "start": u.start,
                "end": u.end,
                "text": u.text,
            }
            for u in result.utterances
        ],
        "raw_text": result.raw_text,
        "language": result.language,
    }
    path.write_text(json.dumps(data, indent=2))


def transcribe(
    audio_path: Path,
    model_name: str = "nvidia/parakeet-tdt-0.6b-v2",
    device: str = "cuda",
    save_transcript: Path | None = None,
) -> TranscriptResult:
    """Transcribe an audio file using NVIDIA Parakeet via chunked inference.

    Args:
        audio_path: Path to the audio file.
        model_name: NeMo model identifier.
        device: Device to run inference on ('cuda' or 'cpu').
        save_transcript: If provided, write transcript JSON to this path.

    Returns:
        TranscriptResult with utterances, raw text, and language.
    """
    duration_s = _probe_duration_s(audio_path)
    windows = plan_windows(duration_s, _WINDOW_SIZE_S, _OVERLAP_S)

    # Defer temp-dir creation until after the model loads: if _load_model
    # raises (missing NeMo, download/auth, GPU init), there is no temp dir
    # to leak. Each acquisition has its own try/finally so cleanup order
    # matches acquisition order in reverse.
    model = _load_model(model_name, device)
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix="recap-chunks-"))
        try:
            stitched: list[Utterance] = []
            for i, (start_s, end_s) in enumerate(windows):
                chunk_path = slice_window_to_temp(
                    source=audio_path,
                    start_s=start_s,
                    duration_s=end_s - start_s,
                    temp_dir=temp_dir,
                )
                try:
                    # timestamps=True tells NeMo to populate hyp.timestamp
                    # with per-segment {segment, start, end, start_offset,
                    # end_offset} dicts. Without it the attribute is an
                    # empty list.
                    results = model.transcribe(
                        [str(chunk_path)], timestamps=True,
                    )
                    hyp = results[0]
                    window_utts = _hypothesis_to_utterances(hyp)
                    offset = offset_utterances(window_utts, start_s)
                    if i == 0:
                        stitched = list(offset)
                    else:
                        prior_window_end = windows[i - 1][1]
                        overlap_start = start_s
                        overlap_end = min(prior_window_end, end_s)
                        stitched = merge_overlapping_windows(
                            stitched, offset, overlap_start, overlap_end,
                        )
                finally:
                    chunk_path.unlink(missing_ok=True)

            raw_text = " ".join(u.text for u in stitched)
            result = TranscriptResult(
                utterances=stitched, raw_text=raw_text, language="en",
            )
            if save_transcript is not None:
                _save_transcript_json(save_transcript, result)
            return result
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    finally:
        _unload_model(model)

"""Transcription via NVIDIA Parakeet (NeMo)."""
from __future__ import annotations

import gc
import json
from pathlib import Path

from recap.models import TranscriptResult, Utterance


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


def transcribe(
    audio_path: Path,
    model_name: str = "nvidia/parakeet-tdt-0.6b-v2",
    device: str = "cuda",
    save_transcript: Path | None = None,
) -> TranscriptResult:
    """Transcribe an audio file using NVIDIA Parakeet.

    Args:
        audio_path: Path to the audio file.
        model_name: NeMo model identifier.
        device: Device to run inference on ('cuda' or 'cpu').
        save_transcript: If provided, write transcript JSON to this path.

    Returns:
        TranscriptResult with utterances, raw text, and language.
    """
    model = _load_model(model_name, device)
    try:
        results = model.transcribe([str(audio_path)])
        hyp = results[0]

        # Parse segments from NeMo hypothesis timestep data
        segments = hyp.timestep.get("segment", [])
        utterances = [
            Utterance(
                speaker="UNKNOWN",
                start=seg["start"],
                end=seg["end"],
                text=seg["text"],
            )
            for seg in segments
        ]

        raw_text = hyp.text

        result = TranscriptResult(
            utterances=utterances,
            raw_text=raw_text,
            language="en",
        )

        if save_transcript is not None:
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
            save_transcript.write_text(json.dumps(data, indent=2))

        return result
    finally:
        _unload_model(model)

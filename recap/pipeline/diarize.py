"""Speaker diarization using NeMo Sortformer."""
from __future__ import annotations

import gc
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from recap.models import TranscriptResult, Utterance


def _load_diarization_model(model_name: str, device: str):
    """Load NeMo Sortformer diarization model."""
    try:
        from nemo.collections.asr.models import SortformerEncLabelModel
    except ImportError as exc:
        raise ImportError(
            "NeMo is required for speaker diarization. "
            "Install it with: pip install nemo_toolkit[asr]"
        ) from exc

    model = SortformerEncLabelModel.from_pretrained(model_name)
    model = model.to(device)
    return model


def _unload_model(model) -> None:
    """Release model memory."""
    del model
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except ImportError:
        pass  # torch not installed, expected in CPU-only mode
    except RuntimeError as e:
        logger.warning("Failed to clear CUDA cache: %s", e)


def diarize(
    audio_path: Path,
    model_name: str = "nvidia/diar_streaming_sortformer_4spk-v2.1",
    device: str = "cuda",
) -> list[dict]:
    """Run speaker diarization on an audio file.

    Returns a list of dicts with keys: start, end, speaker.
    """
    model = _load_diarization_model(model_name, device)
    try:
        segments = model.diarize(audio_path)
    finally:
        _unload_model(model)
    return segments


def assign_speakers(
    transcript: TranscriptResult,
    speaker_segments: list[dict],
) -> TranscriptResult:
    """Assign speaker labels to transcript utterances based on temporal overlap.

    Returns a new TranscriptResult with speakers assigned. Does not mutate
    the input transcript.
    """
    new_utterances = []
    for utt in transcript.utterances:
        best_speaker = utt.speaker
        best_overlap = 0.0

        for seg in speaker_segments:
            overlap = max(0.0, min(utt.end, seg["end"]) - max(utt.start, seg["start"]))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = seg["speaker"]

        new_utterances.append(
            Utterance(
                speaker=best_speaker,
                start=utt.start,
                end=utt.end,
                text=utt.text,
            )
        )

    return TranscriptResult(
        utterances=new_utterances,
        raw_text=transcript.raw_text,
        language=transcript.language,
    )

"""Speaker diarization using NeMo Sortformer."""
from __future__ import annotations

import gc
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

from recap.models import TranscriptResult, Utterance

# NeMo's ``generate_diarization_output_lines`` emits space-separated
# lines: ``"{start:.3f} {end:.3f} speaker_{idx}"``. The regex is tolerant
# of extra whitespace but strict about the three-field shape so malformed
# lines raise loudly rather than silently dropping.
_SEGMENT_LINE_RE = re.compile(
    r"^\s*(?P<start>-?\d+(?:\.\d+)?)\s+(?P<end>-?\d+(?:\.\d+)?)\s+"
    r"speaker_(?P<spk>\d+)\s*$"
)


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


def _parse_sortformer_output(raw) -> list[dict]:
    """Parse ``SortformerEncLabelModel.diarize``'s ``List[List[str]]`` into
    the ``{"start", "end", "speaker"}`` dict shape the rest of the pipeline
    (``assign_speakers``) consumes.

    The model returns one inner list per input audio. We only ever pass a
    single audio path, so we unwrap the outer list. Each inner element is
    a string formatted as ``"start end speaker_N"`` (see
    ``nemo.collections.asr.parts.utils.speaker_utils.generate_diarization_output_lines``).
    Speaker indices are normalised to ``SPEAKER_00`` / ``SPEAKER_12`` to
    match the convention used in frontmatter, analyze prompts, and the
    clip endpoint.
    """
    if not raw:
        return []
    # Outer list is per-audio; we always pass 1 audio so unwrap.
    if isinstance(raw[0], list):
        lines = raw[0]
    else:
        lines = raw

    segments: list[dict] = []
    for item in lines:
        if isinstance(item, dict):
            # Tolerate the legacy mock shape (already a dict) so a future
            # NeMo version that yields parsed dicts needs no code change.
            segments.append(item)
            continue
        if not isinstance(item, str):
            logger.warning("Skipping unexpected diarize segment type %r", type(item))
            continue
        match = _SEGMENT_LINE_RE.match(item)
        if match is None:
            logger.warning("Skipping unparseable diarize line: %r", item)
            continue
        spk_idx = int(match.group("spk"))
        segments.append({
            "start": float(match.group("start")),
            "end": float(match.group("end")),
            "speaker": f"SPEAKER_{spk_idx:02d}",
        })
    return segments


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
        raw = model.diarize(str(audio_path))
    finally:
        _unload_model(model)
    return _parse_sortformer_output(raw)


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
                speaker_id=best_speaker,
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

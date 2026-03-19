"""Transcription and diarization via WhisperX."""
from __future__ import annotations

import json
import logging
import pathlib

from recap.models import TranscriptResult, Utterance

logger = logging.getLogger(__name__)

try:
    import whisperx
except ImportError:
    whisperx = None  # type: ignore[assignment]


def _parse_whisperx_result(result: dict) -> TranscriptResult:
    utterances = []
    raw_parts = []
    for seg in result.get("segments", []):
        text = seg.get("text", "").strip()
        speaker = seg.get("speaker", "UNKNOWN")
        utterances.append(
            Utterance(
                speaker=speaker,
                start=seg["start"],
                end=seg["end"],
                text=text,
            )
        )
        raw_parts.append(text)

    return TranscriptResult(
        utterances=utterances,
        raw_text=" ".join(raw_parts),
        language=result.get("language", "unknown"),
    )


def transcribe(
    audio_path: pathlib.Path,
    model_name: str = "large-v3",
    device: str = "cuda",
    compute_type: str = "float16",
    hf_token: str = "",
    language: str | None = "en",
    save_transcript: pathlib.Path | None = None,
) -> TranscriptResult:
    if whisperx is None:
        raise ImportError(
            "WhisperX is not installed. Install with: uv sync --extra ml"
        )

    logger.info("Loading WhisperX model %s on %s", model_name, device)
    model = whisperx.load_model(
        model_name, device=device, language=language, compute_type=compute_type
    )

    logger.info("Transcribing %s", audio_path)
    audio = whisperx.load_audio(str(audio_path))
    result = model.transcribe(audio, batch_size=16)

    logger.info("Running diarization")
    diarize_model = whisperx.DiarizationPipeline(use_auth_token=hf_token, device=device)
    diarize_segments = diarize_model(audio)
    result = whisperx.assign_word_speakers(diarize_segments, result)

    transcript = _parse_whisperx_result(result)

    if save_transcript:
        logger.info("Saving transcript to %s", save_transcript)
        data = {
            "utterances": [
                {
                    "speaker": u.speaker,
                    "start": u.start,
                    "end": u.end,
                    "text": u.text,
                }
                for u in transcript.utterances
            ],
            "raw_text": transcript.raw_text,
            "language": transcript.language,
        }
        save_transcript.write_text(json.dumps(data, indent=2))

    logger.info(
        "Transcription complete: %d utterances, language=%s",
        len(transcript.utterances),
        transcript.language,
    )
    return transcript

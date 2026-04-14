"""Pipeline orchestrator -- runs transcription, diarization, analysis, export, and conversion."""
from __future__ import annotations

import json
import logging
import pathlib
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime

from recap.artifacts import (
    RecordingMetadata,
    load_analysis,
    load_transcript,
    save_analysis,
    save_transcript,
    speakers_path,
    transcript_path,
    write_recording_metadata,
)
from recap.errors import map_error
from recap.models import AnalysisResult, MeetingMetadata, TranscriptResult

logger = logging.getLogger(__name__)

PIPELINE_STAGES = ["transcribe", "diarize", "analyze", "export", "convert"]

# __file__ is recap/pipeline/__init__.py -> .parent.parent = recap/ -> .parent = project root
DEFAULT_PROMPT_TEMPLATE = pathlib.Path(__file__).parent.parent.parent / "prompts" / "meeting_analysis.md"
_FFPROBE_TIMEOUT_SECONDS = 30


@dataclass
class PipelineRuntimeConfig:
    """Configuration for a pipeline run."""

    transcription_model: str = "nvidia/parakeet-tdt-0.6b-v2"
    diarization_model: str = "nvidia/diar_streaming_sortformer_4spk-v2.1"
    device: str = "cuda"
    llm_backend: str = "claude"
    ollama_model: str = ""
    archive_format: str = "aac"
    archive_bitrate: str = "64k"
    delete_source_after_archive: bool = False
    auto_retry: bool = False
    max_retries: int = 0
    prompt_template_path: pathlib.Path | None = None
    status_dir: pathlib.Path | None = None


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------

def _status_path(config: PipelineRuntimeConfig, recording_stem: str) -> pathlib.Path | None:
    if config.status_dir is None:
        return None
    config.status_dir.mkdir(parents=True, exist_ok=True)
    return config.status_dir / f"{recording_stem}.json"


def _write_status(config: PipelineRuntimeConfig, recording_stem: str, data: dict) -> None:
    path = _status_path(config, recording_stem)
    if path is not None:
        path.write_text(json.dumps(data, indent=2))


def _stage_started(config: PipelineRuntimeConfig, recording_stem: str, stage: str) -> None:
    _write_status(config, recording_stem, {
        "pipeline-status": _stage_label(stage),
        "stage": stage,
        "started": datetime.now().isoformat(),
    })


def _stage_completed(config: PipelineRuntimeConfig, recording_stem: str, stage: str) -> None:
    _write_status(config, recording_stem, {
        "pipeline-status": _stage_label(stage),
        "stage": stage,
        "completed": datetime.now().isoformat(),
    })


def _stage_failed(config: PipelineRuntimeConfig, recording_stem: str, stage: str, error: str) -> None:
    _write_status(config, recording_stem, {
        "pipeline-status": f"failed:{stage}",
        "stage": stage,
        "error": error,
    })


_STAGE_LABELS = {
    "transcribe": "transcribing",
    "diarize": "diarizing",
    "analyze": "analyzing",
    "export": "exporting",
    "convert": "converting",
}


def _stage_label(stage: str) -> str:
    return _STAGE_LABELS.get(stage, stage)


def _update_note_frontmatter(note_path: pathlib.Path, status: str, error: str | None = None) -> None:
    """Update pipeline-status (and optionally pipeline-error) in an existing note's YAML frontmatter."""
    if not note_path.exists():
        return
    content = note_path.read_text(encoding="utf-8")
    # Normalize line endings for consistent splitting
    content = content.replace("\r\n", "\n")
    if not content.startswith("---\n"):
        return
    parts = content.split("---\n", 2)
    if len(parts) < 3:
        return
    try:
        import yaml
        fm = yaml.safe_load(parts[1])
        if not isinstance(fm, dict):
            return
        fm["pipeline-status"] = status
        if error:
            fm["pipeline-error"] = error
        elif "pipeline-error" in fm:
            del fm["pipeline-error"]
        new_fm = yaml.dump(fm, default_flow_style=False, sort_keys=False).strip()
        new_content = "---\n" + new_fm + "\n---\n" + parts[2]
        note_path.write_text(new_content, encoding="utf-8")
    except Exception:
        logger.warning("Could not update frontmatter in %s", note_path, exc_info=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_audio_duration(path: pathlib.Path) -> float:
    """Get audio duration in seconds via ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=_FFPROBE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "ffprobe failed")
        return float(result.stdout.strip())
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired):
        logger.warning("Could not determine audio duration for %s, defaulting to 0", path)
        return 0.0


def _should_skip(stage: str, from_stage: str | None) -> bool:
    """Return True if *stage* should be skipped because it precedes *from_stage*."""
    if from_stage is None:
        return False
    return PIPELINE_STAGES.index(stage) < PIPELINE_STAGES.index(from_stage)


def validate_from_stage(audio_path: pathlib.Path, from_stage: str | None) -> str | None:
    """Return an error message when the requested restart stage lacks prerequisites."""
    if from_stage is None:
        return None
    if from_stage not in PIPELINE_STAGES:
        return f"unknown from_stage: {from_stage}"
    if from_stage in {"diarize", "analyze"} and load_transcript(audio_path) is None:
        return (
            f"Cannot reprocess {audio_path.name} from '{from_stage}': "
            "missing transcript artifact."
        )
    if from_stage == "export" and load_analysis(audio_path) is None:
        return (
            f"Cannot reprocess {audio_path.name} from 'export': "
            "missing analysis artifact."
        )
    return None


def _has_real_speakers(transcript: TranscriptResult) -> bool:
    """Return True if at least one utterance has a non-UNKNOWN speaker."""
    return any(u.speaker != "UNKNOWN" for u in transcript.utterances)


def _apply_speaker_mapping(
    transcript: TranscriptResult, mapping: dict[str, str],
) -> TranscriptResult:
    """Return a copy of *transcript* with speaker labels replaced per *mapping*."""
    from recap.models import Utterance

    new_utterances = [
        Utterance(
            speaker=mapping.get(u.speaker, u.speaker),
            start=u.start,
            end=u.end,
            text=u.text,
        )
        for u in transcript.utterances
    ]
    return TranscriptResult(
        utterances=new_utterances,
        raw_text=transcript.raw_text,
        language=transcript.language,
    )


def _resolve_note_path(
    metadata: MeetingMetadata,
    recording_metadata: RecordingMetadata | None,
    meetings_dir: pathlib.Path,
) -> pathlib.Path:
    from recap.artifacts import safe_note_title

    if recording_metadata is not None:
        if recording_metadata.note_path:
            return pathlib.Path(recording_metadata.note_path)
        if recording_metadata.event_id:
            from recap.daemon.calendar.sync import find_note_by_event_id

            note = find_note_by_event_id(recording_metadata.event_id, meetings_dir)
            if note is not None:
                recording_metadata.note_path = str(note)
                return note

    return meetings_dir / f"{metadata.date.isoformat()} - {safe_note_title(metadata.title)}.md"


def _run_with_retry(
    fn,
    stage: str,
    config: PipelineRuntimeConfig,
    recording_stem: str,
    note_path: pathlib.Path | None,
    *,
    is_claude: bool = False,
):
    """Execute *fn* with optional retry logic.

    Returns the result of fn() on success.  On failure writes status and
    re-raises the exception.
    """
    try:
        return fn()
    except Exception as first_error:
        should_retry = False
        if is_claude:
            # Always retry Claude once (network/timeout), never more
            should_retry = True
        elif config.auto_retry and config.max_retries > 0:
            should_retry = True

        if should_retry:
            logger.warning("Stage '%s' failed, retrying in 30s: %s", stage, first_error)
            time.sleep(30)
            try:
                return fn()
            except Exception as retry_error:
                actionable = map_error(stage, retry_error)
                _stage_failed(config, recording_stem, stage, actionable)
                if note_path:
                    _update_note_frontmatter(note_path, f"failed:{stage}", actionable)
                raise retry_error from first_error

        # No retry -- fail immediately
        actionable = map_error(stage, first_error)
        _stage_failed(config, recording_stem, stage, actionable)
        if note_path:
            _update_note_frontmatter(note_path, f"failed:{stage}", actionable)
        raise


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_pipeline(
    audio_path: pathlib.Path,
    metadata: MeetingMetadata,
    config: PipelineRuntimeConfig,
    org_slug: str,
    org_subfolder: str,
    vault_path: pathlib.Path,
    user_name: str,
    streaming_transcript: TranscriptResult | None = None,
    from_stage: str | None = None,
    recording_metadata: RecordingMetadata | None = None,
) -> pathlib.Path:
    """Run the full processing pipeline and return the path to the meeting note.

    Stages (in order): transcribe, diarize, analyze, export, convert.
    """
    # Lazy imports so the module is importable without heavy deps installed
    from recap.pipeline.transcribe import transcribe
    from recap.pipeline.diarize import diarize, assign_speakers
    from recap.analyze import analyze
    from recap.vault import (
        find_previous_meeting,
        write_meeting_note,
        write_profile_stubs,
    )
    from recap.pipeline.audio_convert import convert_flac_to_aac, delete_source_if_configured

    prompt_path = config.prompt_template_path or DEFAULT_PROMPT_TEMPLATE
    duration = _get_audio_duration(audio_path)
    recording_stem = audio_path.stem

    # Vault directories
    org_dir = vault_path / org_subfolder
    meetings_dir = org_dir / "Meetings"
    people_dir = org_dir / "People"
    companies_dir = org_dir / "Companies"
    for d in (meetings_dir, people_dir, companies_dir):
        d.mkdir(parents=True, exist_ok=True)

    prerequisite_error = validate_from_stage(audio_path, from_stage)
    if prerequisite_error is not None:
        raise FileNotFoundError(prerequisite_error)

    note_path = _resolve_note_path(metadata, recording_metadata, meetings_dir)
    note_filename = note_path.name
    if recording_metadata is not None and str(note_path) != recording_metadata.note_path:
        recording_metadata.note_path = str(note_path)
        write_recording_metadata(audio_path, recording_metadata)

    transcript: TranscriptResult | None = None
    recording_reference_path = (
        audio_path.with_suffix(".m4a")
        if config.archive_format == "aac"
        else audio_path
    )

    # ------------------------------------------------------------------
    # Decide whether to use streaming transcript
    # ------------------------------------------------------------------
    use_streaming = (
        streaming_transcript is not None
        and streaming_transcript.utterances
        and _has_real_speakers(streaming_transcript)
    )

    if use_streaming:
        logger.info(
            "Using streaming transcript (%d utterances)",
            len(streaming_transcript.utterances),
        )
        transcript = streaming_transcript
        save_transcript(audio_path, transcript)
    else:
        # ------------------------------------------------------------------
        # 1. Transcribe
        # ------------------------------------------------------------------
        if not _should_skip("transcribe", from_stage):
            _stage_started(config, recording_stem, "transcribe")
            transcript_save = transcript_path(audio_path)

            def do_transcribe():
                return transcribe(
                    audio_path=audio_path,
                    model_name=config.transcription_model,
                    device=config.device,
                    save_transcript=transcript_save,
                )

            transcript = _run_with_retry(
                do_transcribe, "transcribe", config, recording_stem, note_path,
            )
            save_transcript(audio_path, transcript)
            _stage_completed(config, recording_stem, "transcribe")
        else:
            # Load from saved transcript if skipping
            transcript = load_transcript(audio_path)

        # ------------------------------------------------------------------
        # 2. Diarize
        # ------------------------------------------------------------------
        if not _should_skip("diarize", from_stage) and transcript is not None:
            _stage_started(config, recording_stem, "diarize")

            def do_diarize():
                segments = diarize(
                    audio_path=audio_path,
                    model_name=config.diarization_model,
                    device=config.device,
                )
                return assign_speakers(transcript, segments)

            transcript = _run_with_retry(
                do_diarize, "diarize", config, recording_stem, note_path,
            )
            save_transcript(audio_path, transcript)
            _stage_completed(config, recording_stem, "diarize")

    # ------------------------------------------------------------------
    # Apply speaker corrections (if a .speakers.json exists)
    # ------------------------------------------------------------------
    speakers_file = speakers_path(audio_path)
    if transcript is not None and speakers_file.exists():
        try:
            speaker_mapping = json.loads(speakers_file.read_text(encoding="utf-8"))
            if isinstance(speaker_mapping, dict) and speaker_mapping:
                transcript = _apply_speaker_mapping(transcript, speaker_mapping)
                save_transcript(audio_path, transcript)
                logger.info(
                    "Applied speaker mapping from %s (%d entries)",
                    speakers_file, len(speaker_mapping),
                )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load speaker mapping: %s", exc)

    # ------------------------------------------------------------------
    # 3. Analyze
    # ------------------------------------------------------------------
    analysis: AnalysisResult | None = None
    if not _should_skip("analyze", from_stage) and transcript is not None:
        _stage_started(config, recording_stem, "analyze")

        def do_analyze():
            return analyze(
                transcript=transcript,
                metadata=metadata,
                prompt_path=prompt_path,
                backend=config.llm_backend,
                ollama_model=config.ollama_model,
            )

        analysis = _run_with_retry(
            do_analyze, "analyze", config, recording_stem, note_path, is_claude=(config.llm_backend == "claude"),
        )
        save_analysis(audio_path, analysis)
        _stage_completed(config, recording_stem, "analyze")
    elif _should_skip("analyze", from_stage):
        analysis = load_analysis(audio_path)

    # ------------------------------------------------------------------
    # 4. Export
    # ------------------------------------------------------------------
    if not _should_skip("export", from_stage) and analysis is not None:
        _stage_started(config, recording_stem, "export")

        def do_export():
            previous = find_previous_meeting(
                participant_names=[p.name for p in metadata.participants],
                meetings_dir=meetings_dir,
                exclude_filename=note_filename,
            )
            written = write_meeting_note(
                metadata=metadata,
                analysis=analysis,
                duration_seconds=duration,
                recording_path=recording_reference_path,
                meetings_dir=meetings_dir,
                org=org_slug,
                org_subfolder=org_subfolder,
                previous_meeting=previous,
                user_name=user_name,
                note_path=note_path,
                recording_metadata=recording_metadata,
            )
            write_profile_stubs(
                analysis=analysis,
                people_dir=people_dir,
                companies_dir=companies_dir,
            )
            return written

        result_note = _run_with_retry(
            do_export, "export", config, recording_stem, note_path,
        )
        if result_note is not None:
            note_path = result_note
            note_filename = note_path.name
            if recording_metadata is not None and str(note_path) != recording_metadata.note_path:
                recording_metadata.note_path = str(note_path)
                write_recording_metadata(audio_path, recording_metadata)
        _stage_completed(config, recording_stem, "export")

    # ------------------------------------------------------------------
    # 5. Convert
    # ------------------------------------------------------------------
    if not _should_skip("convert", from_stage) and config.archive_format == "aac":
        _stage_started(config, recording_stem, "convert")

        def do_convert():
            aac_path = convert_flac_to_aac(audio_path, bitrate=config.archive_bitrate)
            delete_source_if_configured(audio_path, config.delete_source_after_archive)
            return aac_path

        _run_with_retry(do_convert, "convert", config, recording_stem, note_path)
        _stage_completed(config, recording_stem, "convert")

    # Final status
    _write_status(config, recording_stem, {
        "pipeline-status": "complete",
        "completed": datetime.now().isoformat(),
    })
    if note_path.exists():
        _update_note_frontmatter(note_path, "complete")

    logger.info("Pipeline complete: %s", note_path)
    return note_path

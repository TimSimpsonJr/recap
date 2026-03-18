"""Pipeline orchestrator — ties all modules together."""
from __future__ import annotations

import json
import logging
import pathlib
import shutil
import subprocess

from recap.analyze import analyze
from recap.config import RecapConfig
from recap.frames import extract_frames
from recap.models import MeetingMetadata, TranscriptResult
from recap.todoist import create_tasks, save_retry_file
from recap.transcribe import transcribe
from recap.vault import find_previous_meeting, write_meeting_note, write_profile_stubs, slugify

logger = logging.getLogger(__name__)

# Stage definitions:
# - merge: handled by Rust side (ffmpeg merge of video + dual audio) before pipeline runs
# - frames: extract video frames for visual context
# - transcribe: WhisperX transcription (includes diarization via WhisperX's built-in speaker assignment)
# - diarize: reserved for future standalone diarization; currently bundled into transcribe
# - analyze: Claude analysis of transcript + metadata
# - export: write meeting note, profile stubs, Todoist tasks
PIPELINE_STAGES = ["merge", "frames", "transcribe", "diarize", "analyze", "export"]


def _load_status(working_dir: pathlib.Path) -> dict:
    """Load status.json from working dir, or return default."""
    status_path = working_dir / "status.json"
    if status_path.exists():
        return json.loads(status_path.read_text())
    return {
        stage: {"completed": False, "timestamp": None, "error": None, "waiting": None}
        for stage in PIPELINE_STAGES
    }


def _save_status(
    working_dir: pathlib.Path,
    status: dict,
    recordings_dir_stem: pathlib.Path | None = None,
) -> None:
    """Write status.json to working dir and optionally to recordings folder."""
    payload = json.dumps(status, indent=2)
    (working_dir / "status.json").write_text(payload)
    if recordings_dir_stem is not None:
        recordings_dir_stem.with_suffix(".status.json").write_text(payload)


def _mark_stage(status: dict, stage: str, completed: bool, error: str | None = None) -> None:
    """Update a stage's status."""
    from datetime import datetime
    status[stage] = {
        "completed": completed,
        "timestamp": datetime.now().isoformat() if completed else None,
        "error": error,
        "waiting": None,
    }


def _mark_waiting(status: dict, stage: str, reason: str) -> None:
    """Set a waiting state on a stage (e.g. awaiting speaker review)."""
    status[stage]["waiting"] = reason


def _should_run(stage: str, status: dict, from_stage: str | None, only_stage: str | None) -> bool:
    """Determine whether a pipeline stage should run."""
    if only_stage:
        return stage == only_stage
    if from_stage:
        return PIPELINE_STAGES.index(stage) >= PIPELINE_STAGES.index(from_stage)
    return not status[stage]["completed"]


def _get_audio_duration(path: pathlib.Path) -> float:
    """Get audio/video duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip())
    except (ValueError, OSError):
        logger.warning("Could not determine audio duration, defaulting to 0")
        return 0.0


def _apply_speaker_labels(transcript: TranscriptResult, labels_path: pathlib.Path) -> TranscriptResult:
    """Apply speaker label corrections from a JSON mapping file."""
    if not labels_path.exists():
        return transcript
    labels = json.loads(labels_path.read_text())
    for utterance in transcript.utterances:
        if utterance.speaker in labels:
            utterance.speaker = labels[utterance.speaker]
    return transcript


def run_pipeline(
    audio_path: pathlib.Path,
    metadata_path: pathlib.Path,
    config: RecapConfig,
    from_stage: str | None = None,
    only_stage: str | None = None,
) -> dict:
    """Run the full processing pipeline.

    Returns a dict with:
        meeting_note: Path to the generated meeting note (or None)
        recording: Path to the moved recording
        transcript: Path to saved transcript JSON
        todoist_tasks: list of created task IDs
        profiles_created: list of created profile names
        frames: list of extracted frame paths
    """
    results: dict = {}
    working_dir = audio_path.parent
    status = _load_status(working_dir)

    # Load metadata
    logger.info("Loading metadata from %s", metadata_path)
    raw_meta = json.loads(metadata_path.read_text())
    metadata = MeetingMetadata.from_dict(raw_meta)

    # Get duration before moving
    duration = _get_audio_duration(audio_path)

    # Move recording to recordings directory
    slug = slugify(metadata.title)
    ext = audio_path.suffix
    recording_name = f"{metadata.date.isoformat()}-{slug}{ext}"
    recording_dest = config.recordings_path / recording_name
    config.recordings_path.mkdir(parents=True, exist_ok=True)
    shutil.move(str(audio_path), str(recording_dest))
    results["recording"] = recording_dest
    logger.info("Moved recording to %s", recording_dest)

    # Copy meeting metadata alongside recording for dashboard scanning
    meeting_json_dest = recording_dest.with_suffix(".meeting.json")
    shutil.copy2(str(metadata_path), str(meeting_json_dest))
    logger.info("Copied meeting metadata to %s", meeting_json_dest)

    # Transcribe
    transcript_path = recording_dest.with_suffix(".transcript.json")
    transcript = None
    if _should_run("transcribe", status, from_stage, only_stage):
        try:
            logger.info("Starting transcription")
            transcript = transcribe(
                audio_path=recording_dest,
                model_name=config.whisperx.model,
                device=config.whisperx.device,
                hf_token=config.huggingface_token,
                language=config.whisperx.language,
                save_transcript=transcript_path,
            )
            _mark_stage(status, "transcribe", True)
            _save_status(working_dir, status, recording_dest)
        except Exception as e:
            _mark_stage(status, "transcribe", False, str(e))
            _save_status(working_dir, status, recording_dest)
            raise
    elif transcript_path.exists():
        transcript = json.loads(transcript_path.read_text())
    results["transcript"] = transcript_path

    # Extract frames (video only, warn on failure)
    frames = []
    if _should_run("frames", status, from_stage, only_stage):
        try:
            config.frames_path.mkdir(parents=True, exist_ok=True)
            frames = extract_frames(recording_dest, config.frames_path)
            _mark_stage(status, "frames", True)
            _save_status(working_dir, status, recording_dest)
        except Exception as e:
            logger.warning("Frame extraction failed, continuing: %s", e)
            _mark_stage(status, "frames", False, str(e))
            _save_status(working_dir, status, recording_dest)
    results["frames"] = [f.path for f in frames]

    # Pause for speaker review if no participants are available
    if not metadata.participants:
        _mark_waiting(status, "analyze", "speaker_review")
        _save_status(working_dir, status, recording_dest)
        logger.info("No participants available — pausing for speaker review")
        return {"paused": True, "waiting_at": "analyze"}

    # Apply speaker label corrections if available
    labels_path = working_dir / "speaker_labels.json"
    if transcript is not None and isinstance(transcript, TranscriptResult):
        transcript = _apply_speaker_labels(transcript, labels_path)

    # Analyze with Claude
    analysis = None
    if _should_run("analyze", status, from_stage, only_stage):
        try:
            prompt_path = pathlib.Path(__file__).parent.parent / "prompts" / "meeting_analysis.md"
            logger.info("Starting Claude analysis")
            analysis = analyze(
                transcript=transcript,
                metadata=metadata,
                prompt_path=prompt_path,
                claude_command=config.claude.command,
            )
            _mark_stage(status, "analyze", True)
            _save_status(working_dir, status, recording_dest)
        except Exception as e:
            _mark_stage(status, "analyze", False, str(e))
            _save_status(working_dir, status, recording_dest)
            raise

    # Export: meeting note, profiles, Todoist tasks
    note_path = None
    if _should_run("export", status, from_stage, only_stage) and analysis is not None:
        try:
            # Find previous meeting
            note_filename = f"{metadata.date.isoformat()} - {metadata.title}.md"
            previous = find_previous_meeting(
                participant_names=[p.name for p in metadata.participants],
                meetings_dir=config.meetings_path,
                exclude_filename=note_filename,
            )

            # Write meeting note
            config.meetings_path.mkdir(parents=True, exist_ok=True)
            note_path = write_meeting_note(
                metadata=metadata,
                analysis=analysis,
                duration_seconds=duration,
                recording_path=recording_dest,
                meetings_dir=config.meetings_path,
                frames=frames,
                previous_meeting=previous,
                user_name=config.user_name,
            )
            results["meeting_note"] = note_path

            # Write profile stubs (warn on failure)
            try:
                config.people_path.mkdir(parents=True, exist_ok=True)
                config.companies_path.mkdir(parents=True, exist_ok=True)
                created = write_profile_stubs(
                    analysis=analysis,
                    people_dir=config.people_path,
                    companies_dir=config.companies_path,
                )
                results["profiles_created"] = created
            except Exception as e:
                logger.warning("Profile stub creation failed, continuing: %s", e)
                results["profiles_created"] = []

            _mark_stage(status, "export", True)
            _save_status(working_dir, status, recording_dest)
        except Exception as e:
            _mark_stage(status, "export", False, str(e))
            _save_status(working_dir, status, recording_dest)
            raise

    # Create Todoist tasks (warn on failure, save retry)
    if analysis is not None and analysis.action_items:
        note_filename = f"{metadata.date.isoformat()} - {metadata.title}.md"
        try:
            project_name = config.todoist.project_for_type(analysis.meeting_type)
            vault_name = config.vault_path.name
            note_rel = f"Work/Meetings/{note_filename}" if note_path else ""
            task_ids = create_tasks(
                action_items=analysis.action_items,
                user_name=config.user_name,
                api_token=config.todoist.api_token,
                project_name=project_name,
                vault_name=vault_name,
                note_path=note_rel,
            )
            results["todoist_tasks"] = task_ids
        except Exception as e:
            logger.warning("Todoist task creation failed, saving to retry: %s", e)
            retry_items = [
                {
                    "description": item.description,
                    "due_date": item.due_date,
                    "priority": item.priority,
                    "project": config.todoist.project_for_type(analysis.meeting_type),
                    "note_path": note_rel if note_path else "",
                }
                for item in analysis.action_items
                if item.assignee.lower() == config.user_name.lower()
            ]
            save_retry_file(retry_items, config.retry_path)
            results["todoist_tasks"] = []
    else:
        results["todoist_tasks"] = []

    logger.info("Pipeline complete")
    return results

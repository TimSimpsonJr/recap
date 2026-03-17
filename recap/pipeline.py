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
from recap.models import MeetingMetadata
from recap.todoist import create_tasks, save_retry_file
from recap.transcribe import transcribe
from recap.vault import find_previous_meeting, write_meeting_note, write_profile_stubs, _slugify

logger = logging.getLogger(__name__)


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


def run_pipeline(
    audio_path: pathlib.Path,
    metadata_path: pathlib.Path,
    config: RecapConfig,
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

    # Load metadata
    logger.info("Loading metadata from %s", metadata_path)
    raw_meta = json.loads(metadata_path.read_text())
    metadata = MeetingMetadata.from_dict(raw_meta)

    # Get duration before moving
    duration = _get_audio_duration(audio_path)

    # Move recording to recordings directory
    slug = _slugify(metadata.title)
    ext = audio_path.suffix
    recording_name = f"{metadata.date.isoformat()}-{slug}{ext}"
    recording_dest = config.recordings_path / recording_name
    config.recordings_path.mkdir(parents=True, exist_ok=True)
    shutil.move(str(audio_path), str(recording_dest))
    results["recording"] = recording_dest
    logger.info("Moved recording to %s", recording_dest)

    # Transcribe
    transcript_path = recording_dest.with_suffix(".transcript.json")
    logger.info("Starting transcription")
    transcript = transcribe(
        audio_path=recording_dest,
        model_name=config.whisperx.model,
        device=config.whisperx.device,
        hf_token=config.huggingface_token,
        language=config.whisperx.language,
        save_transcript=transcript_path,
    )
    results["transcript"] = transcript_path

    # Extract frames (video only, warn on failure)
    frames = []
    try:
        config.frames_path.mkdir(parents=True, exist_ok=True)
        frames = extract_frames(recording_dest, config.frames_path)
    except Exception as e:
        logger.warning("Frame extraction failed, continuing: %s", e)
    results["frames"] = [f.path for f in frames]

    # Analyze with Claude
    prompt_path = pathlib.Path(__file__).parent.parent / "prompts" / "meeting_analysis.md"
    logger.info("Starting Claude analysis")
    analysis = analyze(
        transcript=transcript,
        metadata=metadata,
        prompt_path=prompt_path,
        claude_command=config.claude.command,
    )

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

    # Create Todoist tasks (warn on failure, save retry)
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

    logger.info("Pipeline complete")
    return results

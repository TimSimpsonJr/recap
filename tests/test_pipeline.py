"""Tests for pipeline orchestrator."""
import json
import pathlib
from datetime import date
from unittest.mock import MagicMock, patch, call

import pytest

from recap.config import RecapConfig, WhisperXConfig, TodoistConfig, ClaudeConfig
from recap.models import (
    AnalysisResult,
    ActionItem,
    KeyPoint,
    MeetingMetadata,
    Participant,
    ProfileStub,
    TranscriptResult,
    Utterance,
)
from recap.frames import FrameResult
from recap.pipeline import run_pipeline


@pytest.fixture
def config(tmp_path) -> RecapConfig:
    vault = tmp_path / "vault"
    (vault / "Work" / "Meetings").mkdir(parents=True)
    (vault / "Work" / "People").mkdir(parents=True)
    (vault / "Work" / "Companies").mkdir(parents=True)
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    frames = tmp_path / "frames"
    frames.mkdir()
    (tmp_path / "logs").mkdir()

    return RecapConfig(
        vault_path=vault,
        recordings_path=recordings,
        frames_path=frames,
        user_name="Tim",
        whisperx=WhisperXConfig(),
        huggingface_token="hf_fake",
        todoist=TodoistConfig(api_token="test", default_project="Recap", project_map={}),
        claude=ClaudeConfig(command="claude"),
    )


@pytest.fixture
def metadata_file(tmp_path) -> pathlib.Path:
    meta = {
        "title": "Weekly Standup",
        "date": "2026-03-16",
        "participants": [
            {"name": "Tim", "email": "tim@example.com"},
            {"name": "Jane Smith", "email": "jane@acme.com"},
        ],
        "platform": "zoom",
    }
    path = tmp_path / "meeting.json"
    path.write_text(json.dumps(meta))
    return path


@pytest.fixture
def audio_file(tmp_path) -> pathlib.Path:
    path = tmp_path / "meeting.mp4"
    path.write_bytes(b"fake audio content")
    return path


@pytest.fixture
def mock_transcript() -> TranscriptResult:
    return TranscriptResult(
        utterances=[
            Utterance(speaker="SPEAKER_00", start=0.0, end=3.0, text="Hello."),
        ],
        raw_text="Hello.",
        language="en",
    )


@pytest.fixture
def mock_analysis() -> AnalysisResult:
    return AnalysisResult(
        speaker_mapping={"SPEAKER_00": "Tim"},
        meeting_type="standup",
        summary="Quick sync.",
        key_points=[KeyPoint(topic="Status", detail="All on track")],
        decisions=[],
        action_items=[
            ActionItem(assignee="Tim", description="Update board", due_date=None, priority="normal"),
        ],
        follow_ups=[],
        relationship_notes=None,
        people=[ProfileStub(name="Jane Smith", company="Acme Corp", role="Engineer")],
        companies=[ProfileStub(name="Acme Corp", industry="SaaS")],
    )


class TestRunPipeline:
    @patch("recap.pipeline.create_tasks")
    @patch("recap.pipeline.analyze")
    @patch("recap.pipeline.extract_frames")
    @patch("recap.pipeline.transcribe")
    @patch("recap.pipeline._get_audio_duration")
    def test_full_pipeline(
        self,
        mock_duration,
        mock_transcribe,
        mock_frames,
        mock_analyze,
        mock_todoist,
        config,
        metadata_file,
        audio_file,
        mock_transcript,
        mock_analysis,
    ):
        mock_duration.return_value = 1800.0
        mock_transcribe.return_value = mock_transcript
        mock_frames.return_value = []
        mock_analyze.return_value = mock_analysis
        mock_todoist.return_value = ["task_1"]

        result = run_pipeline(audio_file, metadata_file, config)

        assert result["meeting_note"].exists()
        assert "2026-03-16 - Weekly Standup.md" in result["meeting_note"].name
        mock_transcribe.assert_called_once()
        mock_analyze.assert_called_once()
        mock_todoist.assert_called_once()

    @patch("recap.pipeline.create_tasks")
    @patch("recap.pipeline.analyze")
    @patch("recap.pipeline.extract_frames")
    @patch("recap.pipeline.transcribe")
    @patch("recap.pipeline._get_audio_duration")
    def test_pipeline_moves_recording(
        self,
        mock_duration,
        mock_transcribe,
        mock_frames,
        mock_analyze,
        mock_todoist,
        config,
        metadata_file,
        audio_file,
        mock_transcript,
        mock_analysis,
    ):
        mock_duration.return_value = 1800.0
        mock_transcribe.return_value = mock_transcript
        mock_frames.return_value = []
        mock_analyze.return_value = mock_analysis
        mock_todoist.return_value = []

        run_pipeline(audio_file, metadata_file, config)

        # Original file should be moved
        assert not audio_file.exists()
        # Should be in recordings dir
        moved = list(config.recordings_path.glob("*.mp4"))
        assert len(moved) == 1
        assert "2026-03-16" in moved[0].name

    @patch("recap.pipeline.save_retry_file")
    @patch("recap.pipeline.create_tasks")
    @patch("recap.pipeline.analyze")
    @patch("recap.pipeline.extract_frames")
    @patch("recap.pipeline.transcribe")
    @patch("recap.pipeline._get_audio_duration")
    def test_pipeline_continues_on_todoist_failure(
        self,
        mock_duration,
        mock_transcribe,
        mock_frames,
        mock_analyze,
        mock_todoist,
        mock_save_retry,
        config,
        metadata_file,
        audio_file,
        mock_transcript,
        mock_analysis,
    ):
        mock_duration.return_value = 1800.0
        mock_transcribe.return_value = mock_transcript
        mock_frames.return_value = []
        mock_analyze.return_value = mock_analysis
        mock_todoist.side_effect = Exception("API down")

        result = run_pipeline(audio_file, metadata_file, config)

        # Meeting note should still be written
        assert result["meeting_note"].exists()
        # Retry file should be saved
        mock_save_retry.assert_called_once()

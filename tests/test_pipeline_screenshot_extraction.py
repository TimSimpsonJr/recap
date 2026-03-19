"""Tests for screenshot-based participant extraction integration in pipeline."""
import json
import pathlib
from datetime import date
from unittest.mock import MagicMock, patch

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


class TestScreenshotExtraction:
    @patch("recap.pipeline.extract_participants_from_screenshots")
    @patch("recap.pipeline.extract_frames")
    @patch("recap.pipeline.transcribe")
    @patch("recap.pipeline._get_audio_duration")
    def test_extracts_participants_when_metadata_empty(
        self,
        mock_duration,
        mock_transcribe,
        mock_frames,
        mock_extract,
        config,
        tmp_path,
    ):
        # Setup: audio + metadata with no participants + participant frames
        audio_file = tmp_path / "meeting.mp4"
        audio_file.write_bytes(b"fake audio")

        meta = {
            "title": "Team Sync",
            "date": "2026-03-18",
            "participants": [],
            "platform": "zoom",
        }
        metadata_file = tmp_path / "meeting.json"
        metadata_file.write_text(json.dumps(meta))

        # Create participant frame files in working dir
        for i in range(2):
            (tmp_path / f"participant_frame_{i:05d}.png").write_bytes(b"fake png")

        mock_duration.return_value = 1800.0
        mock_transcribe.return_value = TranscriptResult(
            utterances=[Utterance(speaker="SPEAKER_00", start=0.0, end=3.0, text="Hello.")],
            raw_text="Hello.",
            language="en",
        )
        mock_frames.return_value = []
        mock_extract.return_value = ["Jane Smith", "Bob Jones"]

        # The pipeline should call extract and then continue (not pause)
        # We need to mock analyze too since it will proceed past the pause
        with patch("recap.pipeline.analyze") as mock_analyze, \
             patch("recap.pipeline.create_tasks") as mock_todoist:
            mock_analyze.return_value = AnalysisResult(
                speaker_mapping={"SPEAKER_00": "Jane Smith"},
                meeting_type="standup",
                summary="Quick sync.",
                key_points=[],
                decisions=[],
                action_items=[],
                follow_ups=[],
                relationship_notes=None,
                people=[],
                companies=[],
            )
            mock_todoist.return_value = []

            result = run_pipeline(audio_file, metadata_file, config)

        # extract_participants_from_screenshots was called with the participant frames
        mock_extract.assert_called_once()
        called_paths = mock_extract.call_args[0][0]
        assert len(called_paths) == 2
        assert all("participant_frame_" in p.name for p in called_paths)

        # Pipeline should NOT have paused
        assert "paused" not in result or not result.get("paused")

    @patch("recap.pipeline.extract_participants_from_screenshots")
    @patch("recap.pipeline.extract_frames")
    @patch("recap.pipeline.transcribe")
    @patch("recap.pipeline._get_audio_duration")
    def test_pauses_when_no_screenshots_and_no_participants(
        self,
        mock_duration,
        mock_transcribe,
        mock_frames,
        mock_extract,
        config,
        tmp_path,
    ):
        # Setup: no participants, no participant frames
        audio_file = tmp_path / "meeting.mp4"
        audio_file.write_bytes(b"fake audio")

        meta = {
            "title": "Team Sync",
            "date": "2026-03-18",
            "participants": [],
            "platform": "zoom",
        }
        metadata_file = tmp_path / "meeting.json"
        metadata_file.write_text(json.dumps(meta))

        mock_duration.return_value = 1800.0
        mock_transcribe.return_value = TranscriptResult(
            utterances=[],
            raw_text="",
            language="en",
        )
        mock_frames.return_value = []

        result = run_pipeline(audio_file, metadata_file, config)

        # extract should NOT have been called (no participant frames)
        mock_extract.assert_not_called()

        # Pipeline should pause
        assert result.get("paused") is True
        assert result.get("waiting_at") == "analyze"

    @patch("recap.pipeline.extract_participants_from_screenshots")
    @patch("recap.pipeline.extract_frames")
    @patch("recap.pipeline.transcribe")
    @patch("recap.pipeline._get_audio_duration")
    def test_pauses_when_screenshot_extraction_returns_empty(
        self,
        mock_duration,
        mock_transcribe,
        mock_frames,
        mock_extract,
        config,
        tmp_path,
    ):
        # Setup: no participants, participant frames exist but extraction returns empty
        audio_file = tmp_path / "meeting.mp4"
        audio_file.write_bytes(b"fake audio")

        meta = {
            "title": "Team Sync",
            "date": "2026-03-18",
            "participants": [],
            "platform": "zoom",
        }
        metadata_file = tmp_path / "meeting.json"
        metadata_file.write_text(json.dumps(meta))

        (tmp_path / "participant_frame_00000.png").write_bytes(b"fake png")

        mock_duration.return_value = 1800.0
        mock_transcribe.return_value = TranscriptResult(
            utterances=[],
            raw_text="",
            language="en",
        )
        mock_frames.return_value = []
        mock_extract.return_value = []

        result = run_pipeline(audio_file, metadata_file, config)

        # extract was called
        mock_extract.assert_called_once()

        # But pipeline should still pause since extraction returned empty
        assert result.get("paused") is True
        assert result.get("waiting_at") == "analyze"

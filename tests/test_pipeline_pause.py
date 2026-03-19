"""Tests for pipeline pause when no participants are available."""
import json
import pathlib
from datetime import date
from unittest.mock import patch

import pytest

from recap.config import RecapConfig, WhisperXConfig, TodoistConfig, ClaudeConfig
from recap.models import TranscriptResult, Utterance
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
def metadata_no_participants(tmp_path) -> pathlib.Path:
    meta = {
        "title": "Quick Sync",
        "date": "2026-03-17",
        "participants": [],
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


class TestPipelinePause:
    @patch("recap.pipeline.extract_frames")
    @patch("recap.pipeline.transcribe")
    @patch("recap.pipeline._get_audio_duration")
    def test_pauses_when_no_participants(
        self,
        mock_duration,
        mock_transcribe,
        mock_frames,
        config,
        metadata_no_participants,
        audio_file,
        mock_transcript,
    ):
        mock_duration.return_value = 600.0
        mock_transcribe.return_value = mock_transcript
        mock_frames.return_value = []

        result = run_pipeline(audio_file, metadata_no_participants, config)

        assert result["paused"] is True
        assert result["waiting_at"] == "analyze"

    @patch("recap.pipeline.extract_frames")
    @patch("recap.pipeline.transcribe")
    @patch("recap.pipeline._get_audio_duration")
    def test_pause_writes_status_json(
        self,
        mock_duration,
        mock_transcribe,
        mock_frames,
        config,
        metadata_no_participants,
        audio_file,
        mock_transcript,
    ):
        mock_duration.return_value = 600.0
        mock_transcribe.return_value = mock_transcript
        mock_frames.return_value = []

        run_pipeline(audio_file, metadata_no_participants, config)

        # Status should be written to working dir
        status_path = audio_file.parent / "status.json"
        assert status_path.exists()
        status = json.loads(status_path.read_text())
        assert status["analyze"]["waiting"] == "speaker_review"

        # Status should also be copied to recordings dir (<recording>.status.json)
        recordings_status = config.recordings_path / "meeting.status.json"
        assert recordings_status.exists(), "status.json was not copied to recordings dir"
        rec_status = json.loads(recordings_status.read_text())
        assert rec_status["analyze"]["waiting"] == "speaker_review"

    @patch("recap.pipeline.analyze")
    @patch("recap.pipeline.extract_frames")
    @patch("recap.pipeline.transcribe")
    @patch("recap.pipeline._get_audio_duration")
    def test_pause_does_not_call_analyze(
        self,
        mock_duration,
        mock_transcribe,
        mock_frames,
        mock_analyze,
        config,
        metadata_no_participants,
        audio_file,
        mock_transcript,
    ):
        mock_duration.return_value = 600.0
        mock_transcribe.return_value = mock_transcript
        mock_frames.return_value = []

        run_pipeline(audio_file, metadata_no_participants, config)

        mock_analyze.assert_not_called()

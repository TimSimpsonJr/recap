"""Tests for transcription module."""
import pathlib
from unittest.mock import MagicMock, patch

import pytest

from recap.models import TranscriptResult, Utterance
from recap.transcribe import transcribe, _parse_whisperx_result


class TestParseWhisperxResult:
    """Test parsing of WhisperX output into our models."""

    def test_parse_segments_with_speakers(self):
        whisperx_result = {
            "segments": [
                {
                    "start": 0.0,
                    "end": 3.5,
                    "text": " Hello everyone.",
                    "speaker": "SPEAKER_00",
                },
                {
                    "start": 4.0,
                    "end": 8.2,
                    "text": " Thanks for joining.",
                    "speaker": "SPEAKER_01",
                },
            ],
            "language": "en",
        }
        result = _parse_whisperx_result(whisperx_result)
        assert isinstance(result, TranscriptResult)
        assert len(result.utterances) == 2
        assert result.utterances[0].speaker == "SPEAKER_00"
        assert result.utterances[0].text == "Hello everyone."
        assert result.utterances[1].start == 4.0
        assert result.language == "en"

    def test_parse_strips_leading_whitespace(self):
        whisperx_result = {
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "  Some text  ", "speaker": "SPEAKER_00"},
            ],
            "language": "en",
        }
        result = _parse_whisperx_result(whisperx_result)
        assert result.utterances[0].text == "Some text"

    def test_parse_missing_speaker_defaults(self):
        whisperx_result = {
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "Hello", },
            ],
            "language": "en",
        }
        result = _parse_whisperx_result(whisperx_result)
        assert result.utterances[0].speaker == "UNKNOWN"

    def test_raw_text_concatenation(self):
        whisperx_result = {
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "Hello.", "speaker": "SPEAKER_00"},
                {"start": 1.5, "end": 3.0, "text": "World.", "speaker": "SPEAKER_01"},
            ],
            "language": "en",
        }
        result = _parse_whisperx_result(whisperx_result)
        assert result.raw_text == "Hello. World."


class TestTranscribe:
    """Test the transcribe function with mocked WhisperX."""

    @patch("recap.transcribe.whisperx")
    def test_transcribe_calls_whisperx(self, mock_wx, tmp_path: pathlib.Path):
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        mock_model = MagicMock()
        mock_wx.load_model.return_value = mock_model
        mock_model.transcribe.return_value = {
            "segments": [
                {"start": 0.0, "end": 3.0, "text": "Hello.", "speaker": "SPEAKER_00"},
            ],
            "language": "en",
        }
        mock_diarize_model = MagicMock()
        mock_wx.DiarizationPipeline.return_value = mock_diarize_model
        mock_diarize_model.return_value = "fake_diarize_segments"
        mock_wx.assign_word_speakers.return_value = {
            "segments": [
                {"start": 0.0, "end": 3.0, "text": "Hello.", "speaker": "SPEAKER_00"},
            ],
            "language": "en",
        }

        result = transcribe(
            audio_path=audio_file,
            model_name="large-v3",
            device="cpu",
            hf_token="hf_fake",
        )

        assert isinstance(result, TranscriptResult)
        assert len(result.utterances) == 1
        mock_wx.load_model.assert_called_once()

    @patch("recap.transcribe.whisperx")
    def test_transcribe_saves_transcript_json(self, mock_wx, tmp_path: pathlib.Path):
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")
        transcript_out = tmp_path / "transcript.json"

        mock_model = MagicMock()
        mock_wx.load_model.return_value = mock_model
        mock_model.transcribe.return_value = {
            "segments": [
                {"start": 0.0, "end": 3.0, "text": "Hello.", "speaker": "SPEAKER_00"},
            ],
            "language": "en",
        }
        mock_diarize_model = MagicMock()
        mock_wx.DiarizationPipeline.return_value = mock_diarize_model
        mock_diarize_model.return_value = "fake_segments"
        mock_wx.assign_word_speakers.return_value = mock_model.transcribe.return_value

        result = transcribe(
            audio_path=audio_file,
            model_name="large-v3",
            device="cpu",
            hf_token="hf_fake",
            save_transcript=transcript_out,
        )

        assert transcript_out.exists()

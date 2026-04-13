"""Tests for NeMo speaker diarization."""
import pytest
from unittest.mock import patch, MagicMock
from recap.pipeline.diarize import diarize, assign_speakers
from recap.models import TranscriptResult, Utterance


class TestDiarize:
    def test_returns_speaker_segments(self, tmp_path):
        mock_model = MagicMock()
        mock_model.diarize.return_value = [
            {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"},
            {"start": 5.0, "end": 10.0, "speaker": "SPEAKER_01"},
        ]

        with patch("recap.pipeline.diarize._load_diarization_model", return_value=mock_model):
            with patch("recap.pipeline.diarize._unload_model"):
                segments = diarize(
                    audio_path=tmp_path / "test.flac",
                    device="cpu",
                )
        assert len(segments) == 2
        assert segments[0]["speaker"] == "SPEAKER_00"

    def test_unloads_model(self, tmp_path):
        mock_model = MagicMock()
        mock_model.diarize.return_value = []

        with patch("recap.pipeline.diarize._load_diarization_model", return_value=mock_model):
            with patch("recap.pipeline.diarize._unload_model") as unload:
                diarize(audio_path=tmp_path / "test.flac", device="cpu")
                unload.assert_called_once()


class TestAssignSpeakers:
    def test_assigns_speakers_by_overlap(self):
        transcript = TranscriptResult(
            utterances=[
                Utterance(speaker="UNKNOWN", start=0.0, end=3.0, text="Hello"),
                Utterance(speaker="UNKNOWN", start=5.0, end=8.0, text="Hi there"),
            ],
            raw_text="Hello Hi there",
            language="en",
        )
        speaker_segments = [
            {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"},
            {"start": 5.0, "end": 10.0, "speaker": "SPEAKER_01"},
        ]

        result = assign_speakers(transcript, speaker_segments)
        assert result.utterances[0].speaker == "SPEAKER_00"
        assert result.utterances[1].speaker == "SPEAKER_01"

    def test_does_not_mutate_input(self):
        transcript = TranscriptResult(
            utterances=[
                Utterance(speaker="UNKNOWN", start=0.0, end=3.0, text="Hello"),
            ],
            raw_text="Hello",
            language="en",
        )
        segments = [{"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"}]
        result = assign_speakers(transcript, segments)
        assert transcript.utterances[0].speaker == "UNKNOWN"
        assert result.utterances[0].speaker == "SPEAKER_00"

    def test_handles_no_overlap(self):
        transcript = TranscriptResult(
            utterances=[
                Utterance(speaker="UNKNOWN", start=20.0, end=25.0, text="Late"),
            ],
            raw_text="Late",
            language="en",
        )
        segments = [{"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"}]
        result = assign_speakers(transcript, segments)
        assert result.utterances[0].speaker == "UNKNOWN"

    def test_picks_best_overlap(self):
        transcript = TranscriptResult(
            utterances=[
                Utterance(speaker="UNKNOWN", start=4.0, end=7.0, text="overlap"),
            ],
            raw_text="overlap",
            language="en",
        )
        segments = [
            {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"},  # 1s overlap
            {"start": 5.0, "end": 10.0, "speaker": "SPEAKER_01"},  # 2s overlap
        ]
        result = assign_speakers(transcript, segments)
        assert result.utterances[0].speaker == "SPEAKER_01"

    def test_empty_segments_keeps_unknown(self):
        transcript = TranscriptResult(
            utterances=[
                Utterance(speaker="UNKNOWN", start=0.0, end=3.0, text="Hello"),
            ],
            raw_text="Hello",
            language="en",
        )
        result = assign_speakers(transcript, [])
        assert result.utterances[0].speaker == "UNKNOWN"

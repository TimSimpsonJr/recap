"""Tests for speaker label correction logic."""
import json
import pathlib

import pytest

from recap.models import TranscriptResult, Utterance
from recap.pipeline import _apply_speaker_labels


@pytest.fixture
def transcript() -> TranscriptResult:
    return TranscriptResult(
        utterances=[
            Utterance(speaker="SPEAKER_00", start=0.0, end=3.0, text="Hello everyone."),
            Utterance(speaker="SPEAKER_01", start=3.0, end=6.0, text="Hi there."),
            Utterance(speaker="SPEAKER_00", start=6.0, end=9.0, text="Let's begin."),
            Utterance(speaker="SPEAKER_02", start=9.0, end=12.0, text="Sounds good."),
        ],
        raw_text="Hello everyone. Hi there. Let's begin. Sounds good.",
        language="en",
    )


class TestApplySpeakerLabels:
    def test_applies_corrections(self, transcript, tmp_path):
        labels_path = tmp_path / "speaker_labels.json"
        labels_path.write_text(json.dumps({
            "SPEAKER_00": "Tim",
            "SPEAKER_01": "Jane Smith",
        }))

        result = _apply_speaker_labels(transcript, labels_path)

        assert result.utterances[0].speaker == "Tim"
        assert result.utterances[1].speaker == "Jane Smith"
        assert result.utterances[2].speaker == "Tim"
        # SPEAKER_02 not in labels, should remain unchanged
        assert result.utterances[3].speaker == "SPEAKER_02"

    def test_no_labels_file_returns_transcript_unchanged(self, transcript, tmp_path):
        labels_path = tmp_path / "speaker_labels.json"
        # File does not exist

        result = _apply_speaker_labels(transcript, labels_path)

        assert result.utterances[0].speaker == "SPEAKER_00"
        assert result.utterances[1].speaker == "SPEAKER_01"

    def test_empty_labels_returns_transcript_unchanged(self, transcript, tmp_path):
        labels_path = tmp_path / "speaker_labels.json"
        labels_path.write_text(json.dumps({}))

        result = _apply_speaker_labels(transcript, labels_path)

        assert result.utterances[0].speaker == "SPEAKER_00"
        assert result.utterances[1].speaker == "SPEAKER_01"

    def test_returns_same_object(self, transcript, tmp_path):
        """_apply_speaker_labels mutates in place and returns the same object."""
        labels_path = tmp_path / "speaker_labels.json"
        labels_path.write_text(json.dumps({"SPEAKER_00": "Tim"}))

        result = _apply_speaker_labels(transcript, labels_path)

        assert result is transcript

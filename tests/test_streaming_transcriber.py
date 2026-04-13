"""Tests for streaming transcriber."""
import pytest
from unittest.mock import MagicMock, patch
from recap.daemon.streaming.transcriber import StreamingTranscriber
from recap.models import TranscriptResult


class TestStreamingTranscriber:
    def test_initial_state(self):
        transcriber = StreamingTranscriber(model_name="nvidia/parakeet-tdt-0.6b-v2")
        assert transcriber.is_running is False
        assert transcriber.segments == []
        assert transcriber.had_errors is False

    def test_records_segments(self):
        transcriber = StreamingTranscriber()
        transcriber._on_segment({"text": "Hello world", "start": 0.0, "end": 1.5, "speaker": "SPEAKER_00"})
        assert len(transcriber.segments) == 1
        assert transcriber.segments[0]["text"] == "Hello world"

    def test_fires_callback(self):
        callback = MagicMock()
        transcriber = StreamingTranscriber()
        transcriber.on_segment = callback
        transcriber._on_segment({"text": "Hello", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"})
        callback.assert_called_once()

    def test_has_error_flag(self):
        transcriber = StreamingTranscriber()
        assert transcriber.had_errors is False
        transcriber._on_error(Exception("GPU OOM"))
        assert transcriber.had_errors is True

    def test_get_transcript_result(self):
        transcriber = StreamingTranscriber()
        transcriber._on_segment({"text": "Hello", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"})
        transcriber._on_segment({"text": "Hi", "start": 1.0, "end": 2.0, "speaker": "SPEAKER_01"})
        result = transcriber.get_transcript_result()
        assert isinstance(result, TranscriptResult)
        assert len(result.utterances) == 2
        assert result.utterances[0].speaker == "SPEAKER_00"
        assert result.utterances[0].text == "Hello"

    def test_get_transcript_result_empty(self):
        transcriber = StreamingTranscriber()
        result = transcriber.get_transcript_result()
        assert len(result.utterances) == 0
        assert result.raw_text == ""

    def test_start_with_failed_model_sets_error(self):
        transcriber = StreamingTranscriber()
        with patch.object(transcriber, "_load_model", side_effect=Exception("Model not found")):
            transcriber.start()
        assert transcriber.had_errors is True
        assert transcriber.is_running is False

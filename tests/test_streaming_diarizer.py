"""Tests for streaming diarizer."""

from unittest.mock import MagicMock, patch

from recap.daemon.streaming.diarizer import StreamingDiarizer


class TestStreamingDiarizer:
    def test_initial_state(self):
        diarizer = StreamingDiarizer()
        assert diarizer.is_running is False
        assert diarizer.speaker_segments == []
        assert diarizer.had_errors is False

    def test_tracks_speaker_segments(self):
        diarizer = StreamingDiarizer()
        diarizer._on_speaker_segment({"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"})
        diarizer._on_speaker_segment({"start": 5.0, "end": 10.0, "speaker": "SPEAKER_01"})
        assert len(diarizer.speaker_segments) == 2
        assert diarizer.speaker_segments[0]["speaker"] == "SPEAKER_00"

    def test_fires_callback(self):
        callback = MagicMock()
        diarizer = StreamingDiarizer()
        diarizer.on_speaker_segment = callback
        diarizer._on_speaker_segment({"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"})
        callback.assert_called_once()

    def test_error_flag(self):
        diarizer = StreamingDiarizer()
        assert diarizer.had_errors is False
        diarizer._on_error(Exception("CUDA OOM"))
        assert diarizer.had_errors is True

    def test_get_speaker_segments_returns_copy(self):
        diarizer = StreamingDiarizer()
        diarizer._on_speaker_segment({"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"})
        segments = diarizer.get_speaker_segments()
        assert len(segments) == 1
        # Modifying returned list shouldn't affect internal state
        segments.clear()
        assert len(diarizer.speaker_segments) == 1

    def test_start_with_failed_model_sets_error(self):
        diarizer = StreamingDiarizer()
        with patch.object(diarizer, "_load_model", side_effect=Exception("VRAM exceeded")):
            diarizer.start()
        assert diarizer.had_errors is True
        assert diarizer.is_running is False

    def test_stop_returns_none_on_errors(self):
        diarizer = StreamingDiarizer()
        diarizer._had_errors = True
        result = diarizer.stop()
        assert result is None

    def test_stop_returns_segments_on_success(self):
        diarizer = StreamingDiarizer()
        diarizer._on_speaker_segment({"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"})
        diarizer._running = True  # simulate started state
        result = diarizer.stop()
        assert result is not None
        assert len(result) == 1

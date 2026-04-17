"""Tests for streaming diarizer."""

from recap.daemon.streaming.diarizer import StreamingDiarizer


class TestStreamingDiarizer:
    def test_initial_state(self):
        diarizer = StreamingDiarizer()
        assert diarizer.is_running is False
        assert diarizer.speaker_segments == []
        assert diarizer.had_errors is False

    def test_stop_returns_none_on_errors(self):
        diarizer = StreamingDiarizer()
        diarizer._had_errors = True
        result = diarizer.stop()
        assert result is None


def test_streaming_diarizer_start_logs_deferred_message(caplog):
    import logging
    caplog.set_level(logging.INFO, logger="recap.daemon.streaming.diarizer")

    from recap.daemon.streaming.diarizer import StreamingDiarizer
    d = StreamingDiarizer()
    d.start()

    assert any(
        "Live streaming diarization deferred" in r.message
        for r in caplog.records
    )


def test_streaming_diarizer_no_load_model_method():
    from recap.daemon.streaming.diarizer import StreamingDiarizer
    assert not hasattr(StreamingDiarizer, "_load_model")

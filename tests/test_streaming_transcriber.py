"""Tests for streaming transcriber."""
from recap.daemon.streaming.transcriber import StreamingTranscriber


class TestStreamingTranscriber:
    def test_initial_state(self):
        transcriber = StreamingTranscriber(model_name="nvidia/parakeet-tdt-0.6b-v2")
        assert transcriber.is_running is False
        assert transcriber.segments == []
        assert transcriber.had_errors is False

    def test_get_transcript_result_empty(self):
        transcriber = StreamingTranscriber()
        result = transcriber.get_transcript_result()
        assert len(result.utterances) == 0
        assert result.raw_text == ""


def test_streaming_transcriber_start_logs_deferred_message(caplog):
    """Stub emits 'Live streaming transcription deferred' at INFO level."""
    import logging
    caplog.set_level(logging.INFO, logger="recap.daemon.streaming.transcriber")

    from recap.daemon.streaming.transcriber import StreamingTranscriber
    t = StreamingTranscriber()
    t.start()

    assert any(
        "Live streaming transcription deferred" in r.message
        for r in caplog.records
    )


def test_streaming_transcriber_no_load_model_method():
    """Stub removes _load_model entirely."""
    from recap.daemon.streaming.transcriber import StreamingTranscriber
    assert not hasattr(StreamingTranscriber, "_load_model")

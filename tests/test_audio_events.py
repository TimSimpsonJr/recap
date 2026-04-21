"""Tests for audio_events module: journal event types + warning code constants."""


def test_event_type_constants_exist():
    from recap.daemon.recorder.audio_events import (
        EVT_AUDIO_NO_LOOPBACK_AT_START,
        EVT_AUDIO_NO_SYSTEM_AUDIO,
        EVT_AUDIO_ALL_LOOPBACKS_LOST,
    )
    assert EVT_AUDIO_NO_LOOPBACK_AT_START == "audio_capture_no_loopback_at_start"
    assert EVT_AUDIO_NO_SYSTEM_AUDIO == "audio_capture_no_system_audio"
    assert EVT_AUDIO_ALL_LOOPBACKS_LOST == "audio_capture_all_loopbacks_lost"


def test_warning_code_constants_exist():
    from recap.daemon.recorder.audio_events import (
        WARN_NO_SYSTEM_AUDIO_CAPTURED,
        WARN_SYSTEM_AUDIO_INTERRUPTED,
    )
    assert WARN_NO_SYSTEM_AUDIO_CAPTURED == "no-system-audio-captured"
    assert WARN_SYSTEM_AUDIO_INTERRUPTED == "system-audio-interrupted"

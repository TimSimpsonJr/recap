"""Tests for recorder orchestrator."""
import pytest
from unittest.mock import MagicMock, patch
from recap.daemon.recorder.recorder import Recorder
from recap.daemon.recorder.state_machine import RecorderState


class TestRecorder:
    @pytest.fixture
    def recorder(self, tmp_path):
        return Recorder(
            recordings_path=tmp_path,
            sample_rate=16000,
            channels=2,
            silence_timeout_minutes=5,
            max_duration_hours=4,
        )

    def test_generates_unique_filename(self, recorder):
        path = recorder._generate_recording_path("disbursecloud")
        assert path.suffix == ".flac"
        assert "disbursecloud" in path.stem

    def test_filename_includes_date(self, recorder):
        path = recorder._generate_recording_path("personal")
        import re
        assert re.search(r"\d{4}-\d{2}-\d{2}", path.stem)

    def test_is_recording_false_initially(self, recorder):
        assert recorder.is_recording is False

    def test_current_recording_path_none_when_idle(self, recorder):
        assert recorder.current_recording_path is None

    def test_state_is_idle_initially(self, recorder):
        assert recorder.state_machine.state == RecorderState.IDLE

    def test_disk_space_check_passes_with_plenty(self, recorder):
        with patch("shutil.disk_usage") as mock_usage:
            mock_usage.return_value = MagicMock(free=5_000_000_000)  # 5GB
            assert recorder._check_disk_space() is True

    def test_disk_space_check_warns_when_low(self, recorder):
        with patch("shutil.disk_usage") as mock_usage:
            mock_usage.return_value = MagicMock(free=500_000_000)  # 500MB
            assert recorder._check_disk_space() is False


def test_start_streaming_wires_on_chunk_to_feed_streaming_models(tmp_path):
    """_start_streaming must route decoded chunks through _feed_streaming_models."""
    recorder = Recorder(recordings_path=tmp_path)

    # Provide a stand-in AudioCapture — only needs an on_chunk attribute that
    # _start_streaming can assign to.
    fake_capture = MagicMock()
    fake_capture.on_chunk = None
    recorder._audio_capture = fake_capture

    # Patch the streaming model constructors so _start_streaming does not spin
    # up real threads when it instantiates them.
    with patch(
        "recap.daemon.recorder.recorder.StreamingTranscriber",
        return_value=MagicMock(),
    ), patch(
        "recap.daemon.recorder.recorder.StreamingDiarizer",
        return_value=MagicMock(),
    ):
        recorder._start_streaming()

    # The wiring invariant: _start_streaming must point on_chunk at
    # _feed_streaming_models so decoded chunks reach both streaming models.
    # Bound-method equality checks identity of (self, __func__), which is what
    # we want — `is` fails because each attribute access creates a new bound
    # method object.
    assert recorder._audio_capture.on_chunk == recorder._feed_streaming_models
    assert recorder._audio_capture.on_chunk.__func__ is Recorder._feed_streaming_models
    assert recorder._audio_capture.on_chunk.__self__ is recorder


def test_feed_streaming_models_forwards_to_transcriber_and_diarizer(tmp_path):
    """_feed_streaming_models feeds both transcriber.feed_audio and diarizer.feed_audio."""
    recorder = Recorder(recordings_path=tmp_path)

    transcriber = MagicMock()
    diarizer = MagicMock()
    recorder._transcriber = transcriber
    recorder._diarizer = diarizer

    chunk = b"\x00" * 320
    sample_rate = 16000
    recorder._feed_streaming_models(chunk, sample_rate)

    transcriber.feed_audio.assert_called_once_with(chunk, sample_rate)
    diarizer.feed_audio.assert_called_once_with(chunk, sample_rate)


@pytest.mark.asyncio
async def test_monitor_capture_health_stops_recorder_on_fatal_event(tmp_path):
    """When AudioCapture._fatal_event is tripped during recording, the
    _monitor_capture_health task observes it within one poll (~0.5s),
    calls recorder.stop(), and the state machine returns to IDLE."""
    import asyncio
    import threading
    from recap.daemon.recorder.recorder import Recorder
    from recap.daemon.recorder.state_machine import RecorderState

    recorder = Recorder(
        recordings_path=tmp_path,
        sample_rate=16000,
        channels=2,
        silence_timeout_minutes=5,
        max_duration_hours=4,
    )

    # Inject a minimal fake AudioCapture + drive the state machine to
    # RECORDING so the monitor task can exit through the fatal branch
    # rather than being short-circuited by a None audio_capture check.
    fake_capture = MagicMock()
    fake_capture._fatal_event = threading.Event()
    fake_capture._fatal_error = None
    fake_capture.current_rms = 0.0
    fake_capture.stop = MagicMock()
    recorder._audio_capture = fake_capture
    recorder._current_path = tmp_path / "fake.flac"
    recorder.state_machine.detected("testorg")
    recorder.state_machine.start_recording("testorg")

    # Launch just the monitor task (bypass full start() which opens PyAudio).
    monitor = asyncio.create_task(recorder._monitor_capture_health())
    try:
        # Trip the fatal event with an informative error.
        fake_capture._fatal_error = RuntimeError("both sources degraded")
        fake_capture._fatal_event.set()
        # Give the monitor one poll cycle + a margin.
        await asyncio.sleep(0.7)
        # Monitor called stop() -> state machine is no longer RECORDING.
        assert recorder.state_machine.state != RecorderState.RECORDING
        # fake_capture.stop was invoked by Recorder.stop().
        assert fake_capture.stop.called
    finally:
        if not monitor.done():
            monitor.cancel()
            try:
                await monitor
            except (asyncio.CancelledError, Exception):
                pass


@pytest.mark.asyncio
async def test_stop_persists_audio_warnings_into_sidecar(tmp_path):
    """On stop, the recorder must rewrite the sidecar with the AudioCapture's
    accumulated _audio_warnings / _system_audio_devices_seen so the pipeline
    export stage can render them in the note frontmatter + body callout."""
    from recap.artifacts import RecordingMetadata, load_recording_metadata
    from recap.daemon.recorder.recorder import Recorder

    recorder = Recorder(recordings_path=tmp_path)

    # Bypass full start() — inject a fake AudioCapture + populate the
    # initial sidecar like start() would.
    fake_capture = MagicMock()
    fake_capture._audio_warnings = ["no-system-audio-captured"]
    fake_capture._system_audio_devices_seen = ["Laptop Speakers", "HDMI Audio"]
    fake_capture.stop = MagicMock()

    audio_path = tmp_path / "test.flac"
    audio_path.touch()
    initial_metadata = RecordingMetadata(
        org="testorg",
        note_path="",
        title="Test",
        date="2026-04-21",
        participants=[],
        platform="manual",
    )
    from recap.artifacts import write_recording_metadata
    write_recording_metadata(audio_path, initial_metadata)

    recorder._audio_capture = fake_capture
    recorder._current_path = audio_path
    recorder._current_metadata = initial_metadata
    recorder.state_machine.detected("testorg")
    recorder.state_machine.start_recording("testorg")

    await recorder.stop()

    loaded = load_recording_metadata(audio_path)
    assert loaded is not None
    assert loaded.audio_warnings == ["no-system-audio-captured"]
    assert loaded.system_audio_devices_seen == ["Laptop Speakers", "HDMI Audio"]


@pytest.mark.asyncio
async def test_stop_captures_audio_warnings_after_final_drain_tick(tmp_path):
    """Regression: audio_warnings must be read AFTER audio_capture.stop()
    so any Scenario warning emitted during the final drain tick is
    persisted to the sidecar. Previously the read happened before stop,
    missing any final-tick warnings."""
    from recap.artifacts import RecordingMetadata, load_recording_metadata, write_recording_metadata
    from recap.daemon.recorder.recorder import Recorder

    recorder = Recorder(recordings_path=tmp_path)

    # Fake AudioCapture where stop() is the point at which _audio_warnings
    # gains its final entry — simulating Scenario A/B/C firing during the
    # final drain tick inside AudioCapture.stop().
    fake_capture = MagicMock()
    fake_capture._audio_warnings = []
    fake_capture._system_audio_devices_seen = []

    def _stop_side_effect():
        fake_capture._audio_warnings.append("late-warning")

    fake_capture.stop = MagicMock(side_effect=_stop_side_effect)

    audio_path = tmp_path / "test.flac"
    audio_path.touch()
    initial_metadata = RecordingMetadata(
        org="testorg",
        note_path="",
        title="Test",
        date="2026-04-21",
        participants=[],
        platform="manual",
    )
    write_recording_metadata(audio_path, initial_metadata)

    recorder._audio_capture = fake_capture
    recorder._current_path = audio_path
    recorder._current_metadata = initial_metadata
    recorder.state_machine.detected("testorg")
    recorder.state_machine.start_recording("testorg")

    # Pre-stop invariant: no warnings have been accumulated yet.
    assert fake_capture._audio_warnings == []

    await recorder.stop()

    # The late-warning added during stop() must land in the sidecar.
    loaded = load_recording_metadata(audio_path)
    assert loaded is not None
    assert loaded.audio_warnings == ["late-warning"]


@pytest.mark.asyncio
async def test_recorder_passes_event_journal_into_audio_capture(tmp_path):
    """When the Recorder is constructed with an event_journal, starting a
    recording must thread that journal into the AudioCapture so Scenarios
    A/B/C fire in production rather than being silently dropped."""
    import threading
    from recap.daemon.recorder.recorder import Recorder

    journal = MagicMock()
    recorder = Recorder(recordings_path=tmp_path, event_journal=journal)

    captured: dict = {}

    class _FakeAudioCapture:
        def __init__(self, **kwargs):
            self._event_journal = None
            self._fatal_event = threading.Event()
            self._audio_warnings: list[str] = []
            self._system_audio_devices_seen: list[str] = []
            captured["instance"] = self

        def start(self):
            pass

        def stop(self):
            pass

        @property
        def is_recording(self):
            return True

        on_chunk = None

    with patch(
        "recap.daemon.recorder.recorder.AudioCapture",
        _FakeAudioCapture,
    ), patch(
        "recap.daemon.recorder.recorder.StreamingTranscriber",
        return_value=MagicMock(),
    ), patch(
        "recap.daemon.recorder.recorder.StreamingDiarizer",
        return_value=MagicMock(),
    ):
        try:
            await recorder.start("testorg")
            instance = captured.get("instance")
            assert instance is not None
            assert instance._event_journal is journal
        finally:
            # Tear down the async monitors start() spun up so the test
            # doesn't leak "Task was destroyed but it is pending!" warnings.
            await recorder.stop()

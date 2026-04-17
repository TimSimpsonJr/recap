"""Tests for detection polling loop."""
import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, AsyncMock
from recap.daemon.recorder.detector import MeetingDetector
from recap.daemon.recorder.detection import MeetingWindow


def _make_recorder_mock():
    """Create a mock recorder with async start/stop methods."""
    mock = MagicMock()
    mock.start = AsyncMock()
    mock.stop = AsyncMock()
    mock.is_recording = False
    return mock


class TestMeetingDetector:
    @pytest.fixture
    def mock_config(self):
        config = MagicMock()
        config.detection.teams.enabled = True
        config.detection.teams.behavior = "auto-record"
        config.detection.teams.default_org = "disbursecloud"
        config.detection.zoom.enabled = True
        config.detection.zoom.behavior = "auto-record"
        config.detection.zoom.default_org = "disbursecloud"
        config.detection.signal.enabled = True
        config.detection.signal.behavior = "prompt"
        config.detection.signal.default_org = "personal"
        config.known_contacts = []
        return config

    def test_enabled_platforms(self, mock_config):
        detector = MeetingDetector(config=mock_config, recorder=MagicMock())
        assert "teams" in detector.enabled_platforms
        assert "zoom" in detector.enabled_platforms
        assert "signal" in detector.enabled_platforms

    def test_disabled_platform_excluded(self, mock_config):
        mock_config.detection.teams.enabled = False
        detector = MeetingDetector(config=mock_config, recorder=MagicMock())
        assert "teams" not in detector.enabled_platforms

    def test_get_behavior(self, mock_config):
        detector = MeetingDetector(config=mock_config, recorder=MagicMock())
        assert detector.get_behavior("teams") == "auto-record"
        assert detector.get_behavior("signal") == "prompt"

    def test_get_default_org(self, mock_config):
        detector = MeetingDetector(config=mock_config, recorder=MagicMock())
        assert detector.get_default_org("teams") == "disbursecloud"
        assert detector.get_default_org("signal") == "personal"

    @pytest.mark.asyncio
    async def test_auto_record_starts_recorder(self, mock_config):
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)

        meeting = MeetingWindow(hwnd=1, title="Sprint | Microsoft Teams", platform="teams")
        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[meeting]):
            with patch("recap.daemon.recorder.detector.enrich_meeting_metadata", return_value={"title": "Sprint", "participants": [], "platform": "teams"}):
                await detector._poll_once()

        mock_recorder.start.assert_called_once()
        args, kwargs = mock_recorder.start.call_args
        assert args == ("disbursecloud",)
        assert kwargs["detected"] is True
        assert kwargs["metadata"].title == "Sprint"

    @pytest.mark.asyncio
    async def test_prompt_behavior_calls_callback(self, mock_config):
        mock_recorder = _make_recorder_mock()
        on_signal = AsyncMock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder, on_signal_detected=on_signal)

        meeting = MeetingWindow(hwnd=1, title="Signal", platform="signal")
        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[meeting]):
            with patch("recap.daemon.recorder.detector.enrich_meeting_metadata", return_value={"title": "Signal Call", "participants": [], "platform": "signal"}):
                await detector._poll_once()

        # The callback is scheduled as a background task so the poll loop
        # stays non-blocking; drain it before asserting it was awaited.
        if detector._pending_signal_tasks:
            await asyncio.gather(
                *detector._pending_signal_tasks, return_exceptions=True,
            )

        on_signal.assert_awaited_once()
        mock_recorder.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_retrigger_same_meeting(self, mock_config):
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)

        meeting = MeetingWindow(hwnd=1, title="Sprint | Microsoft Teams", platform="teams")
        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[meeting]):
            with patch("recap.daemon.recorder.detector.enrich_meeting_metadata", return_value={"title": "Sprint", "participants": [], "platform": "teams"}):
                await detector._poll_once()
                mock_recorder.start.reset_mock()
                # Second poll with same meeting
                mock_recorder.is_recording = True  # now recording
                await detector._poll_once()

        mock_recorder.start.assert_not_called()  # should not trigger again

    @pytest.mark.asyncio
    async def test_does_not_start_when_already_recording(self, mock_config):
        mock_recorder = _make_recorder_mock()
        mock_recorder.is_recording = True  # already recording
        detector = MeetingDetector(config=mock_config, recorder=MagicMock())

        meeting = MeetingWindow(hwnd=1, title="Sprint | Microsoft Teams", platform="teams")
        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[meeting]):
            with patch("recap.daemon.recorder.detector.enrich_meeting_metadata", return_value={"title": "Sprint", "participants": [], "platform": "teams"}):
                await detector._poll_once()

        mock_recorder.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleans_up_closed_windows(self, mock_config):
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)

        meeting = MeetingWindow(hwnd=1, title="Sprint | Microsoft Teams", platform="teams")
        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[meeting]):
            with patch("recap.daemon.recorder.detector.enrich_meeting_metadata", return_value={"title": "Sprint", "participants": [], "platform": "teams"}):
                await detector._poll_once()

        assert 1 in detector._tracked_meetings

        # Second poll: window is gone
        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[]):
            await detector._poll_once()

        assert 1 not in detector._tracked_meetings


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.detection.teams.enabled = True
    config.detection.teams.behavior = "auto-record"
    config.detection.teams.default_org = "disbursecloud"
    config.detection.zoom.enabled = True
    config.detection.zoom.behavior = "auto-record"
    config.detection.zoom.default_org = "disbursecloud"
    config.detection.signal.enabled = True
    config.detection.signal.behavior = "prompt"
    config.detection.signal.default_org = "personal"
    config.known_contacts = []
    return config


class TestCalendarArming:
    def test_arm_sets_armed(self, mock_config):
        mock_recorder = MagicMock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        detector.arm_for_event(
            event_id="evt1",
            start_time=datetime.now() + timedelta(minutes=5),
            org="disbursecloud",
        )
        assert detector.is_armed is True
        mock_recorder.state_machine.arm.assert_called_once_with("disbursecloud")

    def test_disarm_clears_armed(self, mock_config):
        mock_recorder = MagicMock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        detector.arm_for_event(
            event_id="evt1",
            start_time=datetime.now() + timedelta(minutes=5),
            org="disbursecloud",
        )
        detector.disarm()
        assert detector.is_armed is False

    @pytest.mark.asyncio
    async def test_armed_detection_starts_recording(self, mock_config):
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        detector.arm_for_event(
            event_id="evt1",
            start_time=datetime.now() - timedelta(minutes=1),  # meeting started
            org="disbursecloud",
        )

        meeting = MeetingWindow(hwnd=1, title="Sprint | Microsoft Teams", platform="teams")
        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[meeting]):
            with patch("recap.daemon.recorder.detector.enrich_meeting_metadata", return_value={"title": "Sprint", "participants": [], "platform": "teams"}):
                await detector._poll_once()

        mock_recorder.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_arm_timeout_disarms(self, mock_config):
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        # Arm with a start_time far in the past (beyond timeout)
        detector.arm_for_event(
            event_id="evt1",
            start_time=datetime.now() - timedelta(minutes=15),
            org="disbursecloud",
        )

        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[]):
            await detector._poll_once()

        assert detector.is_armed is False


class TestWindowMonitoring:
    @pytest.mark.asyncio
    async def test_stops_recording_when_window_closes(self, mock_config):
        mock_recorder = _make_recorder_mock()
        mock_recorder.is_recording = True
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)

        # Simulate: meeting was detected and recording started
        detector._recording_hwnd = 12345
        detector._tracked_meetings[12345] = MeetingWindow(hwnd=12345, title="Sprint | Microsoft Teams", platform="teams")

        # Next poll: window is gone (hard Windows signal confirms it).
        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[]):
            with patch("recap.daemon.recorder.detector.is_window_alive", return_value=False):
                with patch("recap.daemon.recorder.detector.enrich_meeting_metadata"):
                    await detector._poll_once()

        mock_recorder.stop.assert_called_once()
        assert detector._recording_hwnd is None

    @pytest.mark.asyncio
    async def test_keeps_recording_when_window_still_open(self, mock_config):
        mock_recorder = _make_recorder_mock()
        mock_recorder.is_recording = True
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)

        meeting = MeetingWindow(hwnd=12345, title="Sprint | Microsoft Teams", platform="teams")
        detector._recording_hwnd = 12345
        detector._tracked_meetings[12345] = meeting

        # Next poll: window still there
        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[meeting]):
            with patch("recap.daemon.recorder.detector.is_window_alive", return_value=True):
                with patch("recap.daemon.recorder.detector.enrich_meeting_metadata"):
                    await detector._poll_once()

        mock_recorder.stop.assert_not_called()


class TestAwaitableSignalCallback:
    """Detector ``on_signal_detected`` must be awaitable so the poll loop
    can yield while the Signal popup is up and still tick on schedule.
    """

    def _make_config(self):
        config = MagicMock()
        config.detection.teams.enabled = False
        config.detection.zoom.enabled = False
        config.detection.signal.enabled = True
        config.detection.signal.behavior = "prompt"
        config.detection.signal.default_org = "personal"
        config.known_contacts = []
        return config

    @pytest.mark.asyncio
    async def test_detector_awaits_signal_callback_without_blocking_poll(self):
        """The detector keeps ticking while the signal callback is awaited.

        We simulate a callback that awaits for a short period and fire a
        concurrent polling task. Both callback invocations must complete
        and the poll loop must continue ticking during the await window.
        """
        mock_recorder = _make_recorder_mock()
        callback_hits: list[tuple[MeetingWindow, dict]] = []

        async def _slow_callback(meeting, enriched):
            await asyncio.sleep(0.02)
            callback_hits.append((meeting, enriched))

        config = self._make_config()
        detector = MeetingDetector(
            config=config,
            recorder=mock_recorder,
            on_signal_detected=_slow_callback,
        )

        # Two distinct meeting windows (different hwnds) seen on consecutive
        # polls. Each should trigger the callback exactly once.
        meeting_a = MeetingWindow(hwnd=1, title="Signal", platform="signal")
        meeting_b = MeetingWindow(hwnd=2, title="Signal", platform="signal")

        poll_ticks: list[int] = []

        async def _poll_loop():
            with patch(
                "recap.daemon.recorder.detector.enrich_meeting_metadata",
                return_value={"title": "Call", "participants": [], "platform": "signal"},
            ):
                with patch(
                    "recap.daemon.recorder.detector.detect_meeting_windows",
                    side_effect=[
                        [meeting_a],       # first tick: new window A
                        [meeting_a, meeting_b],  # second tick: new window B
                        [meeting_a, meeting_b],  # third tick: nothing new
                    ],
                ):
                    for i in range(3):
                        await detector._poll_once()
                        poll_ticks.append(i)
                        await asyncio.sleep(0)

        await _poll_loop()

        # Drain any pending callback tasks so the slow ones finish.
        if detector._pending_signal_tasks:
            await asyncio.gather(
                *detector._pending_signal_tasks, return_exceptions=True,
            )

        # Both callbacks ran to completion while the poll loop continued.
        assert len(callback_hits) == 2
        assert {hit[0].hwnd for hit in callback_hits} == {1, 2}
        assert poll_ticks == [0, 1, 2]
        mock_recorder.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_detector_polls_concurrently_with_pending_signal_callback(self):
        """Poll loop progresses while a slow signal callback is still running.

        Stronger variant: the callback holds open on an asyncio.Event so we
        can *prove* the poll loop ticks while the callback is still pending
        (not yet completed).
        """
        mock_recorder = _make_recorder_mock()
        callback_started = asyncio.Event()
        release_callback = asyncio.Event()

        async def _slow_callback(meeting, enriched):
            callback_started.set()
            await release_callback.wait()  # hold the callback open

        config = self._make_config()
        detector = MeetingDetector(
            config=config,
            recorder=mock_recorder,
            on_signal_detected=_slow_callback,
        )

        meeting_a = MeetingWindow(hwnd=1, title="Signal", platform="signal")

        with patch(
            "recap.daemon.recorder.detector.enrich_meeting_metadata",
            return_value={"title": "Call", "participants": [], "platform": "signal"},
        ):
            with patch(
                "recap.daemon.recorder.detector.detect_meeting_windows",
                return_value=[meeting_a],
            ):
                # First poll spawns the callback task.
                await detector._poll_once()
                # Yield to let the task actually start.
                await callback_started.wait()

                # Now poll several more times. The callback is still
                # pending (blocked on the release event), but the polls
                # should complete promptly.
                extra_polls = 0
                for _ in range(3):
                    await detector._poll_once()
                    extra_polls += 1
                    await asyncio.sleep(0)

        # Callback is still pending — if _poll_once had awaited the
        # callback directly we would have deadlocked before getting here.
        assert extra_polls == 3
        assert not release_callback.is_set()
        assert len(detector._pending_signal_tasks) == 1

        # Release and drain.
        release_callback.set()
        if detector._pending_signal_tasks:
            await asyncio.gather(
                *detector._pending_signal_tasks, return_exceptions=True,
            )
        assert len(detector._pending_signal_tasks) == 0

    @pytest.mark.asyncio
    async def test_stop_cancels_pending_signal_callbacks(self):
        """``stop()`` should cancel and drain any in-flight callback tasks."""
        mock_recorder = _make_recorder_mock()
        started = asyncio.Event()
        cancelled_flag = {"seen": False}

        async def _never_returns(meeting, enriched):
            started.set()
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                cancelled_flag["seen"] = True
                raise

        config = self._make_config()
        detector = MeetingDetector(
            config=config,
            recorder=mock_recorder,
            on_signal_detected=_never_returns,
        )

        meeting = MeetingWindow(hwnd=1, title="Signal", platform="signal")
        with patch(
            "recap.daemon.recorder.detector.enrich_meeting_metadata",
            return_value={"title": "Call", "participants": [], "platform": "signal"},
        ):
            with patch(
                "recap.daemon.recorder.detector.detect_meeting_windows",
                return_value=[meeting],
            ):
                await detector._poll_once()

        await started.wait()
        assert len(detector._pending_signal_tasks) == 1

        await detector.stop()

        assert cancelled_flag["seen"] is True
        assert len(detector._pending_signal_tasks) == 0

    @pytest.mark.asyncio
    async def test_sync_callback_raises_type_error(self):
        """A non-awaitable callback should blow up clearly (mypy/runtime)."""
        mock_recorder = _make_recorder_mock()

        def _sync_cb(meeting, enriched):
            return None

        config = self._make_config()
        detector = MeetingDetector(
            config=config, recorder=mock_recorder, on_signal_detected=_sync_cb,
        )

        meeting = MeetingWindow(hwnd=1, title="Signal", platform="signal")
        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[meeting]):
            with patch(
                "recap.daemon.recorder.detector.enrich_meeting_metadata",
                return_value={"title": "Call", "participants": [], "platform": "signal"},
            ):
                with pytest.raises(TypeError):
                    await detector._poll_once()


class TestPromptStartedRecordingWindowMonitoring:
    """Prompt-started (Signal popup) recordings must participate in the
    ``is_window_alive`` stop-monitoring contract the same way auto-record
    and armed recordings do. Regression guard for the Signal-prompt path
    previously bypassing hard window-close monitoring.
    """

    def test_mark_active_recording_sets_recording_hwnd(self, mock_config):
        """mark_active_recording(hwnd) sets _recording_hwnd on the detector."""
        recorder = MagicMock()
        recorder.start = AsyncMock()
        recorder.stop = AsyncMock()
        recorder.is_recording = False

        detector = MeetingDetector(
            config=mock_config, recorder=recorder, on_signal_detected=None
        )
        assert detector._recording_hwnd is None

        detector.mark_active_recording(42)

        assert detector._recording_hwnd == 42

    @pytest.mark.asyncio
    async def test_stop_path_fires_for_prompt_started_recording(self, mock_config):
        """After mark_active_recording(hwnd), _poll_once auto-stops when
        is_window_alive(hwnd) returns False.

        Regression guard for the Signal-prompt path previously bypassing
        hard window-close monitoring (Codex P2 finding on Phase 7).
        """
        recorder = MagicMock()
        recorder.start = AsyncMock()
        recorder.stop = AsyncMock()
        recorder.is_recording = True  # simulate ongoing recording

        detector = MeetingDetector(
            config=mock_config, recorder=recorder, on_signal_detected=None
        )
        detector.mark_active_recording(12345)

        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[]):
            with patch("recap.daemon.recorder.detector.is_window_alive", return_value=False):
                await detector._poll_once()

        recorder.stop.assert_awaited()
        assert detector._recording_hwnd is None


class TestStopPathUIAResilience:
    """Stop-path must not be triggered by UIA-confirmation flaps.

    After Task 11 gated ``detect_meeting_windows`` behind UIA
    confirmation, Teams screen-sharing can transiently hide its Leave
    button and drop the hwnd from the detected set for a poll or two.
    The recording hwnd must survive that flap: only ``is_window_alive``
    (hard Windows signal) should tear down an active recording.
    """

    @pytest.mark.asyncio
    async def test_tracked_meeting_pruned_when_dropped_from_detected(self, mock_config):
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)

        meeting = MeetingWindow(hwnd=1, title="Sprint | Microsoft Teams", platform="teams")
        # First poll: meeting visible, should be tracked.
        with patch(
            "recap.daemon.recorder.detector.detect_meeting_windows",
            return_value=[meeting],
        ):
            with patch(
                "recap.daemon.recorder.detector.enrich_meeting_metadata",
                return_value={"title": "Sprint", "participants": [], "platform": "teams"},
            ):
                await detector._poll_once()
        assert 1 in detector._tracked_meetings

        # Second poll: meeting no longer detected. Since the detector
        # is NOT recording this hwnd, the prune branch removes it.
        mock_recorder.is_recording = True  # unrelated recording
        detector._recording_hwnd = 99  # different, not 1
        with patch(
            "recap.daemon.recorder.detector.detect_meeting_windows",
            return_value=[],
        ):
            await detector._poll_once()
        assert 1 not in detector._tracked_meetings

    @pytest.mark.asyncio
    async def test_stop_path_ignores_uia_false_negative(self, mock_config):
        """UIA flap (empty detect) with live hwnd must NOT stop recording."""
        mock_recorder = _make_recorder_mock()
        mock_recorder.is_recording = True
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)

        detector._recording_hwnd = 12345
        detector._tracked_meetings[12345] = MeetingWindow(
            hwnd=12345, title="Sprint | Microsoft Teams", platform="teams",
        )

        with patch(
            "recap.daemon.recorder.detector.detect_meeting_windows",
            return_value=[],  # UIA flap: nothing confirmed this tick
        ):
            with patch(
                "recap.daemon.recorder.detector.is_window_alive",
                return_value=True,  # but the hwnd is still alive
            ):
                with patch(
                    "recap.daemon.recorder.detector.enrich_meeting_metadata",
                ):
                    await detector._poll_once()

        mock_recorder.stop.assert_not_called()
        assert detector._recording_hwnd == 12345

    @pytest.mark.asyncio
    async def test_recording_hwnd_survives_uia_flap_during_recording(self, mock_config):
        """``_recording_hwnd`` must remain in ``_tracked_meetings`` across a flap."""
        mock_recorder = _make_recorder_mock()
        mock_recorder.is_recording = True
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)

        detector._recording_hwnd = 12345
        detector._tracked_meetings[12345] = MeetingWindow(
            hwnd=12345, title="Sprint | Microsoft Teams", platform="teams",
        )

        with patch(
            "recap.daemon.recorder.detector.detect_meeting_windows",
            return_value=[],
        ):
            with patch(
                "recap.daemon.recorder.detector.is_window_alive",
                return_value=True,
            ):
                with patch(
                    "recap.daemon.recorder.detector.enrich_meeting_metadata",
                ):
                    await detector._poll_once()

        assert 12345 in detector._tracked_meetings

    @pytest.mark.asyncio
    async def test_no_retrigger_after_recording_stops_if_hwnd_still_tracked(self, mock_config):
        """A tracked hwnd should not retrigger ``start`` after a stop.

        Scenario: recording has been stopped (is_recording=False), but the
        hwnd is still in ``_tracked_meetings`` and still appears in
        ``detect_meeting_windows``. The "already tracking" guard must
        prevent a concurrent retrigger.
        """
        mock_recorder = _make_recorder_mock()
        mock_recorder.is_recording = False
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)

        meeting = MeetingWindow(hwnd=1, title="Sprint | Microsoft Teams", platform="teams")
        detector._tracked_meetings[1] = meeting

        with patch(
            "recap.daemon.recorder.detector.detect_meeting_windows",
            return_value=[meeting],
        ):
            with patch(
                "recap.daemon.recorder.detector.enrich_meeting_metadata",
                return_value={"title": "Sprint", "participants": [], "platform": "teams"},
            ):
                await detector._poll_once()

        mock_recorder.start.assert_not_called()


class TestStopSealsPollTaskUnwind:
    """``stop()`` must await the cancelled poll task so any late
    ``create_task`` inside its finally/except block lands in the
    ``_pending_signal_tasks`` set before we drain it.
    """

    @pytest.mark.asyncio
    async def test_stop_waits_for_poll_task_unwind(self):
        mock_recorder = _make_recorder_mock()
        config = MagicMock()
        config.detection.teams.enabled = False
        config.detection.zoom.enabled = False
        config.detection.signal.enabled = False
        config.known_contacts = []

        detector = MeetingDetector(config=config, recorder=mock_recorder)

        started = asyncio.Event()
        late_task_seen = asyncio.Event()

        async def _late_awaitable():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                late_task_seen.set()
                raise

        async def _poll_body():
            """Simulate a poll body: awaits forever, and on cancellation
            schedules a late signal-callback task the same way
            ``_poll_once`` would if it raced with stop().
            """
            started.set()
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                # Register a late task inside the cancellation handler.
                task = asyncio.create_task(
                    _late_awaitable(), name="signal-callback",
                )
                detector._pending_signal_tasks.add(task)
                task.add_done_callback(detector._on_signal_task_done)
                raise

        loop = asyncio.get_event_loop()
        detector._poll_task = loop.create_task(_poll_body())
        await started.wait()

        # The late task does not exist yet.
        assert len(detector._pending_signal_tasks) == 0

        await detector.stop()

        # After stop: the unwind ran, registered the late task, stop
        # then snapshotted it and cancelled it.
        assert late_task_seen.is_set()
        assert len(detector._pending_signal_tasks) == 0


class TestOrgSubfolderResolution:
    """``_find_calendar_note`` should resolve the org subfolder via
    ``OrgConfig.resolve_subfolder`` instead of the deleted
    ``_org_subfolder`` hand-join helper (Phase 2 carryover).
    """

    @pytest.mark.asyncio
    async def test_find_calendar_note_uses_org_by_slug(self, tmp_path):
        """Detector should look up the org via ``org_by_slug`` + resolve_subfolder."""
        from recap.daemon.config import DaemonConfig, OrgConfig

        vault = tmp_path / "vault"
        vault.mkdir()
        # Simulate an org with a non-trivial subfolder path; the detector
        # must look at org.subfolder, not hand-join the slug.
        org = OrgConfig(name="acme", subfolder="Work/Acme", default=True)
        config = DaemonConfig(
            vault_path=vault,
            recordings_path=tmp_path / "recordings",
            _orgs=[org],
        )
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=config, recorder=mock_recorder)

        # find_note_by_event_id will be called with the resolved meetings dir.
        captured = {}

        def _fake_find_note(event_id, meetings_dir, *, vault_path, event_index):
            captured["meetings_dir"] = meetings_dir
            captured["vault_path"] = vault_path
            return None  # don't care about return here

        import recap.daemon.calendar.sync as sync_module
        with patch.object(sync_module, "find_note_by_event_id", _fake_find_note):
            result = detector._find_calendar_note("acme", "evt-1")

        assert result == ""  # no note found
        assert captured["meetings_dir"] == vault / "Work" / "Acme" / "Meetings"
        assert captured["vault_path"] == vault

    @pytest.mark.asyncio
    async def test_find_calendar_note_falls_back_to_default_org(self, tmp_path):
        """Unknown slug should fall back to the default org's subfolder."""
        from recap.daemon.config import DaemonConfig, OrgConfig

        vault = tmp_path / "vault"
        vault.mkdir()
        default_org = OrgConfig(name="personal", subfolder="Personal", default=True)
        config = DaemonConfig(
            vault_path=vault,
            recordings_path=tmp_path / "recordings",
            _orgs=[default_org],
        )
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=config, recorder=mock_recorder)

        captured = {}

        def _fake_find_note(event_id, meetings_dir, *, vault_path, event_index):
            captured["meetings_dir"] = meetings_dir
            return None

        import recap.daemon.calendar.sync as sync_module
        with patch.object(sync_module, "find_note_by_event_id", _fake_find_note):
            detector._find_calendar_note("unknown-slug", "evt-1")

        assert captured["meetings_dir"] == vault / "Personal" / "Meetings"

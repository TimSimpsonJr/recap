"""Tests for detection polling loop."""
import asyncio
import re
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch, AsyncMock
from recap.daemon.recorder.detector import MeetingDetector
from recap.daemon.recorder.detection import MeetingWindow
from recap.models import Participant


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
        # Unscheduled synthesis (Task 3) overrides the enriched window title
        # with the platform label when there's no calendar event and no
        # pre-existing note. The window-derived "Sprint" is intentionally
        # replaced by "Teams call" to avoid PII leaking into filenames.
        assert kwargs["metadata"].title == "Teams call"
        assert kwargs["metadata"].event_id is not None
        assert kwargs["metadata"].event_id.startswith("unscheduled:")

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


# ---------------------------------------------------------------------------
# _resolve_org_and_subfolder helper (Task 2 for unscheduled-meetings)
# ---------------------------------------------------------------------------


def _make_detector_with_org(tmp_path):
    """Factory: minimal detector where 'acme' org resolves to a subfolder."""
    org_cfg = Mock()
    org_cfg.slug = "acme"
    org_cfg.resolve_subfolder = lambda vault: vault / "Acme"

    config = Mock()
    config.vault_path = str(tmp_path)
    config.org_by_slug = lambda slug: org_cfg if slug == "acme" else None
    config.default_org = org_cfg

    recorder = Mock()
    return MeetingDetector(config=config, recorder=recorder)


def test_resolve_org_and_subfolder_returns_tuple(tmp_path):
    """Helper returns (OrgConfig, resolved-subfolder-path)."""
    detector = _make_detector_with_org(tmp_path)
    org_cfg, subfolder = detector._resolve_org_and_subfolder("acme")
    assert org_cfg.slug == "acme"
    assert subfolder == tmp_path / "Acme"


def test_resolve_org_and_subfolder_returns_none_when_no_match(tmp_path):
    """Unknown slug + no default returns (None, None)."""
    config = Mock()
    config.vault_path = str(tmp_path)
    config.org_by_slug = lambda slug: None
    config.default_org = None
    detector = MeetingDetector(config=config, recorder=Mock())
    assert detector._resolve_org_and_subfolder("nonexistent") == (None, None)


# ---------------------------------------------------------------------------
# _build_recording_metadata synthesis (Task 3 for unscheduled-meetings)
# ---------------------------------------------------------------------------


def test_build_recording_metadata_synthesizes_unscheduled_identity(tmp_path, monkeypatch):
    """No calendar event + no existing note -> synthetic id + precomputed path."""
    class _FakeDatetime:
        @staticmethod
        def now(tz=None):
            # Simulate a machine where the local wall-clock is 2026-04-22 14:30.
            # datetime.now() returns naive local; .astimezone() picks up host tz.
            if tz is None:
                return datetime(2026, 4, 22, 14, 30, 0)  # naive, represents local wall-clock
            return datetime(2026, 4, 22, 14, 30, 0, tzinfo=tz)

    import recap.daemon.recorder.detector as det_mod
    monkeypatch.setattr(det_mod, "datetime", _FakeDatetime)

    detector = _make_detector_with_org(tmp_path)
    (tmp_path / "Acme" / "Meetings").mkdir(parents=True)

    metadata = detector._build_recording_metadata(
        org="acme",
        title="Whatever window said",
        platform="teams",
        participants=[],
        meeting_link="",
        event_id=None,
    )

    assert metadata.event_id is not None
    assert re.fullmatch(r"unscheduled:[0-9a-f]{32}", metadata.event_id)
    assert metadata.note_path == "Acme/Meetings/2026-04-22 1430 - Teams call.md"
    assert metadata.recording_started_at is not None
    assert metadata.title == "Teams call"
    assert metadata.participants == []
    assert metadata.meeting_link == ""
    assert metadata.calendar_source is None
    assert metadata.platform == "teams"
    assert metadata.date == "2026-04-22"


def test_build_recording_metadata_with_event_id_keeps_calendar_path(tmp_path, monkeypatch):
    """With an event_id, no synthesis happens (scheduled path unchanged)."""
    detector = _make_detector_with_org(tmp_path)
    metadata = detector._build_recording_metadata(
        org="acme", title="Sprint Planning", platform="teams",
        participants=[Participant(name="Alice")],
        meeting_link="https://teams.example/x",
        event_id="real-calendar-event-id-123",
    )
    assert metadata.event_id == "real-calendar-event-id-123"
    assert not metadata.event_id.startswith("unscheduled:")
    assert metadata.title == "Sprint Planning"
    assert metadata.recording_started_at is None


def test_build_recording_metadata_platform_label_map(tmp_path, monkeypatch):
    """Each known platform gets its 'X call' label; unknown falls back to Titlecase + ' call'."""
    import recap.daemon.recorder.detector as det_mod

    class _FakeDatetime:
        @staticmethod
        def now(tz=None):
            if tz is None:
                return datetime(2026, 4, 22, 9, 7, 0)
            return datetime(2026, 4, 22, 9, 7, 0, tzinfo=tz)
    monkeypatch.setattr(det_mod, "datetime", _FakeDatetime)

    detector = _make_detector_with_org(tmp_path)
    (tmp_path / "Acme" / "Meetings").mkdir(parents=True)

    for platform, label in [("teams", "Teams call"), ("zoom", "Zoom call"),
                             ("signal", "Signal call")]:
        m = detector._build_recording_metadata(
            org="acme", title="", platform=platform,
            participants=[], meeting_link="", event_id=None,
        )
        assert m.title == label
        assert f"- {label}.md" in m.note_path


def test_build_recording_metadata_collision_appends_suffix(tmp_path, monkeypatch):
    """Second same-minute Teams call gets '(2)' suffix."""
    import recap.daemon.recorder.detector as det_mod

    class _FakeDatetime:
        @staticmethod
        def now(tz=None):
            if tz is None:
                return datetime(2026, 4, 22, 14, 30, 0)
            return datetime(2026, 4, 22, 14, 30, 0, tzinfo=tz)
    monkeypatch.setattr(det_mod, "datetime", _FakeDatetime)

    detector = _make_detector_with_org(tmp_path)
    meetings_dir = tmp_path / "Acme" / "Meetings"
    meetings_dir.mkdir(parents=True)
    (meetings_dir / "2026-04-22 1430 - Teams call.md").write_text("stub")

    metadata = detector._build_recording_metadata(
        org="acme", title="", platform="teams",
        participants=[], meeting_link="", event_id=None,
    )
    assert metadata.note_path == "Acme/Meetings/2026-04-22 1430 - Teams call (2).md"


def test_build_recording_metadata_collision_escalates_to_seconds(tmp_path, monkeypatch):
    """9 pre-existing suffixes -> falls through to HHMMSS timestamp."""
    import recap.daemon.recorder.detector as det_mod

    class _FakeDatetime:
        @staticmethod
        def now(tz=None):
            if tz is None:
                return datetime(2026, 4, 22, 14, 30, 45)
            return datetime(2026, 4, 22, 14, 30, 45, tzinfo=tz)
    monkeypatch.setattr(det_mod, "datetime", _FakeDatetime)

    detector = _make_detector_with_org(tmp_path)
    meetings_dir = tmp_path / "Acme" / "Meetings"
    meetings_dir.mkdir(parents=True)
    (meetings_dir / "2026-04-22 1430 - Teams call.md").write_text("stub")
    for n in range(2, 10):
        (meetings_dir / f"2026-04-22 1430 - Teams call ({n}).md").write_text("stub")

    metadata = detector._build_recording_metadata(
        org="acme", title="", platform="teams",
        participants=[], meeting_link="", event_id=None,
    )
    assert metadata.note_path == "Acme/Meetings/2026-04-22 143045 - Teams call.md"


def test_build_recording_metadata_unknown_platform_label_fallback(tmp_path, monkeypatch):
    """Platform not in _PLATFORM_LABELS uses Titlecase fallback."""
    import recap.daemon.recorder.detector as det_mod

    class _FakeDatetime:
        @staticmethod
        def now(tz=None):
            if tz is None:
                return datetime(2026, 4, 22, 10, 0, 0)
            return datetime(2026, 4, 22, 10, 0, 0, tzinfo=tz)
    monkeypatch.setattr(det_mod, "datetime", _FakeDatetime)

    detector = _make_detector_with_org(tmp_path)
    (tmp_path / "Acme" / "Meetings").mkdir(parents=True)

    metadata = detector._build_recording_metadata(
        org="acme", title="", platform="meet",
        participants=[], meeting_link="", event_id=None,
    )
    assert metadata.title == "Meet call"
    assert metadata.note_path == "Acme/Meetings/2026-04-22 1000 - Meet call.md"


def test_extension_detection_path_synthesizes_unscheduled(tmp_path, monkeypatch):
    """`_recording_metadata_from_enriched` inherits synthesis behavior."""
    import recap.daemon.recorder.detector as det_mod

    class _FakeDatetime:
        @staticmethod
        def now(tz=None):
            if tz is None:
                return datetime(2026, 4, 22, 16, 15, 0)
            return datetime(2026, 4, 22, 16, 15, 0, tzinfo=tz)
    monkeypatch.setattr(det_mod, "datetime", _FakeDatetime)

    detector = _make_detector_with_org(tmp_path)
    (tmp_path / "Acme" / "Meetings").mkdir(parents=True)

    metadata = detector._recording_metadata_from_enriched(
        "acme",
        {"title": "Browser Meeting", "participants": [], "platform": "zoom"},
        meeting_link="https://zoom.example/42",
        event_id=None,
    )
    assert metadata.event_id is not None
    assert metadata.event_id.startswith("unscheduled:")
    assert metadata.title == "Zoom call"
    assert metadata.note_path == "Acme/Meetings/2026-04-22 1615 - Zoom call.md"
    assert metadata.meeting_link == "https://zoom.example/42"
    assert metadata.recording_started_at is not None
    # Belt-and-braces: the captured instant is timezone-aware.
    assert metadata.recording_started_at.tzinfo is not None


class TestRosterSessionLifecycle:
    """Session begin/end contract for the ParticipantRoster (#29)."""

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

    def test_begin_creates_fresh_roster(self, mock_config):
        detector = MeetingDetector(config=mock_config, recorder=_make_recorder_mock())
        detector._begin_roster_session()
        assert detector._active_roster is not None
        assert detector._active_roster.current() == []

    def test_begin_seeds_from_initial_names(self, mock_config):
        detector = MeetingDetector(config=mock_config, recorder=_make_recorder_mock())
        detector._begin_roster_session(
            initial_names=["Alice", "Bob"],
            initial_source="teams_uia_detection",
        )
        assert detector._active_roster.current() == ["Alice", "Bob"]

    def test_begin_registers_both_recorder_hooks(self, mock_config):
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        detector._begin_roster_session()
        assert mock_recorder.on_before_finalize is not None
        assert mock_recorder.on_after_stop is not None

    def test_begin_stores_tab_id_and_browser_platform(self, mock_config):
        detector = MeetingDetector(config=mock_config, recorder=_make_recorder_mock())
        detector._begin_roster_session(tab_id=42, browser_platform="google_meet")
        assert detector._extension_recording_tab_id == 42
        assert detector._current_browser_platform == "google_meet"

    def test_end_clears_all_session_state(self, mock_config):
        detector = MeetingDetector(config=mock_config, recorder=_make_recorder_mock())
        detector._begin_roster_session(tab_id=42, browser_platform="google_meet")
        detector._polls_since_roster_refresh = 7
        detector._recording_hwnd = 999  # simulate an hwnd-based recording having set this
        detector._end_roster_session()
        assert detector._active_roster is None
        assert detector._extension_recording_tab_id is None
        assert detector._current_browser_platform is None
        assert detector._polls_since_roster_refresh == 0
        assert detector._recording_hwnd is None

    def test_end_registered_as_on_after_stop_hook(self, mock_config):
        """_begin_roster_session must register _end_roster_session as
        the recorder's on_after_stop hook, so every stop path triggers
        cleanup — not just detector-initiated stops."""
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        detector._begin_roster_session(tab_id=5)
        # Simulate the recorder calling on_after_stop (as it does at end of stop()).
        mock_recorder.on_after_stop()
        assert detector._active_roster is None
        assert detector._extension_recording_tab_id is None

    @pytest.mark.asyncio
    async def test_end_clears_recording_hwnd_prevents_cross_session_contamination(
        self, mock_config,
    ):
        """Regression test: a prior hwnd-based recording whose window stays
        open after stop (e.g., API/silence/duration stop while Zoom client
        keeps running) must not leak its hwnd into the next recording's
        Zoom UIA periodic refresh or stop-monitoring. Without clearing
        _recording_hwnd in _end_roster_session, a later browser or manual
        recording would inherit the stale hwnd and harvest participants
        from the wrong meeting. Refs Codex review of commit 631740d."""
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)

        # Session 1: hwnd-based Zoom recording, ends via API/silence/etc
        # (not via window-closed path — so the inline clear at _poll_once
        # doesn't run).
        detector._tracked_meetings[500] = MeetingWindow(
            hwnd=500, title="Zoom Meeting", platform="zoom",
        )
        detector._recording_hwnd = 500
        detector._begin_roster_session()
        # Simulate recorder.stop() firing on_after_stop (as API path would).
        mock_recorder.on_after_stop()

        # Session 1 teardown must fully clear hwnd.
        assert detector._recording_hwnd is None, (
            "Stale _recording_hwnd from session 1 would contaminate session 2"
        )

        # Session 2: browser recording — does NOT set _recording_hwnd.
        detector._begin_roster_session(tab_id=77, browser_platform="google_meet")
        # _recording_hwnd must still be None — no leak from session 1.
        assert detector._recording_hwnd is None


class TestStartPathsUseRoster:
    """Every recorder.start() call site must arm a roster session. #29."""

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

    @pytest.mark.asyncio
    async def test_auto_record_path_primes_roster_with_enriched_participants(self, mock_config):
        """Teams auto-record path: enriched["participants"] seeds the roster."""
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        meeting = MeetingWindow(hwnd=100, title="Standup | Microsoft Teams", platform="teams")
        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[meeting]):
            with patch(
                "recap.daemon.recorder.detector.enrich_meeting_metadata",
                return_value={"title": "Standup", "participants": ["Alice", "Bob"], "platform": "teams"},
            ):
                await detector._poll_once()
        assert detector._active_roster is not None
        assert detector._active_roster.current() == ["Alice", "Bob"]

    @pytest.mark.asyncio
    async def test_auto_record_zoom_initial_empty_roster(self, mock_config):
        """Zoom auto-record: no UIA enrichment yet, so initial roster is empty."""
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        meeting = MeetingWindow(hwnd=200, title="Zoom Meeting", platform="zoom")
        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[meeting]):
            with patch(
                "recap.daemon.recorder.detector.enrich_meeting_metadata",
                return_value={"title": "Zoom Meeting", "participants": [], "platform": "zoom"},
            ):
                await detector._poll_once()
        assert detector._active_roster is not None
        assert detector._active_roster.current() == []

    @pytest.mark.asyncio
    async def test_begin_session_only_after_successful_start(self, mock_config):
        """Recorder.start() raising must NOT leak detector session state."""
        mock_recorder = _make_recorder_mock()
        mock_recorder.start = AsyncMock(side_effect=RuntimeError("start failed"))
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        meeting = MeetingWindow(hwnd=300, title="Zoom Meeting", platform="zoom")
        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[meeting]):
            with patch(
                "recap.daemon.recorder.detector.enrich_meeting_metadata",
                return_value={"title": "Zoom Meeting", "participants": [], "platform": "zoom"},
            ):
                try:
                    await detector._poll_once()
                except Exception:
                    pass
        # Failed start must not leak session state.
        assert detector._active_roster is None
        assert detector._extension_recording_tab_id is None

    @pytest.mark.asyncio
    async def test_browser_path_primes_tab_id_and_browser_platform(self, mock_config):
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        await detector.handle_extension_meeting_detected(
            platform="google_meet",
            url="https://meet.google.com/abc-defg-hij",
            title="Quick Call",
            tab_id=77,
        )
        assert detector._extension_recording_tab_id == 77
        assert detector._current_browser_platform == "google_meet"
        assert detector._active_roster is not None

    @pytest.mark.asyncio
    async def test_signal_mark_active_recording_begins_session(self, mock_config):
        """Signal popup acceptance calls detector.mark_active_recording(hwnd),
        which must also arm an (empty) roster session — otherwise stale hooks
        from a previous recording could fire at Signal's stop time."""
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        detector.mark_active_recording(hwnd=555)
        assert detector._active_roster is not None
        assert detector._active_roster.current() == []

    @pytest.mark.asyncio
    async def test_end_session_clears_recorder_hooks(self, mock_config):
        """_end_roster_session must clear recorder.on_before_finalize and
        on_after_stop to None, so a subsequent manual recording (tray/API
        start) that bypasses _begin_roster_session doesn't invoke stale
        roster.finalize from the previous session."""
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        detector._begin_roster_session()
        # Hooks are now set.
        assert mock_recorder.on_before_finalize is not None
        assert mock_recorder.on_after_stop is not None
        # End the session.
        detector._end_roster_session()
        # Hooks are cleared.
        assert mock_recorder.on_before_finalize is None
        assert mock_recorder.on_after_stop is None

    @pytest.mark.asyncio
    async def test_extension_ended_does_not_double_clear_tab_id(self, mock_config):
        """handle_extension_meeting_ended no longer sets _extension_recording_tab_id
        = None directly — cleanup happens via on_after_stop → _end_roster_session.
        Verify the direct assignment was removed and the cleanup still works."""
        mock_recorder = _make_recorder_mock()
        mock_recorder.is_recording = True
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        # Simulate an extension-triggered recording is active.
        detector._begin_roster_session(tab_id=77, browser_platform="google_meet")
        # Call handle_extension_meeting_ended for matching tab.
        result = await detector.handle_extension_meeting_ended(tab_id=77)
        assert result is True
        # After stop() returns, on_after_stop (registered by _begin_roster_session)
        # fires — but in this mock test stop is an AsyncMock that doesn't invoke
        # the hook, so we simulate it explicitly to verify the cleanup path.
        # (The real integration would exercise this end-to-end.)
        mock_recorder.on_after_stop()
        assert detector._extension_recording_tab_id is None
        assert detector._active_roster is None


class TestZoomPeriodicRefresh:
    """Zoom UIA roster refresh every 30s during active Zoom recording. #29."""

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

    def _setup_active_zoom_recording(self, detector, hwnd=500):
        """Simulate the post-start state: recording an hwnd-based Zoom meeting.
        Sets is_recording=True, installs the MeetingWindow in tracked, arms
        the roster session."""
        detector._recorder.is_recording = True
        detector._tracked_meetings[hwnd] = MeetingWindow(
            hwnd=hwnd, title="Zoom Meeting", platform="zoom",
        )
        detector._recording_hwnd = hwnd
        detector._begin_roster_session()

    @pytest.mark.asyncio
    async def test_refresh_every_tenth_poll(self, mock_config):
        """Poll interval is 3s; refresh cadence is every 10 polls (30s)."""
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        self._setup_active_zoom_recording(detector)

        call_count = 0

        def fake_extract(hwnd):
            nonlocal call_count
            call_count += 1
            return ["Alice"]

        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[]):
            with patch("recap.daemon.recorder.detector.extract_zoom_participants", side_effect=fake_extract):
                with patch("recap.daemon.recorder.detector.is_window_alive", return_value=True):
                    for _ in range(10):
                        await detector._poll_once()

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_off_cycle_polls_skip_uia(self, mock_config):
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        self._setup_active_zoom_recording(detector)

        called: list[int] = []

        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[]):
            with patch(
                "recap.daemon.recorder.detector.extract_zoom_participants",
                side_effect=lambda hwnd: called.append(hwnd) or [],
            ):
                with patch("recap.daemon.recorder.detector.is_window_alive", return_value=True):
                    for _ in range(9):
                        await detector._poll_once()

        assert called == []

    @pytest.mark.asyncio
    async def test_refresh_merges_into_roster(self, mock_config):
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        self._setup_active_zoom_recording(detector)

        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[]):
            with patch(
                "recap.daemon.recorder.detector.extract_zoom_participants",
                return_value=["Dana", "Eve"],
            ):
                with patch("recap.daemon.recorder.detector.is_window_alive", return_value=True):
                    for _ in range(10):
                        await detector._poll_once()

        assert "Dana" in detector._active_roster.current()
        assert "Eve" in detector._active_roster.current()

    @pytest.mark.asyncio
    async def test_refresh_skipped_when_not_recording(self, mock_config):
        mock_recorder = _make_recorder_mock()
        mock_recorder.is_recording = False
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)

        called: list[int] = []

        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[]):
            with patch(
                "recap.daemon.recorder.detector.extract_zoom_participants",
                side_effect=lambda hwnd: called.append(hwnd),
            ):
                for _ in range(20):
                    await detector._poll_once()

        assert called == []

    @pytest.mark.asyncio
    async def test_refresh_skipped_for_non_zoom_platform(self, mock_config):
        """Teams stays one-shot per issue non-goal. Signal has no hwnd tracked."""
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        # Simulate active Teams recording (hwnd-based, platform=teams).
        detector._recorder.is_recording = True
        detector._tracked_meetings[600] = MeetingWindow(
            hwnd=600, title="Standup | Microsoft Teams", platform="teams",
        )
        detector._recording_hwnd = 600
        detector._begin_roster_session()

        called: list[int] = []

        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[]):
            with patch(
                "recap.daemon.recorder.detector.extract_zoom_participants",
                side_effect=lambda hwnd: called.append(hwnd),
            ):
                with patch("recap.daemon.recorder.detector.is_window_alive", return_value=True):
                    for _ in range(10):
                        await detector._poll_once()

        assert called == []

    @pytest.mark.asyncio
    async def test_refresh_skipped_when_extract_returns_none(self, mock_config):
        """When extract_zoom_participants returns None (UIA failure), no merge."""
        mock_recorder = _make_recorder_mock()
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        self._setup_active_zoom_recording(detector)

        with patch("recap.daemon.recorder.detector.detect_meeting_windows", return_value=[]):
            with patch(
                "recap.daemon.recorder.detector.extract_zoom_participants",
                return_value=None,
            ):
                with patch("recap.daemon.recorder.detector.is_window_alive", return_value=True):
                    for _ in range(10):
                        await detector._poll_once()

        # Roster remains empty since None -> skip merge.
        assert detector._active_roster.current() == []


class TestHandleExtensionParticipantsUpdated:
    """Detector handler for /api/meeting-participants-updated HTTP pushes. #29."""

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

    @pytest.mark.asyncio
    async def test_valid_payload_merges_into_roster(self, mock_config):
        mock_recorder = _make_recorder_mock()
        mock_recorder.is_recording = True
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        detector._begin_roster_session(tab_id=55, browser_platform="google_meet")
        accepted = await detector.handle_extension_participants_updated(
            tab_id=55, participants=["Fiona", "Greg"],
        )
        assert accepted is True
        assert "Fiona" in detector._active_roster.current()
        assert "Greg" in detector._active_roster.current()

    @pytest.mark.asyncio
    async def test_merge_source_uses_browser_platform(self, mock_config):
        mock_recorder = _make_recorder_mock()
        mock_recorder.is_recording = True
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        detector._begin_roster_session(tab_id=55, browser_platform="zoho_meet")
        await detector.handle_extension_participants_updated(
            tab_id=55, participants=["Henry"],
        )
        # Source tag should be "browser_dom_zoho_meet"
        assert "browser_dom_zoho_meet" in detector._active_roster._last_merge_per_source

    @pytest.mark.asyncio
    async def test_wrong_tab_id_returns_false(self, mock_config):
        mock_recorder = _make_recorder_mock()
        mock_recorder.is_recording = True
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        detector._begin_roster_session(tab_id=55, browser_platform="google_meet")
        accepted = await detector.handle_extension_participants_updated(
            tab_id=999, participants=["Alice"],
        )
        assert accepted is False
        assert detector._active_roster.current() == []

    @pytest.mark.asyncio
    async def test_no_active_roster_returns_false(self, mock_config):
        mock_recorder = _make_recorder_mock()
        mock_recorder.is_recording = False
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        accepted = await detector.handle_extension_participants_updated(
            tab_id=55, participants=["Alice"],
        )
        assert accepted is False

    @pytest.mark.asyncio
    async def test_not_recording_returns_false(self, mock_config):
        mock_recorder = _make_recorder_mock()
        mock_recorder.is_recording = False
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        # Even with a roster armed, if not recording we reject.
        detector._begin_roster_session(tab_id=55)
        accepted = await detector.handle_extension_participants_updated(
            tab_id=55, participants=["Alice"],
        )
        assert accepted is False

    @pytest.mark.asyncio
    async def test_none_tab_id_returns_false(self, mock_config):
        mock_recorder = _make_recorder_mock()
        mock_recorder.is_recording = True
        detector = MeetingDetector(config=mock_config, recorder=mock_recorder)
        detector._begin_roster_session(tab_id=55, browser_platform="google_meet")
        accepted = await detector.handle_extension_participants_updated(
            tab_id=None, participants=["Alice"],
        )
        assert accepted is False

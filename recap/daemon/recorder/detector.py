"""Meeting detection polling loop.

Periodically polls for active meeting windows and orchestrates
auto-recording or prompt callbacks based on per-platform config.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable

from recap.daemon.recorder.detection import MeetingWindow, detect_meeting_windows
from recap.daemon.recorder.enrichment import enrich_meeting_metadata

log = logging.getLogger(__name__)

# Platforms that the detector knows how to inspect.
_PLATFORMS = ("teams", "zoom", "signal")

_POLL_INTERVAL_SECONDS = 3
_ARMED_POLL_INTERVAL_SECONDS = 1
_ARM_TIMEOUT = timedelta(minutes=10)


class MeetingDetector:
    """Polls for meeting windows and triggers recording or prompts."""

    def __init__(
        self,
        config: object,
        recorder: object,
        on_signal_detected: Callable[..., object] | None = None,
    ) -> None:
        self._config = config
        self._recorder = recorder
        self._on_signal_detected = on_signal_detected
        self._tracked_meetings: dict[int, MeetingWindow] = {}
        self._poll_task: asyncio.Task[None] | None = None
        self._armed_event: dict | None = None
        self._recording_hwnd: int | None = None

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    @property
    def enabled_platforms(self) -> set[str]:
        """Return the set of platform names where detection is enabled."""
        result: set[str] = set()
        for name in _PLATFORMS:
            app_cfg = getattr(self._config.detection, name, None)
            if app_cfg is not None and app_cfg.enabled:
                result.add(name)
        return result

    def get_behavior(self, platform: str) -> str:
        """Return 'auto-record' or 'prompt' for *platform*."""
        return getattr(self._config.detection, platform).behavior  # type: ignore[no-any-return]

    def get_default_org(self, platform: str) -> str:
        """Return the configured default org for *platform*."""
        return getattr(self._config.detection, platform).default_org  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Calendar arming
    # ------------------------------------------------------------------

    @property
    def is_armed(self) -> bool:
        """Return True if the detector is armed for an upcoming event."""
        return self._armed_event is not None

    def arm_for_event(
        self,
        event_id: str,
        start_time: datetime,
        org: str,
        platform_hint: str | None = None,
    ) -> None:
        """Arm the detector for an upcoming calendar event."""
        self._armed_event = {
            "event_id": event_id,
            "start_time": start_time,
            "org": org,
            "platform_hint": platform_hint,
        }
        self._recorder.state_machine.arm(org)
        log.info("Armed for event %s (org=%s, start=%s)", event_id, org, start_time)

    def disarm(self) -> None:
        """Clear arming info and return to IDLE."""
        if self._armed_event is not None:
            log.info("Disarmed (was event %s)", self._armed_event["event_id"])
            self._armed_event = None
            self._recorder.state_machine.disarm()

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def _poll_once(self) -> None:
        """Execute a single detection cycle (synchronous)."""
        # --- Window monitoring: stop recording if window closed ---
        if self._recorder.is_recording and self._recording_hwnd is not None:
            current_windows = detect_meeting_windows(self.enabled_platforms)
            current_hwnds = {m.hwnd for m in current_windows}
            if self._recording_hwnd not in current_hwnds:
                log.info("Meeting window closed, stopping recording")
                self._recorder.stop()
                self._recording_hwnd = None
                # Update tracked meetings
                closed = set(self._tracked_meetings) - current_hwnds
                for hwnd in closed:
                    del self._tracked_meetings[hwnd]
                return

        # --- Arm timeout check ---
        if self._armed_event is not None:
            deadline = self._armed_event["start_time"] + _ARM_TIMEOUT
            if datetime.now() > deadline:
                log.info("Arm timeout reached, disarming")
                self.disarm()

        detected = detect_meeting_windows(self.enabled_platforms)
        detected_hwnds: set[int] = set()

        for meeting in detected:
            detected_hwnds.add(meeting.hwnd)

            if meeting.hwnd in self._tracked_meetings:
                continue  # already tracking this window

            # New meeting — enrich and act
            self._tracked_meetings[meeting.hwnd] = meeting
            enriched = enrich_meeting_metadata(
                meeting.hwnd,
                meeting.title,
                meeting.platform,
                self._config.known_contacts,
            )

            # Armed detection overrides platform behavior
            if self._armed_event is not None and not self._recorder.is_recording:
                org = self._armed_event["org"]
                log.info(
                    "Armed detection: auto-recording %s meeting (org=%s, event=%s)",
                    meeting.platform, org, self._armed_event["event_id"],
                )
                self._recorder.start(org)
                self._recording_hwnd = meeting.hwnd
                self._armed_event = None  # consumed
                continue

            behavior = self.get_behavior(meeting.platform)
            if behavior == "auto-record" and not self._recorder.is_recording:
                org = self.get_default_org(meeting.platform)
                log.info("Auto-recording %s meeting (org=%s)", meeting.platform, org)
                self._recorder.start(org)
                self._recording_hwnd = meeting.hwnd
            elif behavior == "prompt" and self._on_signal_detected is not None:
                self._on_signal_detected(meeting, enriched)

        # Clean up meetings whose windows have closed.
        closed = set(self._tracked_meetings) - detected_hwnds
        for hwnd in closed:
            log.debug("Meeting window closed: hwnd=%s", hwnd)
            del self._tracked_meetings[hwnd]

    # ------------------------------------------------------------------
    # Async loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        """Poll in a loop until cancelled."""
        while True:
            try:
                self._poll_once()
            except Exception:
                log.exception("Detection poll error")
            interval = (
                _ARMED_POLL_INTERVAL_SECONDS
                if self.is_armed
                else _POLL_INTERVAL_SECONDS
            )
            await asyncio.sleep(interval)

    def start(self) -> None:
        """Start the async polling loop."""
        loop = asyncio.get_event_loop()
        self._poll_task = loop.create_task(self._run())

    def stop(self) -> None:
        """Cancel the polling task."""
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None

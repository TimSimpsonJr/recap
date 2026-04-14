"""Meeting detection polling loop.

Periodically polls for active meeting windows and orchestrates
auto-recording or prompt callbacks based on per-platform config.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from recap.artifacts import RecordingMetadata, to_vault_relative
from recap.daemon.recorder.detection import MeetingWindow, detect_meeting_windows
from recap.daemon.recorder.enrichment import enrich_meeting_metadata
from recap.models import Participant

logger = logging.getLogger(__name__)

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
        self._extension_recording_tab_id: int | None = None

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
        app_cfg = getattr(self._config.detection, platform, None)
        if app_cfg is not None and app_cfg.default_org:
            return app_cfg.default_org  # type: ignore[no-any-return]
        default_org = getattr(self._config, "default_org", None)
        if default_org is not None and getattr(default_org, "name", None):
            return default_org.name  # type: ignore[no-any-return]
        return "default"

    def _org_subfolder(self, org: str) -> str:
        for org_config in getattr(self._config, "orgs", []):
            if org_config.name == org:
                return org_config.subfolder
        default_org = getattr(self._config, "default_org", None)
        if default_org is not None and getattr(default_org, "subfolder", None):
            return default_org.subfolder
        return org

    def _find_calendar_note(self, org: str, event_id: str | None) -> str:
        if not event_id:
            return ""
        try:
            from recap.daemon.calendar.sync import find_note_by_event_id

            vault_path = Path(self._config.vault_path)
            meetings_dir = (
                vault_path
                / self._org_subfolder(org)
                / "Meetings"
            )
            note = find_note_by_event_id(event_id, meetings_dir)
            if note is None:
                return ""
            return to_vault_relative(note, vault_path)
        except Exception:
            logger.debug("Failed to resolve calendar note for event %s", event_id, exc_info=True)
            return ""

    def _build_recording_metadata(
        self,
        *,
        org: str,
        title: str,
        platform: str,
        participants: list[Participant],
        meeting_link: str = "",
        event_id: str | None = None,
    ) -> RecordingMetadata:
        note_path = self._find_calendar_note(org, event_id)
        return RecordingMetadata(
            org=org,
            note_path=note_path,
            title=title.strip() or "Meeting",
            date=datetime.now().date().isoformat(),
            participants=participants,
            platform=platform,
            calendar_source=None,
            event_id=event_id,
            meeting_link=meeting_link,
        )

    def _participants_from_names(self, names: list[str]) -> list[Participant]:
        return [Participant(name=name) for name in names if name]

    def _recording_metadata_from_enriched(
        self,
        org: str,
        enriched: dict,
        *,
        meeting_link: str = "",
        event_id: str | None = None,
    ) -> RecordingMetadata:
        metadata = self._build_recording_metadata(
            org=org,
            title=enriched.get("title", "Meeting"),
            platform=enriched.get("platform", "unknown"),
            participants=self._participants_from_names(
                enriched.get("participants", []),
            ),
            meeting_link=meeting_link,
            event_id=event_id,
        )
        return metadata

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
        logger.info("Armed for event %s (org=%s, start=%s)", event_id, org, start_time)

    def disarm(self) -> None:
        """Clear arming info and return to IDLE."""
        if self._armed_event is not None:
            logger.info("Disarmed (was event %s)", self._armed_event["event_id"])
            self._armed_event = None
            self._recorder.state_machine.disarm()

    async def handle_extension_meeting_detected(
        self,
        *,
        platform: str,
        url: str,
        title: str,
        tab_id: int | None,
    ) -> bool:
        """Handle a browser-extension meeting signal."""
        if self._recorder.is_recording:
            return False

        org = (
            self._armed_event["org"]
            if self._armed_event is not None
            else self.get_default_org(platform)
        )
        metadata = self._recording_metadata_from_enriched(
            org,
            {
                "title": title or "Browser Meeting",
                "participants": [],
                "platform": platform,
            },
            meeting_link=url,
            event_id=self._armed_event["event_id"] if self._armed_event is not None else None,
        )

        await self._recorder.start(org, metadata=metadata, detected=True)
        self._extension_recording_tab_id = tab_id
        if self._armed_event is not None:
            self._armed_event = None
        logger.info("Extension-triggered recording started for %s", platform)
        return True

    async def handle_extension_meeting_ended(self, *, tab_id: int | None) -> bool:
        """Handle a browser-extension meeting-ended signal."""
        if (
            tab_id is None
            or tab_id != self._extension_recording_tab_id
            or not self._recorder.is_recording
        ):
            return False

        await self._recorder.stop()
        self._extension_recording_tab_id = None
        logger.info("Extension-triggered recording stopped for tab %s", tab_id)
        return True

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_once(self) -> None:
        """Execute a single detection cycle."""
        # --- Window monitoring: stop recording if window closed ---
        if self._recorder.is_recording and self._recording_hwnd is not None:
            current_windows = detect_meeting_windows(self.enabled_platforms)
            current_hwnds = {m.hwnd for m in current_windows}
            if self._recording_hwnd not in current_hwnds:
                logger.info("Meeting window closed, stopping recording")
                await self._recorder.stop()
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
                logger.info("Arm timeout reached, disarming")
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
                metadata = self._recording_metadata_from_enriched(
                    org,
                    enriched,
                    event_id=self._armed_event["event_id"],
                )
                logger.info(
                    "Armed detection: auto-recording %s meeting (org=%s, event=%s)",
                    meeting.platform, org, self._armed_event["event_id"],
                )
                await self._recorder.start(org, metadata=metadata, detected=True)
                self._recording_hwnd = meeting.hwnd
                self._armed_event = None  # consumed
                continue

            behavior = self.get_behavior(meeting.platform)
            if behavior == "auto-record" and not self._recorder.is_recording:
                org = self.get_default_org(meeting.platform)
                metadata = self._recording_metadata_from_enriched(org, enriched)
                logger.info("Auto-recording %s meeting (org=%s)", meeting.platform, org)
                await self._recorder.start(org, metadata=metadata, detected=True)
                self._recording_hwnd = meeting.hwnd
            elif behavior == "prompt" and self._on_signal_detected is not None:
                self._on_signal_detected(meeting, enriched)

        # Clean up meetings whose windows have closed.
        closed = set(self._tracked_meetings) - detected_hwnds
        for hwnd in closed:
            logger.debug("Meeting window closed: hwnd=%s", hwnd)
            del self._tracked_meetings[hwnd]

    # ------------------------------------------------------------------
    # Async loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        """Poll in a loop until cancelled."""
        while True:
            try:
                await self._poll_once()
            except Exception:
                logger.exception("Detection poll error")
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

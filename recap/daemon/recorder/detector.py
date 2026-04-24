"""Meeting detection polling loop.

Periodically polls for active meeting windows and orchestrates
auto-recording or prompt callbacks based on per-platform config.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from recap.artifacts import RecordingMetadata, to_vault_relative
from recap.daemon.recorder.call_state import extract_zoom_participants
from recap.daemon.recorder.detection import MeetingWindow, detect_meeting_windows, is_window_alive
from recap.daemon.recorder.enrichment import enrich_meeting_metadata, match_known_contacts
from recap.daemon.recorder.roster import ParticipantRoster
from recap.models import Participant

if TYPE_CHECKING:
    from recap.daemon.calendar.index import EventIndex
    from recap.daemon.config import DaemonConfig, OrgConfig
    from recap.daemon.recorder.recorder import Recorder

logger = logging.getLogger(__name__)

# Platforms that the detector knows how to inspect.
_PLATFORMS = ("teams", "zoom", "signal")

# Human-readable titles for unscheduled-meeting synthesis. The keys must
# mirror ``_PLATFORMS``; unknown platforms fall back to ``"{Titlecase} call"``.
_PLATFORM_LABELS = {
    "teams": "Teams call",
    "zoom": "Zoom call",
    "signal": "Signal call",
}

_POLL_INTERVAL_SECONDS = 3
_ARMED_POLL_INTERVAL_SECONDS = 1
_ARM_TIMEOUT = timedelta(minutes=10)
_ROSTER_REFRESH_POLLS = 10  # 10 polls * 3s base interval = 30s cadence


class MeetingDetector:
    """Polls for meeting windows and triggers recording or prompts."""

    def __init__(
        self,
        config: "DaemonConfig",
        recorder: "Recorder",
        on_signal_detected: Callable[..., Awaitable[None]] | None = None,
        event_index: "EventIndex | None" = None,
    ) -> None:
        self._config = config
        self._recorder = recorder
        self._on_signal_detected = on_signal_detected
        self._event_index = event_index
        self._tracked_meetings: dict[int, MeetingWindow] = {}
        self._poll_task: asyncio.Task[None] | None = None
        self._armed_event: dict | None = None
        self._recording_hwnd: int | None = None
        self._extension_recording_tab_id: int | None = None
        # #29: roster accumulator for the currently-active recording. None
        # when not recording. Set by _begin_roster_session() AFTER
        # recorder.start() succeeds; cleared by _end_roster_session().
        self._active_roster: ParticipantRoster | None = None
        self._polls_since_roster_refresh: int = 0
        # Captured at browser-path start so periodic refreshes can tag
        # the merge with "browser_dom_<platform>".
        self._current_browser_platform: str | None = None
        # In-flight signal-callback tasks (typically the Signal popup).
        # Spawning via ``create_task`` lets the poll loop keep ticking
        # while a callback is awaiting (e.g. the user is staring at the
        # popup). We retain hard references here so the tasks aren't
        # garbage-collected mid-flight.
        self._pending_signal_tasks: set[asyncio.Task[None]] = set()

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
        return getattr(self._config.detection, platform).behavior

    def get_default_org(self, platform: str) -> str:
        """Return the configured default org for *platform*."""
        app_cfg = getattr(self._config.detection, platform, None)
        if app_cfg is not None and app_cfg.default_org:
            return app_cfg.default_org
        default_org = getattr(self._config, "default_org", None)
        if default_org is not None and getattr(default_org, "name", None):
            return default_org.name
        return "default"

    def _resolve_org_config(self, org: str) -> "OrgConfig | None":
        """Return the ``OrgConfig`` for *org*, falling back to default_org.

        ``DaemonConfig`` always exposes ``org_by_slug``. The attribute check
        keeps the type-checker happy and guards against unusual test doubles.
        Returns ``None`` if neither the slug nor a default is configured.
        """
        by_slug = getattr(self._config, "org_by_slug", None)
        if callable(by_slug):
            matched = by_slug(org)
            if matched is not None:
                return matched
        return getattr(self._config, "default_org", None)

    def _resolve_org_and_subfolder(
        self, org: str,
    ) -> tuple["OrgConfig | None", "Path | None"]:
        """Return ``(OrgConfig, vault/subfolder)`` for *org*, or ``(None, None)``.

        Unscheduled-meeting synthesis needs both values from one lookup site.
        Scheduled paths already have ``note_path`` from the calendar sync layer
        and don't need this helper.
        """
        config = self._resolve_org_config(org)
        if config is None:
            return None, None
        vault_path = Path(self._config.vault_path)
        return config, config.resolve_subfolder(vault_path)

    def _find_calendar_note(self, org: str, event_id: str | None) -> str:
        if not event_id:
            return ""
        try:
            from recap.daemon.calendar.sync import find_note_by_event_id

            vault_path = Path(self._config.vault_path)
            org_config = self._resolve_org_config(org)
            if org_config is None:
                return ""
            meetings_dir = org_config.resolve_subfolder(vault_path) / "Meetings"
            note = find_note_by_event_id(
                event_id,
                meetings_dir,
                vault_path=vault_path,
                event_index=self._event_index,
            )
            if note is None:
                return ""
            return to_vault_relative(note, vault_path)
        except Exception:
            logger.debug("Failed to resolve calendar note for event %s", event_id, exc_info=True)
            return ""

    def _synthesize_unscheduled_identity(
        self, *, org: str, platform: str, captured: datetime,
    ) -> tuple[str, str, str]:
        """Return ``(event_id, note_path, title)`` for an unscheduled recording.

        ``captured`` is the single instant that seeds all three values so
        retries on a persisted sidecar stay stable.
        """
        event_id = f"unscheduled:{uuid.uuid4().hex}"
        title = _PLATFORM_LABELS.get(platform, f"{platform.title()} call")
        _, subfolder = self._resolve_org_and_subfolder(org)
        if subfolder is None:
            return event_id, "", title
        vault_path = Path(self._config.vault_path)
        meetings_dir = subfolder / "Meetings"
        base = f"{captured:%Y-%m-%d %H%M} - {title}"
        candidate = meetings_dir / f"{base}.md"

        for n in range(2, 10):
            if not candidate.exists():
                break
            candidate = meetings_dir / f"{base} ({n}).md"
        else:
            if candidate.exists():
                # Extreme fallback: full seconds. Still deterministic.
                candidate = meetings_dir / f"{captured:%Y-%m-%d %H%M%S} - {title}.md"

        return event_id, to_vault_relative(candidate, vault_path), title

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
        recording_started_at: datetime | None = None

        if not event_id and not note_path:
            captured = datetime.now().astimezone()
            event_id, note_path, title = self._synthesize_unscheduled_identity(
                org=org, platform=platform, captured=captured,
            )
            recording_started_at = captured
            date_str = captured.date().isoformat()
        else:
            date_str = datetime.now().date().isoformat()

        return RecordingMetadata(
            org=org,
            note_path=note_path,
            title=title.strip() or "Meeting",
            date=date_str,
            participants=participants,
            platform=platform,
            calendar_source=None,
            event_id=event_id,
            meeting_link=meeting_link,
            recording_started_at=recording_started_at,
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

    def on_config_reloaded(self, new_config: "DaemonConfig") -> None:
        """Update cached config reference after :meth:`Daemon.refresh_config`.

        Called by the daemon when ``known_contacts`` or other
        live-editable config fields change. Downstream callers
        (enrichment, periodic UIA refresh, browser participant merges)
        read ``self._config`` on their next access, so a simple rebind
        is all that's required.
        """
        self._config = new_config

    def mark_active_recording(self, hwnd: int) -> None:
        """Register a prompt-started recording's hwnd with the detector.

        Called by the Signal popup acceptance path so prompt-started recordings
        participate in the ``is_window_alive`` stop-monitoring contract the same
        way auto-record and armed recordings do. Without this, a Signal
        recording continues until silence/max-duration/manual stop even after
        the user closes the Signal window.

        Also arms an empty roster session so that stop-time finalization hooks
        fire correctly; Signal has no participant enrichment so the roster
        stays empty and no sidecar rewrite happens.
        """
        self._recording_hwnd = hwnd
        self._begin_roster_session()

    def _begin_roster_session(
        self,
        initial_names: Sequence[str] = (),
        initial_source: str | None = None,
        tab_id: int | None = None,
        browser_platform: str | None = None,
    ) -> None:
        """Arm a fresh roster and register stop hooks.

        MUST be called AFTER recorder.start() succeeds so a failed start
        cannot leak detector session state. Seeds the roster when the
        caller has a one-shot extraction (e.g. Teams UIA at detection),
        so finalize() is idempotent when no later merges happen.
        """
        roster = ParticipantRoster()
        if initial_names and initial_source:
            roster.merge(
                initial_source,
                list(initial_names),
                datetime.now().astimezone(),
            )
        self._active_roster = roster
        self._extension_recording_tab_id = tab_id
        self._current_browser_platform = browser_platform
        self._polls_since_roster_refresh = 0
        self._recorder.on_before_finalize = roster.finalize
        self._recorder.on_after_stop = self._end_roster_session

    def _end_roster_session(self) -> None:
        """Clear detector-owned session state and recorder hooks.

        Registered as Recorder.on_after_stop so it fires on every stop
        path — API, silence, duration, fatal, extension. Clearing the
        recorder hooks here prevents stale roster.finalize from a previous
        session firing on a subsequent manual recording (tray/API start)
        that bypasses _begin_roster_session.

        Also clears ``_recording_hwnd``: the existing stop-monitoring path
        only clears it when ``is_window_alive`` returns false, so stops
        triggered by other paths (API, silence, duration, fatal, extension)
        would leave it pointing at a possibly-still-alive window. The
        Zoom UIA periodic refresh and window-alive stop check both key
        off ``_recording_hwnd``, so a stale value lets a later recording
        harvest participants from the wrong meeting or stop when the old
        window closes.
        """
        self._active_roster = None
        self._extension_recording_tab_id = None
        self._current_browser_platform = None
        self._polls_since_roster_refresh = 0
        self._recording_hwnd = None
        self._recorder.on_before_finalize = None
        self._recorder.on_after_stop = None

    async def _refresh_roster_uia(self) -> None:
        """Platform-dispatched UIA roster refresh during active recording.

        v1 scope: Zoom only. Teams deliberately skipped per issue non-goal
        'don't change Teams enrichment.' Browser-platform recordings don't
        have a daemon-side hwnd to walk — their refresh comes over HTTP.
        """
        if self._active_roster is None or self._recording_hwnd is None:
            return
        meeting = self._tracked_meetings.get(self._recording_hwnd)
        if meeting is None or meeting.platform != "zoom":
            return
        names = extract_zoom_participants(self._recording_hwnd)
        if not names:
            return
        as_participants = [Participant(name=n) for n in names]
        matched = match_known_contacts(as_participants, self._config.known_contacts)
        matched_names = [p.name for p in matched]
        self._active_roster.merge(
            "zoom_uia_periodic",
            matched_names,
            datetime.now().astimezone(),
        )

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
        self._begin_roster_session(tab_id=tab_id, browser_platform=platform)
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
        # _extension_recording_tab_id cleared by _end_roster_session via Recorder.on_after_stop.
        logger.info("Extension-triggered recording stopped for tab %s", tab_id)
        return True

    async def handle_extension_participants_updated(
        self,
        *,
        tab_id: int | None,
        participants: list[str],
    ) -> bool:
        """Browser-extension hook for live participant roster refresh.

        Returns True if merged. Returns False (silent drop) for:
          - no active recording
          - no roster armed
          - tab_id missing or mismatched with the current extension recording
        """
        if (
            tab_id is None
            or tab_id != self._extension_recording_tab_id
            or self._active_roster is None
            or not self._recorder.is_recording
        ):
            return False
        platform = self._current_browser_platform or "unknown"
        source = f"browser_dom_{platform}"
        as_participants = [Participant(name=n) for n in participants]
        matched = match_known_contacts(as_participants, self._config.known_contacts)
        matched_names = [p.name for p in matched]
        self._active_roster.merge(
            source, matched_names, datetime.now().astimezone(),
        )
        return True

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_once(self) -> None:
        """Execute a single detection cycle."""
        # --- Stop-monitoring path: hard Windows signal only ---
        # We only stop the active recording when the OS confirms the
        # window is gone. Using ``detect_meeting_windows`` here would
        # conflate UIA-confirmation flaps (e.g. Teams hiding its Leave
        # button during screen share) with real window closure.
        if self._recorder.is_recording and self._recording_hwnd is not None:
            if not is_window_alive(self._recording_hwnd):
                logger.info("Meeting window closed, stopping recording")
                await self._recorder.stop()
                self._recording_hwnd = None

        # --- Arm timeout check ---
        if self._armed_event is not None:
            deadline = self._armed_event["start_time"] + _ARM_TIMEOUT
            if datetime.now() > deadline:
                logger.info("Arm timeout reached, disarming")
                self.disarm()

        # --- Detection path ---
        detected = detect_meeting_windows(self.enabled_platforms)
        detected_hwnds: set[int] = set()

        for meeting in detected:
            detected_hwnds.add(meeting.hwnd)

            if meeting.hwnd in self._tracked_meetings:
                continue  # already tracking this window

            if self._recorder.is_recording:
                continue  # don't start concurrent recordings

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
                initial_source = (
                    f"{meeting.platform}_uia_detection"
                    if enriched.get("participants")
                    else None
                )
                self._begin_roster_session(
                    initial_names=enriched.get("participants", ()),
                    initial_source=initial_source,
                )
                self._armed_event = None  # consumed
                continue

            behavior = self.get_behavior(meeting.platform)
            if behavior == "auto-record" and not self._recorder.is_recording:
                org = self.get_default_org(meeting.platform)
                metadata = self._recording_metadata_from_enriched(org, enriched)
                logger.info("Auto-recording %s meeting (org=%s)", meeting.platform, org)
                await self._recorder.start(org, metadata=metadata, detected=True)
                self._recording_hwnd = meeting.hwnd
                initial_source = (
                    f"{meeting.platform}_uia_detection"
                    if enriched.get("participants")
                    else None
                )
                self._begin_roster_session(
                    initial_names=enriched.get("participants", ()),
                    initial_source=initial_source,
                )
            elif behavior == "prompt" and self._on_signal_detected is not None:
                # Fire-and-track: run the callback as a concurrent task so
                # the poll loop continues ticking while a slow awaitable
                # (e.g. the Signal popup) is pending. See ``stop()`` for
                # cancellation / draining.
                task = asyncio.create_task(
                    self._on_signal_detected(meeting, enriched),
                    name="signal-callback",
                )
                self._pending_signal_tasks.add(task)
                task.add_done_callback(self._on_signal_task_done)

        # --- Periodic roster refresh for hwnd-based recordings (Zoom v1) ---
        if (
            self._recorder.is_recording
            and self._recording_hwnd is not None
            and self._active_roster is not None
        ):
            self._polls_since_roster_refresh += 1
            if self._polls_since_roster_refresh >= _ROSTER_REFRESH_POLLS:
                self._polls_since_roster_refresh = 0
                await self._refresh_roster_uia()

        # --- End-of-poll prune with active-recording protection ---
        # A UIA flap can make ``detect_meeting_windows`` briefly omit the
        # currently-recording window. Protect ``_recording_hwnd`` from
        # being pruned so the stop path stays the only way recording
        # ends via window loss. Only protect while actually recording;
        # a stale ``_recording_hwnd`` left over from a previous session
        # should not keep a closed window in the tracked set.
        stale = set(self._tracked_meetings) - detected_hwnds
        if self._recorder.is_recording and self._recording_hwnd is not None:
            stale.discard(self._recording_hwnd)
        for hwnd in stale:
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

    def _on_signal_task_done(self, task: asyncio.Task[None]) -> None:
        """Reap a finished signal callback task.

        Removes the task from the pending set so it can be GC'd, and logs
        any uncaught exception. Without this hook a callback that raised
        would just surface as a warning at event-loop close time.
        """
        self._pending_signal_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.exception("Signal callback raised", exc_info=exc)

    async def stop(self) -> None:
        """Cancel the polling task and drain any pending signal callbacks.

        Awaitable so the daemon's ``stop()`` can wait for in-flight
        callbacks (e.g. a Signal popup still up when the user quits) to
        cancel cleanly before we tear down the event loop.
        """
        if self._poll_task is not None:
            self._poll_task.cancel()
            # Await the cancellation so any ``finally`` / exception
            # handler inside the poll body gets to run (and register
            # late tasks in ``_pending_signal_tasks``) before we
            # snapshot the pending set below.
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

        # Cancel any in-flight signal callbacks and wait for them to
        # settle. ``return_exceptions=True`` so a misbehaving callback
        # can't block shutdown.
        if self._pending_signal_tasks:
            for task in list(self._pending_signal_tasks):
                task.cancel()
            await asyncio.gather(
                *self._pending_signal_tasks, return_exceptions=True,
            )
            self._pending_signal_tasks.clear()

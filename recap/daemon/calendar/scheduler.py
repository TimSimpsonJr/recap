"""Calendar sync scheduler — periodic sync loop with token refresh."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from collections.abc import Awaitable, Callable

from recap.daemon.calendar.sync import (
    CalendarEvent,
    find_note_by_event_id,
    should_update_note,
    update_calendar_note,
    write_calendar_note,
)
from recap.daemon.credentials import (
    get_credential,
    has_credential,
    store_credential,
)

if TYPE_CHECKING:
    from recap.daemon.calendar.index import EventIndex
    from recap.daemon.config import DaemonConfig
    from recap.daemon.recorder.detector import MeetingDetector

logger = logging.getLogger("recap.daemon.calendar.scheduler")

_FETCH_MODULES = {
    "zoho": "recap.daemon.calendar.zoho",
    "google": "recap.daemon.calendar.google",
}

_FETCH_FUNCTIONS = {
    "zoho": "fetch_zoho_events",
    "google": "fetch_google_events",
}


class CalendarSyncScheduler:
    """Periodically syncs calendar events to vault notes."""

    def __init__(
        self,
        config: DaemonConfig,
        vault_path: Path,
        detector: MeetingDetector | None = None,
        on_rename_queued: Callable[[int], Awaitable[None] | None] | None = None,
        event_index: "EventIndex | None" = None,
    ) -> None:
        self._config = config
        self._vault_path = vault_path
        self._detector = detector
        self._on_rename_queued = on_rename_queued
        self._event_index = event_index
        self._task: asyncio.Task[None] | None = None
        self._last_sync: datetime | None = None
        self._failure_start: dict[str, datetime] = {}

    @property
    def last_sync(self) -> datetime | None:
        """When the last successful sync completed."""
        return self._last_sync

    async def start(self) -> None:
        """Start the sync loop. Runs immediate sync if configured."""
        self._task = asyncio.get_event_loop().create_task(self._run())

    def stop(self) -> None:
        """Cancel the sync loop task."""
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        """Main loop: optional immediate sync, then periodic."""
        if self._config.calendar_sync.sync_on_startup:
            await self.sync()

        interval = self._config.calendar_sync.interval_minutes * 60
        while True:
            await asyncio.sleep(interval)
            await self.sync()

    async def sync(self) -> None:
        """Run a single calendar sync cycle across all configured providers.

        Providers whose config block sets ``enabled: false`` are skipped
        so users can pause sync from Settings without disconnecting
        OAuth. Providers with no config block at all retain the legacy
        behavior of being synced unconditionally.
        """
        all_events: list[CalendarEvent] = []

        for provider in ("zoho", "google"):
            provider_cfg = self._config.calendars.get(provider)
            if provider_cfg is not None and not provider_cfg.enabled:
                # Clear any stale failure tracking so a re-enable starts clean.
                self._failure_start.pop(provider, None)
                continue
            try:
                events = await self._sync_provider(provider)
                all_events.extend(events)
                # Clear failure tracking on success
                self._failure_start.pop(provider, None)
            except Exception:
                logger.exception("Calendar sync failed for provider %s", provider)
                self._track_failure(provider)

        synced = 0
        armed = 0
        queued_renames = 0
        rename_queue_path = self._vault_path / "_Recap" / ".recap" / "rename-queue.json"

        for event in all_events:
            try:
                org_config = self._config.org_by_slug(event.org)
                if org_config is None:
                    logger.warning(
                        "No OrgConfig for slug %s; skipping event %s",
                        event.org,
                        event.event_id,
                    )
                    continue

                action = should_update_note(
                    event.event_id,
                    self._vault_path,
                    org_config,
                    new_time=event.time,
                    new_participants=event.participants,
                    event_index=self._event_index,
                )

                if action == "create":
                    write_calendar_note(
                        event,
                        self._vault_path,
                        org_config,
                        event_index=self._event_index,
                    )
                    synced += 1
                elif action == "update":
                    meetings_dir = org_config.resolve_subfolder(self._vault_path) / "Meetings"
                    note = find_note_by_event_id(
                        event.event_id,
                        meetings_dir,
                        vault_path=self._vault_path,
                        event_index=self._event_index,
                    )
                    if note is not None:
                        queued_renames += update_calendar_note(
                            note,
                            new_time=event.time,
                            new_participants=event.participants,
                            rename_queue_path=rename_queue_path,
                            vault_path=self._vault_path,
                            org_config=org_config,
                        )
                        synced += 1
            except Exception:
                logger.exception(
                    "Failed to write/update note for event %s", event.event_id,
                )

        # Arm detector for upcoming events (within 30 minutes)
        if self._detector is not None:
            now = datetime.now()
            for event in all_events:
                try:
                    start_dt = self._parse_event_start(event)
                    if start_dt is None:
                        continue
                    delta = start_dt - now
                    if timedelta(0) <= delta <= timedelta(minutes=30):
                        self._detector.arm_for_event(
                            event.event_id, start_dt, event.org,
                        )
                        armed += 1
                except Exception:
                    logger.exception(
                        "Failed to arm for event %s", event.event_id,
                    )

        self._last_sync = datetime.now()
        if queued_renames > 0 and self._on_rename_queued is not None:
            try:
                maybe_awaitable = self._on_rename_queued(queued_renames)
                if asyncio.iscoroutine(maybe_awaitable):
                    await maybe_awaitable
            except Exception:
                logger.exception("Failed to publish rename queue notification")
        logger.info(
            "Calendar sync complete: %d events synced, %d armed, %d renames queued",
            synced, armed, queued_renames,
        )

    async def _sync_provider(self, provider: str) -> list[CalendarEvent]:
        """Fetch events from a single provider, handling token refresh."""
        access_token = get_credential(provider, "access_token")
        if not access_token:
            return []

        provider_config = self._config.calendars.get(provider)
        org = "personal"
        if provider_config:
            org = provider_config.org or provider_config.default_org or "personal"

        # Resolve calendar_id: config > credential store > "primary" for Google
        calendar_id = None
        if provider_config and provider_config.calendar_id:
            calendar_id = provider_config.calendar_id
        if not calendar_id:
            calendar_id = get_credential(provider, "calendar_id")
        if not calendar_id and provider == "google":
            calendar_id = "primary"
        if not calendar_id:
            logger.warning(
                "No calendar_id configured for %s — skipping sync. "
                "Set 'calendar-id' in the calendars.%s config section.",
                provider,
                provider,
            )
            return []

        today = datetime.now().strftime("%Y-%m-%dT00:00:00Z")
        end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59Z")

        events = await self._fetch_events(provider, access_token, calendar_id, today, end, org)

        # If we got an empty list, check if token might be expired by
        # attempting a refresh (the fetch functions return [] on 401)
        if not events and has_credential(provider, "refresh_token"):
            refreshed = await self._try_refresh(provider)
            if refreshed:
                new_token = get_credential(provider, "access_token")
                if new_token:
                    events = await self._fetch_events(
                        provider, new_token, calendar_id, today, end, org,
                    )

        return events

    async def _fetch_events(
        self,
        provider: str,
        access_token: str,
        calendar_id: str,
        start_date: str,
        end_date: str,
        org: str,
    ) -> list[CalendarEvent]:
        """Call the appropriate provider fetch function."""
        import importlib

        module = importlib.import_module(_FETCH_MODULES[provider])
        fetch_fn = getattr(module, _FETCH_FUNCTIONS[provider])
        return await fetch_fn(access_token, calendar_id, start_date, end_date, org)

    async def _try_refresh(self, provider: str) -> bool:
        """Attempt to refresh the access token. Returns True on success."""
        from recap.daemon.calendar.oauth import OAuthManager

        refresh_tok = get_credential(provider, "refresh_token")
        client_id = get_credential(provider, "client_id")
        client_secret = get_credential(provider, "client_secret")

        if not all([refresh_tok, client_id, client_secret]):
            return False

        try:
            mgr = OAuthManager(provider, client_id, client_secret)  # type: ignore[arg-type]
            tokens = mgr.refresh_token(refresh_tok)  # type: ignore[arg-type]
            store_credential(provider, "access_token", tokens["access_token"])
            if "refresh_token" in tokens:
                store_credential(provider, "refresh_token", tokens["refresh_token"])
            logger.info("Refreshed %s access token", provider)
            return True
        except Exception:
            logger.warning(
                "Failed to refresh %s token — calendar disconnected, re-authenticate",
                provider,
            )
            return False

    def _track_failure(self, provider: str) -> None:
        """Track continuous failures and warn after 1 hour."""
        from recap.daemon.notifications import notify

        now = datetime.now()
        if provider not in self._failure_start:
            self._failure_start[provider] = now

        elapsed = now - self._failure_start[provider]
        if elapsed >= timedelta(hours=1):
            notify(
                "Recap",
                f"Calendar sync for {provider} has been failing for over 1 hour.",
            )
            # Reset so we don't spam
            self._failure_start[provider] = now

    @staticmethod
    def _parse_event_start(event: CalendarEvent) -> datetime | None:
        """Parse event date + time into a datetime for arming."""
        if not event.date or not event.time:
            return None
        # time is like "14:00-15:00" — take the start
        start_time = event.time.split("-")[0].strip()
        try:
            return datetime.strptime(f"{event.date} {start_time}", "%Y-%m-%d %H:%M")
        except ValueError:
            return None

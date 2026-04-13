"""Tests for the calendar sync scheduler."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from recap.daemon.calendar.scheduler import CalendarSyncScheduler
from recap.daemon.calendar.sync import CalendarEvent
from recap.daemon.config import (
    CalendarProviderConfig,
    CalendarSyncConfig,
    DaemonConfig,
    DaemonPortConfig,
    DetectionConfig,
    LoggingConfig,
    PipelineConfig,
    RecordingConfig,
)


def _make_config(
    vault_path: Path,
    sync_on_startup: bool = False,
    interval_minutes: int = 15,
    calendars: dict | None = None,
) -> DaemonConfig:
    return DaemonConfig(
        vault_path=vault_path,
        recordings_path=vault_path / "recordings",
        calendar_sync=CalendarSyncConfig(
            interval_minutes=interval_minutes,
            sync_on_startup=sync_on_startup,
        ),
        calendars=calendars or {},
    )


def _make_event(
    event_id: str = "evt-1",
    title: str = "Standup",
    date: str = "2026-04-14",
    time: str = "09:00-09:30",
    org: str = "testorg",
) -> CalendarEvent:
    return CalendarEvent(
        event_id=event_id,
        title=title,
        date=date,
        time=time,
        participants=["Alice", "Bob"],
        calendar_source="google",
        org=org,
    )


class TestSchedulerInit:
    def test_initial_state(self, tmp_path):
        config = _make_config(tmp_path)
        scheduler = CalendarSyncScheduler(config, tmp_path)
        assert scheduler.last_sync is None

    def test_accepts_detector(self, tmp_path):
        config = _make_config(tmp_path)
        detector = MagicMock()
        scheduler = CalendarSyncScheduler(config, tmp_path, detector=detector)
        assert scheduler._detector is detector


class TestSchedulerSync:
    @pytest.mark.asyncio
    async def test_sync_creates_note(self, tmp_path):
        config = _make_config(
            tmp_path,
            calendars={"google": CalendarProviderConfig(org="testorg")},
        )
        scheduler = CalendarSyncScheduler(config, tmp_path)

        event = _make_event()
        with (
            patch.object(scheduler, "_sync_provider", new_callable=AsyncMock) as mock_sync,
        ):
            mock_sync.side_effect = lambda p: [event] if p == "google" else []
            await scheduler.sync()

        assert scheduler.last_sync is not None
        # Check that the note was created
        meetings_dir = tmp_path / "_Recap" / "Testorg" / "Meetings"
        assert meetings_dir.exists()
        notes = list(meetings_dir.glob("*.md"))
        assert len(notes) == 1
        assert "standup" in notes[0].name.lower()

    @pytest.mark.asyncio
    async def test_sync_skips_existing_unchanged_note(self, tmp_path):
        config = _make_config(tmp_path)
        scheduler = CalendarSyncScheduler(config, tmp_path)

        event = _make_event()
        with patch.object(scheduler, "_sync_provider", new_callable=AsyncMock) as mock_sync:
            mock_sync.side_effect = lambda p: [event] if p == "google" else []
            await scheduler.sync()
            await scheduler.sync()

        # Should still be only 1 note
        meetings_dir = tmp_path / "_Recap" / "Testorg" / "Meetings"
        notes = list(meetings_dir.glob("*.md"))
        assert len(notes) == 1

    @pytest.mark.asyncio
    async def test_sync_handles_provider_failure(self, tmp_path):
        config = _make_config(tmp_path)
        scheduler = CalendarSyncScheduler(config, tmp_path)

        with patch.object(scheduler, "_sync_provider", new_callable=AsyncMock) as mock_sync:
            mock_sync.side_effect = Exception("API down")
            await scheduler.sync()

        # Should not crash, last_sync still set
        assert scheduler.last_sync is not None

    @pytest.mark.asyncio
    async def test_sync_arms_upcoming_events(self, tmp_path):
        config = _make_config(tmp_path)
        detector = MagicMock()
        scheduler = CalendarSyncScheduler(config, tmp_path, detector=detector)

        # Create an event starting 15 minutes from now
        now = datetime.now()
        soon = now + timedelta(minutes=15)
        event = _make_event(
            date=soon.strftime("%Y-%m-%d"),
            time=f"{soon.strftime('%H:%M')}-{(soon + timedelta(hours=1)).strftime('%H:%M')}",
        )

        with patch.object(scheduler, "_sync_provider", new_callable=AsyncMock) as mock_sync:
            mock_sync.side_effect = lambda p: [event] if p == "google" else []
            await scheduler.sync()

        detector.arm_for_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_does_not_arm_far_events(self, tmp_path):
        config = _make_config(tmp_path)
        detector = MagicMock()
        scheduler = CalendarSyncScheduler(config, tmp_path, detector=detector)

        # Event 2 hours from now — should not arm
        now = datetime.now()
        later = now + timedelta(hours=2)
        event = _make_event(
            date=later.strftime("%Y-%m-%d"),
            time=f"{later.strftime('%H:%M')}-{(later + timedelta(hours=1)).strftime('%H:%M')}",
        )

        with patch.object(scheduler, "_sync_provider", new_callable=AsyncMock) as mock_sync:
            mock_sync.side_effect = lambda p: [event] if p == "google" else []
            await scheduler.sync()

        detector.arm_for_event.assert_not_called()


class TestSchedulerStartStop:
    @pytest.mark.asyncio
    async def test_start_creates_task(self, tmp_path):
        config = _make_config(tmp_path, sync_on_startup=False)
        scheduler = CalendarSyncScheduler(config, tmp_path)

        await scheduler.start()
        assert scheduler._task is not None
        scheduler.stop()
        assert scheduler._task is None

    @pytest.mark.asyncio
    async def test_stop_is_safe_when_not_started(self, tmp_path):
        config = _make_config(tmp_path)
        scheduler = CalendarSyncScheduler(config, tmp_path)
        scheduler.stop()  # Should not raise


class TestParseEventStart:
    def test_parses_valid_event(self):
        event = _make_event(date="2026-04-14", time="09:00-09:30")
        result = CalendarSyncScheduler._parse_event_start(event)
        assert result is not None
        assert result.hour == 9
        assert result.minute == 0

    def test_returns_none_for_empty_date(self):
        event = _make_event(date="", time="09:00-09:30")
        assert CalendarSyncScheduler._parse_event_start(event) is None

    def test_returns_none_for_empty_time(self):
        event = _make_event(date="2026-04-14", time="")
        assert CalendarSyncScheduler._parse_event_start(event) is None


class TestSyncProvider:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_token(self, tmp_path):
        config = _make_config(tmp_path)
        scheduler = CalendarSyncScheduler(config, tmp_path)

        with patch("recap.daemon.calendar.scheduler.get_credential", return_value=None):
            events = await scheduler._sync_provider("google")

        assert events == []

    @pytest.mark.asyncio
    async def test_fetches_with_valid_token(self, tmp_path):
        config = _make_config(
            tmp_path,
            calendars={"google": CalendarProviderConfig(org="testorg")},
        )
        scheduler = CalendarSyncScheduler(config, tmp_path)

        event = _make_event()

        def mock_get_cred(provider, key):
            return {
                "access_token": "tok123",
                "calendar_id": "primary",
                "refresh_token": "ref456",
            }.get(key)

        with (
            patch("recap.daemon.calendar.scheduler.get_credential", side_effect=mock_get_cred),
            patch("recap.daemon.calendar.scheduler.has_credential", return_value=True),
            patch.object(scheduler, "_fetch_events", new_callable=AsyncMock, return_value=[event]),
        ):
            events = await scheduler._sync_provider("google")

        assert len(events) == 1
        assert events[0].event_id == "evt-1"

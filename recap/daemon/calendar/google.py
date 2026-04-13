"""Google Calendar API client — fetch events and map to CalendarEvent."""
from __future__ import annotations

import logging
from datetime import datetime

import aiohttp

from recap.daemon.calendar.sync import CalendarEvent

logger = logging.getLogger(__name__)


def _parse_google_datetime(raw: str) -> tuple[str, str]:
    """Parse an RFC 3339 datetime like '2026-04-14T10:00:00-04:00' into (date, time).

    Returns ('2026-04-14', '10:00').
    """
    # Python's fromisoformat handles the offset
    dt = datetime.fromisoformat(raw)
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def _extract_meeting_link(event: dict) -> str:
    """Extract meeting link from hangoutLink or conferenceData."""
    link = event.get("hangoutLink", "")
    if link:
        return link

    conference = event.get("conferenceData", {})
    for entry_point in conference.get("entryPoints", []):
        uri = entry_point.get("uri", "")
        if uri:
            return uri

    return ""


def _parse_event(raw: dict, org: str) -> CalendarEvent:
    """Map a single Google Calendar API event dict to a CalendarEvent."""
    start = raw.get("start", {})
    end = raw.get("end", {})

    start_dt = start.get("dateTime", "")
    end_dt = end.get("dateTime", "")

    start_date, start_time = _parse_google_datetime(start_dt) if start_dt else ("", "")
    _, end_time = _parse_google_datetime(end_dt) if end_dt else ("", "")

    time_range = f"{start_time}-{end_time}" if start_time and end_time else start_time

    attendees = raw.get("attendees", [])
    participants = [
        a.get("displayName") or a.get("email", "")
        for a in attendees
    ]
    # Filter out empty strings
    participants = [p for p in participants if p]

    return CalendarEvent(
        event_id=raw.get("id", ""),
        title=raw.get("summary", ""),
        date=start_date,
        time=time_range,
        participants=participants,
        calendar_source="google",
        org=org,
        meeting_link=_extract_meeting_link(raw),
        description=raw.get("description", ""),
    )


async def fetch_google_events(
    access_token: str,
    calendar_id: str = "primary",
    start_date: str | None = None,
    end_date: str | None = None,
    org: str = "personal",
) -> list[CalendarEvent]:
    """Fetch calendar events from the Google Calendar API.

    Returns parsed CalendarEvent objects, or an empty list on error.
    """
    url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
    headers = {"Authorization": f"Bearer {access_token}"}
    params: dict[str, str] = {
        "singleEvents": "true",
        "orderBy": "startTime",
    }

    if start_date:
        params["timeMin"] = start_date
    if end_date:
        params["timeMax"] = end_date

    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.get(url, headers=headers, params=params)
            if resp.status != 200:
                body = await resp.text()
                logger.error("Google Calendar API error %d: %s", resp.status, body)
                return []

            data = await resp.json()
            raw_items = data.get("items", [])
            return [_parse_event(item, org) for item in raw_items]
    except Exception:
        logger.exception("Failed to fetch Google calendar events")
        return []

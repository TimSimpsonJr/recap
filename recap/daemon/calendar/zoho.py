"""Zoho Calendar API client — fetch events and map to CalendarEvent."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

import aiohttp

from recap.daemon.calendar.sync import CalendarEvent

logger = logging.getLogger(__name__)

# Matches common meeting URLs in description text.
_MEETING_LINK_RE = re.compile(
    r"https?://(?:teams\.microsoft\.com|meet\.google\.com|zoom\.us|us\d+web\.zoom\.us"
    r"|meeting\.zoho\.com)[^\s)\"'>]*",
    re.IGNORECASE,
)


def _parse_zoho_datetime(raw: str) -> tuple[str, str]:
    """Parse Zoho datetime string like '20260414T140000+0000' into (date, time).

    Returns ('2026-04-14', '14:00').
    """
    # Strip timezone offset for parsing the local portion
    dt = datetime.strptime(raw[:15], "%Y%m%dT%H%M%S")
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def _to_zoho_compact(iso_datetime: str) -> str:
    """Convert an ISO 8601 datetime (``2026-04-20T00:00:00Z``) to Zoho's
    compact datetime format (``20260420T000000Z``).

    The scheduler passes ISO 8601 strings for date ranges, but the Zoho
    Calendar API's ``range`` query parameter rejects dashes and colons
    with ``PATTERN_NOT_MATCHED``. This helper strips them (keeping the
    ``T`` separator and any trailing ``Z``). Already-compact inputs
    pass through unchanged so the helper is idempotent."""
    return iso_datetime.replace("-", "").replace(":", "")


def _extract_meeting_link(event: dict) -> str:
    """Try to find a meeting link from the event URL or description."""
    url = event.get("url", "")
    if url:
        return url

    description = event.get("description", "")
    match = _MEETING_LINK_RE.search(description)
    return match.group(0) if match else ""


def _parse_event(raw: dict, org: str) -> CalendarEvent:
    """Map a single Zoho API event dict to a CalendarEvent."""
    dt = raw.get("dateandtime", {})
    start_raw = dt.get("start", "")
    end_raw = dt.get("end", "")

    start_date, start_time = _parse_zoho_datetime(start_raw) if start_raw else ("", "")
    _, end_time = _parse_zoho_datetime(end_raw) if end_raw else ("", "")

    time_range = f"{start_time}-{end_time}" if start_time and end_time else start_time

    attendees = raw.get("attendees", [])
    participants = [a["name"] for a in attendees if a.get("name")]

    return CalendarEvent(
        event_id=raw.get("uid", ""),
        title=raw.get("title", ""),
        date=start_date,
        time=time_range,
        participants=participants,
        calendar_source="zoho",
        org=org,
        meeting_link=_extract_meeting_link(raw),
        description=raw.get("description", ""),
    )


async def fetch_zoho_events(
    access_token: str,
    calendar_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
    org: str = "disbursecloud",
) -> list[CalendarEvent]:
    """Fetch calendar events from the Zoho Calendar API.

    Returns parsed CalendarEvent objects, or an empty list on error.
    """
    url = f"https://calendar.zoho.com/api/v1/calendars/{calendar_id}/events"
    headers = {"Authorization": f"Bearer {access_token}"}
    params: dict[str, str] = {}

    if start_date or end_date:
        range_obj: dict[str, str] = {}
        if start_date:
            range_obj["start"] = _to_zoho_compact(start_date)
        if end_date:
            range_obj["end"] = _to_zoho_compact(end_date)
        params["range"] = json.dumps(range_obj)

    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.get(url, headers=headers, params=params)
            if resp.status != 200:
                body = await resp.text()
                logger.error("Zoho API error %d: %s", resp.status, body)
                return []

            data = await resp.json()
            raw_events = data.get("events", [])
            return [_parse_event(e, org) for e in raw_events]
    except Exception:
        logger.exception("Failed to fetch Zoho calendar events")
        return []

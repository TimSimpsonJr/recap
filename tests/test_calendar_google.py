"""Tests for Google Calendar API client."""
import pytest
from unittest.mock import patch, AsyncMock
from recap.daemon.calendar.google import fetch_google_events


class TestFetchGoogleEvents:
    @pytest.mark.asyncio
    async def test_parses_event_response(self):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "items": [
                {
                    "id": "goog1",
                    "summary": "Client Call",
                    "start": {"dateTime": "2026-04-14T10:00:00-04:00"},
                    "end": {"dateTime": "2026-04-14T11:00:00-04:00"},
                    "attendees": [
                        {"displayName": "Alice", "email": "alice@example.com"},
                    ],
                    "hangoutLink": "https://meet.google.com/abc-def-ghi",
                    "description": "Discuss project timeline",
                }
            ]
        })

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            events = await fetch_google_events(
                access_token="token",
                org="personal",
            )

        assert len(events) == 1
        assert events[0].title == "Client Call"
        assert events[0].event_id == "goog1"
        assert "Alice" in events[0].participants
        assert events[0].calendar_source == "google"
        assert events[0].org == "personal"

    @pytest.mark.asyncio
    async def test_handles_api_error(self):
        mock_response = AsyncMock()
        mock_response.status = 403
        mock_response.text = AsyncMock(return_value="Forbidden")

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            events = await fetch_google_events(access_token="bad", org="personal")
        assert events == []

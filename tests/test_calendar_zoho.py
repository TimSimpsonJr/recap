"""Tests for Zoho Calendar API client."""
import pytest
from unittest.mock import patch, AsyncMock
from recap.daemon.calendar.zoho import fetch_zoho_events


class TestFetchZohoEvents:
    @pytest.mark.asyncio
    async def test_parses_event_response(self):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "events": [
                {
                    "uid": "evt1",
                    "title": "Team Standup",
                    "dateandtime": {
                        "start": "20260414T140000+0000",
                        "end": "20260414T150000+0000",
                    },
                    "attendees": [
                        {"email": "jane@example.com", "name": "Jane Smith"},
                        {"email": "bob@example.com", "name": "Bob Lee"},
                    ],
                    "description": "Daily standup\nhttps://teams.microsoft.com/meet123",
                }
            ]
        })

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            events = await fetch_zoho_events(
                access_token="token",
                calendar_id="cal1",
                org="disbursecloud",
            )

        assert len(events) == 1
        assert events[0].title == "Team Standup"
        assert events[0].event_id == "evt1"
        assert "Jane Smith" in events[0].participants
        assert events[0].calendar_source == "zoho"
        assert events[0].org == "disbursecloud"

    @pytest.mark.asyncio
    async def test_handles_api_error(self):
        mock_response = AsyncMock()
        mock_response.status = 401
        mock_response.text = AsyncMock(return_value="Unauthorized")

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            events = await fetch_zoho_events(
                access_token="bad-token",
                calendar_id="cal1",
            )
        assert events == []

    @pytest.mark.asyncio
    async def test_handles_empty_events(self):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"events": []})

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            events = await fetch_zoho_events(access_token="token", calendar_id="cal1")
        assert events == []

    @pytest.mark.asyncio
    async def test_converts_iso_date_range_to_zoho_compact_format(self):
        """Scheduler passes ISO 8601 strings like ``2026-04-20T00:00:00Z``
        but Zoho's Calendar API requires its compact datetime format
        ``20260420T000000Z`` in the ``range`` query parameter. The
        client must convert ISO -> compact before building the
        request; otherwise Zoho returns 400 PATTERN_NOT_MATCHED.
        Regression guard for the hardware diagnostic on 2026-04-20."""
        import json as _json
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"events": []})

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await fetch_zoho_events(
                access_token="token",
                calendar_id="cal1",
                start_date="2026-04-20T00:00:00Z",
                end_date="2026-04-27T23:59:59Z",
            )

        call_kwargs = mock_session.get.call_args.kwargs
        sent_params = call_kwargs.get("params", {})
        range_json = sent_params.get("range")
        assert range_json is not None, "range param missing from Zoho request"
        parsed_range = _json.loads(range_json)
        # No dashes, no colons -- Zoho compact format.
        assert parsed_range["start"] == "20260420T000000Z"
        assert parsed_range["end"] == "20260427T235959Z"

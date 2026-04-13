# Phase 5: Calendar Sync + OAuth

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Sync calendar events from Zoho and Google into vault notes, OAuth token management via Authlib + keyring, and wire calendar events to the detector for auto-arming.

**Architecture:** Calendar sync runs as a periodic async task in the daemon. OAuth flows use Authlib with a localhost callback server. Tokens are stored in Windows Credential Manager via keyring. Calendar events become vault notes in `_Recap/Calendar/`.

**Tech Stack:** Authlib, keyring, aiohttp, pyyaml

---

### Task 1: Credentials module

**Files:**
- Create: `recap/daemon/credentials.py`
- Test: `tests/test_credentials.py`

**Step 1: Write the failing tests**

```python
"""Tests for credential storage."""
import pytest
from unittest.mock import patch
from recap.daemon.credentials import store_credential, get_credential, delete_credential


class TestCredentials:
    @patch("recap.daemon.credentials.keyring")
    def test_store_and_retrieve(self, mock_keyring):
        mock_keyring.get_password.return_value = "my-token"
        store_credential("zoho", "access_token", "my-token")
        mock_keyring.set_password.assert_called_once_with("recap-zoho", "access_token", "my-token")

        result = get_credential("zoho", "access_token")
        assert result == "my-token"

    @patch("recap.daemon.credentials.keyring")
    def test_missing_credential_returns_none(self, mock_keyring):
        mock_keyring.get_password.return_value = None
        result = get_credential("zoho", "missing_key")
        assert result is None

    @patch("recap.daemon.credentials.keyring")
    def test_delete_credential(self, mock_keyring):
        delete_credential("zoho", "access_token")
        mock_keyring.delete_password.assert_called_once()
```

**Step 2: Run, fail, implement**

`recap/daemon/credentials.py`:
- `store_credential(provider, key, value)` — `keyring.set_password(f"recap-{provider}", key, value)`
- `get_credential(provider, key) -> str | None` — `keyring.get_password(...)`
- `delete_credential(provider, key)` — `keyring.delete_password(...)`
- All wrapped in try/except with logging (never crash on keyring failure)

**Step 3: Run tests, commit**

```bash
pytest tests/test_credentials.py -v
git add recap/daemon/credentials.py tests/test_credentials.py
git commit -m "feat: add keyring-backed credential storage"
```

---

### Task 2: OAuth flow module

**Files:**
- Create: `recap/daemon/calendar/oauth.py`
- Create: `recap/daemon/calendar/__init__.py`
- Test: `tests/test_oauth.py`

**Step 1: Write the failing tests**

```python
"""Tests for OAuth flow management."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from recap.daemon.calendar.oauth import OAuthManager


class TestOAuthManager:
    def test_zoho_config(self):
        manager = OAuthManager(provider="zoho", client_id="id", client_secret="secret")
        assert manager.authorize_url.startswith("https://accounts.zoho")
        assert manager.token_url.startswith("https://accounts.zoho")

    def test_google_config(self):
        manager = OAuthManager(provider="google", client_id="id", client_secret="secret")
        assert manager.authorize_url.startswith("https://accounts.google")

    def test_redirect_uri_is_localhost(self):
        manager = OAuthManager(provider="zoho", client_id="id", client_secret="secret")
        assert "localhost" in manager.redirect_uri
```

**Step 2: Run, fail, implement**

`OAuthManager`:
- `__init__(provider, client_id, client_secret, redirect_port=8399)` — configure Authlib OAuth2Session for the provider
- Provider configs (authorize URL, token URL, scopes) for Zoho and Google
- `start_auth_flow() -> str` — returns the authorization URL to open in the browser
- `handle_callback(code: str) -> dict` — exchange code for tokens via Authlib
- `refresh_token() -> dict` — refresh expired token via Authlib
- `get_valid_token() -> str` — return access token, auto-refresh if expired
- Tokens stored/retrieved via credentials module (keyring)
- Localhost callback server: temporary aiohttp server on port 8399 that catches the OAuth redirect, extracts the code, calls `handle_callback()`

**Step 3: Run tests, commit**

```bash
pytest tests/test_oauth.py -v
git add recap/daemon/calendar/ tests/test_oauth.py
git commit -m "feat: add OAuth flow management with Authlib and keyring"
```

---

### Task 3: Calendar sync module

**Files:**
- Create: `recap/daemon/calendar/sync.py`
- Test: `tests/test_calendar_sync.py`

**Step 1: Write the failing tests**

```python
"""Tests for calendar sync."""
import pytest
from pathlib import Path
from recap.daemon.calendar.sync import (
    CalendarEvent,
    write_calendar_note,
    should_update_note,
)


class TestWriteCalendarNote:
    def test_creates_note_with_frontmatter(self, tmp_path):
        event = CalendarEvent(
            event_id="abc123",
            title="Sprint Planning",
            date="2026-04-14",
            time="14:00-15:00",
            participants=["Tim", "Jane Smith"],
            calendar_source="zoho",
            org="disbursecloud",
            meeting_link="https://teams.microsoft.com/...",
            description="Review sprint goals",
        )
        path = write_calendar_note(event, tmp_path / "_Recap")
        assert path.exists()
        content = path.read_text()
        assert "event-id: \"abc123\"" in content
        assert "Sprint Planning" in content
        assert "[[Tim]]" in content
        assert "## Agenda" in content
        assert "Review sprint goals" in content

    def test_note_goes_to_correct_org_folder(self, tmp_path):
        event = CalendarEvent(
            event_id="abc",
            title="Meeting",
            date="2026-04-14",
            time="10:00-11:00",
            participants=[],
            calendar_source="zoho",
            org="disbursecloud",
        )
        path = write_calendar_note(event, tmp_path / "_Recap")
        assert "Disbursecloud" in str(path) or "disbursecloud" in str(path)


class TestShouldUpdateNote:
    def test_new_event_should_create(self, tmp_path):
        assert should_update_note(
            event_id="new",
            vault_path=tmp_path,
        ) == "create"

    def test_existing_event_with_changed_time_should_update(self, tmp_path):
        # Create existing note with event-id
        note_path = tmp_path / "test.md"
        note_path.write_text("---\nevent-id: \"abc\"\ntime: \"10:00-11:00\"\n---\n")
        assert should_update_note(
            event_id="abc",
            vault_path=tmp_path,
            new_time="14:00-15:00",
        ) == "update"

    def test_existing_event_unchanged_should_skip(self, tmp_path):
        note_path = tmp_path / "test.md"
        note_path.write_text("---\nevent-id: \"abc\"\ntime: \"10:00-11:00\"\n---\n")
        assert should_update_note(
            event_id="abc",
            vault_path=tmp_path,
            new_time="10:00-11:00",
        ) == "skip"
```

**Step 2: Run, fail, implement**

`CalendarEvent` dataclass with all frontmatter fields.

`write_calendar_note(event, recap_path) -> Path`:
- Target: `{recap_path}/{org}/Meetings/{date} - {title}.md`
- Write frontmatter (date, time, title, participants as wikilinks, calendar-source, org, meeting-link, event-id, pipeline-status: pending)
- Write `## Agenda` section with event description if available
- Create directories if needed

`should_update_note(event_id, vault_path, new_time=None, new_participants=None) -> str`:
- Scan vault for note with matching `event-id` in frontmatter
- If not found: return "create"
- If found and time/participants changed: return "update"
- If found and unchanged: return "skip"

`update_calendar_note(note_path, new_time=None, new_participants=None, rename_queue_path=None)`:
- Update time and/or participants in frontmatter only
- If date changed: update frontmatter, queue file rename to `rename_queue_path`

**Step 3: Run tests, commit**

```bash
pytest tests/test_calendar_sync.py -v
git add recap/daemon/calendar/sync.py tests/test_calendar_sync.py
git commit -m "feat: add calendar event to vault note sync"
```

---

### Task 4: Zoho Calendar API client

**Files:**
- Create: `recap/daemon/calendar/zoho.py`
- Test: `tests/test_calendar_zoho.py`

**Step 1: Write the failing tests (mocked API)**

```python
"""Tests for Zoho Calendar API client."""
import pytest
from unittest.mock import patch, AsyncMock
from recap.daemon.calendar.zoho import fetch_zoho_events


class TestZohoCalendarAPI:
    @pytest.mark.asyncio
    async def test_parses_event_response(self):
        mock_response = {
            "events": [
                {
                    "uid": "evt1",
                    "title": "Team Standup",
                    "dateandtime": {"start": "20260414T140000", "end": "20260414T150000"},
                    "attendees": [{"email": "jane@example.com", "name": "Jane Smith"}],
                    "url": "https://teams.microsoft.com/...",
                    "description": "Daily standup",
                }
            ]
        }
        with patch("recap.daemon.calendar.zoho._api_request", new_callable=AsyncMock, return_value=mock_response):
            events = await fetch_zoho_events(access_token="token", calendar_id="cal1")

        assert len(events) == 1
        assert events[0].title == "Team Standup"
        assert events[0].event_id == "evt1"
        assert "Jane Smith" in events[0].participants
```

**Step 2: Run, fail, implement**

`fetch_zoho_events(access_token, calendar_id, date_range=None) -> list[CalendarEvent]`:
- Call Zoho Calendar API: `GET /api/v1/calendars/{id}/events`
- Parse response into `CalendarEvent` objects
- Handle pagination if needed
- Rate limiting: respect Zoho's limits

**Step 3: Run tests, commit**

```bash
pytest tests/test_calendar_zoho.py -v
git add recap/daemon/calendar/zoho.py tests/test_calendar_zoho.py
git commit -m "feat: add Zoho Calendar API client"
```

---

### Task 5: Google Calendar API client

**Files:**
- Create: `recap/daemon/calendar/google.py`
- Test: `tests/test_calendar_google.py`

**Step 1: Same pattern as Zoho**

Implement `fetch_google_events(access_token, calendar_id) -> list[CalendarEvent]`. Google Calendar API: `GET /calendars/{id}/events`.

**Step 2: Run tests, commit**

```bash
pytest tests/test_calendar_google.py -v
git add recap/daemon/calendar/google.py tests/test_calendar_google.py
git commit -m "feat: add Google Calendar API client"
```

---

### Task 6: Calendar sync loop

**Files:**
- Create: `recap/daemon/calendar/scheduler.py`
- Modify: `recap/daemon/__main__.py`

**Step 1: Implement sync scheduler**

`CalendarSyncScheduler`:
- `__init__(config, oauth_manager, detector)` — takes config for interval, calendar mapping
- `start()` — async loop: sync immediately, then every N minutes
- `sync()`:
  1. For each configured calendar provider: get valid OAuth token, fetch events
  2. For each event: check `should_update_note()`, create/update vault note
  3. For upcoming events (within 30 minutes): call `detector.arm_for_event()`
  4. Log sync results
  5. Handle errors gracefully (token expired → notify, API error → retry with backoff)

**Step 2: Wire to daemon**

In `__main__.py`:
- Create `CalendarSyncScheduler` with config
- Start sync on daemon startup
- If sync-on-startup is True: run immediate sync before entering main loop

**Step 3: Add OAuth trigger endpoints to HTTP server**

- `GET /api/oauth/:provider/status` — connected/disconnected + token expiry
- `POST /api/oauth/:provider/start` — initiate OAuth flow (opens browser)
- `DELETE /api/oauth/:provider` — disconnect (delete tokens from keyring)

**Step 4: Manual test**

1. Start daemon
2. Trigger Zoho OAuth via HTTP: `POST /api/oauth/zoho/start`
3. Complete OAuth in browser
4. Verify calendar events appear as vault notes in `_Recap/Disbursecloud/Meetings/`
5. Wait for sync interval, verify new events picked up

**Step 5: Commit**

```bash
git add recap/daemon/calendar/scheduler.py recap/daemon/__main__.py recap/daemon/server.py
git commit -m "feat: add calendar sync loop with auto-arming and OAuth endpoints"
```

---

### Task 7: Push and verify

```bash
pytest tests/ -v --ignore=tests/fixtures
git push
```

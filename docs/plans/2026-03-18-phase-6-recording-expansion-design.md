# Phase 6: Recording Expansion — Multi-Platform Detection, Enrichment, Auto-Record

## Status: Design Complete

## Overview

Four workstreams in dependency order: (1) a lightweight Chrome/Edge browser extension for detecting browser-based meetings, (2) multi-platform meeting detection combining WASAPI monitoring with extension signals, (3) per-platform API metadata enrichment with screenshot-based fallback, and (4) auto-record from calendar events.

## Section 0: Browser Extension

### Purpose

Detect Google Meet, Zoho Meet, and Teams web meetings running in Chrome or Edge. The extension tells Recap "a meeting is happening on this tab" — Recap handles all recording via existing WASAPI + Graphics Capture infrastructure.

### Architecture

Manifest V3 extension living in `extension/` in the Recap repo. Loaded as an unpacked extension for personal use (no Chrome Web Store needed).

### What it does

- Listens for `chrome.tabs.onUpdated` events
- Matches tab URLs against meeting patterns (configurable, stored in `chrome.storage.local`)
- On match: POSTs to Recap's localhost HTTP listener with meeting info
- On tab close/navigate away: POSTs meeting-ended signal
- Periodically pings Recap's health endpoint; shows green/gray badge icon for connection status

### Default URL patterns

| Platform | Pattern |
|----------|---------|
| Google Meet | `https://meet.google.com/*` (excluding bare homepage without meeting code) |
| Zoho Meet | `https://meeting.zoho.com/meeting/*`, `https://meeting.zoho.{region}/meeting/*`, `https://meeting.tranzpay.io/*` |
| Teams Web | `https://teams.microsoft.com/*` with `/meetup-join/` or `/pre-join/` in path |

### Screen share detection (content script)

A small content script injected into meeting pages detects when the user starts/stops sharing their screen. Platform-specific DOM selectors:

- Google Meet: watches for the "You are presenting" banner
- Zoho Meet: watches for the sharing indicator overlay
- Teams Web: watches for the "You're sharing" status

When sharing is detected, the extension signals Recap to switch video capture from the meeting window to the configured screen share display. When sharing stops, it signals to switch back.

### Communication

- POST `http://localhost:17839/meeting-detected` — `{url, title, platform, tabId}`
- POST `http://localhost:17839/meeting-ended` — `{tabId}`
- POST `http://localhost:17839/sharing-started` — `{tabId}`
- POST `http://localhost:17839/sharing-stopped` — `{tabId}`
- GET `http://localhost:17839/health` — connection check for badge icon

### Permissions

- `tabs` — read tab URLs
- `host_permissions: ["http://localhost/*"]` — communicate with Recap
- Content script permissions for meeting domains (for screen share detection)

### Files

- `extension/manifest.json`
- `extension/background.js` (~100-150 lines)
- `extension/content.js` (~100 lines, screen share detection)

### Configurable patterns

URL patterns stored in `chrome.storage.local` so users can add custom meeting domains without editing code. Default patterns ship with the extension; users can add/remove via a simple options page.

## Section 1: Multi-Platform Detection

### Localhost HTTP listener

New module `src-tauri/src/recorder/listener.rs`:

- HTTP server on `localhost:17839` started in Tauri `.setup()`
- Port fallback: tries 17839-17845 if the primary port is in use
- Routes:
  - `GET /health` — returns 200 (extension badge check)
  - `POST /meeting-detected` — receives extension signal, forwards to recorder
  - `POST /meeting-ended` — receives extension signal, forwards to recorder
  - `POST /sharing-started` — triggers capture source switch
  - `POST /sharing-stopped` — triggers capture source switch back

### Monitor expansion

Update `src-tauri/src/recorder/monitor.rs`:

- New event variants:
  - `MonitorEvent::BrowserMeetingDetected { url, title, platform, tab_id }`
  - `MonitorEvent::BrowserMeetingEnded { tab_id }`
  - `MonitorEvent::SharingStarted`
  - `MonitorEvent::SharingStopped`
- Keep existing WASAPI polling for `Zoom.exe` and `Teams.exe`
- Deduplication: if a recording is already active, ignore overlapping detection signals from the other source (WASAPI vs extension)

### Screen share detection (desktop apps)

Update monitor to detect screen sharing for native desktop apps via Win32 window monitoring:

- Zoom: detect `ZPToolBarParentWndClass` window appearing (Zoom's sharing toolbar)
- Teams: detect the share indicator overlay window

When detected, emit `MonitorEvent::SharingStarted`. When the indicator window disappears, emit `MonitorEvent::SharingStopped`.

### Video capture source switching

When sharing is detected (from extension or Win32 monitoring):

1. Pause meeting window capture
2. Switch Graphics Capture target to the configured display/monitor
3. Continue recording at the same frame rate, scaling to 1920x1080

When sharing stops:

1. Switch back to the meeting window capture
2. Continue recording

**Screen share display setting:** Added to Recording Settings — "When sharing, capture: [Primary Monitor / Monitor 2 / ...]". Lists available displays. Default: primary monitor.

### Platform identification

New enum in `src-tauri/src/recorder/types.rs`:

```
pub enum MeetingPlatform {
    Zoom,
    Teams,
    GoogleMeet,
    ZohoMeet,
    Unknown,
}
```

Derived from process name (`Zoom.exe` → Zoom, `Teams.exe` → Teams) or extension URL pattern. Stored in `RecordingSession` for post-recording API enrichment routing.

### Browser PID resolution

When the extension signals a browser meeting, the recorder finds the browser PID from the WASAPI audio session list (the browser process that has active audio). This PID is used for audio capture targeting.

## Section 2: API Metadata Enrichment

### Unified metadata model

All platform clients map their responses into a common struct:

```
pub struct MeetingMetadata {
    pub title: String,
    pub platform: MeetingPlatform,
    pub participants: Vec<Participant>,
    pub user_name: String,
    pub user_email: String,
    pub start_time: DateTime<Utc>,
    pub end_time: DateTime<Utc>,
}

pub struct Participant {
    pub name: String,
    pub email: Option<String>,
    pub join_time: Option<String>,
    pub leave_time: Option<String>,
}
```

The existing `zoom.rs` refactored to output this common struct.

### Zoom (existing, refactored)

- Module: `src-tauri/src/recorder/zoom.rs` (already exists)
- Refactor `ZoomMeetingInfo` → `MeetingMetadata`
- No API changes, just type alignment

### Google Meet

- Module: `src-tauri/src/recorder/google_meet.rs`
- Uses Google Meet REST API (available to Workspace admins):
  - `GET /v2/conferenceRecords` — list recent meetings
  - `GET /v2/conferenceRecords/{id}/participants` — actual attendees with join/leave times
- OAuth scope: add `https://www.googleapis.com/auth/meetings.space.readonly` to Google OAuth config (currently only `calendar.readonly`)
- Match by: conference code from meeting URL or time overlap with recording
- Returns `MeetingMetadata` with actual attendance data

### Teams

- Module: `src-tauri/src/recorder/teams.rs`
- Personal Microsoft accounts cannot access `OnlineMeetings.Read` or call records APIs
- Primary metadata source: calendar event data (from Zoho Calendar or Outlook calendar if connected)
- Meeting title fallback: Win32 `GetWindowText` on the Teams window, or extension-provided tab title
- No participant list from API — relies on screenshot extraction fallback or speaker correction UI

### Zoho Meeting

- Module: `src-tauri/src/recorder/zoho_meet.rs`
- Endpoints:
  - `GET /meeting/api/v1/meetings` — list meetings
  - `GET /meeting/api/v1/meetings/{meetingId}/attendees` — actual attendees
- OAuth scope `ZohoMeeting.manageOrg.READ` already configured
- Regional endpoint handling already exists in `oauth.rs`
- Match by: meeting end time within 5 minutes of recording stop

### Screenshot-based participant extraction (universal fallback)

When no API or calendar data provides a participant list:

1. During recording, capture 2-3 screenshots of the meeting window at intervals (30s, 2min, 5min after start)
2. After recording stops, send screenshots to Claude CLI with a vision prompt: "List all participant names visible in this meeting screenshot. Return as JSON array."
3. Union names across all screenshots (participants may join late)
4. Use extracted names as the participant list for the pipeline's speaker mapping

Implementation options:
- In the Rust recorder: take screenshots via Graphics Capture at defined intervals, store alongside the recording, call Claude CLI post-recording
- In the Python pipeline: new pre-analysis step in `frames.py` that processes early frames for participant identification

Works for all platforms since every meeting app shows participant names on video tiles. Best results when the meeting grid/gallery view is visible (not during screen shares).

Prompt template: `prompts/participant_extraction.md`

### Enrichment routing

After recording stops, the recorder checks `MeetingPlatform` and calls the appropriate API client:

1. Try platform-specific API (Zoom/Google Meet/Zoho Meeting)
2. If API fails or unavailable (Teams personal): try calendar event matching
3. If no calendar match: use screenshot extraction
4. If screenshot extraction fails or is empty: meeting proceeds to speaker correction UI (Phase 5c)

## Section 3: Auto-Record from Calendar

### Concept

Per-event or per-series auto-record flag in the calendar cache. When a flagged event is approaching, the recorder arms so the next detected meeting auto-records without a notification prompt.

### Data model

Extend the calendar event cache (from Phase 5c) with:

```
pub struct CalendarEvent {
    // ... existing fields ...
    pub auto_record: bool,           // NEW
    pub recurring_series_id: Option<String>,  // for per-series flags
    pub meeting_url: Option<String>,  // parsed from description/location
    pub detected_platform: Option<MeetingPlatform>,  // derived from meeting_url
}
```

### Calendar link parsing

Parse meeting URLs from calendar event description and location fields:

| URL pattern | Platform |
|-------------|----------|
| `zoom.us/j/*` | Zoom |
| `meet.google.com/*` | Google Meet |
| `teams.microsoft.com/*/meetup-join/*` | Teams |
| `meeting.tranzpay.io/*` | Zoho Meet |
| `meeting.zoho.*/meeting/*` | Zoho Meet |

Pre-identified platform is a hint for enrichment routing, not a filter for detection — any meeting process/extension signal is accepted when armed.

### UI

- Calendar view: each upcoming event gets a toggle icon (record dot) for "Auto-record this meeting"
- Recurring events: additional option "Auto-record all in this series" (sets flag by `recurring_series_id`)
- Settings → Recording: global "Auto-record all calendar meetings" toggle (overrides per-event flags)
- Armed events show a gold record indicator in the calendar view

### Backend behavior

1. Periodic check (every 60 seconds) compares upcoming auto-record events against current time
2. When an event is within the configured lead time (uses existing 5/10/15 min notification setting from Phase 5c):
   - Set recorder to "armed" mode — next meeting detection auto-records
   - Pre-identify expected platform from calendar link (if available)
3. When the monitor detects a meeting while armed → start recording immediately (no notification prompt)
4. After recording starts → disarm (one-shot per event)
5. If event time passes with no detection → disarm after event end time + 5 min buffer

### Edge cases

**Back-to-back meetings:** When the first meeting ends (WASAPI session ends or extension signals tab close), stop recording, process, then arm for the next event. If the first meeting runs late into the second meeting's time slot, prioritize the active recording — don't cut off mid-meeting.

**Late app startup:** On startup, check if any auto-record events are happening NOW (start time in the past, end time in the future). If so, immediately scan for active meeting processes and begin recording.

**Platform mismatch:** Calendar says Zoom but meeting happens on Google Meet. Armed state accepts ANY meeting detection, not just the expected platform.

**Multiple calendar sources:** Auto-record flags are stored per event regardless of calendar source. If Google Calendar is added later, its events get the same treatment.

### Storage

- Auto-record flags stored in the existing calendar cache JSON (Tauri app data dir)
- Per-series flags keyed by `recurring_series_id`
- Persist across app restart

## Dependencies

- Section 0 (Extension) is independent — can be built first
- Section 1 (Detection) depends on Section 0 for browser meeting signals
- Section 2 (Enrichment) depends on Section 1 for platform identification
- Section 3 (Auto-Record) depends on Section 1 for detection infrastructure
- Screenshot extraction (Section 2) depends on video capture working for all platforms (Section 1)
- All sections depend on Phase 5c being merged (done)

## Key Design Decisions

1. **Browser extension for detection** — reliable URL-based detection without false positives. Lightweight MV3 extension with minimal permissions. Optional — manual start works without it.

2. **Localhost HTTP listener** — extension communicates with Recap via `localhost:17839`. Fixed port with fallback range. No native messaging complexity.

3. **Content script for browser share detection** — detects screen sharing state changes in meeting page DOM. Combined with Win32 window monitoring for desktop app share detection.

4. **Capture source switching on share** — when user shares their screen, video capture switches from meeting window to configured display. User configures which monitor in Recording Settings.

5. **Scale to 1080p canvas** — all captured frames scaled to 1920x1080 regardless of window size. Handles resize gracefully. Video is primarily for frame extraction, not pixel-perfect playback.

6. **Accept mixed browser audio** — WASAPI captures all Chrome tabs' audio together. No per-tab isolation. WhisperX handles background noise well enough.

7. **Google Meet uses Workspace admin API** — `meetings.space.readonly` scope provides actual attendance data. Available because user is a Workspace admin.

8. **Teams falls back to calendar + screenshots** — personal Microsoft accounts can't access meeting APIs. Calendar event data + screenshot-based participant extraction covers the gap.

9. **Screenshot extraction as universal fallback** — Claude vision reads participant names from meeting window screenshots. Works for all platforms. 2-3 screenshots at intervals to catch late joiners.

10. **Calendar arms the monitor** — auto-record sets the recorder to "armed" mode. Next meeting detection auto-records. One-shot per event. Pre-identifies expected platform from calendar links but accepts any detection.

11. **Custom meeting domains configurable** — extension URL patterns stored in `chrome.storage.local`. `meeting.tranzpay.io` ships as default alongside standard platform domains.

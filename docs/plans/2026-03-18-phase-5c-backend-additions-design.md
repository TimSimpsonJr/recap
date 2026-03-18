# Phase 5c: Backend Additions — Calendar, Speaker Correction, Notifications

## Status: Design Draft — Needs Further Brainstorming

This document captures the current design direction. Sections marked 🔶 require additional brainstorming before implementation planning.

## Overview

Add new Rust backend capabilities and their frontend integration: Zoho Calendar polling with local cache, speaker diarization correction with hybrid pipeline pausing, and pre-meeting briefing notifications.

## Section 1: Calendar Integration

### Backend (Rust)

New Tauri commands:
- `fetch_calendar_events(date_range)` — calls Zoho Calendar API using stored OAuth tokens, returns events
- `get_upcoming_meetings(hours_ahead)` — returns cached events within the time window
- `sync_calendar()` — manual refresh trigger

Caching:
- Store last-known calendar data as JSON in Tauri app data directory
- Automatic refresh twice daily (configurable)
- Stale indicator when cache is older than refresh interval and API is unreachable

Calendar → recording matching:
- Compare calendar event time windows against recording timestamps
- Match on overlap (event start/end vs recording start time ± duration)
- Store matches in cache for fast lookup

Auto-record:
- Per-event or per-series flag stored in calendar cache
- When a matching calendar event is approaching and auto-record is on, prepare recorder

### Frontend (Svelte)

- "Calendar" tab or sub-section in top nav
- Upcoming meetings list: participant names, time, company, auto-record toggle
- Past calendar events linked to recordings when matched
- Empty state: "Connect Zoho Calendar in Settings"
- Last-synced timestamp shown in calendar view

### 🔶 Needs Brainstorming

- **Calendar invitation content:** How to access the email body/description from calendar invitations for pre-meeting briefings when no prior meetings exist. Does Zoho Calendar API return event descriptions or notes? Or do we need Zoho Mail API integration? This affects the briefing feature in Section 3.
- **Cache format:** Exact JSON schema for cached events. What fields do we need from Zoho's API response?
- **Invalidation beyond twice-daily:** Should we also refresh on app focus? On manual pull-to-refresh? When the user opens the Calendar tab?
- **OAuth scope:** Current Zoho OAuth may need additional scopes for calendar read access. Verify against Zoho Calendar API docs.

## Section 2: Speaker Correction UI

### Hybrid Pipeline Pause

The pipeline runs fully if all speakers are identified by diarization. It only pauses if unidentified speakers remain ("Speaker 1", "Speaker 2", etc.).

**When all speakers identified:**
1. Pipeline runs to completion (merge → frames → transcribe → diarize → analyze → export)
2. Vault note generated immediately
3. Speaker correction still accessible from detail panel — corrections trigger re-analysis and note regeneration

**When unidentified speakers present:**
1. Pipeline runs through diarization, then pauses
2. Meeting card shows "Needs Speaker Review" indicator
3. User corrects speaker labels
4. Pipeline resumes from analyze stage with corrected labels
5. Vault note generated with correct attributions

### Backend (Rust)

New command: `update_speaker_labels(recording_dir, corrections: Map<String, String>)`
- Writes corrections to `speaker_labels.json` alongside the recording
- Triggers `retry_processing(recording_dir, from_stage: "analyze")`

### Pipeline (Python sidecar)

- After diarization, check if any speakers are unidentified (generic "Speaker N" labels)
- If all identified: continue to analyze
- If unidentified present: set `PipelineStatus.diarize.completed = true`, leave `analyze` as pending with a status indicating "awaiting speaker review", then exit
- On resume: read `speaker_labels.json`, apply corrections to transcript, proceed with analysis

### Frontend (Svelte)

- "Needs Speaker Review" badge on meeting cards with unidentified speakers
- Speaker review interface: transcript preview with speaker labels, correction controls
- For completed meetings: speaker correction accessible from detail panel transcript tab
- After correction: visual feedback showing pipeline resuming

### 🔶 Needs Brainstorming

- **Speaker review UX:** Inline in detail panel? Modal? Dedicated view? Consider that this might be a quick 2-speaker fix or a complex 8-person meeting.
- **Speaker dropdown population:** From calendar event participants? Manual entry? Both? Address book / contact list?
- **Pipeline "paused" status model:** New enum value in `PipelineStatus`? Special status string on the analyze stage? How does the frontend distinguish "waiting for review" from "failed"?
- **Speaker identification logic:** How does the sidecar determine if a speaker is "identified" vs generic? Name matching against participant list? Confidence threshold from Pyannote?

## Section 3: Meeting Notifications with Pre-Meeting Briefing

### Backend (Rust)

- Periodic check against cached calendar data (on app focus + configurable timer)
- Configurable lead time: 5, 10, or 15 minutes before meeting
- New command: `generate_briefing(company, participants)` — queries past meetings with same company/participants, assembles summary

Briefing data assembly:
- Query recordings dir for past meetings matching company or participant overlap
- Read vault notes for matched meetings
- Compile into briefing format

### Frontend (Svelte)

- System tray notification via `tauri-plugin-notification` (already configured)
- Notification includes: meeting title, time, participant names, "View Briefing" action
- "View Briefing" link opens briefing panel in the app
- Briefing also accessible from Calendar tab → click upcoming meeting → "Meeting Prep" section
- No previous meetings → briefing based on calendar invitation content
- Settings: notification toggle, lead time selector (5/10/15 min)

### Briefing Content

When previous meetings exist:
- Summary of key discussion points from recent meetings with the same company/participants
- Open action items attributed to meeting participants
- Relationship context (how long you've been meeting, frequency)

When no previous meetings exist:
- Note that this is the first meeting with these participants
- Any context from calendar invitation description/notes

### 🔶 Needs Brainstorming

- **Summarization engine:** Where does the briefing summary happen? Options:
  - LLM call via Python sidecar (`--briefing` mode) — best quality, requires API call
  - Rust reads vault notes directly, extracts summary sections — no API cost, simpler, but less intelligent
  - Hybrid: Rust extracts, Python/LLM summarizes only when multiple meetings need condensing
- **Briefing format:** Bullet points? Structured sections? Configurable depth?
- **Lookback window:** How far back for "previous meetings"? All time? Last 6 months? Last N meetings?
- **Calendar invitation content:** Depends on Section 1 brainstorming — need to resolve Zoho Calendar API capabilities first
- **Notification action:** Can Tauri notifications include clickable action buttons that open a specific view in the app? Or just a generic "click to open" that we route internally?

## Dependencies

- Section 1 (Calendar) blocks Section 3 (Notifications) — briefings need calendar data and invitation content
- Section 2 (Speaker Correction) is independent and can be built in parallel with Section 1
- All sections depend on Phase 5b being complete (real data wiring established)

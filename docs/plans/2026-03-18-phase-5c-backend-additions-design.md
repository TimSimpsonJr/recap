# Phase 5c: Backend Additions — Theme, Calendar, Speaker Correction, Notifications

## Status: Design Complete

## Overview

Four workstreams: migrate from Warm Ink to Recap Dark color scheme, add Zoho Calendar polling with local cache, implement speaker diarization correction with pipeline pausing, and build pre-meeting briefing notifications via Claude CLI.

## Section 0: Theme Migration + Zoom Controls

### Recap Dark Palette

Replace all hardcoded Warm Ink hex values across ~30 component files with CSS custom properties defined in `app.css`.

| Token | Value | Usage |
|-------|-------|-------|
| `--bg` | `#151921` | Page background |
| `--surface` | `#1c2128` | Nav, cards, sidebars |
| `--raised` | `#272d35` | Dropdowns, modals, elevated surfaces |
| `--border` | `#363d47` | Borders |
| `--text` | `#d4dae3` | Primary text |
| `--text-muted` | `#7a8493` | Secondary/muted text |
| `--blue` | `#4d9cf5` | Links, identified speakers, accents |
| `--gold` | `#C4A84D` | Active states, nav highlights, pipeline dots |
| `--green` | `#4baa55` | Success states |
| `--red` | `#ef534a` | Error states |

Also update: scrollbar colors in `app.css`, SVG icon source (`static/icon-source.svg`).

### Zoom Controls

- Ctrl+Scroll and Ctrl++/- for UI zoom via Tauri's `webview.setZoom()` API
- Ctrl+0 to reset to default (1.0)
- Persist zoom level in settings store, apply on app launch

## Section 1: Calendar Integration

### Backend (Rust)

New Tauri commands:
- `fetch_calendar_events(date_range)` — calls Zoho Calendar API using stored OAuth tokens, returns events
- `get_upcoming_meetings(hours_ahead)` — returns cached events within the time window
- `sync_calendar()` — manual refresh trigger

Zoho Calendar API:
- OAuth scope `ZohoCalendar.calendar.READ` already configured
- Use `Accept: application/json+large` header to include event descriptions (needed for first-meeting briefing fallback)

Caching:
- Store last-known calendar data as JSON in Tauri app data directory
- Automatic refresh twice daily (configurable)
- Refresh on app focus (debounced to once per 15 minutes)
- Manual sync button in Calendar view
- Stale indicator when cache is older than refresh interval and API is unreachable

Calendar → recording matching:
- Compare calendar event time windows against recording timestamps
- Match on overlap (event start/end vs recording start time ± duration)
- Store matches in cache for fast lookup

Auto-record: deferred to a later phase when all recording integrations are complete.

### Frontend (Svelte)

- Calendar section in top nav
- Upcoming meetings list: participant names, time, company
- Past calendar events linked to recordings when matched
- Last-synced timestamp + manual sync button
- Empty state: "Connect Zoho Calendar in Settings"

## Section 2: Speaker Correction

### Pause Trigger

The pipeline pauses when the meeting has **no participant list** — no calendar event match and no platform metadata (Zoom/Teams) providing names. If participants are known, Claude maps `SPEAKER_XX` labels to names during the analyze stage as it does today — no pause needed.

**When participants are available:**
1. Pipeline runs to completion (merge → frames → transcribe → diarize → analyze → export)
2. Claude maps SPEAKER_XX → participant names via conversational context
3. Vault note generated immediately
4. Speaker correction still accessible from detail panel for post-hoc corrections

**When no participant list:**
1. Pipeline runs through diarization, then pauses
2. Analyze stage status: `{completed: false, waiting: "speaker_review", error: null}`
3. Meeting card shows "Review Speakers" badge with pulsing gold dot
4. User assigns speaker names via inline UI
5. Pipeline resumes from analyze stage with corrected labels

### Pipeline Status Model

Add an optional `waiting` field to `PipelineStageStatus`:

```
// Python status.json
"analyze": {
  "completed": false,
  "waiting": "speaker_review",
  "timestamp": null,
  "error": null
}

// Rust types.rs
pub struct PipelineStageStatus {
    pub completed: bool,
    pub timestamp: Option<String>,
    pub error: Option<String>,
    pub waiting: Option<String>,  // NEW
}

// TypeScript tauri.ts
interface PipelineStageStatus {
  completed: boolean;
  timestamp: string | null;
  error: string | null;
  waiting: string | null;  // NEW
}
```

Frontend dot state logic: `completed` → done, `waiting` → pulsing gold, `error` → red, else → pending gray.

### Speaker Review UI (Option A: Inline in Transcript Tab)

- Warning banner at top of Transcript tab: "N of M speakers could not be identified. Assign names below, or skip to use generic labels."
- Speaker mapping section below banner: each `SPEAKER_XX` label with utterance count and a searchable dropdown
- Dropdown population: calendar event participants (if matched) + all known participants from past meetings (searchable) + manual name entry
- Two actions: "Apply & Resume Pipeline" and "Skip — Use Generic Labels"
- For already-completed meetings: same UI accessible from Transcript tab for post-hoc corrections (triggers re-analysis)

### Backend (Rust)

- `get_known_participants(recordings_dir)` — scans past meetings for unique participant names, returns sorted list
- `update_speaker_labels(recording_dir, corrections: Map<String, String>)` — writes corrections to `speaker_labels.json` alongside the recording, triggers `retry_processing(recording_dir, from_stage: "analyze")`

### Pipeline (Python sidecar)

- After diarization, check if `MeetingMetadata.participants` is empty
- If participants exist: continue to analyze (Claude maps speakers)
- If no participants: set analyze stage to `waiting: "speaker_review"`, exit
- On resume: read `speaker_labels.json`, inject names into transcript utterances, proceed with analysis

## Section 3: Meeting Notifications with Pre-Meeting Briefing

### Notification Trigger

- Periodic check against cached calendar data on app focus + configurable timer
- Configurable lead time: 5, 10, or 15 minutes before meeting (Settings)
- System tray notification via `tauri-plugin-notification`: meeting title, time, participant names
- Notification click opens briefing view (whole notification clickable — action buttons are mobile-only on Tauri)
- Route to `#meeting/{eventId}` with briefing panel visible

### Briefing Engine

Claude CLI (`claude --print --output-format json`) with a structured prompt in `prompts/meeting_briefing.md`.

Briefing prompt produces JSON with fields:
- `topics` — ongoing discussion threads across past meetings
- `action_items` — open items attributed to meeting attendees
- `context` — meeting frequency, duration trends, first-meeting flag
- `relationship_summary` — working relationship context and dynamics

Lookback window: last 4 meetings OR last 3 months with same company/participants, whichever is greater.

Data assembly (Rust):
- Query recordings dir for past meetings matching company or participant overlap
- Read vault notes for matched meetings
- Pass note content to Claude CLI via the briefing prompt

First-meeting fallback: calendar event description (available via `json+large` header). Briefing notes this is a first meeting and surfaces any agenda/description from the invitation.

### Briefing Cache

- Stored in Tauri app data dir, keyed by calendar event ID
- Invalidated when new meetings with the same participants complete processing
- Avoids repeated Claude CLI calls for the same upcoming meeting

### Frontend (Svelte)

- Briefing panel in meeting detail view (new tab or section)
- Also accessible from Calendar view → click upcoming meeting → "Meeting Prep" section
- Structured display: Topics, Action Items, Context, Relationship Summary
- Settings: notification toggle, lead time selector (5/10/15 min)

## Dependencies

- Section 0 (Theme) is independent — can parallel everything
- Section 1 (Calendar) blocks Section 3 (Notifications) — briefings need calendar data
- Section 2 (Speaker Correction) is independent — can parallel Section 1
- All sections depend on Phase 5b being complete (real data wiring established)

## Mockups

- `docs/mockups/speaker-review-options.html` — Speaker review UI options comparison
- `docs/mockups/theme-comparison.html` — Dark Default vs Dark Dimmed side-by-side
- `docs/mockups/theme-final.html` — Final Recap Dark palette applied to all views
- `docs/mockups/pipeline-pause-model.html` — Pipeline pause data model options comparison

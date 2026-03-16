# Recap — Implementation Plan

## What Recap Does

A Tauri desktop app that sits in your system tray, auto-detects and records meetings across Zoom, Teams, Google Meet, and Zoho Meet via platform APIs and URL interception, transcribes locally with Whisper+Pyannote on your RTX 4070, then uses Claude Code CLI to generate meeting notes with action items in your Obsidian vault, sync tasks to Todoist, and build/update people and company profiles — all browsable from a built-in dashboard.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Tauri Desktop App                     │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ System   │  │  Dashboard   │  │  Settings /       │  │
│  │ Tray     │  │  (Web UI)    │  │  OAuth Flows      │  │
│  │ + Hotkeys│  │              │  │                   │  │
│  └────┬─────┘  └──────┬───────┘  └───────────────────┘  │
│       │               │                                  │
│  ┌────┴───────────────┴──────────────────────────────┐  │
│  │              Core Orchestrator (Rust)              │  │
│  │  - Calendar polling (Zoho Calendar API)            │  │
│  │  - URL interception (deep links)                   │  │
│  │  - Meeting lifecycle management                    │  │
│  │  - Platform module dispatch                        │  │
│  └────┬──────────┬──────────┬───────────┬────────────┘  │
│       │          │          │           │                 │
│  ┌────┴───┐ ┌───┴────┐ ┌──┴─────┐ ┌──┴──────┐         │
│  │ Zoom   │ │ Teams  │ │ Google │ │ Zoho    │         │
│  │ Module │ │ Module │ │ Meet   │ │ Meet    │         │
│  │ (API)  │ │(URL/   │ │ Module │ │ Module  │         │
│  │        │ │ manual)│ │(URL/   │ │(URL/    │         │
│  │        │ │        │ │ manual)│ │ manual) │         │
│  └────────┘ └────────┘ └────────┘ └─────────┘         │
└─────────────────────┬───────────────────────────────────┘
                      │
                      │ Audio/Video files
                      ▼
┌─────────────────────────────────────────────────────────┐
│              Processing Pipeline (Python)                │
│                                                         │
│  1. Whisper large-v3 → raw transcript                   │
│  2. Pyannote 3.1 → speaker diarization                  │
│  3. Align speakers with roster from calendar invite      │
│  4. Extract frames from video for screen captures        │
│  5. Claude Code CLI → analysis subprocess:               │
│     - Generate meeting note (vault markdown)             │
│     - Extract action items → Todoist API                 │
│     - Create/update People & Company profiles            │
│     - Caption screenshots with AI analysis               │
└─────────────────────────────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────┐  ┌────────────────────┐
│       Obsidian Vault         │  │     Todoist        │
│  Work/Meetings/              │  │                    │
│  Work/People/                │  │  Action items with │
│  Work/Companies/             │  │  due dates, links  │
│                              │  │  back to vault     │
│  ◄── scheduled sync ──────────── completion status  │
└──────────────────────────────┘  └────────────────────┘
```

## Tech Stack

| Component | Technology | Notes |
|-----------|-----------|-------|
| Desktop app | Tauri v2 | System tray, global hotkeys, URL intercept, ~30MB RAM |
| Frontend | TBD (React/Svelte/Vue) | Dashboard UI — design phase later |
| Backend | Rust (Tauri) + Python (pipeline) | Rust for app shell, Python for ML pipeline |
| Transcription | Whisper large-v3 | Local, runs on RTX 4070 GPU |
| Speaker diarization | Pyannote 3.1 | Local, paired with Whisper |
| AI analysis | Claude Code CLI | Invoked as subprocess, not API |
| Task tracker | Todoist | Free tier, periodic sync back to vault |
| Calendar | Zoho Calendar API | Primary meeting source |
| Storage | Local filesystem | Recordings + vault on same machine |

## Platform Integration Strategy

| Platform | Day 1 | Future |
|----------|-------|--------|
| Zoom | Full API (events, recording, participants) | — |
| Teams | URL intercept + manual start | Full API if upgraded to Business account |
| Google Meet | URL intercept + manual start | Full API when Workspace admin approves |
| Zoho Meet | URL intercept + manual start | Full API when admin access granted |
| Signal | Not in v1 | Local audio capture (WASAPI/VB-Cable) |
| Discord | Not in v1 | Local audio capture (WASAPI/VB-Cable) |

## Meeting Detection (Three Layers)

1. **Platform API event subscriptions** — Primary. Zoom calls trigger webhooks automatically. Teams Graph API (if Business account) sends call events.
2. **Calendar polling** — Zoho Calendar API checked periodically. Upcoming meetings matched to platform, recording pre-staged.
3. **URL interception** — Fallback/catch-all. Tauri registers as handler for meeting URLs (zoom.us/j/*, meet.google.com/*, teams.microsoft.com/*). Clicking a link anywhere triggers recording + opens the meeting.

## Obsidian Vault Structure

```
Tim's Vault/
└── Work/
    ├── Meetings/
    │   ├── 2026-03-16 - Project Kickoff with Acme Corp.md
    │   └── 2026-03-15 - Weekly Standup.md
    ├── People/
    │   ├── Jane Smith.md
    │   └── Bob Jones.md
    └── Companies/
        └── Acme Corp.md
```

### Meeting Note Template (Universal Base + Conditional Sections)

```markdown
---
date: 2026-03-16
participants:
  - "[[Jane Smith]]"
  - "[[Bob Jones]]"
company: "[[Acme Corp]]"
platform: zoom
duration: 45m
recording: ../Recordings/2026-03-16-acme-kickoff.mp4
type: client-call
---

## Summary
[AI-generated 2-3 sentence summary]

## Key Points
[Discussion points organized by topic]

## Decisions Made                    ← conditional: only if decisions detected
[Decisions reached during meeting]

## Action Items
- [ ] Tim: Send proposal by Friday #todoist
- [ ] [[Jane Smith]]: Review budget numbers

## Follow-up Required               ← conditional: only if follow-ups detected
[Items needing future attention]

## Relationship Notes                ← conditional: only for 1:1 meetings
[Context about working relationship]

## Previous Meeting                  ← conditional: only for recurring meetings
[[2026-03-09 - Weekly Standup]]
Unresolved items from last time: ...

## Screenshots
![[2026-03-16-acme-kickoff-slide-01.png]]
[AI caption: Q3 revenue projections slide]
```

### People Profile (`Work/People/Jane Smith.md`)

```markdown
---
company: "[[Acme Corp]]"
role: VP of Engineering
email: jane@acme.com
---

## Key Topics
- Deeply interested in CI/CD pipeline improvements
- Owns the Q3 infrastructure budget

## Meeting History
[Automatic via Obsidian backlinks]

## Action Items (Assigned to Jane)
[Populated from meeting notes, synced with Todoist]
```

### Company Profile (`Work/Companies/Acme Corp.md`)

```markdown
---
industry: SaaS
key_contacts:
  - "[[Jane Smith]]"
  - "[[Bob Jones]]"
---

## Ongoing Themes
- Infrastructure modernization project (started Q1 2026)
- Budget approval cycles are slow

## Key Contacts
[Automatic via Obsidian backlinks]
```

## Speaker Recognition Strategy

**Phase 1 (v1): Roster-based**
- Calendar invite provides participant list
- Pyannote separates speakers by voice characteristics
- System maps Speaker 1/2/3 to roster names
- User can correct mismatches in the dashboard after processing

**Phase 2 (future): Passive voice fingerprinting**
- After multiple meetings with the same person, build a voice embedding profile
- System stores embeddings in a local database
- Over time, auto-identifies known speakers even in ad-hoc meetings without a roster

## Screen Capture

- Extract frames from video stream recording (not desktop screen capture)
- Periodic frame extraction during detected screen share segments
- Claude Code CLI analyzes screenshots during the analysis step
- Screenshots stored alongside recordings, embedded in meeting notes with AI captions
- OCR available on demand for specific screenshots (rare use case)

## Task Sync Flow

```
Meeting ends
    → Claude Code CLI extracts action items
    → Todoist API creates tasks (with labels, due dates, links to vault note)
    → Vault meeting note has checkbox items marked #todoist

Scheduled task (periodic):
    → Check Todoist API for completed items
    → Update corresponding vault checkboxes
    → Update People profiles (completed items assigned to them)
```

## Legal / Consent

- v1: Rely on platform recording notifications (Zoom, Teams, Meet, Zoho all show "Recording" indicators when their APIs are used)
- Revisit when adding Signal/Discord (no built-in notification — app would need to announce recording)

## Build Phases

### Phase 1: Research Spike
**Goal:** Validate that the core technical bets work before writing app code.

Research items:
- [ ] Zoom API: meeting event webhooks, cloud recording download, participant list endpoint
- [ ] Teams Graph API: what's available on personal accounts vs Business
- [ ] Google Meet API: recording capabilities, Workspace admin requirements
- [ ] Zoho Meet API: does a recording API exist? What admin permissions are needed?
- [ ] Zoho Calendar API: event polling, meeting link extraction
- [ ] Whisper + Pyannote pipeline: run a test transcription with diarization on RTX 4070
- [ ] WhisperX as potential simpler alternative to raw Whisper + Pyannote
- [ ] Tauri v2: system tray API, global hotkey API, deep link / URL protocol handler on Windows
- [ ] Todoist API: task creation, label support, completion polling
- [ ] Claude Code CLI: confirm subprocess invocation pattern works for batch analysis

### Phase 2: Core Pipeline (CLI-only, no UI)
**Goal:** End-to-end pipeline from audio file → vault notes + Todoist tasks.

- Python script that takes an audio/video file + meeting metadata JSON
- Runs Whisper transcription → Pyannote diarization → speaker alignment
- Invokes Claude Code CLI with transcript + prompt
- Outputs meeting note markdown to vault
- Creates Todoist tasks via API
- Creates/updates People and Company profiles

### Phase 3: Tauri App Shell
**Goal:** Background app with system tray, hotkeys, and settings.

- Tauri v2 project setup
- System tray icon with menu (start/stop recording, open dashboard, settings)
- Global hotkey for quick-start recording
- URL protocol handler registration for meeting links
- Settings page with OAuth flows for each platform + Todoist
- Local config storage (encrypted credentials)

### Phase 4: Zoom Integration
**Goal:** First fully-functional platform module.

- Zoom OAuth flow in settings
- Meeting event webhook subscription
- Cloud recording download after meeting ends
- Participant list extraction for roster-based diarization
- Trigger processing pipeline automatically

### Phase 5: Dashboard UI
**Goal:** Design and build the main app window.

- Frontend design phase (dedicated session)
- Call history list with search/filter
- Meeting detail view: notes, transcript, screenshots
- Recording playback (audio/video player)
- Upcoming meetings with recording status
- Manual recording controls

### Phase 6: Todoist Integration
**Goal:** Bidirectional task sync.

- Action items → Todoist (already in Phase 2 pipeline)
- Scheduled task: poll Todoist for completions → update vault checkboxes
- Labels/projects for organizing meeting tasks

### Phase 7: People & Company Profiles
**Goal:** AI-maintained relationship intelligence in the vault.

- Claude Code CLI prompt engineering for profile creation/updates
- Wikilink detection: link to existing vault notes when names mentioned
- Company profile aggregation across meetings
- Avoid duplicate profiles for the same person

### Phase 8: Remaining Platforms
**Goal:** Expand beyond Zoom.

- Teams: URL intercept + manual start (personal account limitations)
- Google Meet: URL intercept + manual start (pending admin access)
- Zoho Meet: URL intercept + manual start (pending admin access)
- Each platform follows the same pluggable module pattern as Zoom

### Phase 9 (Future)
- Signal/Discord local audio capture (WASAPI or VB-Cable)
- Voice fingerprinting / passive learning
- Real-time transcription during meetings
- Cloud storage for recordings

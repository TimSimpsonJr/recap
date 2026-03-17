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
| Frontend | Svelte + Vite + Tailwind | Lightweight, strong Tauri community, good for forms/lists/status UI |
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
- [x] Zoom API: meeting event webhooks, cloud recording download, participant list endpoint
- [x] Teams Graph API: what's available on personal accounts vs Business
- [x] Google Meet API: recording capabilities, Workspace admin requirements
- [x] Zoho Meet API: does a recording API exist? What admin permissions are needed?
- [x] Zoho Calendar API: event polling, meeting link extraction
- [x] Whisper + Pyannote pipeline: run a test transcription with diarization on RTX 4070
- [x] WhisperX as potential simpler alternative to raw Whisper + Pyannote
- [x] Tauri v2: system tray API, global hotkey API, deep link / URL protocol handler on Windows
- [x] Todoist API: task creation, label support, completion polling
- [x] Claude Code CLI: confirm subprocess invocation pattern works for batch analysis

### Phase 2: Core Pipeline (CLI-only, no UI)
**Goal:** End-to-end pipeline from audio file → vault notes + Todoist tasks.

- Python script that takes an audio/video file + meeting metadata JSON
- Runs Whisper transcription → Pyannote diarization → speaker alignment
- Invokes Claude Code CLI with transcript + prompt
- Outputs meeting note markdown to vault
- Creates Todoist tasks via API
- Creates/updates People and Company profiles

### Phase 3: Tauri App Shell
**Goal:** Background desktop app with system tray, URL protocol handling, OAuth for all platforms, encrypted credential storage, and settings UI.

**Design doc:** `docs/plans/2026-03-17-tauri-app-shell-design.md`

**Tech decisions:**
- Frontend: Svelte (lightweight, strong Tauri community adoption)
- Credentials: Tauri Stronghold (encrypted vault)
- Non-secret settings: tauri-plugin-store (plain JSON in AppData)
- Python integration: PyInstaller sidecar binary
- OAuth credentials: user-provided (no hardcoded client IDs/secrets)
- OAuth redirects: deep links for Zoom/Zoho/Todoist, localhost HTTP server for Google/Microsoft

**Scope:**
- Tauri v2 + Svelte + Vite + Tailwind project scaffolding (monorepo expansion)
- System tray icon with menu (Start/Stop Recording disabled, Open Dashboard, Settings, Quit)
- App starts minimized to tray, closing window hides to tray
- `recap://` URL protocol handler registration (OAuth callbacks, future meeting links)
- OAuth flows for all five platforms (Zoom, Google, Microsoft, Zoho, Todoist)
- Background token refresh with provider-specific lifetime handling
- Settings page: platform connections (with client credential fields), vault paths, recording folder, WhisperX settings, Todoist settings, about/diagnostics
- `tauri-plugin-autostart` included but disabled (enabled in final phase)
- PyInstaller sidecar build script + Tauri sidecar declaration + Rust invocation wrapper
- Existing `config.yaml` as read-only fallback for first-run defaults

### Phase 4: Zoom Integration
**Goal:** First fully-functional platform module.

- ~~Zoom OAuth flow in settings~~ (done in Phase 3)
- Meeting event webhook subscription
- Cloud recording download after meeting ends
- Participant list extraction for roster-based diarization
- Trigger processing pipeline via sidecar automatically

### Phase 5: Dashboard UI
**Goal:** Design and build the main app window.

- Frontend design phase (dedicated session)
- Call history list with search/filter
- Meeting detail view: notes, transcript, screenshots
- Recording playback (audio/video player — vidstack or native `<video>`)
- Upcoming meetings with recording status
- Manual recording controls

### Phase 6: Todoist Integration
**Goal:** Bidirectional task sync.

- ~~Todoist OAuth flow~~ (done in Phase 3)
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
- **Prerequisite:** local audio capture (WASAPI or virtual audio cable) must be implemented before non-Zoom platforms are functional — see open question below

**Open question — recording capture for non-Zoom platforms:** PLAN.md originally deferred local audio capture to Phase 9, but Teams/Google Meet/Zoho Meet all need it for recording since they lack API-based recording on personal/non-admin accounts. Options: (1) pull WASAPI/local capture into Phase 8, (2) implement screen/window recording, (3) require manual file drop. Decide when planning Phase 8.

### Phase 9 (Future)
- Signal/Discord local audio capture (WASAPI or VB-Cable) — may be partially addressed in Phase 8
- Voice fingerprinting / passive learning
- Real-time transcription during meetings
- Cloud storage for recordings

### Final Assembly
- Enable autostart (`tauri-plugin-autostart`)
- OAuth `state` parameter verification — currently generated but never checked on callback (CSRF hardening)
- End-to-end integration testing across all phases
- Distribution packaging and testing with friends

# Recap — Structural Map

## Stack

- **Desktop app:** Tauri v2 (Rust backend) + Svelte 5 + Tailwind CSS 4
- **ML pipeline:** Python (WhisperX, Pyannote 3.1, Claude via CLI)
- **Integrations:** Zoom, Google Meet, Teams, Zoho Meet (OAuth + APIs); Todoist (task sync)
- **Capture:** Windows WASAPI + Graphics Capture API + ffmpeg H.265 NVENC
- **Dashboard:** Vidstack (player), marked (markdown), d3-force (graph)
- **Browser extension:** Chrome/Edge MV3 for meeting URL detection + screen share signaling

## Structure

```
recap/
├── src/
│   ├── main.ts                            # Svelte mount point
│   ├── app.css                            # Tailwind base + Warm Ink dark theme
│   ├── App.svelte                         # Hash routing, top nav bar, OAuth listeners, calendar sync
│   ├── routes/
│   │   ├── Dashboard.svelte               # Split-panel: FilterSidebar | MeetingList + DetailPanel
│   │   ├── MeetingDetail.svelte           # Full meeting view: player, notes, transcript, screenshots
│   │   ├── Calendar.svelte                # Calendar view with upcoming/past events
│   │   ├── GraphView.svelte               # d3-force graph + controls panel + sidebar
│   │   └── Settings.svelte                # Provider connections, vault, recording, WhisperX config
│   └── lib/
│       ├── tauri.ts                       # Tauri IPC wrappers + TypeScript types for commands
│       ├── assets.ts / markdown.ts         # Asset URL helper + Obsidian-flavored markdown → HTML
│       ├── dummy-data.ts                  # Dev-only dummy data gated by VITE_DUMMY_DATA env var
│       ├── stores/
│       │   ├── credentials.ts             # Per-provider OAuth token state
│       │   ├── settings.ts                # App settings with Tauri persistence
│       │   ├── meetings.ts                # Meeting list, pagination, filters, resetMeetings, graphDataVersion
│       │   └── recorder.ts                # Recording state machine (idle → armed → detected → recording → processing)
│       └── components/                    # 30 Svelte components (see Key Relationships)
├── extension/                               # Chrome/Edge meeting detector extension
│   ├── manifest.json                        # MV3 manifest with meeting URL content scripts
│   ├── background.js                        # Tab URL matching + Recap localhost signaling
│   ├── content.js                           # Screen share detection via DOM observation
│   ├── options.html / options.js            # Custom meeting URL pattern configuration
│   └── icons/                               # Extension icons (16/48/128)
├── recap/                                 # Python ML pipeline
│   ├── pipeline.py                        # Stage-tracked orchestrator with status.json
│   ├── transcribe.py / frames.py          # WhisperX transcription + video frame extraction
│   ├── analyze.py / vault.py              # Claude analysis + Obsidian vault note writer
│   ├── todoist.py / models.py             # Task sync + data models
│   ├── config.py / cli.py                 # YAML config loader + CLI entry point
│   └── __main__.py                        # python -m recap entry
├── src-tauri/src/
│   ├── lib.rs                             # Plugin registration, tray, window state, IPC commands
│   ├── main.rs                            # Tauri entry point
│   ├── meetings.rs                        # Filesystem scanning, list/detail/search/filter/graph IPC
│   ├── calendar.rs                        # Zoho Calendar API, cache, event-recording matching
│   ├── briefing.rs                        # Claude CLI briefing generation with caching
│   ├── display.rs                         # Monitor enumeration for screen share settings
│   ├── notifications.rs                   # Pre-meeting desktop notification trigger
│   ├── oauth.rs / credentials.rs          # 5-provider OAuth + Stronghold credential store
│   ├── deep_link.rs                       # recap:// URI handler for OAuth callbacks
│   ├── sidecar.rs / diagnostics.rs        # Pipeline invocation + NVENC/ffmpeg checks
│   ├── tray.rs                            # System tray menu + hide-on-close behavior
│   └── recorder/                          # State machine: Idle → Armed → Detected → Recording → Processing
│       ├── mod.rs / recorder.rs           # Orchestrator: transitions states, owns capture handles,
│       │                                  #   handles MonitorEvents, enriches metadata on stop
│       ├── capture.rs / monitor.rs        # WASAPI audio + Graphics Capture; monitor polls EnumWindows
│       ├── types.rs                       # RecorderState, MeetingPlatform, PipelineStatus, CaptureSource
│       ├── listener.rs                    # Localhost HTTP listener for extension signals
│       ├── share_detect.rs                # Win32 screen share window detection
│       ├── zoom.rs                        # Zoom meeting metadata extraction
│       ├── google_meet.rs                 # Google Meet API client (Workspace admin)
│       ├── zoho_meet.rs                   # Zoho Meeting API client
│       └── teams.rs                       # Teams metadata (calendar + window title fallback)
├── prompts/                               # Claude prompt templates (analysis + briefing)
├── docs/plans/                            # Design specs + implementation plans per phase
├── scripts/build-sidecar.py               # Packages Python pipeline as Tauri sidecar
├── tests/                                 # Python tests (pytest): pipeline, transcribe, vault, etc.
├── config.example.yaml                    # Pipeline config template (see Implicit Contracts)
├── .reap/genome/                          # Cortex project genome (principles, conventions, constraints)
└── package.json / pyproject.toml          # JS + Python dependency manifests
```

## Key Relationships

- `App.svelte` routes `#meeting/{id}` → MeetingDetail, `#calendar` → Calendar, `#graph` → GraphView, `#settings` → Settings; auto-syncs calendar on focus (debounced 15 min)
- `Dashboard` renders FilterSidebar + MeetingList; clicking a row opens inline DetailPanel
- `MeetingDetail` composes Header, Player, Notes, Transcript, ScreenshotGallery, PipelineDots, SpeakerReview
- `BriefingPanel` calls Claude CLI through briefing.rs, results cached per event ID
- `MeetingTranscript` timestamp clicks seek `MeetingPlayer` (Vidstack) via shared time binding
- `markdown.ts` renders `[[wikilinks]]` as `<a href="#filter/participant/{name}">` for filtering
- `meetings.ts` store bridges IPC → derived `filteredMeetings`; invalidates briefing cache on pipeline-completed
- Calendar events matched to recordings via time overlap (calendar.rs ↔ meetings.rs)
- `extension/background.js` signals `listener.rs` via HTTP → `monitor.rs` events → `recorder.rs`
- `extension/content.js` detects screen sharing → `listener.rs` → capture source switch in `recorder.rs`
- `share_detect.rs` monitors Win32 windows for desktop share indicators → same capture switch path
- `recorder.rs::enrich_metadata()` routes to zoom.rs, google_meet.rs, zoho_meet.rs, or teams.rs based on MeetingPlatform
- `pipeline.py::extract_participants_from_screenshots()` is Claude vision fallback when APIs don't provide participants
- Calendar `auto_record` flags arm `recorder.rs` via periodic check in `lib.rs`
- `dummy-data.ts` provides mock data when `VITE_DUMMY_DATA=true`; tree-shaken out of prod builds
- `lib.rs` hides window on close (not quit); `oauth.rs` spawns localhost for Google/Microsoft OAuth
- `pipeline.py` writes `status.json` per stage; `--from`/`--only` flags enable retry from any stage

## Recorder State Machine

`recorder.rs` manages a 6-state lifecycle. Each transition emits `recorder-state-changed` to the frontend.

```
Idle ──(calendar arm)──→ Armed ──(meeting detected)──→ Recording
 │                         │ (no meeting within window)    │
 │                         └──→ Idle                       │ (user/tab stops)
 │                                                         ▼
 ├──(meeting detected)──→ Detected ──(user accepts)──→ Recording ──→ Processing ──→ Idle
 │                           │                             │
 │                           └──(user declines)──→ Declined ──(meeting ends)──→ Idle
```

- **Idle → Armed**: periodic check (60s) finds a calendar event with `auto_record=true` within lead time
- **Armed → Recording**: meeting detected (WASAPI or extension); skips notification, starts immediately
- **Idle → Detected**: WASAPI poll or extension signal finds a meeting; shows desktop notification
- **Detected → Recording**: user accepts notification, or timeout fires with `timeout_action: Record`
- **Recording → Processing**: recording stops (tab closed, process exited, user manual stop); triggers ffmpeg merge + metadata enrichment + sidecar launch
- **During Recording**: `SharingStarted`/`SharingStopped` events switch capture between Window and Display sources without state transition
- **Failure during Recording**: if capture crashes, logs error and transitions to Idle (no partial processing)

## Implicit Contracts

### status.json (per meeting directory)

Written by Python pipeline, read by Rust (`PipelineStatus` in types.rs) and Svelte (`PipelineDots` component). Each stage key maps to a `StageStatus` object:

```json
{
  "merge":      { "completed": true,  "timestamp": "2026-03-19T10:00:00Z", "error": null, "waiting": null },
  "frames":     { "completed": true,  "timestamp": "...", "error": null, "waiting": null },
  "transcribe": { "completed": true,  "timestamp": "...", "error": null, "waiting": null },
  "diarize":    { "completed": false, "timestamp": null,  "error": null, "waiting": null },
  "analyze":    { "completed": false, "timestamp": null,  "error": null, "waiting": "speaker_review" },
  "export":     { "completed": false, "timestamp": null,  "error": null, "waiting": null }
}
```

- `completed: true` = stage finished successfully
- `error: string` = stage failed; pipeline stops, retryable via `--from`
- `waiting: string` = stage paused for user action (e.g., `"speaker_review"` when no participants found)
- Stages always run in order: merge → frames → transcribe → diarize → analyze → export

### config.yaml (Python pipeline)

Read by `recap/config.py`, loaded once at pipeline start. Template at `config.example.yaml`. Required fields: `vault_path`, `recordings_path`, `frames_path`, `user_name`. Optional: `whisperx.*`, `huggingface_token`, `todoist.*`, `claude.command`. If missing or malformed, pipeline exits with a clear error message — the app creates this file during onboarding (Phase 7)

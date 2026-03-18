# Recap — Structural Map

## Stack

- **Desktop app:** Tauri v2 (Rust backend) + Svelte 5 + Tailwind CSS 4
- **ML pipeline:** Python (WhisperX, Pyannote 3.1, Claude via CLI)
- **Integrations:** Zoom, Google, Microsoft, Zoho, Todoist (OAuth flows)
- **Capture:** Windows WASAPI + Graphics Capture API + ffmpeg H.265 NVENC
- **Dashboard:** Vidstack (player), marked (markdown), d3-force (graph)

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
│       │   └── recorder.ts                # Recording state machine (idle → recording → processing)
│       └── components/                    # 30 Svelte components (see Key Relationships)
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
│   ├── notifications.rs                   # Pre-meeting desktop notification trigger
│   ├── oauth.rs / credentials.rs          # 5-provider OAuth + Stronghold credential store
│   ├── deep_link.rs                       # recap:// URI handler for OAuth callbacks
│   ├── sidecar.rs / diagnostics.rs        # Pipeline invocation + NVENC/ffmpeg checks
│   ├── tray.rs                            # System tray menu + hide-on-close behavior
│   └── recorder/                          # Monitor → capture → merge → zoom metadata → sidecar
│       ├── mod.rs / recorder.rs           # Public API + state machine orchestrator
│       ├── capture.rs / monitor.rs        # WASAPI audio + Graphics Capture screen recording
│       ├── types.rs                       # RecorderState enum + shared types
│       └── zoom.rs                        # Zoom meeting metadata extraction
├── prompts/                               # Claude prompt templates (analysis + briefing)
├── docs/plans/                            # Design specs + implementation plans per phase
├── scripts/build-sidecar.py               # Packages Python pipeline as Tauri sidecar
├── tests/                                 # Python tests (pytest): pipeline, transcribe, vault, etc.
└── package.json / pyproject.toml          # JS + Python dependency manifests
```

## Key Relationships

- `App.svelte` routes `#meeting/{id}` → MeetingDetail, `#calendar` → Calendar, `#graph` → GraphView, `#settings` → Settings; auto-syncs calendar on focus (debounced 15 min)
- `Dashboard` renders FilterSidebar + MeetingList; clicking a row opens inline DetailPanel
- `MeetingDetail` composes Header, Player, Notes, Transcript, ScreenshotGallery, PipelineDots, SpeakerReview
- `SpeakerReview` reads `waiting` field from PipelineStatus, writes speaker_labels.json via IPC
- `BriefingPanel` calls Claude CLI through briefing.rs, results cached per event ID
- `MeetingTranscript` timestamp clicks seek `MeetingPlayer` (Vidstack) via shared time binding
- `markdown.ts` renders `[[wikilinks]]` as `<a href="#filter/participant/{name}">` for filtering
- `meetings.ts` store bridges IPC → derived `filteredMeetings`; invalidates briefing cache on pipeline-completed
- Calendar events matched to recordings via time overlap (calendar.rs ↔ meetings.rs)
- Pipeline pauses at analyze when no participant list, resumes after speaker review
- `FilterSidebar` drives filter state; `RecordingSettings`/`VaultSettings` call `resetMeetings()` on path changes
- `dummy-data.ts` provides mock data when `VITE_DUMMY_DATA=true`; tree-shaken out of prod builds
- `notifications.rs` runs on 60s timer, reads calendar cache + settings, sends desktop notifications within lead time
- `lib.rs` hides window on close (not quit); `oauth.rs` spawns localhost for Google/Microsoft OAuth
- `recorder.rs` orchestrates monitor → capture → merge → zoom metadata → sidecar pipeline launch
- `pipeline.py` writes `status.json` per stage; `--from`/`--only` flags enable retry from any stage
- `GraphView` integrates GraphControls (d3 force sliders) + GraphSidebar (person/company drill-down)

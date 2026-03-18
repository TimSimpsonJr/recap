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
│   ├── App.svelte                         # Hash routing, top nav bar, OAuth listeners
│   ├── routes/
│   │   ├── Dashboard.svelte               # Split-panel: FilterSidebar | MeetingList
│   │   ├── MeetingDetail.svelte           # Full meeting view: player, notes, transcript, screenshots
│   │   ├── GraphView.svelte               # d3-force graph + controls panel + sidebar
│   │   └── Settings.svelte                # Provider connections, vault, recording, WhisperX config
│   └── lib/
│       ├── tauri.ts                       # Tauri IPC wrappers + TypeScript types for commands
│       ├── assets.ts                      # convertFileSrc helper for local asset URLs
│       ├── markdown.ts                    # Obsidian-flavored markdown → HTML (wikilinks, callouts)
│       ├── dummy-data.ts                  # Dev-only dummy data gated by VITE_DUMMY_DATA env var
│       ├── stores/
│       │   ├── credentials.ts             # Per-provider OAuth token state
│       │   ├── settings.ts                # App settings with Tauri persistence
│       │   ├── meetings.ts                # Meeting list, pagination, filters, derived filteredMeetings
│       │   └── recorder.ts                # Recording state machine (idle → recording → processing)
│       └── components/                    # 26 Svelte components (see Key Relationships)
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
│   ├── oauth.rs / credentials.rs          # 5-provider OAuth + Stronghold credential store
│   ├── deep_link.rs                       # recap:// URI handler for OAuth callbacks
│   ├── sidecar.rs / diagnostics.rs        # Pipeline invocation + NVENC/ffmpeg checks
│   ├── tray.rs                            # System tray menu + hide-on-close behavior
│   └── recorder/                          # Monitor → capture → merge → zoom metadata → sidecar
│       ├── mod.rs / recorder.rs           # Public API + state machine orchestrator
│       ├── capture.rs / monitor.rs        # WASAPI audio + Graphics Capture screen recording
│       ├── types.rs                       # RecorderState enum + shared types
│       └── zoom.rs                        # Zoom meeting metadata extraction
├── prompts/meeting_analysis.md            # Claude prompt template for meeting analysis
├── scripts/build-sidecar.py               # Packages Python pipeline as Tauri sidecar
├── tests/                                 # Python tests (pytest): pipeline, transcribe, vault, etc.
├── config.example.yaml                    # Sample pipeline config
├── vite.config.ts / tsconfig.json         # Vite + TypeScript build config
└── package.json / pyproject.toml          # JS + Python dependency manifests
```

## Key Relationships

- `App.svelte` routes `#meeting/{id}` → MeetingDetail, `#graph` → GraphView, `#settings` → Settings
- `Dashboard` renders FilterSidebar + MeetingList; clicking a row navigates to MeetingDetail route
- `MeetingDetail` composes Header, Player, Notes, Transcript, ScreenshotGallery, PipelineStatusBadge
- `MeetingTranscript` timestamp clicks seek `MeetingPlayer` (Vidstack) via shared time binding
- `markdown.ts` renders `[[wikilinks]]` as `<a href="#filter/participant/{name}">` for filtering
- `meetings.ts` store bridges IPC (list/search/filter) → derived `filteredMeetings` re-filters on change
- `FilterSidebar` drives filter state in meetings store; filters include date, participants, pipeline status
- `dummy-data.ts` provides mock data when `VITE_DUMMY_DATA=true`; tree-shaken out of prod builds
- `lib.rs` hides window on close (not quit), saves geometry; quit only via tray context menu
- `oauth.rs` spawns localhost server for Google/Microsoft; `deep_link.rs` handles `recap://` callbacks
- `recorder.rs` orchestrates monitor → capture → merge → zoom metadata → sidecar pipeline launch
- `pipeline.py` writes `status.json` per stage; `--from`/`--only` flags enable retry from any stage
- `GraphView` integrates GraphControls (d3 force sliders) + GraphSidebar (person/company drill-down)

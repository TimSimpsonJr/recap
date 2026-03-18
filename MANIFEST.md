# Recap — Structural Map

## Stack

- **Desktop app:** Tauri v2 (Rust backend) + Svelte 5 (plain, no SvelteKit) + Tailwind CSS 4
- **ML pipeline:** Python (Whisper large-v3, Pyannote 3.1)
- **AI analysis:** Claude Code CLI (subprocess)
- **Integrations:** Zoom, Google, Microsoft, Zoho, Todoist (OAuth flows)
- **Capture:** Windows WASAPI (dual audio), Graphics Capture API (video), ffmpeg (H.265 NVENC merge)
- **Dashboard:** Vidstack (video player), marked (markdown), d3-force (graph view)

## Structure

```
recap/
├── index.html                          # Vite entry point — loads src/main.ts
├── package.json                        # Node deps (Tauri plugins, Svelte, Tailwind)
├── vite.config.ts                      # Vite config — Svelte + Tailwind plugins
├── tsconfig.json                       # TypeScript config for plain Svelte
├── run_pipeline.py                     # PyInstaller entry point — imports recap.cli for sidecar bundling
├── scripts/
│   └── build-sidecar.py                # Builds PyInstaller sidecar → src-tauri/binaries/
├── src/
│   ├── main.ts                         # Mounts App.svelte to #app
│   ├── app.css                         # Global CSS — Tailwind import
│   ├── App.svelte                      # Root: hash routing (#meeting, #filter/participant), nav bar, OAuth listeners
│   ├── routes/
│   │   ├── Dashboard.svelte            # Split-panel: FilterSidebar | MeetingList | DetailPanel
│   │   ├── MeetingDetail.svelte        # Full-page detail view (legacy, kept for reference)
│   │   ├── GraphView.svelte            # Force-directed graph with controls panel + sidebar
│   │   └── Settings.svelte             # Full settings page — connections, vault, whisperx, etc.
│   └── lib/
│       ├── tauri.ts                    # Typed invoke() wrappers (OAuth, sidecar, diagnostics)
│       ├── assets.ts                   # Asset URL utility (convertFileSrc wrapper)
│       ├── markdown.ts                 # Obsidian markdown renderer (wikilinks → clickable participant links)
│       ├── stores/
│       │   ├── credentials.ts          # Stronghold-backed credential store (5 providers)
│       │   ├── settings.ts             # tauri-plugin-store backed app settings (incl. recording behavior)
│       │   ├── meetings.ts             # Meetings store — pagination, search, filters, IPC bridge
│       │   └── recorder.ts             # Recorder state store (event listener)
│       └── components/
│           ├── ProviderCard.svelte     # OAuth connection card (client ID/secret, connect/disconnect)
│           ├── SettingsSection.svelte  # Reusable section wrapper
│           ├── VaultSettings.svelte    # Vault path + folder config
│           ├── RecordingSettings.svelte # Recordings folder + HDD warning
│           ├── RecordingBehaviorSettings.svelte # Auto-detect, detection action, timeout config
│           ├── WhisperXSettings.svelte # Model, device, compute type, language
│           ├── TodoistSettings.svelte  # Project + labels
│           ├── GeneralSettings.svelte  # Autostart (disabled), notifications
│           ├── AboutSection.svelte     # Version, sidecar, ffmpeg, NVENC status
│           ├── SearchBar.svelte        # Debounced search input for meeting list
│           ├── FilterSidebar.svelte    # Collapsible sidebar — company, participant, platform filters
│           ├── MeetingList.svelte      # Paginated meeting list with selection support
│           ├── MeetingRow.svelte       # Single meeting row — title, date, status, selected state
│           ├── DetailPanel.svelte      # Inline detail panel — header, notes/transcript tabs, close button
│           ├── PipelineStatusBadge.svelte # Color-coded pipeline stage indicator
│           ├── RecordingStatusBar.svelte  # Live recording indicator bar
│           ├── RetryBanner.svelte      # Pipeline error retry prompt
│           ├── MeetingHeader.svelte    # Detail view header — title, date, metadata (optional back link)
│           ├── MeetingPlayer.svelte    # Vidstack video player wrapper
│           ├── MeetingNotes.svelte     # Rendered Obsidian markdown with clickable wikilinks
│           ├── MeetingTranscript.svelte # Timestamped transcript with seek support
│           ├── ScreenshotGallery.svelte # Grid gallery of extracted frames
│           ├── GraphControls.svelte    # Obsidian-style graph settings (filters, groups, display, forces)
│           └── GraphSidebar.svelte     # Graph slide-in sidebar — person/company meeting list + detail
├── recap/                              # Python ML pipeline package
│   ├── cli.py                          # CLI: process command with --from/--only stage restart
│   ├── pipeline.py                     # Orchestrator: stage-tracked pipeline with status.json
│   ├── config.py                       # YAML config loader + dataclasses
│   ├── transcribe.py                   # WhisperX transcription + diarization
│   ├── frames.py                       # Video frame extraction
│   ├── analyze.py                      # Claude Code CLI analysis subprocess
│   ├── meeting_note.py                 # Obsidian meeting note writer
│   ├── profiles.py                     # People/company profile stub writer
│   ├── todoist_sync.py                 # Todoist task creation from action items
│   └── previous.py                     # Previous meeting finder for context
└── src-tauri/
    ├── Cargo.toml                      # Rust deps: tauri plugins, windows crate, reqwest, tokio, chrono
    ├── tauri.conf.json                 # App config: deep-link, sidecar, window (hidden on start)
    ├── build.rs                        # Tauri build script
    ├── capabilities/
    │   └── default.json                # Permissions: core, stronghold, store, deep-link, autostart, shell, dialog, notification
    ├── icons/                          # App icons
    └── src/
        ├── main.rs                     # Entry point → recap_lib::run()
        ├── lib.rs                      # Tauri builder: plugins, tray, deep links, recorder state, IPC commands
        ├── tray.rs                     # System tray menu + recorder start/stop wiring
        ├── deep_link.rs                # recap:// URL handler, emits oauth-callback events
        ├── credentials.rs              # Provider types + placeholder IPC commands
        ├── oauth.rs                    # 5-provider OAuth: auth URLs, token exchange, localhost server
        ├── sidecar.rs                  # Pipeline sidecar invocation with metadata + stage restart support
        ├── diagnostics.rs              # NVENC/ffmpeg availability checks for About section
        ├── meetings.rs                 # Meetings module: filesystem scanning, IPC (list, detail, search, filters, graph)
        └── recorder/
            ├── mod.rs                  # Recorder module root — re-exports submodules
            ├── types.rs                # State machine types, pipeline stages, recording config
            ├── monitor.rs              # WASAPI audio session monitor — detects Zoom/Teams processes
            ├── capture.rs              # Dual audio (WASAPI loopback + mic) + video (Graphics Capture) capture
            ├── zoom.rs                 # Zoom REST API client — post-meeting metadata enrichment
            └── recorder.rs             # Orchestrator — lifecycle state machine, notifications, merge, sidecar
```

## Key Relationships

- `App.svelte` initializes stores on mount, routes `#meeting/{id}` and `#filter/participant/{name}` to Dashboard
- `Dashboard.svelte` renders split-panel: FilterSidebar | MeetingList (320px when detail open) | DetailPanel
- `DetailPanel.svelte` loads meeting detail inline — same content as MeetingDetail but without full-page navigation
- `MeetingRow.svelte` supports `isSelected` + `onSelect` for inline selection (no hash navigation)
- `GraphView.svelte` integrates `GraphControls` (force parameters, display toggles) and `GraphSidebar` (person/company drill-down)
- `GraphControls.svelte` sliders update d3 simulation forces in real-time via callback props
- `GraphSidebar.svelte` shows filtered meeting list for clicked person/company nodes, with inline detail view
- `markdown.ts` renders `[[wikilinks]]` as clickable `<a href="#filter/participant/{name}">` links
- `lib.rs` registers all plugins in `.setup()`, creates tray, manages `RecorderHandle` state, hides window on start
- `deep_link.rs` emits `oauth-callback` → `App.svelte` exchanges code via IPC → saves tokens via Stronghold
- `oauth.rs` `start_oauth` opens browser; for Google/Microsoft, spawns localhost server → exchanges code → emits `oauth-tokens`
- `credentials.ts` store wraps Stronghold JS API; `settings.ts` wraps tauri-plugin-store
- `meetings.rs` scans vault filesystem, exposes IPC commands → `meetings.ts` store consumes via typed invoke wrappers
- `FilterSidebar.svelte` drives filter state in `meetings.ts` store → triggers IPC re-fetch with filter params
- `MeetingTranscript.svelte` timestamp clicks seek `MeetingPlayer.svelte` (Vidstack) via shared time binding
- `recorder.ts` store listens for recorder events → `RecordingStatusBar.svelte` reflects live state
- `recorder.rs` orchestrates `monitor.rs` → `capture.rs` → ffmpeg merge → `zoom.rs` → `sidecar.rs`
- `pipeline.py` tracks stage completion in `status.json`; `cli.py` `--from`/`--only` flags skip completed stages
- Window close → hide (not quit); quit only via tray menu

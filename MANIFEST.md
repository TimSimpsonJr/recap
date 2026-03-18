# Recap — Structural Map

## Stack

- **Desktop app:** Tauri v2 (Rust backend) + Svelte 5 + Tailwind CSS 4
- **ML pipeline:** Python (Whisper large-v3, Pyannote 3.1, Claude Code CLI)
- **Integrations:** Zoom, Google, Microsoft, Zoho, Todoist (OAuth flows)
- **Capture:** Windows WASAPI + Graphics Capture API + ffmpeg H.265 NVENC
- **Dashboard:** Vidstack (player), marked (markdown), d3-force (graph)

## Structure

```
recap/
├── src/
│   ├── App.svelte                      # Root: hash routing, nav bar, OAuth listeners
│   ├── routes/
│   │   ├── Dashboard.svelte            # Split-panel: FilterSidebar | MeetingList | DetailPanel
│   │   ├── GraphView.svelte            # d3-force graph + controls panel + sidebar
│   │   └── Settings.svelte             # Provider connections, vault, recording, whisperx config
│   └── lib/
│       ├── tauri.ts / assets.ts / markdown.ts  # IPC wrappers, asset URLs, Obsidian markdown
│       ├── stores/                     # credentials, settings, meetings (pagination/filters), recorder
│       └── components/                 # 24 Svelte components (see Key Relationships)
├── recap/                              # Python ML pipeline
│   ├── pipeline.py                     # Stage-tracked orchestrator with status.json
│   ├── transcribe.py / frames.py       # WhisperX + video frame extraction
│   ├── analyze.py / meeting_note.py    # Claude analysis + Obsidian note writer
│   └── todoist_sync.py / profiles.py   # Task sync + people/company profiles
└── src-tauri/src/
    ├── lib.rs                          # Plugin registration, tray, window state, IPC commands
    ├── meetings.rs                     # Filesystem scanning, list/detail/search/filter/graph IPC
    ├── oauth.rs / credentials.rs       # 5-provider OAuth + Stronghold credential store
    ├── sidecar.rs / diagnostics.rs     # Pipeline invocation + NVENC/ffmpeg checks
    └── recorder/                       # Monitor → capture → merge → metadata → sidecar lifecycle
```

## Key Relationships

- `App.svelte` routes `#meeting/{id}` and `#filter/participant/{name}` → Dashboard with props
- `Dashboard` renders FilterSidebar | MeetingList (320px when detail) | DetailPanel (slide-in)
- `GraphView` integrates GraphControls (force sliders) + GraphSidebar (person/company drill-down)
- `markdown.ts` renders `[[wikilinks]]` as `<a href="#filter/participant/{name}">` links
- `meetings.ts` store bridges IPC (list/search/filter) with derived filteredMeetings store
- `lib.rs` hides window on close (not quit), saves window state; quit only via tray
- `oauth.rs` spawns localhost server for Google/Microsoft; `deep_link.rs` handles `recap://` callbacks
- `recorder.rs` orchestrates monitor → capture → merge → zoom metadata → sidecar pipeline
- `pipeline.py` writes `status.json` per stage; `--from`/`--only` flags enable retry from any stage
- `MeetingTranscript` timestamp clicks seek `MeetingPlayer` (Vidstack) via shared time binding
- `FilterSidebar` drives filter state in meetings store → `filteredMeetings` derived store re-filters

# Recap — Structural Map

## Stack

- **Desktop app:** Tauri v2 (Rust backend) + Svelte 5 + Tailwind CSS 4
- **ML pipeline:** Python (WhisperX, Pyannote 3.1, Claude via CLI)
- **Integrations:** Zoom, Google Meet, Teams, Zoho Meet (OAuth); Todoist (task sync)
- **Capture:** Windows WASAPI + Graphics Capture API + ffmpeg H.265 NVENC
- **Browser extension:** Chrome/Edge MV3 for meeting URL detection + screen share signaling

## Structure

```
├── src/
│   ├── App.svelte                         # Hash routing, nav bar, OAuth listeners, calendar sync
│   ├── app.css / main.ts                  # Tailwind dark theme + Svelte mount
│   ├── routes/                            # Dashboard, MeetingDetail, Calendar, GraphView, Settings
│   └── lib/
│       ├── tauri.ts                       # IPC wrappers + TypeScript types
│       ├── assets.ts / markdown.ts        # Asset URLs + Obsidian-flavored markdown → HTML
│       ├── dummy-data.ts                  # Dev-only mock data (VITE_DUMMY_DATA)
│       ├── stores/                        # credentials, settings, meetings, recorder
│       └── components/                    # 30+ Svelte components including:
│           ├── Onboarding.svelte          # 4-step first-run wizard (storage, vault, pipeline)
│           ├── SetupChecklist.svelte      # Dashboard checklist for optional integrations
│           └── ClaudeSettings.svelte      # Claude model + CLI path settings
├── extension/                             # MV3 meeting detector (manifest, background, content, options)
├── recap/                                 # Python ML pipeline
│   ├── pipeline.py                        # Stage-tracked orchestrator with status.json
│   ├── transcribe.py / frames.py          # WhisperX transcription + frame extraction
│   ├── analyze.py / vault.py              # Claude analysis + Obsidian vault writer
│   ├── todoist.py / models.py             # Task sync + data models
│   ├── errors.py                          # Maps exceptions to actionable Settings-referencing messages
│   ├── config.py / cli.py                 # YAML config loader + CLI entry
│   └── __main__.py                        # python -m recap entry
├── src-tauri/src/
│   ├── lib.rs / main.rs                   # Plugin registration, tray, window state, IPC commands
│   ├── meetings.rs                        # Filesystem scanning, list/detail/search/filter/graph
│   ├── calendar.rs                        # Zoho Calendar API, cache, event-recording matching
│   ├── briefing.rs                        # Claude CLI briefing generation with caching
│   ├── oauth.rs / credentials.rs          # 5-provider OAuth + Stronghold credential store
│   ├── config_gen.rs                      # Generates config.yaml from settings store + drive check
│   ├── sidecar.rs / diagnostics.rs        # Pipeline invocation + NVENC/ffmpeg checks
│   ├── display.rs / notifications.rs      # Monitor enumeration + pre-meeting notifications
│   ├── deep_link.rs / tray.rs             # recap:// URI handler + system tray
│   └── recorder/                          # 6-state machine: Idle→Armed→Detected→Recording→Processing
│       ├── mod.rs / recorder.rs           # Orchestrator: state transitions, capture, metadata enrichment
│       ├── capture.rs / monitor.rs        # WASAPI + Graphics Capture; EnumWindows polling
│       ├── types.rs / listener.rs         # Types + localhost HTTP listener for extension signals
│       ├── share_detect.rs                # Win32 screen share window detection
│       └── zoom.rs / google_meet.rs / zoho_meet.rs / teams.rs  # Per-platform metadata
├── prompts/                               # Claude prompt templates (analysis + briefing)
├── docs/plans/                            # Design specs + implementation plans per phase
├── tests/                                 # Pytest: pipeline, transcribe, vault, errors
│   └── test_errors.py                     # Tests for actionable error message mapping
├── scripts/build-sidecar.py               # Packages Python pipeline as Tauri sidecar
├── config.example.yaml                    # Pipeline config template
├── .reap/genome/                          # Cortex project genome
└── package.json / pyproject.toml          # JS + Python dependency manifests
```

## Key Relationships

- `App.svelte` routes to Dashboard, MeetingDetail, Calendar, GraphView, Settings; auto-syncs calendar on focus
- `Onboarding.svelte` gates app behind `onboardingComplete` setting; saves to settings store + Stronghold
- `SetupChecklist.svelte` derives completion from credentials store; opens same modals as Settings
- `config_gen.rs` generates `config.yaml` from settings store before sidecar launch; secrets as env vars
- `sidecar.rs` passes `HUGGINGFACE_TOKEN` and `TODOIST_API_TOKEN` as env vars to pipeline
- `errors.py` maps pipeline exceptions to actionable messages referencing Settings sections
- `extension/background.js` signals `listener.rs` → `monitor.rs` → `recorder.rs` state transitions
- `extension/content.js` + `share_detect.rs` detect screen sharing → capture source switch in `recorder.rs`
- `recorder.rs::enrich_metadata()` routes to platform-specific modules based on MeetingPlatform
- `pipeline.py` writes `status.json` per stage; `--from`/`--only` enable retry from any stage
- Calendar `auto_record` flags arm `recorder.rs` via periodic 60s check in `lib.rs`
- `MeetingTranscript` timestamp clicks seek `MeetingPlayer` (Vidstack) via shared time binding
- `markdown.ts` renders `[[wikilinks]]` as participant filter links
- **config.yaml:** auto-generated from settings store; secrets via env vars, not written to file
- **status.json:** per-meeting pipeline progress; stages: merge→frames→transcribe→diarize→analyze→export

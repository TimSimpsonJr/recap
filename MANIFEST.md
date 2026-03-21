# Recap — Structural Map

## Stack

- **Desktop app:** Tauri v2 (Rust backend) + Svelte 5 + Tailwind CSS 4
- **ML pipeline:** Python (WhisperX, Pyannote 3.1, Claude via CLI)
- **Integrations:** Zoom, Google Meet, Teams, Zoho Meet (OAuth via localhost:8399); Todoist (bidirectional sync); Zoho Calendar
- **Capture:** Windows WASAPI + Graphics Capture API + ffmpeg H.265 NVENC
- **Browser extension:** Chrome/Edge MV3 for meeting URL detection + screen share signaling

## Structure

```
├── src/
│   ├── App.svelte                         # Custom title bar, hash routing, nav, OAuth, calendar sync
│   ├── app.css / main.ts                  # Tailwind dark theme (focus-visible, responsive) + Svelte mount
│   ├── vite-env.d.ts                      # TypeScript declarations for SVG/asset imports
│   ├── routes/                            # Dashboard, MeetingDetail, Calendar, GraphView, Settings
│   └── lib/
│       ├── tauri.ts                       # IPC wrappers + TypeScript types
│       ├── assets.ts / markdown.ts        # Asset URLs + Obsidian-flavored markdown → HTML
│       ├── calendar-utils.ts              # Date helpers, event positioning, time grid layout
│       ├── reduced-motion.ts              # Reduced motion detection + transition helpers
│       ├── dummy-data.ts                  # Dev-only mock data (VITE_DUMMY_DATA)
│       ├── assets/logo.svg               # Recap logo SVG (title bar + onboarding)
│       ├── stores/                        # credentials, settings, meetings, recorder, toasts, selection, calendar
│       │   ├── calendar.ts               # Calendar event fetching, caching, auto-record matching
│       │   ├── toasts.ts                  # Toast notification store (success/error/info)
│       │   └── selection.ts              # Bulk selection state (select mode, selected IDs)
│       └── components/                    # 39 Svelte components including:
│           ├── Onboarding.svelte          # 4-step first-run wizard (storage, vault, pipeline)
│           ├── SetupChecklist.svelte      # Dashboard checklist for optional integrations
│           ├── Modal.svelte               # Accessible dialog (role=dialog, aria-modal, aria-labelledby)
│           ├── ProviderCard.svelte        # Provider OAuth modal with setup guides
│           ├── ParticipantPopover.svelte  # Meeting participant detail popover
│           ├── SettingsTooltip.svelte     # Keyboard-accessible settings info tooltips
│           ├── ToastContainer.svelte      # Accessible toast overlay (aria-live, auto-dismiss)
│           ├── RecordingStatusBar.svelte  # Recording state bar (aria-live status announcements)
│           ├── SkeletonLoader.svelte      # Loading skeleton with fade-in animation
│           ├── BulkActionBar.svelte       # Bulk operations bar (delete, reprocess, speaker fix)
│           ├── BulkSpeakerModal.svelte    # Bulk speaker rename across meetings
│           ├── RelinkNotesModal.svelte    # Vault note relink after path change
│           └── calendar/                  # Calendar sub-components
│               ├── DayView.svelte         # Single-day time grid with event blocks
│               ├── WeekView.svelte        # 7-day time grid with overlap handling
│               ├── MonthView.svelte       # Month grid with event chips
│               ├── EventPopover.svelte    # Calendar event quick-view popover
│               └── EventSidePanel.svelte  # Full event detail side panel
├── extension/                             # MV3 meeting detector (manifest, background, content, options)
├── recap/                                 # Python ML pipeline
│   ├── pipeline.py                        # Stage-tracked orchestrator with status.json
│   ├── transcribe.py / frames.py          # WhisperX transcription + frame extraction
│   ├── analyze.py / vault.py              # Claude analysis + Obsidian vault writer
│   ├── todoist.py / models.py             # Task sync (bidirectional) + data models
│   ├── errors.py                          # Maps exceptions to actionable Settings-referencing messages
│   ├── config.py / cli.py                 # YAML config loader + CLI entry
│   └── __main__.py                        # python -m recap entry
├── src-tauri/src/
│   ├── lib.rs / main.rs                   # Plugin registration, tray, decorations:false, IPC commands
│   ├── meetings.rs                        # Filesystem scanning, list/detail/search/filter/graph
│   ├── participants.rs                    # Participant metadata, speaker mapping, bulk operations
│   ├── calendar.rs                        # Multi-provider calendar API, token refresh, cache
│   ├── briefing.rs                        # Claude CLI briefing generation with caching
│   ├── oauth.rs                           # 5-provider OAuth with localhost:8399 redirect
│   ├── credentials.rs                     # AES-256-GCM encrypted SecretStore (machine-derived key)
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
├── tests/                                 # Pytest: pipeline, transcribe, vault, errors, and more
├── scripts/build-sidecar.py               # Packages Python pipeline as Tauri sidecar
├── config.example.yaml                    # Pipeline config template
├── .reap/genome/                          # Cortex project genome
└── package.json / pyproject.toml          # JS + Python dependency manifests
```

## Key Relationships

- `App.svelte` renders custom title bar (drag region + logo), routes pages, auto-syncs calendar on focus
- `calendar.ts` store fetches events from `calendar.rs`, caches them, matches against recordings for auto-record
- `calendar-utils.ts` provides layout math (time→Y, overlap columns) consumed by DayView/WeekView/MonthView
- `ParticipantPopover.svelte` reads `participants.rs` data; shown on hover in MeetingHeader/DetailPanel
- `ToastContainer.svelte` subscribes to `toasts.ts` store; auto-dismisses after timeout
- `selection.ts` drives `BulkActionBar.svelte`; `MeetingRow` checkboxes toggle selection state
- `BulkSpeakerModal.svelte` reads selection store → applies speaker renames via `participants.rs`
- `TodoistSettings.svelte` configures project grouping + completion sync; `todoist.py` handles bidirectional sync
- `SkeletonLoader.svelte` renders during data fetches; route transitions use Svelte fade/fly animations
- `Onboarding.svelte` gates app behind `onboardingComplete` setting; saves to settings store + SecretStore
- `credentials.rs` encrypts secrets with AES-256-GCM (machine-derived key via SHA-256)
- `oauth.rs` redirects all providers to `localhost:8399`; tokens stored via `credentials.rs` IPC commands
- `config_gen.rs` generates `config.yaml` from settings store before sidecar launch; secrets as env vars
- `extension/background.js` signals `listener.rs` → `monitor.rs` → `recorder.rs` state transitions
- `extension/content.js` + `share_detect.rs` detect screen sharing → capture source switch in `recorder.rs`
- `pipeline.py` writes `status.json` per stage; `--from`/`--only` enable retry from any stage
- `MeetingTranscript` timestamp clicks seek `MeetingPlayer` (Vidstack) via shared time binding
- **Responsive breakpoints:** `app.css` defines narrow/standard/wide; layout adapts (stacked vs side-by-side)
- **config.yaml:** auto-generated from settings store; secrets via env vars, not written to file

# Obsidian Plugin + Python Daemon — Architecture Redesign

## Goal

Replace the Tauri desktop app with two simpler components: a **headless Python daemon** that handles recording, ML processing, and integrations, and an **Obsidian community plugin** that provides the dashboard UI. The Python pipeline code carries over largely unchanged. The Svelte frontend is replaced by Obsidian plugin views. Rust is eliminated entirely.

## Why

Recap's UI exists to browse and manage meeting notes that live in an Obsidian vault. Running a separate desktop app for this creates friction — context-switching between Obsidian (where you work) and the Recap window (where you review). Moving the frontend into Obsidian puts meetings where your notes already are, and lets the plugin leverage Obsidian's Vault API, graph, search, and backlinks natively.

Tauri's value is its webview shell. Without the frontend, it's dead weight — the recording, OAuth, and system-level code are all custom Rust that can be replaced with Python equivalents. Consolidating to Python simplifies the build chain (no Rust toolchain, no Svelte/Vite, no sidecar bundling) and puts the entire backend in one language alongside the existing ML pipeline.

## Architecture

```
┌──────────────────────────────────────┐
│         Obsidian Plugin (TS)         │
│                                      │
│  Views:                              │
│    MeetingListView    (dashboard)    │
│    MeetingDetailView  (transcript,   │
│                        video, notes) │
│    CalendarView       (timeline)     │
│    GraphView          (D3 network)   │
│                                      │
│  Settings tab in Obsidian prefs      │
│  Ribbon icon for quick access        │
│  Status bar: recording state         │
│  Commands: start/stop, reprocess     │
│                                      │
│  Communicates with daemon via        │
│  localhost HTTP REST + WebSocket     │
└──────────────┬───────────────────────┘
               │
               │  localhost:9847
               │  REST  → commands, queries
               │  WS    → live status, recording state
               │
┌──────────────▼───────────────────────┐
│        recap-daemon (Python)         │
│                                      │
│  System tray (pystray)               │
│  HTTP API (aiohttp)                  │
│  WebSocket push (aiohttp)            │
│                                      │
│  Recording:                          │
│    Audio: pyaudiowpatch (WASAPI)     │
│    Screen: ffmpeg gdigrab/dshow      │
│    Encoding: ffmpeg hevc_nvenc       │
│                                      │
│  Meeting detection:                  │
│    pywin32 EnumWindows polling       │
│    Browser extension listener        │
│    Calendar polling (Zoho API)       │
│                                      │
│  OAuth server (localhost:8399)       │
│  Credential storage (keyring)        │
│                                      │
│  Pipeline (existing code):           │
│    transcribe.py  → WhisperX + GPU   │
│    frames.py      → ffmpeg scenes    │
│    analyze.py     → Claude CLI       │
│    vault.py       → Obsidian notes   │
│    todoist.py     → task sync        │
│                                      │
│  Config: config.yaml (unchanged)     │
│  State: status.json per meeting      │
└──────────────────────────────────────┘
```

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Drop Rust entirely | Yes | Recording can use pyaudiowpatch (WASAPI) + ffmpeg (screen). No native APIs require Rust. Eliminates Rust toolchain + Tauri dependency. |
| Backend language | Python only | ML pipeline is already Python. Adding recording + HTTP API to the same process avoids IPC complexity. One language, one build. |
| System tray | pystray | Lightweight, cross-platform tray library. Supports Windows icons, menus, click handlers. No framework needed. |
| HTTP framework | aiohttp | Async server with WebSocket support built in. Lightweight, no Django/Flask overhead. Already async-friendly for concurrent recording + API. |
| Audio capture | pyaudiowpatch | Python fork of PyAudio with WASAPI loopback support. Records system audio including meeting apps. Well-maintained, pip-installable. |
| Screen capture | ffmpeg gdigrab | ffmpeg's built-in Windows screen capture. Supports window targeting by title. GPU encoding via `-c:v hevc_nvenc`. No custom code needed — just subprocess. |
| Credential storage | keyring | Python keyring library — uses Windows Credential Manager on Windows. OS-native, no custom encryption. Replaces Tauri Stronghold. |
| Plugin UI framework | Obsidian ItemView + Setting API | Standard Obsidian plugin patterns. ItemView for custom panes (dashboard, detail). Setting API for config tab. |
| Plugin ↔ daemon auth | Shared token | Daemon generates a random token on first run, writes to config dir. Plugin reads it. All localhost requests include token header. Prevents other local apps from hitting the API. |
| Video playback | HTML5 `<video>` in ItemView | Obsidian plugin views are HTML — native video element works. Loses Vidstack features (chapter markers, HLS) but adequate for local MP4 playback. |
| Distribution | PyInstaller (daemon) + Obsidian community plugins (plugin) | Same sidecar bundling approach as today for the daemon. Plugin distributed via Obsidian's community plugin system or manual install. |

## What Carries Over

The Python pipeline is the core of the existing system and transfers with minimal changes:

| Module | Changes needed |
|--------|---------------|
| `pipeline.py` | None — orchestrator logic unchanged |
| `transcribe.py` | None |
| `frames.py` | None |
| `analyze.py` | None |
| `vault.py` | None — still writes markdown files to vault |
| `todoist.py` | None |
| `models.py` | None |
| `config.py` | Minor — add daemon port, auth token path |
| `cli.py` | Becomes daemon entry point instead of CLI-only |
| `errors.py` | None |

Existing `status.json` per-meeting tracking, `--from`/`--only` stage retry, and Todoist bidirectional sync all work as-is.

## What's New

### Python Daemon (`recap/daemon/`)

```
recap/daemon/
├── __init__.py
├── server.py          # aiohttp app: REST routes + WebSocket
├── routes.py          # API endpoint handlers
├── recorder.py        # Recording orchestrator (state machine)
├── audio.py           # pyaudiowpatch WASAPI loopback capture
├── screen.py          # ffmpeg gdigrab subprocess management
├── detection.py       # Meeting window detection (pywin32 EnumWindows)
├── calendar_poll.py   # Zoho Calendar API polling (port from Rust)
├── oauth.py           # OAuth flow server (port from Rust)
├── credentials.py     # keyring wrapper for token storage
├── tray.py            # pystray system tray icon + menu
└── extension.py       # Browser extension HTTP listener
```

#### HTTP API

```
GET  /api/status                  → daemon status, recording state
GET  /api/meetings                → meeting list (with search/filter params)
GET  /api/meetings/:id            → meeting detail (metadata + transcript + analysis)
GET  /api/meetings/:id/transcript → raw transcript JSON
GET  /api/meetings/:id/status     → pipeline status.json
POST /api/meetings/:id/reprocess  → re-run pipeline from stage
POST /api/meetings/:id/speakers   → save speaker label corrections
DELETE /api/meetings/:id          → delete meeting + artifacts

POST /api/record/start            → start recording
POST /api/record/stop             → stop recording

GET  /api/calendar/events         → upcoming calendar events
GET  /api/briefing/:meeting-id    → pre-meeting briefing

GET  /api/settings                → current config
PUT  /api/settings                → update config

GET  /api/oauth/:provider/status  → OAuth connection status
POST /api/oauth/:provider/start   → initiate OAuth flow
DELETE /api/oauth/:provider       → disconnect provider

WS   /api/ws                      → live updates:
                                     recording state changes
                                     pipeline stage progress
                                     meeting detection events
                                     calendar event notifications
```

All requests require `Authorization: Bearer <token>` header. Token is generated on first daemon start and stored in the config directory.

#### Recording State Machine

Same 6-state model as the Rust recorder, ported to Python:

```
Idle ──(calendar arm)──→ Armed ──(meeting detected)──→ Recording
 │                         │                              │ (stop)
 │                         └──(timeout)──→ Idle           ▼
 ├──(meeting detected)──→ Detected                    Processing ──→ Idle
                            │
                            ├──(accept)──→ Recording
                            └──(decline)──→ Idle
```

State transitions push events over the WebSocket to update the plugin's status bar in real time.

#### Audio Recording

```python
# pyaudiowpatch WASAPI loopback — captures all system audio
import pyaudiowpatch as pyaudio

p = pyaudio.PyAudio()
wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
# Find loopback device for meeting app's audio endpoint
# Record to WAV, ffmpeg merges + encodes after stop
```

Dual-stream capture (mic + system) uses two pyaudiowpatch streams writing to separate WAV files, merged by ffmpeg post-recording — same approach as the Rust recorder but in Python.

#### Screen Recording

```bash
# ffmpeg gdigrab — capture specific window by title
ffmpeg -f gdigrab -framerate 5 -i title="Zoom Meeting" \
       -c:v hevc_nvenc -preset p4 -cq 28 \
       -t 7200 output.mp4
```

Lower framerate (5fps) is fine for meeting content — we're capturing slides and screen shares, not gaming. Keeps file size reasonable and GPU load minimal. The `-i title=` flag targets the meeting window specifically.

For screen share detection: the browser extension already signals share state via HTTP. The daemon listens on the same localhost port as today and switches ffmpeg's capture target accordingly.

### Obsidian Plugin (`obsidian-recap/`)

```
obsidian-recap/
├── manifest.json
├── main.ts                    # Plugin entry: register views, commands, settings
├── styles.css                 # Plugin styles (dark mode inherits from Obsidian theme)
├── src/
│   ├── api.ts                 # HTTP/WS client for daemon communication
│   ├── settings.ts            # PluginSettingTab — daemon URL, paths, integrations
│   ├── views/
│   │   ├── MeetingListView.ts     # ItemView: meeting list + search + filters
│   │   ├── MeetingDetailView.ts   # ItemView: video + transcript + notes
│   │   ├── CalendarView.ts        # ItemView: calendar timeline
│   │   └── GraphView.ts           # ItemView: D3 relationship graph
│   ├── components/
│   │   ├── MeetingRow.ts          # Meeting list row (vanilla DOM or framework)
│   │   ├── TranscriptBlock.ts     # Clickable transcript with timestamps
│   │   ├── PipelineDots.ts        # Pipeline stage status indicators
│   │   ├── FilterSidebar.ts       # Company/platform/date filters
│   │   └── StatusBarItem.ts       # Recording state in Obsidian status bar
│   └── utils/
│       ├── markdown.ts            # Wikilink rendering (simplified — Obsidian handles most)
│       └── format.ts              # Duration, date, timestamp formatting
├── esbuild.config.mjs
├── package.json
└── tsconfig.json
```

#### Plugin Registration

```typescript
export default class RecapPlugin extends Plugin {
  async onload() {
    // Register custom views
    this.registerView(VIEW_MEETING_LIST, (leaf) => new MeetingListView(leaf, this));
    this.registerView(VIEW_MEETING_DETAIL, (leaf) => new MeetingDetailView(leaf, this));
    this.registerView(VIEW_CALENDAR, (leaf) => new CalendarView(leaf, this));
    this.registerView(VIEW_GRAPH, (leaf) => new GraphView(leaf, this));

    // Ribbon icon opens meeting list
    this.addRibbonIcon('mic', 'Recap', () => this.activateView(VIEW_MEETING_LIST));

    // Status bar shows recording state (updated via WebSocket)
    this.statusBar = this.addStatusBarItem();
    this.wsClient = new DaemonWebSocket(this.settings.daemonUrl);
    this.wsClient.on('recording_state', (state) => {
      this.statusBar.setText(state === 'recording' ? '⏺ Recording' : '');
    });

    // Commands
    this.addCommand({ id: 'open-dashboard', name: 'Open meeting dashboard', callback: ... });
    this.addCommand({ id: 'start-recording', name: 'Start recording', callback: ... });
    this.addCommand({ id: 'stop-recording', name: 'Stop recording', callback: ... });

    // Settings tab
    this.addSettingTab(new RecapSettingTab(this.app, this));
  }
}
```

#### Meeting List View

Replaces `Dashboard.svelte` + `MeetingList.svelte` + `FilterSidebar.svelte`. Fetches meetings from `GET /api/meetings` and renders in an Obsidian `ItemView`. Clicking a meeting opens `MeetingDetailView` with that meeting's ID.

Obsidian's native search can also find meeting notes directly (they're markdown files in the vault), but the list view provides the richer filtered/sorted experience with pipeline status indicators.

#### Meeting Detail View

Replaces `MeetingDetail.svelte` + `MeetingPlayer.svelte` + `MeetingTranscript.svelte`. Uses HTML5 `<video>` for playback. Transcript rendered as clickable timestamp blocks that seek the video. Screenshots displayed inline. Pipeline status dots shown at the top.

Speaker review (when participants are unknown) renders inline — the user corrects labels and the plugin POSTs to `/api/meetings/:id/speakers`, then triggers reprocessing.

#### Settings

Replaces `Settings.svelte` and all sub-settings components. Uses Obsidian's `PluginSettingTab` API:

- Daemon connection URL (default `http://localhost:9847`)
- Vault paths (meetings, people, companies folders)
- Recording storage path
- OAuth provider setup (opens browser for OAuth flow via daemon)
- WhisperX model selection
- Todoist configuration
- Claude CLI settings

Heavy settings (model downloads, OAuth flows) are delegated to the daemon — the plugin just triggers them via API and shows status.

## Recording Quality Comparison

| Aspect | Current (Rust) | Proposed (Python) | Impact |
|--------|---------------|-------------------|--------|
| Audio capture | Raw WASAPI via windows-rs | pyaudiowpatch WASAPI loopback | Equivalent — same underlying API |
| Screen capture | Graphics Capture API (window-level, hardware-accelerated) | ffmpeg gdigrab (GDI-based) | Lower quality. GDI is software-based, no hardware compositing. Fine for slides/screenshares at 5fps. |
| Encoding | In-process NVENC via nvenc-rs | ffmpeg subprocess with hevc_nvenc | Equivalent output. Slight overhead from subprocess but negligible. |
| Meeting detection | EnumWindows via windows-rs | EnumWindows via pywin32 | Equivalent — same Win32 call |
| Latency | ~50ms capture loop | ~100-200ms capture loop | Slightly higher. Python GIL + pyaudio callback overhead. Not perceptible for meeting recording. |
| Resource usage | ~30MB RAM (Rust binary) | ~80-150MB RAM (Python + deps) | Higher but acceptable. WhisperX already loads GBs during transcription. |

The main quality regression is screen capture: Graphics Capture API gives pixel-perfect window capture with DPI awareness, transparency support, and hardware compositing. ffmpeg gdigrab is a GDI screen scrape — it works but can miss window chrome, doesn't handle DPI scaling as well, and can't isolate a specific window as cleanly. For meeting content (slides, shared screens, video feeds) this is acceptable.

If screen capture quality becomes a problem, a small standalone Rust binary (~500 lines) could handle just the Graphics Capture → pipe-to-ffmpeg step, keeping the rest in Python. This is a surgical fallback, not a return to the full Tauri architecture.

## Migration Path

### Phase 1: Python daemon (core)

Build the daemon HTTP server, port meeting detection and recording from Rust to Python. Wire up the existing pipeline modules. Test end-to-end: detect meeting → record → transcribe → analyze → vault note.

**New dependencies:**
- `aiohttp` — HTTP server + WebSocket
- `pyaudiowpatch` — WASAPI audio capture
- `pywin32` — EnumWindows, window management
- `pystray` + `Pillow` — system tray icon
- `keyring` — OS credential storage

**Deliverable:** `python -m recap daemon` starts the tray icon + HTTP API. Recording and pipeline work headlessly. Can be tested via curl / browser.

### Phase 2: Obsidian plugin (read-only dashboard)

Scaffold the Obsidian plugin. Implement `MeetingListView` and `MeetingDetailView` talking to the daemon API. Read-only — browse meetings, play recordings, view transcripts.

**Deliverable:** Install plugin in Obsidian, see meeting list, click through to detail with video + transcript.

### Phase 3: Plugin controls + settings

Add recording controls (start/stop commands, status bar indicator). Port settings UI to Obsidian SettingTab. Add OAuth flow triggers. Add speaker review + reprocess. Wire up WebSocket for live status.

**Deliverable:** Full feature parity with current Tauri frontend.

### Phase 4: Calendar + graph views

Port CalendarView and GraphView into plugin ItemViews. These are the most complex UI components and benefit from being done last when the API is stable.

**Deliverable:** Complete replacement of Tauri app. Tauri code can be archived.

## Open Questions

1. **Plugin framework for views?** Obsidian plugin views are vanilla DOM manipulation. The current UI is 38 Svelte components. Vanilla TS is fine for simpler views (meeting list, settings) but the detail view with video + transcript sync + speaker review is complex. Options: vanilla TS (no deps, Obsidian-native), Svelte compiled to web components (reuse some existing code), or Preact (lightweight React-like, common in Obsidian plugins).

2. **Daemon lifecycle** — Should the daemon auto-start on Windows login (scheduled task / startup folder)? Or should the Obsidian plugin spawn it on load? Auto-start is better for meeting detection (catch meetings even before Obsidian is open), but adds install complexity.

3. **Daemon packaging** — PyInstaller single-file EXE (current sidecar approach) or require Python install? PyInstaller is simpler for the user but adds build complexity and ~200MB to the binary size (PyTorch + WhisperX). A conda/pip install is lighter but requires Python on the system.

4. **Browser extension** — Keep as-is? The extension currently signals a localhost HTTP endpoint. The daemon listens on the same port with the same protocol — the extension shouldn't need changes. Confirm by testing.

5. **Screen capture fallback** — If ffmpeg gdigrab proves insufficient, how much effort is a minimal Rust capture binary? Estimate: ~500 lines of Rust, outputs raw frames to a pipe, ffmpeg encodes. Worth spiking early to de-risk.

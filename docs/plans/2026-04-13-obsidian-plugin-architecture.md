# Obsidian Plugin + Python Daemon: Architecture Redesign

## Goal

Replace the Tauri desktop app with two components: a **Python daemon** that handles recording, ML processing, and integrations, and an **Obsidian plugin** that provides the dashboard UI. The Python pipeline carries over with modifications. Rust and Svelte are eliminated entirely. Audio only (no video).

## Why

Recap's UI exists to browse and manage meeting notes that live in an Obsidian vault. Running a separate desktop app creates friction: context-switching between Obsidian (where you work) and the Recap window (where you review). Moving the frontend into Obsidian puts meetings where your notes already are, and lets the plugin lean on Obsidian's Vault API, graph, search, and backlinks natively.

Without the frontend, Tauri is dead weight. The recording, OAuth, and system-level code are all custom Rust that can be replaced with Python equivalents. Consolidating to Python simplifies the build chain (no Rust toolchain, no Svelte/Vite, no sidecar bundling) and puts the entire backend in one language alongside the existing ML pipeline.

Dropping video simplifies further. Frame extraction, screen capture, NVENC encoding, and the browser extension's screen-share signaling all go away. The recording pipeline becomes: capture audio, write FLAC, transcribe, done.

## Architecture

```
                         Obsidian Vault (_Recap/)
                 ┌──────────────────────────────────────┐
                 │  Disbursecloud/Meetings/People/Tasks/ │
                 │  Personal/Meetings/People/Tasks/      │
                 │  Activism/Meetings/People/Tasks/      │
                 │  Calendar/Briefings/                  │
                 │  .recap/ (config, logs, status)       │
                 └──────────┬───────────┬───────────────┘
                            │           │
                  writes    │           │  reads
                 directly   │           │  (Vault API)
                            │           │
              ┌─────────────▼──┐  HTTP  ┌▼──────────────────┐
              │  recap-daemon  │◄──────►│  Obsidian Plugin   │
              │  (Python)      │  /WS   │  (TypeScript)      │
              │                │  local │                    │
              │  Detection     │  host  │  Meeting list view │
              │  Recording     │        │  Live transcript   │
              │  ML pipeline   │        │  Speaker correction│
              │  Calendar sync │        │  Status bar        │
              │  System tray   │        │  Settings tab      │
              │  OAuth flows   │        │  Recording controls│
              └────────────────┘        └────────────────────┘
```

### Critical path (daemon only, no Obsidian dependency)

Detect meeting, record audio, transcribe (Parakeet), diarize (NeMo), analyze (Claude CLI), write vault note + people/company stubs, update frontmatter status. **None of this requires Obsidian to be open.**

### Non-critical path (plugin)

Display recording state, browse meetings, speaker corrections, trigger reprocess, settings UI, live transcript during recording. If the plugin breaks, you lose the dashboard experience but never lose a recording.

### Communication

Daemon and plugin talk over HTTP REST + WebSocket on localhost. The daemon also listens on ports 17839-17845 for browser extension compatibility (same `/health` endpoint the extension already probes).

Most data flows through the vault filesystem. The daemon writes meeting notes, calendar notes, people/company stubs as markdown files. The plugin reads them via Obsidian's Vault API. The HTTP channel is only for commands (start/stop recording, reprocess, speaker corrections) and live state (recording status, pipeline progress via WebSocket).

Auth: daemon generates a random token on first run, writes it to `.recap/auth-token`. Plugin reads it. All HTTP requests include the token header.

### Error philosophy

**Fail loud, fail fast, fail informatively.** Every failure surfaces visibly: tray notification (Windows native toast, respects Focus Assist), frontmatter `pipeline-status: failed:stagename`, human-readable error message explaining what went wrong and what to do. No silent failures anywhere.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Drop Rust/Tauri | Yes | Recording can use PyAudioWPatch (WASAPI) + pyFLAC. No native APIs require Rust. |
| Drop video/screen capture | Yes | Audio-only simplifies recording, encoding, and pipeline. Frame extraction goes away. |
| Backend language | Python only | ML pipeline is already Python. One language, one build. |
| Audio capture | PyAudioWPatch | WASAPI loopback, dual-channel interleaved stream (mic + system in one stream). |
| Recording format | FLAC (real-time via pyFLAC) | ~60% smaller than WAV, lossless, streams in real-time. |
| Archive format | AAC | ~25MB/hr, plays everywhere (including iOS). Converted after pipeline completes. |
| Transcription | NVIDIA Parakeet 0.6B (NeMo) | SOTA accuracy, fits 12GB VRAM (~2-3GB), streaming capable. |
| Diarization | NeMo Sortformer | Sequential with transcription, unload between to share VRAM. |
| Fallback ASR stack | WhisperX + Pyannote 3.1 | If Parakeet/NeMo has issues, swap back. One-file change (transcribe.py). |
| Real-time transcription | Streaming Parakeet + NeMo | Live transcript during meetings. Best-effort preview; post-meeting pipeline is source of truth. |
| LLM analysis | Claude CLI (`claude --print`) | Permitted under Consumer ToS for personal scripted use. |
| LLM backend | Pluggable per-org | Claude CLI default. Ollama for activism org (transcripts can't leave machine). |
| HTTP framework | aiohttp | Async HTTP + WebSocket. Lightweight. |
| OAuth | Authlib | Auto token refresh, PKCE, handles lifecycle. localhost callback on top. |
| Credentials | keyring | Windows Credential Manager natively. Replaces Tauri Stronghold. |
| System tray | pystray | Recording controls (start/stop with org picker), status, quit. |
| Notifications | Windows native toast | Respects Focus Assist / DND. Pipeline completion, errors, silence detection. |
| Plugin framework | Vanilla TypeScript | Views are simple enough that a framework adds more weight than value. |
| Calendar | Hybrid sync into vault | API fetches events, writes as vault notes. Full Calendar plugin renders them. |
| Tasks | Obsidian Tasks inline format | `- [ ]` checkboxes with emoji metadata in meeting notes. Dataview queries for dashboards. |
| People/company notes | Claude Desktop enrichment | Scheduled task updates notes with integrated insights, not blind appends. |
| Briefings | Claude Desktop scheduled task | Morning daily task, appends briefing to today's calendar/meeting notes. |
| Packaging | PyInstaller (folder mode) | Fast builds, proven with PyTorch. |
| Daemon lifecycle | Hybrid | Plugin spawns daemon. Opt-in auto-start via Windows Task Scheduler. |
| Meeting detection | EnumWindows + extension + calendar | Three signal layers. UIA enrichment for Teams metadata. |

## Vault Structure

```
_Recap/
├── Disbursecloud/
│   ├── Meetings/
│   ├── People/
│   ├── Companies/
│   └── Tasks/
├── Personal/
│   ├── Meetings/
│   ├── People/
│   └── Tasks/
├── Activism/
│   ├── Meetings/
│   ├── People/
│   └── Tasks/
├── Calendar/
│   └── Briefings/
└── .recap/
    ├── config.yaml
    ├── auth-token
    ├── logs/            # 7-day retention, auto-rotated
    ├── rename-queue.json
    └── status/          # per-meeting status.json files
```

### Organization routing

| Source | Default org | Behavior |
|--------|-------------|----------|
| Zoho Calendar | Disbursecloud | Auto-record |
| Google Calendar | Personal (configurable per calendar) | Auto-record |
| Unscheduled Teams | Disbursecloud | Auto-record |
| Signal | Personal | Popup: choose org + pipeline backend |
| Manual tray recording | Configurable | Org picker in tray menu |

## Note Formats

### Meeting notes (calendar event = meeting note)

Calendar sync creates the note. Briefing appends to it. Pipeline appends after recording. One note, one meeting, evolving lifecycle.

```yaml
---
date: 2026-04-14
time: "14:00-15:00"
title: Sprint Planning
participants: ["[[Tim]]", "[[Jane Smith]]", "[[Bob Lee]]"]
companies: ["[[Acme Corp]]"]
platform: teams
duration: 45m
recording: "[[2026-04-14-sprint-planning.m4a]]"
type: standup
tags: ["meeting/standup"]
org: disbursecloud
calendar-source: zoho
event-id: "abc123"
pipeline-status: complete
pipeline-error:
---

## Agenda
<!-- from calendar event description -->

## Briefing
<!-- appended by Claude Desktop morning task -->

## Meeting Record
<!-- everything below here written by pipeline -->

## Summary

## Key Points

## Decisions

## Action Items

- [ ] Tim: Send proposal by Friday 📅 2026-04-18 ⏫
- [ ] [[Jane Smith]]: Review budget numbers 📅 2026-04-21

## Follow-ups
```

**Append guard:** the daemon checks if `## Meeting Record` marker exists. If it does (reprocess), replace everything below it. If it doesn't (first run), append it. Content above the marker (agenda, briefing, manual notes) is never touched.

**File renames:** if a calendar event's date changes, the daemon updates frontmatter but queues the file rename. The plugin processes the queue via Obsidian's Vault API so wikilinks update automatically.

### People/company stubs

Created by the pipeline for new people/companies. Existing notes are left alone (backlinks from meeting frontmatter handle the linking). A Claude Desktop scheduled task (3x daily: after briefing, 1pm, 6pm) reads new meeting context and integrates insights into existing people/company notes.

### Task dashboard

A query note per org (e.g., `_Recap/Disbursecloud/Tasks/My Tasks.md`):

````markdown
```tasks
not done
path includes _Recap/Disbursecloud/Meetings
sort by due
```
````

## Daemon Architecture

```
recap-daemon/
├── server.py              # aiohttp: REST + WebSocket + extension listener
├── recorder/
│   ├── state_machine.py   # Idle → Armed → Detected → Recording → Processing
│   ├── audio.py           # PyAudioWPatch: dual-channel interleaved FLAC stream
│   ├── detection.py       # EnumWindows (Teams, Zoom, Signal), browser extension listener
│   ├── silence.py         # Audio level monitoring, 5-min silence → prompt to end
│   └── enrichment.py      # UIA for Teams participant extraction, known contacts matching
├── streaming/
│   ├── transcriber.py     # Streaming Parakeet for real-time transcript
│   └── diarizer.py        # Streaming NeMo Sortformer for real-time speaker labels
├── pipeline/
│   ├── pipeline.py        # Stage orchestrator, status.json + frontmatter updates
│   ├── transcribe.py      # Parakeet 0.6B batch (post-meeting, if streaming failed)
│   ├── diarize.py         # NeMo Sortformer batch (post-meeting, if streaming failed)
│   ├── analyze.py         # Claude CLI (pluggable: claude | ollama per org)
│   ├── vault.py           # Meeting note writer, people/company stubs, org routing
│   └── audio_convert.py   # FLAC → AAC post-pipeline, FLAC deletion (when configured)
├── calendar/
│   ├── sync.py            # Zoho/Google API polling, vault note writer
│   └── oauth.py           # Authlib flows, localhost callback, keyring storage
├── tray.py                # pystray: icon, menu (start/stop/org picker), Windows toast
├── config.py              # Org definitions, calendar mapping, detection config
├── credentials.py         # keyring wrapper
└── errors.py              # Actionable error messages (carried over)
```

### Recording state machine

```
Idle ──(calendar arm)──→ Armed ──(meeting detected)──→ Recording
 │                         │                              │
 │                         └──(timeout)──→ Idle           │ (window close OR
 │                                                        │  silence timeout OR
 ├──(meeting detected)──→ Detected                        │  manual stop OR
 │   (Teams/Zoom: auto)     │                             │  max duration)
 │   (Signal: popup)        │                             ▼
 │                          ├──(accept)──→ Recording   Processing ──→ Idle
 │                          └──(decline)──→ Idle
 │
 └──(manual start via tray/plugin)──→ Recording
```

### Meeting end detection (3 layers)

1. **Window monitoring** (pywin32 EnumWindows): meeting window closes → immediate stop
2. **Audio silence detection**: audio below noise threshold for 5 minutes → tray prompt "Still in a meeting?" → auto-stop after another 5 minutes if no response
3. **Max duration backstop**: hard cutoff at 4 hours, warning at 3 hours

### Sequential GPU usage

Parakeet loads (~2-3GB VRAM), transcribes, unloads (`del model; torch.cuda.empty_cache()`). Then NeMo Sortformer loads, diarizes, unloads. Stays within 12GB RTX 4070.

If real-time streaming transcription + diarization completed without errors during the meeting, skip batch transcription/diarization and go straight to the analyze stage. FLAC is kept as insurance until the full pipeline completes.

### Audio lifecycle

1. During recording: PyAudioWPatch → pyFLAC stream → disk (continuous flush)
2. After transcription + diarization succeed: convert FLAC → AAC
3. Delete FLAC (configurable; keep during development)
4. Long-term: AAC only (~25MB/hr)

### Teams metadata enrichment

Best-effort, never blocks recording:

1. UIA (Python-UIAutomation) walks Teams accessibility tree for participant names + chat/meeting title
2. Match against known contacts list in config
3. If UIA fails: fall back to window title parsing, no error, no noise
4. Unidentified speakers after diarization → speaker correction modal in plugin

### Signal call handling

EnumWindows detects Signal window → popup dialog:

```
Signal call detected. Record?
Org:      [Personal     ▼]
Pipeline: [Local only   ▼]
[ Skip ]              [ Record ]
```

Defaults configurable in settings. Pipeline choice determines LLM backend (Claude CLI or Ollama).

## Plugin Architecture

```
obsidian-recap/
├── manifest.json
├── main.ts
├── styles.css
├── src/
│   ├── api.ts                     # HTTP + WebSocket client for daemon
│   ├── settings.ts                # PluginSettingTab: daemon config, orgs, calendar mapping
│   ├── views/
│   │   ├── MeetingListView.ts     # ItemView: Dataview-powered meeting list with filters
│   │   ├── LiveTranscriptView.ts  # ItemView: real-time streaming transcript via WebSocket
│   │   └── SpeakerCorrectionModal.ts
│   ├── components/
│   │   ├── MeetingRow.ts
│   │   ├── FilterBar.ts           # Org/date/type/pipeline-status filters
│   │   ├── PipelineStatus.ts      # Reads frontmatter, renders status
│   │   └── StatusBarItem.ts       # Recording state + daemon connection
│   └── utils/
│       └── format.ts
├── esbuild.config.mjs
├── package.json
└── tsconfig.json
```

### Plugin responsibilities

- **Meeting list view**: Dataview-powered query across org subfolders, filterable
- **Live transcript view**: WebSocket feed from daemon during recording
- **Speaker correction modal**: audio clip playback per speaker, name autocomplete from People notes + known contacts, sends corrections to daemon, triggers re-export
- **Status bar**: daemon connection state + recording state (idle/recording/processing), recording start/stop controls
- **Settings tab**: reads/writes daemon config via HTTP (orgs, calendar mapping, detection, known contacts)
- **Commands**: open dashboard, start/stop recording, trigger reprocess, open live transcript
- **Ribbon icon**: opens meeting list view
- **File rename processing**: reads `.recap/rename-queue.json`, renames via Vault API so Obsidian updates wikilinks
- **Daemon not running**: status bar shows "Daemon offline", recording controls disabled, "Start daemon" command available

### What the plugin does NOT do

- No meeting detail view (the note IS the detail view)
- No calendar view (Full Calendar plugin)
- No graph view (Obsidian's built-in graph)
- No audio playback UI (Obsidian's native `![[file.m4a]]` embed)

### Dependency on Dataview

The meeting list view uses Dataview's API to query meeting note frontmatter across all org subfolders. This is a hard dependency on the Dataview community plugin being installed.

## Error Handling

### Daemon startup validation

| Check | On failure |
|-------|-----------|
| GPU / CUDA available | Toast: "No GPU detected". Daemon starts (calendar/detection still work). |
| Models downloaded | Toast: "Models not downloaded, run setup". Block pipeline, allow recording. |
| Vault path exists | Toast: "Vault path not found". Refuse to start. |
| Keyring accessible | Toast: "Cannot access credential store". Start without OAuth. |
| Audio devices available | Toast: "No audio capture device". Disable recording. |

### During recording

| Failure | Response |
|---------|---------|
| Audio stream drops | Flush to FLAC, attempt reconnect. Toast: "Audio interrupted, partial recording saved". |
| Daemon crash | pyFLAC flushes continuously. On restart, detect orphaned FLACs: "Incomplete recording found, process anyway?" |
| Disk full | Check before recording (warn < 1GB). If fills mid-recording, stop gracefully + toast. |
| Streaming transcription fails | FLAC continues. Live transcript shows error. Post-meeting pipeline runs normally. |

### Pipeline

| Failure | Response |
|---------|---------|
| Any stage fails | Frontmatter: `pipeline-status: failed:stagename`. `pipeline-error` with actionable message. Toast notification. One auto-retry. |
| Second failure | Toast: "Pipeline failed for [title]: [stage]: [error]". Manual retry required via plugin or tray. |
| Claude CLI timeout | Auto-retry once with backoff. No repeated retries. |

### Plugin to daemon

| Failure | Response |
|---------|---------|
| WebSocket disconnects | Status bar: "Daemon disconnected". Auto-reconnect every 10s. |
| HTTP request fails | Error shown in context. No silent swallowing. |
| Daemon not running | Status bar: "Daemon offline". Recording controls disabled. |

### Calendar sync

| Failure | Response |
|---------|---------|
| Token expired | Authlib auto-refresh. If refresh fails: toast "Calendar disconnected, re-authenticate". |
| API rate limited | Back off, retry. Toast only if failing > 1 hour. |
| File rename queued | Persisted to `.recap/rename-queue.json`. Plugin processes on connect. |

### Recording resilience

- pyFLAC flushes audio to disk continuously (not buffered until stop)
- Daemon crash loses at most a few seconds of audio
- On restart, orphaned FLAC files are detected and surfaced
- FLAC kept as insurance until pipeline completes successfully

### Logging

All events logged to `.recap/logs/recap.log`. `TimedRotatingFileHandler` with 7-day retention, auto-purged on daemon startup. Plugin has a notification history view for events that occurred while Obsidian was closed.

## Claude Desktop Scheduled Tasks

Two scheduled tasks, separate from the daemon:

### Morning briefing (daily)

- Checks today's calendar notes in the vault
- For each meeting: finds past meeting notes with overlapping participants
- Appends `## Briefing` section to the meeting note (open action items, key context, relationship notes)
- Writes a digest note to `_Recap/Calendar/Briefings/` listing all upcoming meetings

### Note enrichment (3x daily: after briefing, 1pm, 6pm)

- Checks for new meeting notes since last run
- For each new meeting: reads existing people/company notes, sends to Claude with new meeting context
- Claude integrates insights into existing notes (not blind appends)
- Creates stubs for new people/companies

## Configuration

### Daemon config (`_Recap/.recap/config.yaml`)

```yaml
config-version: 1

vault-path: "C:/Users/tim/OneDrive/Documents/Tim's Vault"
recordings-path: "D:/Recordings/Recap"

orgs:
  disbursecloud:
    subfolder: "_Recap/Disbursecloud"
    llm-backend: claude
    default: true
  personal:
    subfolder: "_Recap/Personal"
    llm-backend: claude
  activism:
    subfolder: "_Recap/Activism"
    llm-backend: ollama

calendars:
  zoho:
    org: disbursecloud
  google:
    default-org: personal

detection:
  teams:
    enabled: true
    behavior: auto-record
    default-org: disbursecloud
  zoom:
    enabled: true
    behavior: auto-record
    default-org: disbursecloud
  signal:
    enabled: true
    behavior: prompt
    default-org: personal
    default-backend: ollama

known-contacts:
  - name: Jane Smith
    display-name: "Jane Smith"
  - name: Bob Lee
    display-name: "Bob L."

recording:
  format: flac
  archive-format: aac
  delete-source-after-archive: false
  silence-timeout-minutes: 5
  max-duration-hours: 4

pipeline:
  transcription-model: "nvidia/parakeet-tdt-0.6b-v2"
  diarization-model: "nvidia/diar_streaming_sortformer_4spk-v2.1"
  auto-retry: true
  max-retries: 1

calendar-sync:
  interval-minutes: 15
  sync-on-startup: true

logging:
  path: "_Recap/.recap/logs"
  retention-days: 7

daemon:
  extension-port-start: 17839
  extension-port-end: 17845
  plugin-port: 9847
  auto-start: false
```

### Plugin settings

Stored in Obsidian's plugin settings (`.obsidian/plugins/obsidian-recap/data.json`):

- Daemon URL (default `http://localhost:9847`)
- Org visibility filters
- UI preferences

Heavy settings (calendar mapping, detection config, known contacts) read/written to daemon config via HTTP.

## Migration

### Carries over

| Module | Changes |
|--------|---------|
| `models.py` | None |
| `analyze.py` | Pluggable backend param (claude/ollama) |
| `vault.py` | Org subfolder routing, Obsidian Tasks emoji format, append-below-marker logic, no frames section |
| `errors.py` | None |
| `prompts/meeting_analysis.md` | Remove screenshot references |

### New

| Module | Purpose |
|--------|---------|
| `recap/daemon/` | HTTP server, recorder, detection, streaming, calendar sync, tray, credentials |
| `recap/pipeline/transcribe.py` | Rewrite: Parakeet 0.6B instead of WhisperX |
| `recap/pipeline/diarize.py` | New: NeMo Sortformer (was bundled in WhisperX) |
| `recap/pipeline/audio_convert.py` | FLAC to AAC conversion |
| `obsidian-recap/` | Entire Obsidian plugin |

### Dropped

| Component | Why |
|-----------|-----|
| `src-tauri/` | Replaced by Python daemon |
| `src/` (Svelte frontend) | Replaced by Obsidian plugin |
| `recap/frames.py` | Audio only |
| `recap/todoist.py` | Tasks in Obsidian |
| `recap/transcribe.py` | Rewritten for Parakeet |
| `scripts/build-sidecar.py` | Replaced by PyInstaller |
| `prompts/participant_extraction.md` | No screenshots; UIA + known contacts replaces this |

### Browser extension

Strip down to meeting URL detection only. Remove screen share signaling content scripts (audio only, no screen capture). Extension otherwise unchanged; daemon listens on same port range.

### Dependencies

**Adding:** PyAudioWPatch, pyFLAC, NeMo, Parakeet, aiohttp, pystray, Pillow, keyring, Authlib, pywin32, uiautomation, plyer (notifications), PyInstaller

**Dropping:** Tauri, Rust toolchain, Svelte, Vite, Tailwind, WhisperX, Pyannote, todoist-api-python

**Keeping:** PyTorch (CUDA 12.6), pyyaml, python-dotenv, pytest

### Repo cleanup

- Remove Tauri/Svelte code in a clean commit
- Close stale issues from Tauri app
- Create new issues for plugin architecture
- Rewrite README
- Development on feature branch (not master)

## Open Items

- **HTTP API contract**: exact endpoints defined during implementation
- **Task note format**: using Obsidian Tasks inline for now, revisit if richer metadata needed
- **iPhone recording ingest**: future feature (issue #25), drop folder approach
- **Real-time transcript view**: UI details designed during plugin implementation
- **Streaming transcription reliability**: evaluate during implementation, fall back to WhisperX + Pyannote if Parakeet + NeMo streaming proves unstable

## Future Considerations

- **Local LLM for activism org**: Ollama backend placeholder exists, implement when model quality catches up (~14B limit on 12GB RTX 4070)
- **Cross-platform**: Windows-first. macOS/Linux not a current goal but Python + Obsidian are cross-platform by nature.
- **iPhone ingest**: iOS 18 native call recording exports M4A. Watch folder in daemon picks it up. (Issue #25)

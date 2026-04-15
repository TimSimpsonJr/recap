# Recap -- Structural Map

## Stack

- **Language:** Python 3.10+ (daemon, pipeline, analysis); TypeScript (Obsidian plugin)
- **ML:** NVIDIA Parakeet (ASR), NeMo Sortformer (diarization), Claude CLI (analysis)
- **Runtime:** aiohttp server + WebSocket, PyAudioWPatch (WASAPI), pystray system tray
- **Browser extension:** Chrome/Edge MV3 for meeting URL detection

## Structure

```
recap/                                        # Python package
  __init__.py / __main__.py                   # Package init + CLI entry
  cli.py                                      # CLI argument parsing
  analyze.py                                  # Claude CLI invocation for meeting analysis
  artifacts.py                                # RecordingMetadata sidecar + note title/path helpers (resolve_note_path, to_vault_relative)
  vault.py                                    # Obsidian vault note writer; upsert_note updates EventIndex via _update_index_if_applicable
  models.py / errors.py                       # Shared data models + typed exceptions
  daemon/                                     # Background service
    __main__.py                               # Thin entry: constructs `Daemon(config).start()`
    service.py                                # `Daemon` service object: owns EventIndex, EventJournal, PairingWindow, lifecycle
    events.py                                 # `EventJournal` append-only journal (recent errors + notification history)
    pairing.py                                # `PairingWindow` one-shot extension auth bound to loopback
    server.py                                 # aiohttp server; routes consume `request.app["daemon"]`; `/api/*` Bearer-guarded; `/bootstrap/token` gated by `Daemon.pairing`
    config.py / runtime_config.py             # Daemon YAML config (OrgConfig.resolve_subfolder, org_by_slug) + PipelineRuntimeConfig projection
    startup.py / tray.py                      # Service init/shutdown + pystray tray (includes "Pair browser extension..." menu item)
    auth.py / credentials.py                  # Token auth + Windows DPAPI credential storage
    logging_setup.py / notifications.py       # Logging; notifications write to EventJournal
    recorder/                                 # Audio capture subsystem
      recorder.py                             # Recording orchestrator; uses `audio_capture.on_chunk`
      audio.py                                # WASAPI loopback capture (PyAudioWPatch) with public `on_chunk` callback (no monkey-patching)
      detector.py                             # Meeting window detector; awaitable signal callback; consumes EventIndex; uses `resolve_subfolder` (no hand-join)
      detection.py / enrichment.py            # Browser extension signal receiver + calendar metadata enrichment
      state_machine.py / silence.py / recovery.py  # State transitions, silence auto-stop, crash recovery
      signal_popup.py                         # Manual recording trigger popup; async via `loop.run_in_executor`
    calendar/                                 # Calendar integration
      index.py                                # EventIndex: persistent O(1) event-id -> vault-relative note_path map
      sync.py                                 # Sync orchestrator; write/update take OrgConfig; find_note_by_event_id consults EventIndex
      scheduler.py                            # Pre-meeting briefing scheduler; uses org_by_slug + resolve_subfolder
      google.py / zoho.py / oauth.py          # Google + Zoho API clients + OAuth 2.0 flow
    streaming/transcriber.py / diarizer.py    # Live Parakeet ASR + NeMo diarization
  pipeline/                                   # Post-meeting processing
    __init__.py                               # Stage-tracked orchestrator; run_pipeline + _resolve_note_path accept vault_path + EventIndex
    transcribe.py / diarize.py / audio_convert.py  # Batch Parakeet + NeMo + WAV-to-AAC (ffmpeg)
obsidian-recap/                               # Obsidian plugin (TypeScript)
  src/main.ts / api.ts / settings.ts          # Plugin entry, daemon HTTP/WS client, settings tab
  src/renameProcessor.ts / notificationHistory.ts  # Vault rename handler + notification log
  src/views/ / components/ / utils/format.ts  # Views (MeetingListView, LiveTranscriptView, SpeakerCorrectionModal), UI components, formatting
extension/                                    # Chrome/Edge MV3 extension
  manifest.json / background.js / options.*   # Meeting URL detection + daemon signaling + settings
prompts/                                      # Claude prompt templates (meeting_analysis.md, meeting_briefing.md)
tests/                                        # Pytest suite
  conftest.py / fixtures/                     # Shared fixtures + test data
  test_event_index.py                         # EventIndex unit tests (persistence, rebuild, idempotency)
  test_daemon_service.py / test_event_journal.py / test_pairing.py  # Phase 3 unit tests
  test_phase3_integration.py                  # Phase 3 end-to-end: service lifecycle + pairing + journal wiring
  test_phase2_integration.py                  # End-to-end: calendar sync -> detection -> pipeline backfill
  test_daemon_config.py                       # DaemonConfig + OrgConfig.resolve_subfolder + org_by_slug helpers
docs/plans/                                   # Design docs and phase plans
```

## Key Relationships

- `daemon/server.py` exposes REST + WebSocket endpoints consumed by `obsidian-recap/src/api.ts`
- `daemon/recorder/` orchestrates capture; `recorder.py` coordinates `audio.py`, `detector.py`, `state_machine.py`, and `silence.py`
- `daemon/recorder/enrichment.py` pulls calendar data from `daemon/calendar/sync.py` to tag recordings with meeting metadata
- `daemon/streaming/transcriber.py` and `diarizer.py` feed live results through WebSocket to the plugin's `LiveTranscriptView`
- `pipeline/` runs post-meeting: `transcribe.py` and `diarize.py` produce segments consumed by `analyze.py`, which writes via `vault.py`
- `daemon/calendar/oauth.py` handles OAuth flows for both Google and Zoho; tokens stored via `credentials.py` (Windows DPAPI)
- `daemon/config.py` loads the daemon YAML into `DaemonConfig` (server, orgs, `PipelineSettings`); `daemon/runtime_config.py` projects those settings plus an `OrgConfig` and `RecordingMetadata` into the `PipelineRuntimeConfig` consumed by `pipeline/`
- **Daemon ownership:** `Daemon` (in `daemon/service.py`) owns `EventIndex` + `EventJournal` + `PairingWindow`; subservices receive them via constructor or `request.app["daemon"]`. `__main__.py` is a thin entry that builds and starts the `Daemon`.
- **EventIndex flow:** `Daemon` rebuilds the persistent event-id -> vault-relative `note_path` map on startup and threads `EventIndex` into `calendar/scheduler.py`, `calendar/sync.py`, `recorder/detector.py`, `pipeline/__init__.py`, and `vault.py` for O(1) note lookup across sync, detection, and backfill
- **Extension auth:** explicit tray-initiated one-shot `PairingWindow` bound to loopback; `/bootstrap/token` serves only while the window is open; all open/close/grant transitions journaled via `EventJournal`
- **EventJournal as single source of truth:** recent errors surfaced by `/api/status` and plugin notification history both read from `EventJournal` (no plugin-side writes)
- **Org slug vs. subfolder:** `event.org` is the slug for frontmatter identity (`org:`); on-disk path comes from `OrgConfig.resolve_subfolder(vault_path)` in `sync.py`/`scheduler.py`/`recorder/detector.py`. The legacy `sync.org_subfolder()` hardcode is gone
- **Vault-relative `note_path`:** canonical form is vault-relative; `artifacts.to_vault_relative` converts and `artifacts.resolve_note_path` accepts legacy absolute or new relative inputs. Both `sync.write_calendar_note` and `vault.build_canonical_frontmatter` (called via `write_meeting_note` from the pipeline) emit matching canonical frontmatter so calendar-seeded and pipeline-upserted notes stay in lockstep
- `models.py` and `errors.py` are shared across daemon, pipeline, and analysis layers
- `extension/background.js` detects meeting URLs and POSTs to `daemon/recorder/detection.py` endpoint
- Tests mirror source structure: `test_daemon_server.py` tests `daemon/server.py`, `test_streaming_*.py` tests `streaming/`, etc.

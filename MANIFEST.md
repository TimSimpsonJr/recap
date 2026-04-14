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
  models.py                                   # Data models (MeetingMetadata, TranscriptSegment)
  errors.py                                   # Typed exceptions with actionable messages
  daemon/                                     # Background service
    __main__.py                               # `python -m recap.daemon` entry; constructs EventIndex singleton + unconditional startup rebuild
    server.py                                 # aiohttp HTTP + WebSocket server
    config.py                                 # Daemon YAML config; OrgConfig.resolve_subfolder + DaemonConfig.org_by_slug helpers
    runtime_config.py                         # Builds PipelineRuntimeConfig from settings + org + recording metadata
    startup.py / tray.py                      # Service init/shutdown + pystray system tray
    auth.py / credentials.py                  # Token auth + Windows DPAPI credential storage
    autostart.py / logging_setup.py / notifications.py  # Task Scheduler stub, logging, toasts
    recorder/                                 # Audio capture subsystem
      recorder.py                             # Recording orchestrator
      audio.py                                # WASAPI loopback capture (PyAudioWPatch)
      detector.py                             # Meeting window detector; consumes EventIndex; _find_calendar_note returns vault-relative
      detection.py                            # Browser extension signal receiver
      enrichment.py                           # Meeting metadata enrichment from calendar
      state_machine.py / silence.py / recovery.py  # State transitions, silence auto-stop, crash recovery
      signal_popup.py                         # Manual recording trigger popup
    calendar/                                 # Calendar integration
      index.py                                # EventIndex: persistent O(1) event-id -> vault-relative note_path map
      sync.py                                 # Sync orchestrator; write/update take OrgConfig; find_note_by_event_id consults EventIndex
      scheduler.py                            # Pre-meeting briefing scheduler; uses org_by_slug + resolve_subfolder
      google.py / zoho.py / oauth.py          # Google + Zoho API clients + OAuth 2.0 flow
    streaming/                                # Real-time ML
      transcriber.py / diarizer.py            # Live Parakeet ASR + NeMo diarization
  pipeline/                                   # Post-meeting processing
    __init__.py                               # Stage-tracked orchestrator; run_pipeline + _resolve_note_path accept vault_path + EventIndex
    transcribe.py / diarize.py                # Batch Parakeet + NeMo
    audio_convert.py                          # WAV-to-AAC conversion (ffmpeg)
obsidian-recap/                               # Obsidian plugin (TypeScript)
  src/main.ts / api.ts / settings.ts          # Plugin entry, daemon HTTP/WS client, settings tab
  src/renameProcessor.ts / notificationHistory.ts  # Vault rename handler + notification log
  src/views/                                  # MeetingListView, LiveTranscriptView, SpeakerCorrectionModal
  src/components/ / utils/format.ts           # UI components + display formatting
extension/                                    # Chrome/Edge MV3 extension
  manifest.json / background.js               # Meeting URL detection + daemon signaling
  options.html / options.js                   # Extension settings
prompts/                                      # Claude prompt templates (meeting_analysis.md, meeting_briefing.md)
tests/                                        # Pytest suite
  conftest.py / fixtures/                     # Shared fixtures + test data
  test_event_index.py                         # EventIndex unit tests (persistence, rebuild, idempotency)
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
- **EventIndex flow:** `daemon/__main__.py` owns the singleton `EventIndex` (persistent event-id -> vault-relative `note_path`, rebuilt on startup) and threads it into `calendar/scheduler.py`, `calendar/sync.py`, `recorder/detector.py`, `pipeline/__init__.py`, and `vault.py` for O(1) note lookup across sync, detection, and backfill
- **Org slug vs. subfolder:** `event.org` is the slug for frontmatter identity (`org:`); `OrgConfig.resolve_subfolder(vault_path)` is the sole source of truth for the on-disk folder (`org-subfolder:`). The legacy `sync.org_subfolder()` hardcode is gone — callers go through `DaemonConfig.org_by_slug` + `resolve_subfolder`
- **Vault-relative `note_path`:** canonical form is vault-relative; `artifacts.to_vault_relative` converts and `artifacts.resolve_note_path` accepts legacy absolute or new relative inputs. Both `sync.write_calendar_note` and `pipeline.build_canonical_frontmatter` emit matching canonical frontmatter so calendar-seeded and pipeline-upserted notes stay in lockstep
- `models.py` and `errors.py` are shared across daemon, pipeline, and analysis layers
- `extension/background.js` detects meeting URLs and POSTs to `daemon/recorder/detection.py` endpoint
- Tests mirror source structure: `test_daemon_server.py` tests `daemon/server.py`, `test_streaming_*.py` tests `streaming/`, etc.

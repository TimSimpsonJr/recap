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
  analyze.py                                  # Claude CLI invocation for meeting analysis; {{roster_section}}/{{transcript_instruction}} swap for empty-roster prompts
  artifacts.py                                # RecordingMetadata sidecar (+ recording_started_at) + note title/path helpers (resolve_note_path, to_vault_relative)
  vault.py                                    # Obsidian vault note writer; upsert_note updates EventIndex via _update_index_if_applicable; unscheduled tag + time-range derivation from recording_started_at
  models.py / errors.py                       # Shared data models + typed exceptions
  daemon/                                     # Background service
    __main__.py                               # Thin entry: constructs `Daemon(config).start()`
    service.py                                # `Daemon` service object: owns EventIndex, EventJournal, PairingWindow, lifecycle; holds config_path + config_lock for PATCH
    events.py                                 # `EventJournal` append-only journal (microsecond ts; recent errors + notification history)
    pairing.py                                # `PairingWindow` one-shot extension auth bound to loopback
    server.py                                 # aiohttp server; `/api/{status,events,config,meeting-*,record/*,recordings/<stem>/clip}` Bearer-guarded; `/bootstrap/token` gated by `Daemon.pairing`
    api_config.py                             # API DTO + ruamel round-trip for `/api/config` GET+PATCH (kebab/snake + dict/list translation layer)
    config.py / runtime_config.py             # Daemon YAML config (OrgConfig.resolve_subfolder, org_by_slug, CalendarProviderConfig.enabled) + PipelineRuntimeConfig projection
    startup.py / tray.py                      # Service init/shutdown + pystray tray (includes "Pair browser extension..." menu item)
    auth.py / credentials.py                  # Token auth + Windows DPAPI credential storage
    logging_setup.py / notifications.py       # Logging; notifications write to EventJournal
    recorder/                                 # Audio capture subsystem
      recorder.py                             # Recording orchestrator; uses `audio_capture.on_chunk`
      audio.py                                # WASAPI loopback capture (PyAudioWPatch) via pyflac 3.0 StreamEncoder (no `channels=` kwarg)
      detector.py                             # Meeting window detector; two-path pruning (stop-monitoring via is_window_alive + end-of-poll prune protecting _recording_hwnd); stop() awaits cancelled poll task; _synthesize_unscheduled_identity(unscheduled:<uuid>, YYYY-MM-DD HHMM - {Platform} call.md, collision resolution)
      detection.py / enrichment.py            # Extension signal receiver + calendar enrichment; _EXCLUDED_HWNDS set + exclude/include helpers + UIA gate in detect_meeting_windows + is_window_alive
      call_state.py                           # UIA call-state helpers + per-platform checkers (Teams, Zoom); teams checker is two-path: UIA property search hit short-circuits True, else falls back to the manual Control-view walk. Issue #30 round-2 diagnostics (uia_tree_shape, teams_window_identity, teams_leave_button_findall) emit once per hwnd on checker decline
      state_machine.py / silence.py / recovery.py  # State transitions, silence auto-stop, crash recovery
      signal_popup.py                         # Manual recording popup; dedicated ThreadPoolExecutor, sticky shutdown flag, outstanding-futures tracking, ttk.Combobox
    calendar/                                 # Calendar integration
      index.py                                # EventIndex: persistent O(1) event-id -> vault-relative note_path map
      sync.py                                 # Sync orchestrator; write/update take OrgConfig; find_note_by_event_id consults EventIndex
      scheduler.py                            # Pre-meeting briefing scheduler; uses org_by_slug + resolve_subfolder
      google.py / zoho.py / oauth.py          # Google + Zoho API clients + OAuth 2.0 flow
    streaming/transcriber.py / diarizer.py    # No-op stubs — live streaming deferred to Phase 8
  pipeline/                                   # Post-meeting processing
    __init__.py                               # Stage-tracked orchestrator; run_pipeline + _resolve_note_path accept vault_path + EventIndex
    transcribe.py / diarize.py / audio_convert.py  # Batch Parakeet + NeMo + WAV-to-AAC (ffmpeg)
obsidian-recap/                               # Obsidian plugin (TypeScript)
  src/main.ts / api.ts / settings.ts          # Plugin entry, daemon HTTP/WS client (tailEvents, getConfig, patchConfig, fetchSpeakerClip), settings tab (orgs/detection/calendar/contacts/daemon)
  src/renameProcessor.ts / notificationHistory.ts  # Vault rename handler + daemon-backed notification renderer
  src/views/ / components/ / utils/format.ts  # Views (MeetingListView narrows to org subfolders; LiveTranscriptView; SpeakerCorrectionModal plays `/api/recordings/<stem>/clip`)
extension/                                    # Chrome/Edge MV3 extension
  manifest.json / background.js               # Bearer-authed `/api/meeting-*` signaling; authReady promise closes MV3 wake-up race; badge states: connected / AUTH / offline
  options.html / options.js                   # Pairing UI (loopback validation + `/bootstrap/token` exchange) + meeting URL patterns
prompts/                                      # Claude prompt templates (meeting_analysis.md, meeting_briefing.md)
tests/                                        # Pytest suite (unit tier; integration tier excluded by default via `-m 'not integration'`)
  conftest.py / fixtures/                     # Shared fixtures (make_daemon_config, build_daemon_callbacks, daemon_client, MINIMAL_API_CONFIG_YAML) + test data
  test_event_index.py                         # EventIndex unit tests (persistence, rebuild, idempotency)
  test_daemon_service.py / test_event_journal.py / test_pairing.py  # Phase 3 unit tests
  test_api_events.py / test_api_config.py / test_clip_endpoint.py  # Phase 4 endpoint tests (journal backfill, config DTO + PATCH, recording clip)
  test_phase3_integration.py / test_phase4_integration.py  # End-to-end daemon lifecycle + Phase 4 contracts (pairing, Bearer, events, config, WS)
  test_phase2_integration.py                  # End-to-end: calendar sync -> detection -> pipeline backfill
  test_unscheduled_integration.py             # End-to-end #27 flow: synthesis -> sidecar -> vault -> EventIndex
  test_daemon_config.py                       # DaemonConfig + OrgConfig.resolve_subfolder + org_by_slug helpers
  integration/                                # Phase 7 integration tier (marker `integration`)
    conftest.py                               # Session-scoped Parakeet/NeMo model fixtures + cuda_guard skip
    test_contract_smoke.py                    # 6 CPU-safe contract tests (pyflac, uiautomation, pywin32, parakeet/nemo import shape)
    test_ml_pipeline.py                       # 3 GPU tests: model load + end-to-end silent-FLAC pipeline
docs/plans/                                   # Design docs and phase plans
docs/handoffs/                                # Per-phase handoff notes + manual acceptance checklists
```

## Key Relationships

- `daemon/recorder/` orchestrates capture (`recorder.py` coordinates `audio.py`, `detector.py`, `state_machine.py`, `silence.py`); `enrichment.py` pulls calendar data from `daemon/calendar/sync.py` to tag recordings. Live streaming (`streaming/{transcriber,diarizer}.py`) is stubbed — deferred to Phase 8.
- **Phase 7 detection + popup reliability:** `recorder/detection.py` tracks `_EXCLUDED_HWNDS` (daemon-owned popups) and gates window-title matches through `call_state.py` UIA checkers so Teams/Zoom only auto-record when a call is actually active. Teams checker uses a two-path contract (UIA property-search hit or manual walk fallback) after the issue #30 round-2 capture showed the Control-view walk via `GetChildren()` stops at new Teams' WebView2 browser chrome. `signal_popup.py` owns a dedicated `ThreadPoolExecutor` (created in `service.py`) with a sticky shutdown flag so late futures from Signal polling can't hit a dead event loop. `pyproject.toml` adds an `integration` pytest marker (excluded from default runs) so `tests/integration/` can import real libraries and fail fast when pyflac/NeMo/parakeet/pyarrow bump.
- `pipeline/` runs post-meeting: `transcribe.py` and `diarize.py` produce segments consumed by `analyze.py`, which writes via `vault.py`.
- `daemon/calendar/oauth.py` handles OAuth flows for both Google and Zoho; tokens stored via `credentials.py` (Windows DPAPI).
- `daemon/config.py` loads the daemon YAML into `DaemonConfig`; `daemon/runtime_config.py` projects those settings plus an `OrgConfig` and `RecordingMetadata` into the `PipelineRuntimeConfig` consumed by `pipeline/`.
- **Daemon ownership:** `Daemon` (in `daemon/service.py`) owns `EventIndex` + `EventJournal` + `PairingWindow` + `config_path` + `config_lock` + `_popup_executor`; subservices receive them via constructor or `request.app["daemon"]`. `__main__.py` is a thin entry that builds and starts the `Daemon`.
- **EventIndex flow:** `Daemon` rebuilds the persistent event-id -> vault-relative `note_path` map on startup and threads `EventIndex` into `calendar/scheduler.py`, `calendar/sync.py`, `recorder/detector.py`, `pipeline/__init__.py`, and `vault.py` for O(1) note lookup across sync, detection, and backfill.
- **EventJournal as single source of truth:** recent errors surfaced by `/api/status`, plugin notification history (backfill via `/api/events`, live via WS `journal_entry`), and the Phase 4 integration test all read from `EventJournal`. Plugin and extension never write to the journal.
- **Extension pairing:** tray menu → `PairingWindow.open()` → `/bootstrap/token` (loopback-only, one-shot) → extension stores `{token, baseUrl, pairedAt}` in `chrome.storage.local`. All `/api/meeting-*` POSTs carry `Authorization: Bearer <token>`; a 401 response clears the stored token and flips the toolbar badge to "AUTH".
- **Config API translation boundary:** `/api/config` speaks snake_case + list-orgs to the plugin; on-disk YAML stays kebab-case + dict-orgs (the canonical loader's shape). `api_config.py` translates both directions, preserves non-DTO sibling fields (`llm-backend` on orgs, `display-name` on contacts) by name-matching, and validates post-PATCH docs through `parse_daemon_config_dict` so a bad PATCH can't brick the next restart. ruamel round-trips preserve comments; `restart_required: true` in the response directs the user to tray → Quit → relaunch.
- **Org slug vs. subfolder:** `event.org` is the slug for frontmatter identity (`org:`); on-disk path comes from `OrgConfig.resolve_subfolder(vault_path)` in `sync.py`/`scheduler.py`/`recorder/detector.py`. The legacy `sync.org_subfolder()` hardcode is gone.
- **Vault-relative `note_path`:** canonical form is vault-relative; `artifacts.to_vault_relative` converts and `artifacts.resolve_note_path` accepts legacy absolute or new relative inputs. Both `sync.write_calendar_note` and `vault.build_canonical_frontmatter` (called via `write_meeting_note` from the pipeline) emit matching canonical frontmatter so calendar-seeded and pipeline-upserted notes stay in lockstep.
- **Speaker clip endpoint:** `/api/recordings/<stem>/clip?speaker=...` resolves `<stem>.flac` first, falls back to `<stem>.m4a` (archive output). Cached at `<recordings_path>/<stem>.clips/<speaker>_<N>s.mp3`; ffmpeg runs via `asyncio.to_thread(subprocess.run, ...)` and journals `clip_extraction_failed` on non-zero exit.
- **Unscheduled meetings (#27):** `_build_recording_metadata` in `recorder/detector.py` synthesizes `event_id = "unscheduled:<uuid>"`, a precomputed `note_path` under `{org}/Meetings/YYYY-MM-DD HHMM - {Platform} call.md`, and `recording_started_at` (tz-aware). Downstream pipeline + vault + EventIndex see a valid event-id and run their existing calendar-backed codepaths. Vault adds an `unscheduled` tag and a `time: HH:MM-HH:MM` range computed from `recording_started_at + duration_seconds`. Analyze prompt swaps the participant-roster instructions for empty rosters. No retroactive calendar attachment — deferred to #33.
- `models.py` and `errors.py` are shared across daemon, pipeline, and analysis layers.
- Tests mirror source structure: `test_daemon_server.py` tests `daemon/server.py`, `test_streaming_*.py` tests `streaming/`, etc.

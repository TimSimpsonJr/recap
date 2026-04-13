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
  config.py                                   # YAML config loader with env var interpolation
  analyze.py                                  # Claude CLI invocation for meeting analysis
  vault.py                                    # Obsidian vault note writer
  models.py                                   # Data models (MeetingMetadata, TranscriptSegment)
  errors.py                                   # Typed exceptions with actionable messages
  daemon/                                     # Background service
    __main__.py                               # `python -m recap.daemon` entry
    server.py                                 # aiohttp HTTP + WebSocket server
    config.py                                 # Daemon-specific config (ports, paths, orgs)
    startup.py                                # Service initialization and shutdown
    tray.py                                   # pystray system tray icon and menu
    auth.py                                   # Token-based daemon authentication
    credentials.py                            # Credential storage (Windows DPAPI)
    logging_setup.py                          # Structured logging configuration
    notifications.py                          # Desktop toast notifications
    recorder/                                 # Audio capture subsystem
      recorder.py                             # Recording orchestrator
      audio.py                                # WASAPI loopback capture (PyAudioWPatch)
      detector.py                             # Meeting window detector (title matching)
      detection.py                            # Browser extension signal receiver
      enrichment.py                           # Meeting metadata enrichment from calendar
      state_machine.py                        # Recording state transitions
      silence.py                              # Silence detection for auto-stop
      recovery.py                             # Crash recovery for interrupted recordings
      signal_popup.py                         # Manual recording trigger popup
    calendar/                                 # Calendar integration
      sync.py                                 # Calendar sync orchestrator
      scheduler.py                            # Pre-meeting briefing scheduler
      google.py                               # Google Calendar API client
      zoho.py                                 # Zoho Calendar API client
      oauth.py                                # OAuth 2.0 flow handler
    streaming/                                # Real-time ML
      transcriber.py                          # Live Parakeet ASR streaming
      diarizer.py                             # Live NeMo speaker diarization
  pipeline/                                   # Post-meeting processing
    __init__.py                               # Stage-tracked orchestrator
    transcribe.py                             # Batch Parakeet transcription
    diarize.py                                # Batch NeMo diarization
    audio_convert.py                          # WAV-to-AAC conversion (ffmpeg)
obsidian-recap/                               # Obsidian plugin (TypeScript)
  src/main.ts                                 # Plugin entry, command registration
  src/api.ts                                  # HTTP/WS client for daemon
  src/settings.ts                             # Plugin settings tab
  src/renameProcessor.ts                      # Vault file rename handler
  src/notificationHistory.ts                  # Notification log
  src/views/MeetingListView.ts                # Meeting dashboard view
  src/views/LiveTranscriptView.ts             # Real-time transcript view
  src/views/SpeakerCorrectionModal.ts         # Speaker label editor modal
  src/components/                             # UI components (FilterBar, MeetingRow, etc.)
  src/utils/format.ts                         # Display formatting helpers
extension/                                    # Chrome/Edge MV3 extension
  manifest.json / background.js              # Meeting URL detection + daemon signaling
  options.html / options.js                   # Extension settings
prompts/                                      # Claude prompt templates
  meeting_analysis.md                         # Post-meeting analysis prompt
  meeting_briefing.md                         # Pre-meeting briefing prompt
tests/                                        # Pytest suite (32 modules)
  conftest.py                                 # Shared fixtures
  fixtures/                                   # Test data (config.yaml, metadata)
docs/plans/                                   # Design docs and phase plans
```

## Key Relationships

- `daemon/server.py` exposes REST + WebSocket endpoints consumed by `obsidian-recap/src/api.ts`
- `daemon/recorder/` orchestrates capture; `recorder.py` coordinates `audio.py`, `detector.py`, `state_machine.py`, and `silence.py`
- `daemon/recorder/enrichment.py` pulls calendar data from `daemon/calendar/sync.py` to tag recordings with meeting metadata
- `daemon/streaming/transcriber.py` and `diarizer.py` feed live results through WebSocket to the plugin's `LiveTranscriptView`
- `pipeline/` runs post-meeting: `transcribe.py` and `diarize.py` produce segments consumed by `analyze.py`, which writes via `vault.py`
- `daemon/calendar/oauth.py` handles OAuth flows for both Google and Zoho; tokens stored via `credentials.py` (Windows DPAPI)
- `config.py` (top-level) loads pipeline config; `daemon/config.py` extends it with daemon-specific settings (port, orgs, tray)
- `models.py` and `errors.py` are shared across daemon, pipeline, and analysis layers
- `extension/background.js` detects meeting URLs and POSTs to `daemon/recorder/detection.py` endpoint
- Tests mirror source structure: `test_daemon_server.py` tests `daemon/server.py`, `test_streaming_*.py` tests `streaming/`, etc.

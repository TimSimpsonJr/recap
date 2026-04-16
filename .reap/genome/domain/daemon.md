# Domain: Daemon

## Responsibility

The Python background service — the critical path for everything user-facing. Handles meeting detection, audio recording, live streaming transcription/diarization, calendar sync, OAuth, system tray, HTTP/WebSocket API, extension pairing, and vault note writing. Runs headless; the only UI it owns is the system tray.

## Key Entities

- **`Daemon` service** (`daemon/service.py`) — lifecycle root; owns `EventIndex`, `EventJournal`, `PairingWindow`, `config_path`, `config_lock`. Subservices receive these via constructor or `request.app["daemon"]`.
- **aiohttp server** (`daemon/server.py`) — exposes `/api/{status,events,config,meeting-*,record/*,recordings/<stem>/clip}`, Bearer-guarded. Only unauthenticated route is `/bootstrap/token` (loopback-only, opened by `PairingWindow`).
- **`EventIndex`** (`daemon/calendar/index.py`) — persistent `event-id → vault-relative note_path` map; rebuilt on startup; consulted by sync, scheduler, detector, pipeline, vault.
- **`EventJournal`** (`daemon/events.py`) — append-only microsecond-timestamped log. Source of truth for recent errors (`/api/status`), plugin notification history (`/api/events` + WS `journal_entry`), and rename queue (`rename_queued` events).
- **`PairingWindow`** (`daemon/pairing.py`) — one-shot extension auth; opened from the tray menu; exchanges a token via loopback-validated `/bootstrap/token`.
- **Recorder** (`daemon/recorder/`) — state machine coordinating WASAPI loopback capture (`audio.py`), window-title detector (`detector.py`), silence auto-stop, crash recovery, and the manual-trigger signal popup.
- **Calendar** (`daemon/calendar/`) — Google + Zoho OAuth clients, sync orchestrator, pre-meeting briefing scheduler, EventIndex writer.
- **Streaming** (`daemon/streaming/`) — live Parakeet ASR + NeMo Sortformer diarization; results streamed to the plugin via WebSocket.
- **Tray** (`daemon/tray.py`) — pystray menu with "Pair browser extension…", Restart, Quit.
- **Credentials** (`daemon/credentials.py`) — Windows DPAPI-backed token storage.
- **Config API** (`daemon/api_config.py`) — ruamel round-trip for `/api/config` GET+PATCH with kebab/snake + dict/list translation and post-PATCH validation.

## Boundaries

- Owns vault note writing and rename queueing; the plugin applies renames but does not compose note bodies.
- Launches the pipeline as a subprocess; does not run ML inference inline in the HTTP handlers.
- Communicates with the plugin over HTTP/WebSocket (commands, live state) and with the vault filesystem (durable state).
- Communicates with the extension only via `/api/meeting-*` endpoints, authenticated with a Bearer token issued through `/bootstrap/token`.
- Never trusts the plugin or extension to be running; a recording must complete whether or not either is online.

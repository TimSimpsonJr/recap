# Project Principles

## Architecture

- **Three components: Python daemon ↔ Obsidian plugin ↔ browser extension** — the daemon is the critical path (detection, recording, pipeline, vault writes, tray, OAuth). The plugin is the non-critical UI over the daemon's HTTP/WebSocket API. The MV3 extension is a signaling source for meeting URLs. Data flows primarily through the vault filesystem; HTTP/WS carries commands and live state only.
- **Daemon is authoritative, plugin is a view** — if the plugin breaks, the user loses the dashboard but never loses a recording. The daemon writes the vault; the plugin reads it (with one narrow write path: `RenameProcessor` applying the daemon's rename queue through `fileManager.renameFile`).
- **Offline-first, local-data ownership** — recordings, transcripts, and analysis stay on the user's machine. Vault notes live in the user's Obsidian vault. The only remote call is the LLM (Claude CLI or Ollama).
- **Pipeline stages are independently retryable** — each stage writes `status.json` progress; `--from` / `--only` CLI flags let a failed stage be retried without re-running the whole pipeline.
- **EventJournal as the single source of truth for observability** — recent errors surfaced by `/api/status`, plugin notification history (backfill via `/api/events`, live via WS `journal_entry`), and Phase 4 integration tests all read from `EventJournal`. Plugin and extension never write to the journal.
- **EventIndex for O(1) event-id lookup** — the daemon maintains a persistent `event-id → vault-relative note_path` map on startup, threaded into calendar sync, scheduler, recorder detection, pipeline, and vault writer. No hot-path markdown scans.

## Code Quality

- **Optimize for integration, not standalone use** — Recap is a personal daemon-plus-plugin system. Don't over-engineer individual modules for reuse outside this context.
- **Evaluate caching/concurrency before proposing** — don't add by default, but always consider whether they'd benefit the recommendation.

## User Experience

- **Obsidian-native UI** — views render inside Obsidian (MeetingListView, LiveTranscriptView, SpeakerCorrectionModal). Follow Obsidian's theme tokens rather than building a parallel design system.
- **Tray is the daemon's only OS-level UI** — the tray menu is where pairing, restart, and quit live. No separate daemon window.
- **SSD-aware recording** — warn users when selecting HDD for recordings storage since multi-stream capture needs SSD throughput.

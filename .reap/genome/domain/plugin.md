# Domain: Obsidian Plugin

## Responsibility

The user-facing UI, rendered inside Obsidian. Reads the vault filesystem directly, talks to the daemon over HTTP/WebSocket for commands and live state. Non-critical path — if the plugin breaks, no recording is lost.

## Key Entities

- **`main.ts`** — plugin entry; registers views, commands, settings tab; manages the daemon client lifecycle.
- **`api.ts`** — typed daemon HTTP/WS client: `tailEvents`, `getConfig`, `patchConfig`, `fetchSpeakerClip`, `/api/status`, `/api/meeting-*`, etc. Handles 401 → clear token + UI hint.
- **`settings.ts`** — settings tab with orgs, detection patterns, calendar, contacts, and daemon sections; writes go through `patchConfig` (snake_case + list-orgs DTO).
- **`views/`** — `MeetingListView` (narrowed to org subfolders), `LiveTranscriptView` (WS-driven), `SpeakerCorrectionModal` (plays clips via `/api/recordings/<stem>/clip`).
- **`renameProcessor.ts`** — consumes the daemon's `rename_queued` events and applies renames via `fileManager.renameFile` so wikilinks update automatically.
- **`notificationHistory.ts`** — backfills from `/api/events` on modal open, streams via WS `journal_entry` while open.
- **`components/` + `utils/format.ts`** — shared UI bits.

## Boundaries

- Reads the vault directly via Obsidian's Vault API for meeting notes, frontmatter, and wikilinks.
- Writes to the vault in exactly one path: `RenameProcessor` applying the daemon's queued renames.
- Never writes note bodies, never composes frontmatter — the daemon and pipeline own that.
- Never writes to `EventJournal`; only reads via `/api/events` + WS.
- Depends on the daemon for: recording controls, live transcript, speaker clips, config PATCH, pairing status.
- Degrades gracefully when the daemon is offline: surfaces the offline state, stops streaming, keeps the vault browsable.

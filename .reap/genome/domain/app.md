# Domain: App

## Responsibility

The Tauri desktop application — Svelte 5 frontend and Rust backend as one unit. Owns the UI, routing, state management, IPC layer, OAuth flows, credential storage, recording, and system tray behavior.

## Key Entities

- **Meetings** — listed, filtered, searched, and displayed with detail panels; sourced from filesystem via Rust IPC
- **Stores** — Svelte writables for settings, meetings, credentials, recorder state
- **IPC bridge** (`tauri.ts`) — typed wrappers over Tauri invoke commands; the contract between frontend and backend
- **OAuth providers** — Zoom, Google, Microsoft, Zoho, Todoist; each with its own callback flow
- **Recorder** — state machine orchestrating WASAPI audio + Graphics Capture screen → ffmpeg merge → sidecar launch
- **Credentials** — Stronghold-backed encrypted token storage, separate from plugin-store settings

## Boundaries

- Communicates with the Python pipeline only by launching it as a sidecar and reading `status.json` from the filesystem
- Does NOT run ML inference or transcription — that's the pipeline's job
- Does NOT write Obsidian vault notes — the pipeline does that

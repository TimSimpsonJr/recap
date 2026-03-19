# Project Conventions

## File Organization

- Frontend: `src/routes/` for page components, `src/lib/` for shared code
- Stores: `src/lib/stores/` — one file per domain (settings, meetings, credentials, recorder)
- Components: `src/lib/components/` — flat, named by feature (e.g., FilterSidebar, MeetingPlayer)
- Rust backend: `src-tauri/src/` — one module per IPC domain (meetings, oauth, recorder/)
- Python pipeline: `recap/` — one module per pipeline stage (transcribe, analyze, vault, etc.)
- Design docs: `docs/plans/` — dated markdown specs per implementation phase

## Naming

- Svelte components: PascalCase (e.g., `MeetingDetail.svelte`, `GraphControls.svelte`)
- Stores: camelCase exports, one writable per concern (e.g., `meetingStore`, `settingsStore`)
- Rust IPC commands: snake_case Rust functions exposed as camelCase to frontend via `tauri.ts`
- Python: snake_case throughout, CLI flags use `--kebab-case`
- Git commits: Conventional Commits (`feat:`, `fix:`, `docs:`, with optional scope)

## Patterns

- IPC bridge: all Tauri commands wrapped in `src/lib/tauri.ts` with TypeScript types
- Dummy data: gated behind `VITE_DUMMY_DATA` env var, tree-shaken from prod
- Markdown rendering: Obsidian-flavored via `markdown.ts` (wikilinks → filter links)
- OAuth: localhost callback server (Google/Microsoft) + `recap://` deep link (Zoom/Zoho)
- Pipeline status: `status.json` per meeting, read by frontend for progress dots
- Credential storage: Stronghold (`plugin-stronghold`) for secrets/tokens; plugin-store for non-sensitive settings — never mix these
- Store reactivity: `resetMeetings()` and `graphDataVersion` signaling pattern for cross-component refresh after settings changes (e.g., path changes in RecordingSettings/VaultSettings)
- Window lifecycle: hide-on-close, quit only via system tray context menu — don't add window close/quit behavior elsewhere

## Error Handling

- Frontend: actionable error states with Settings links (not generic "something went wrong")
- Pipeline: stage-level failure with retry from any stage via `--from` flag
- Recorder: state machine (idle → recording → processing) with explicit error states

## Testing

- Python: pytest (`tests/` directory), with pytest-asyncio for async tests
- Frontend: no test framework yet — testing is manual/visual for now

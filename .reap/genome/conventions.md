# Project Conventions

## File Organization

- Python daemon: `recap/daemon/` — one module per concern (`server.py`, `service.py`, `events.py`, `pairing.py`, `auth.py`, `tray.py`, `api_config.py`, `config.py`, `runtime_config.py`, etc.)
- Daemon subsystems: `recap/daemon/recorder/`, `recap/daemon/calendar/`, `recap/daemon/streaming/` — each subsystem is self-contained
- Pipeline: `recap/pipeline/` — one module per stage (`transcribe.py`, `diarize.py`, `audio_convert.py`)
- Shared Python: `recap/` top level — `analyze.py`, `vault.py`, `artifacts.py`, `models.py`, `errors.py`
- Obsidian plugin: `obsidian-recap/src/` — `main.ts` (entry), `api.ts` (daemon client), `settings.ts` (settings tab), `renameProcessor.ts`, `notificationHistory.ts`, `views/`, `components/`, `utils/`
- Browser extension: `extension/` — flat MV3 layout (`manifest.json`, `background.js`, `options.html`, `options.js`)
- Prompts: `prompts/` — Claude templates (`meeting_analysis.md`, `meeting_briefing.md`)
- Design docs: `docs/plans/` — dated markdown specs per phase; handoff notes in `docs/handoffs/`

## Naming

- Python: `snake_case` throughout; CLI flags use `--kebab-case`
- TypeScript (plugin): `camelCase` functions, `PascalCase` classes/views (e.g. `MeetingListView`, `RenameProcessor`)
- Daemon HTTP routes: kebab-case paths (`/api/meeting-detected`, `/api/recordings/<stem>/clip`)
- Config API translation: plugin speaks `snake_case` + list-orgs; on-disk YAML stays `kebab-case` + dict-orgs; `api_config.py` translates both directions
- Git commits: Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:` with optional scope)

## Patterns

- **Daemon ownership:** `Daemon` (in `daemon/service.py`) owns `EventIndex`, `EventJournal`, `PairingWindow`, `config_path`, and `config_lock`. Subservices receive them via constructor or `request.app["daemon"]`. `__main__.py` is a thin entry.
- **Bearer auth on every `/api/*`:** `/bootstrap/token` (loopback-only, one-shot, opened by tray "Pair browser extension…") is the only unauthenticated route. A 401 response clears the caller's stored token.
- **EventIndex for note lookup:** `find_note_by_event_id` consults `EventIndex`; never scan the vault in hot paths.
- **Org slug vs. subfolder:** `event.org` is the slug (frontmatter identity); on-disk path comes from `OrgConfig.resolve_subfolder(vault_path)`. Never hand-join paths.
- **Vault-relative `note_path`:** canonical form is vault-relative. `artifacts.to_vault_relative` converts; `artifacts.resolve_note_path` accepts legacy absolute or new relative inputs.
- **Calendar upsert symmetry:** `sync.write_calendar_note` and `vault.build_canonical_frontmatter` (via `write_meeting_note` from the pipeline) emit matching canonical frontmatter so calendar-seeded and pipeline-upserted notes stay in lockstep.
- **Rename queue, not in-place writes:** when a calendar event shifts, the daemon journals `rename_queued` with old + new paths; the plugin's `RenameProcessor` applies the rename via `fileManager.renameFile` so wikilinks update automatically.
- **Config PATCH safety:** `/api/config` PATCH runs through `parse_daemon_config_dict` before writing; a bad PATCH can't brick the next restart. ruamel round-trips preserve comments. `restart_required: true` tells the plugin to prompt the user to quit from tray.
- **LLM backend choice:** per-org `llm-backend` field in YAML picks `claude` (default) or `ollama`. The analyze stage reads this and flips between `claude --print` and `ollama run <model>` subprocess invocations.
- **Speaker clip caching:** `/api/recordings/<stem>/clip?speaker=...` resolves `<stem>.flac` first, falls back to `<stem>.m4a` (archive output); cached at `<recordings_path>/<stem>.clips/<speaker>_<N>s.mp3`; ffmpeg runs via `asyncio.to_thread(subprocess.run, ...)` and journals `clip_extraction_failed` on non-zero exit.

## Error Handling

- Daemon: every failure path journals to `EventJournal` with a structured event name and context; `/api/status` surfaces recent errors.
- Plugin: no bare `catch {}`. Every catch reports via notification or logs with a reason.
- Pipeline: stage-level failure with retry from any stage via `--from` flag.
- Recorder: state machine (idle → recording → processing) with explicit error states.

## Testing

- Python: pytest (`tests/` directory), pytest-asyncio for async, pytest-aiohttp for server tests.
- Coverage gate: `--cov-fail-under=70` over `recap/`.
- Fixtures: shared in `tests/conftest.py` (`make_daemon_config`, `build_daemon_callbacks`, `daemon_client`, `MINIMAL_API_CONFIG_YAML`).
- Plugin: TypeScript build + type-check (`tsc -noEmit`); no runtime test framework yet — verification is manual via Obsidian dev vault.
- Extension: no build step (pure MV3 JS); manual verification via Chrome's unpacked-extension loader.
- Don't mock the exact contract under test — if the test is about `write_meeting_note` or `EventIndex.add`, hit the real function.

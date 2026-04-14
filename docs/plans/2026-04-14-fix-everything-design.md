# Recap Fix-Everything: Design Doc

**Date:** 2026-04-14
**Scope:** Comprehensive fix for contract bugs, architectural debt, scope gaps, and test quality issues identified in the April 14 dual roast (Claude + Codex).
**Execution:** Single-day, one-shot via sequential subagents, reviewed at end by Codex before any merge.

---

## Context

Two independent code reviews of the `obsidian-pivot` branch (Claude roast + Codex roast) converged on the same verdict: the daemon/plugin split is directionally right, but the repo is full of "architecture by README." Surface shape looks complete; core contracts are half-implemented, stubbed, stringly-typed, or silently ignored.

The Codex roast surfaced four silent data-integrity bugs that had been missed on casual reads:

1. `write_meeting_note` never backfills frontmatter when a calendar-seeded note already exists — scheduled meetings finish "complete" missing recording, duration, type, tags, companies.
2. `org_subfolder()` hardcodes `_Recap/<Capitalized>`, ignoring `OrgConfig.subfolder`. Calendar sync and pipeline can write the same meeting to two different locations.
3. Signal popup collects the backend choice and throws it away; the actual pipeline backend comes from `org_config.llm_backend`.
4. Signal popup spawns a thread and immediately joins — blocks the async detector poll loop while the user decides.

Along with the architectural debt (two `PipelineConfig`s with the same name, `__main__.py` god function, monkey-patched audio internals, `_loop_holder`/`_app_holder` closure hacks), the plugin-vs-spec gaps (in-memory notification history, settings UI stub, speaker correction without audio preview), and the performance/correctness liabilities (vault-wide scan on every MeetingListView open, O(n) event-id lookups called repeatedly).

Because nothing ships today, we can do a deeper coordinated refactor than a normal incremental plan would allow. Contracts get frozen up front, implementation is split by disjoint write areas, and Codex performs a hard integration review before anything merges.

---

## Global Gates

Applies to the entire batch. Review blocks merge until all are satisfied.

- No feature may still "look implemented" while returning placeholders, stubs, or ignored user choices.
- No new behavior ships without at least one integration-style test that exercises the real seam.
- `uv run pytest -q` passes, `npm run build` in `obsidian-recap/` passes, and at least one manual end-to-end smoke run is documented in the PR description.
- README and this design doc must match reality by the end of the batch.
- Any remaining deferred work (autostart, etc.) must be hidden, removed, or explicitly unavailable — not half-exposed.

---

## Phase 0 — Contract Freeze

**This section IS Phase 0.** Once this design doc is committed, Phase 0 is complete. No separate implementation plan is generated for it. All later phases reference the contracts below as source of truth.

### 0.1 Canonical meeting note contract

A meeting note has exactly one shape regardless of how it was seeded (calendar sync, manual recording, browser extension, Signal popup). Two write paths exist; both converge on this shape.

**Frontmatter — always present:**

```yaml
---
date: 2026-04-14                       # ISO date
time: "14:00-15:00"                    # optional: set by calendar sync, omitted for ad-hoc
title: "Quarterly Review"
org: disbursecloud                     # ALWAYS the org_slug, never a folder path
org-subfolder: Clients/Disbursecloud   # filesystem path; present so renames can locate the note
participants: ["[[Alice Chen]]", "[[Bob Smith]]"]
companies: ["[[Acme Corp]]"]           # populated post-analysis
platform: google_meet                  # google_meet | teams | zoom | zoho_meet | signal | manual | unknown
calendar-source: google                # google | zoho | null (ad-hoc)
event-id: abc123                       # nullable, populated when calendar-seeded
meeting-link: "https://meet.google.com/xyz"
recording: "2026-04-14-140000-disbursecloud.m4a"   # filename, not wikilink; pipeline updates to m4a after archive
duration: "1h 12m"                     # set post-recording
type: quarterly_review                 # set post-analysis
tags: ["meeting/quarterly_review"]
pipeline-status: pending | transcribing | diarizing | analyzing | exporting | converting | complete | failed:<stage>
pipeline-error: "..."                  # present only when status starts with failed:
---
```

**Body — below `## Meeting Record` marker:**

Calendar-seeded notes may have an `## Agenda` section above the marker (written by `write_calendar_note`). Everything below the marker is owned by the pipeline.

**Upsert rules:**

| Current state of note | Write action |
|---|---|
| Note does not exist | Create with full frontmatter + marker + pipeline content |
| Note exists, no marker, no frontmatter | Create marker, prepend frontmatter, append pipeline content |
| Note exists with calendar frontmatter, no marker | Merge canonical frontmatter over existing, preserving calendar fields (event-id, time, calendar-source, meeting-link, agenda body); append marker + pipeline content |
| Note exists with marker | Merge canonical frontmatter over existing (authoritative for pipeline-owned fields); replace everything below marker |

The merge is field-level, not file-level. Calendar fields win on calendar-owned keys (time, event-id, meeting-link, calendar-source, participants-pre-meeting). Pipeline fields win on pipeline-owned keys (duration, type, tags, companies, recording, pipeline-status). `date`, `title`, `org`, `org-subfolder`, `platform` are shared: last writer wins, but all writers must produce consistent values (the org index enforces this).

### 0.2 Org model: `org_slug` vs `org_subfolder`

- **`org_slug`** — stable lowercase identity. `"disbursecloud"`, `"personal"`, `"acme"`. Used as frontmatter `org`, dict keys, filenames. Never contains `/`, never contains uppercase, never changes for the lifetime of the data.
- **`org_subfolder`** — user-configurable filesystem path under the vault. `"Clients/Disbursecloud"`, `"Personal"`. Used only for directory paths. Configurable in `DaemonConfig.orgs[N].subfolder`.

Frontmatter `org` is **always** the slug. Frontmatter `org-subfolder` is the path (present so rename logic doesn't have to infer). API boundaries always exchange slugs; subfolder resolution is daemon-internal.

Delete `recap/daemon/calendar/sync.py:org_subfolder(org)` (the hardcoded capitalizer). Replace with `DaemonConfig.org_by_slug(slug) → OrgConfig` and `OrgConfig.resolve_subfolder(vault_path) → Path`.

### 0.3 `RecordingMetadata` shape

```python
@dataclass
class RecordingMetadata:
    org: str                         # slug
    note_path: str                   # vault-relative, or empty
    title: str
    date: str                        # ISO
    participants: list[Participant]
    platform: str
    calendar_source: str | None
    event_id: str | None
    meeting_link: str
    llm_backend: str                 # NEW: "claude" | "ollama", chosen at recording time
```

Written alongside each recording as `<recording>.metadata.json`. The pipeline reads it, uses `llm_backend` to select the LLM (overriding `org_config.llm_backend` default).

### 0.4 Daemon event journal

Daemon owns notification history. Location: `<vault>/_Recap/.recap/events.jsonl`. Append-only, one JSON object per line.

```json
{"ts": "2026-04-14T14:30:00-07:00", "level": "info", "event": "recording_started", "message": "Recording for disbursecloud", "payload": {"org": "disbursecloud", "recording": "2026-04-14-143000-disbursecloud.flac"}}
{"ts": "2026-04-14T15:42:11-07:00", "level": "warning", "event": "silence_warning", "message": "No audio for 5 minutes"}
{"ts": "2026-04-14T15:43:00-07:00", "level": "error", "event": "pipeline_failed", "message": "Claude CLI not found", "payload": {"stage": "analyze", "recording_path": "..."}}
```

**Schema (v1):**
- `ts` — RFC 3339 timestamp with offset
- `level` — `info` | `warning` | `error`
- `event` — stable event name (snake_case)
- `message` — human-readable
- `payload` — optional structured data

**Ownership:**
- Daemon writes via `EventJournal` service (thread-safe append).
- Plugin reads on connect (tail last N entries) and subscribes to live stream via WebSocket `event: journal_entry` messages.
- Plugin never writes to the journal. In-memory `NotificationHistory.ts` becomes a thin renderer over daemon data.

**Retention:** rotate at 10 MB to `events.jsonl.1` (keep one backup). Daemon startup prunes backups older than 30 days.

### 0.5 Extension auth

The extension must send Bearer tokens to the daemon like the plugin does. The endpoints `/meeting-detected` and `/meeting-ended` move under `/api/` and require auth.

**Protocol:**

1. Daemon exposes `GET /bootstrap/token`. The endpoint is **disabled by default** — not served on daemon start.
2. User opens pairing explicitly from the tray menu ("Pair browser extension…"). This opens the bootstrap window. No automatic window on daemon start.
3. The endpoint binds only to `127.0.0.1` and `::1` (loopback). No CORS headers are sent, so cross-origin browser contexts cannot read the response body; only the extension's own fetch from its service worker (which bypasses CORS for localhost under MV3 host permissions) can consume it.
4. Extension user clicks "Connect" in extension options. Extension fetches `GET http://127.0.0.1:<port>/bootstrap/token`, stores result in `chrome.storage.local`.
5. **The window is one-shot.** The first successful fetch closes the window and the endpoint returns 403 on subsequent calls until the user re-opens pairing from the tray.
6. All pairing lifecycle events are logged to the daemon event journal:
   - `pairing_opened` (info)
   - `pairing_token_issued` (info, payload includes requester IP)
   - `pairing_closed_timeout` (warning) — if the window expires with no successful fetch (60 s timeout as a safety valve).
   - `pairing_failed_non_loopback` (warning, payload includes source IP) — if a non-loopback caller hits the endpoint while the window is open.
7. All subsequent `/api/meeting-detected` + `/api/meeting-ended` requests include `Authorization: Bearer <token>`.

**Token scope:** if implementation is straightforward, the daemon issues a **scoped extension token** (separate from the plugin's full-access token), authorized only for `/api/meeting-detected` and `/api/meeting-ended`. If scoping materially complicates the auth middleware, it is acceptable to issue the full daemon token for this batch — the guardrails above (explicit pairing, loopback-only, one-shot window, journaling) are the primary defense. Token scoping decision is finalized during Phase 3 implementation based on complexity.

**Rationale:** any local process can hit localhost, so a permanent unauth token endpoint is equivalent to no auth. An explicit, user-initiated, one-shot, loopback-only pairing window gives us comparable UX to the plugin's auth-token file read while avoiding automatic exposure.

**Transitional:** during Phase 3 implementation, the daemon supports both authenticated and unauthenticated endpoints briefly so the extension isn't broken mid-refactor. By the end of Phase 4, unauthenticated paths are removed.

### 0.6 Config naming: settings vs runtime

Two distinct concepts, currently both named `PipelineConfig`:

- **`PipelineSettings`** (in `recap/daemon/config.py`): persisted YAML config. Fields: `transcription_model`, `diarization_model`, `auto_retry`, `max_retries`. Loaded once at daemon start.
- **`PipelineRuntimeConfig`** (in `recap/pipeline/__init__.py`): per-run execution config. Fields: the above, plus `device`, `llm_backend`, `ollama_model`, `archive_format`, `archive_bitrate`, `delete_source_after_archive`, `prompt_template_path`, `status_dir`. Built from `PipelineSettings` + `OrgConfig` + `RecordingMetadata` by `_build_runtime_config()`.

Rename both. Delete the ambiguity.

---

## Phase 1 — Data Contracts

**Owner:** one agent.
**Write scope:** `recap/vault.py`, `recap/pipeline/__init__.py`, `recap/artifacts.py`, `recap/models.py`, `tests/test_vault.py`, `tests/test_pipeline.py`, new `tests/test_vault_upsert.py`.

**Goals:**

- Implement the canonical note upsert from §0.1 (field-level merge, calendar-fields-preserved).
- Extend `RecordingMetadata` with `llm_backend` (§0.3); thread it through `run_pipeline` → analyze.
- Rename `recap.pipeline.PipelineConfig` → `PipelineRuntimeConfig`. Rename `recap.daemon.config.PipelineConfig` → `PipelineSettings`. Update all imports.
- Rewrite `_update_note_frontmatter` to merge an arbitrary dict (not just status) — becomes the shared upsert primitive.

**Specific changes:**

- `vault.py:write_meeting_note` — three branches collapse into one: build canonical frontmatter dict, call new `upsert_note(path, frontmatter, marker, body)` helper that handles all four upsert cases from §0.1.
- `pipeline/__init__.py` — `run_pipeline` populates the full canonical frontmatter (duration, type, tags, companies, recording filename, org-subfolder, pipeline-status) and passes it to `upsert_note`. `_update_note_frontmatter` kept as a thin wrapper for status-only updates during stage progression.
- `pipeline/__init__.py` — honor `recording_metadata.llm_backend` when building `PipelineRuntimeConfig`; fall back to `org_config.llm_backend` only if missing.
- `artifacts.py` — `RecordingMetadata` gets `llm_backend: str = "claude"` (default retains current behavior for legacy metadata files).
- Delete `recap/config.py` references in the MANIFEST (file doesn't exist; stale pointer).

**Acceptance criteria:**

- Running the pipeline against an existing calendar-seeded note produces a fully backfilled canonical note (recording, duration, type, tags, companies, pipeline-status), not just appended body text.
- Frontmatter `org` is always the slug; frontmatter `org-subfolder` is the path. Neither leaks into the other field.
- Recording metadata persists and reloads `llm_backend`.
- The Signal backend choice from §0.3 survives through analyze and affects subprocess invocation (verified in Phase 3 where plumbing is completed; Phase 1 verifies the data path exists).
- `PipelineSettings` and `PipelineRuntimeConfig` are two distinct names; no import ambiguity.
- New `tests/test_vault_upsert.py` uses a real tmp vault and real note files for all four upsert branches. No test mocks `write_meeting_note` or `_update_note_frontmatter`.

---

## Phase 2 — Org Model + Event-ID Index

**Owner:** one agent, starts after Phase 1 lands.
**Write scope:** `recap/daemon/config.py`, `recap/daemon/calendar/sync.py`, `recap/daemon/calendar/scheduler.py`, new `recap/daemon/calendar/index.py`, `tests/test_calendar_sync.py`, new `tests/test_event_index.py`.

**Goals:**

- Eliminate the hardcoded capitalizer; all org-subfolder lookups go through `OrgConfig.subfolder`.
- Build a persistent event-id index so pipeline note resolution and scheduler lookups become O(1) and correct under concurrent rename.

**Specific changes:**

- `daemon/config.py` — add `DaemonConfig.org_by_slug(slug: str) → OrgConfig | None` and `OrgConfig.resolve_subfolder(vault_path: Path) → Path`.
- `calendar/sync.py` — delete `org_subfolder()`. `write_calendar_note` takes `org: OrgConfig` instead of `org: str`. Frontmatter always uses `event.org` slug for `org:` and `org_config.subfolder` for `org-subfolder:`.
- New `calendar/index.py`:
  - `EventIndex` class, persisted at `<vault>/_Recap/.recap/event-index.json`.
  - Schema: `{"version": 1, "entries": {event_id: {"path": vault_relative_path, "mtime": iso, "org": slug}}}`.
  - Methods: `lookup(event_id) → Path | None`, `add(event_id, path, org)`, `remove(event_id)`, `rename(event_id, new_path)`, `rebuild(vault_path)`.
  - `rebuild()` scans all `_Recap/*/Meetings/` dirs once and repopulates from frontmatter `event-id` fields. Called at daemon startup (lazy: only if index file missing or older than startup).
- `calendar/sync.py:find_note_by_event_id` — becomes a thin wrapper over `EventIndex.lookup`, with fallback to scan + rebuild on index miss (covers the case where user added a note by hand).
- `calendar/scheduler.py` — calls `EventIndex.lookup` instead of scanning per-event.
- `pipeline/__init__.py:_resolve_note_path` — uses `EventIndex.lookup`.
- `vault.py:upsert_note` — calls `EventIndex.add` after a successful write if frontmatter has `event-id`.
- `renameProcessor.ts` — when processing a rename, plugin posts to a new daemon endpoint `/api/index/rename` so the index stays consistent.

**Acceptance criteria:**

- Calendar sync writes notes under the configured `OrgConfig.subfolder`, not a capitalized hardcode.
- Frontmatter identity uses `org_slug`; filesystem routing uses `org_subfolder`. Neither leaks.
- Event-id lookup is index-backed in all hot paths (scheduler, pipeline resolver, calendar sync).
- Index updates correctly on create, rename, and delete.
- Pipeline note resolution via `event_id` finds the correct note even after a rename has been queued.
- `tests/test_event_index.py` covers: fresh rebuild, add/remove/rename, stale-entry fallback (file moved externally), concurrent-write safety (write-then-read).
- No remaining correctness-critical O(n) event-id scan in the main path (the only acceptable scan is the one-time rebuild).

---

## Phase 3 — Runtime Foundation

**Owner:** one agent, starts after Phases 1+2 land.
**Write scope:** `recap/daemon/__main__.py`, `recap/daemon/server.py`, new `recap/daemon/service.py`, new `recap/daemon/events.py`, new `recap/daemon/pairing.py`, `recap/daemon/tray.py`, `recap/daemon/recorder/recorder.py`, `recap/daemon/recorder/audio.py`, `recap/daemon/recorder/signal_popup.py`, `recap/daemon/recorder/detector.py`, `recap/daemon/notifications.py`, `recap/daemon/autostart.py` (delete), tests as appropriate.

**Goals:**

- Collapse `__main__.py` into a thin entry point. Introduce `Daemon` service object that owns loop, app, state.
- Replace `_loop_holder`/`_app_holder` with service-object references.
- Make Signal popup truly async; propagate backend choice into `RecordingMetadata.llm_backend`.
- Delete monkey-patching of `AudioCapture`; replace with a proper `on_audio_chunk` callback.
- Real `/api/status`: live uptime, live recent errors from the event journal.
- Extension auth (§0.5) — endpoints moved under `/api/`, Bearer required.
- Remove `autostart.py` + `/api/autostart` endpoint entirely. (Plugin side removes any reference in Phase 4.)

**Specific changes:**

- New `daemon/service.py: Daemon` class. Holds: `config`, `loop`, `app`, `recorder`, `detector`, `scheduler`, `event_journal`, `started_at`. Methods: `start()`, `stop()`, `emit_event(level, event, message, payload=None)`, `run_in_loop(coro)`.
- `__main__.py` shrinks to ~40 lines: parse args, `Daemon(config).start()`.
- All callbacks that previously closed over `_loop_holder` now take a `Daemon` reference.
- New `daemon/events.py: EventJournal`. Thread-safe append, rotation at 10 MB, backfill-read API.
- New `daemon/pairing.py: PairingWindow`. Manages the one-shot bootstrap-token lifecycle: `open()` enables the endpoint, `close(reason)` disables it, 60 s safety timer, source-IP check (loopback only), emits journal events on every transition. Tray menu item "Pair browser extension…" calls `daemon.pairing.open()`.
- `daemon/tray.py` — add "Pair browser extension…" menu item wired to `daemon.pairing.open()`.
- `server.py`:
  - `_api_status` returns `daemon_uptime = (now - daemon.started_at).total_seconds()`, `errors = daemon.event_journal.tail(level="error", limit=10)`.
  - WebSocket broadcast sends `{"event": "journal_entry", ...}` for each new journal entry.
  - Delete `_meeting_detected` + `_meeting_ended` (the dead ones at lines 55, 78).
  - Delete `_autostart_status` route.
  - Move `_meeting_detected_live` + `_meeting_ended_live` behind `/api/`; require Bearer auth via existing middleware.
  - Add `/bootstrap/token` endpoint per §0.5 — disabled by default, opened explicitly from tray ("Pair browser extension…"), bound to 127.0.0.1/::1 only, no CORS, one-shot (first success closes window), 60 s safety timeout, all lifecycle events journaled.
  - Token scope decision: issue an extension-scoped token if the auth middleware accepts a simple allow-list check; otherwise issue the full daemon token (decision made in-phase, recorded in the commit message).
  - Add `/api/index/rename` endpoint for the plugin rename processor.
- `recorder/audio.py:AudioCapture` — add `on_chunk: Callable[[bytes, int], None] | None` public attribute, called after each interleave with the combined mono mix. Remove `_interleave_and_encode` from the public surface.
- `recorder/recorder.py:_start_streaming` — delete the monkey-patch; set `audio_capture.on_chunk = _feed_streaming_models`. No reach-into-private-buffers.
- `recorder/signal_popup.py:show_signal_popup` — becomes `async def show_signal_popup(...) -> dict | None`. Runs tkinter via `loop.run_in_executor(None, _blocking_dialog)`. Returns awaitable; `detector._poll_once` awaits it.
- `recorder/detector.py` — replaces the sync `self._on_signal_detected` callback with an awaitable. Signal popup completion now flows `RecordingMetadata.llm_backend = chosen_backend` and passes it to `recorder.start(org, metadata=metadata)`.
- `notifications.py` — `notify()` also writes to the event journal.
- Delete `recap/daemon/autostart.py`.

**Acceptance criteria:**

- `__main__.py` is a thin entry point. No `_loop_holder`, no `_app_holder`, no closure bag.
- A single `Daemon` service object owns runtime state, loop access, and lifecycle.
- `/api/status` returns real uptime (> 0 after daemon running for a second) and real recent errors (populated when the journal has error entries).
- Signal prompting no longer blocks the detector poll loop (verified: detector keeps polling while popup is open).
- Signal backend choice survives: popup returns `ollama`, `RecordingMetadata.llm_backend == "ollama"`, `PipelineRuntimeConfig.llm_backend == "ollama"`, analyze invokes `ollama run ...`.
- `AudioCapture` exposes `on_chunk` as a public callback. `Recorder` does not access any underscore-prefixed attribute of `AudioCapture`.
- Daemon writes to `events.jsonl`; journal rotation works at 10 MB.
- Extension auth endpoint lives. `/bootstrap/token` is disabled by default, openable only from the tray, loopback-bound, one-shot, journaled. `/api/meeting-detected` requires Bearer.
- `/api/autostart` and `recap/daemon/autostart.py` are gone. No residual references anywhere in the codebase.

---

## Phase 4 — Plugin Parity + Extension

**Owner:** one agent, starts after Phase 3 lands.
**Write scope:** `obsidian-recap/src/*`, `extension/*`, tests as appropriate.

**Goals:**

- Settings UI buildout matching spec: orgs, detection rules, calendar mapping, known contacts, daemon lifecycle.
- Notification history reads daemon journal: backfill on connect + live stream.
- Speaker correction gets audio preview (daemon serves clips) + known contacts from daemon.
- Extension auth plumbed end-to-end.
- `MeetingListView` narrows vault scan to configured org subfolders.
- Silent `catch {}` blocks replaced with `Notice` + journal entry.

**Specific changes:**

**Daemon-side prerequisites (included in Phase 4 scope even though daemon code):**

- `server.py` — new endpoints:
  - `GET /api/events?since=<ts>&limit=N` → returns journal entries (backfill).
  - `GET /api/config` → returns sanitized daemon config for plugin UI.
  - `PATCH /api/config` → accepts partial config updates; persists to YAML.
  - `GET /api/contacts` → returns known contacts from `DaemonConfig.known_contacts`.
  - `GET /api/recordings/<stem>/clip?speaker=<label>&duration=<s>` → returns an MP3 clip of the first utterance by that speaker (via ffmpeg, cached).
  - `GET /api/status/detailed` → daemon state, current recording, calendar sync time, recent errors.

**Plugin-side:**

- `api.ts` — new methods: `tailEvents(since, limit)`, `onEvent(handler)` with journal_entry subscription, `getConfig()`, `patchConfig(partial)`, `getContacts()`, `getSpeakerClipUrl(recordingStem, speaker)`.
- `notificationHistory.ts` — stop being the source of truth. Wraps daemon journal: `load()` tails last 100, `subscribe()` listens for journal_entry WebSocket events, `render()` combines live + backfill.
- `settings.ts` — expand from "daemon URL + OAuth" to full spec:
  - Orgs section: list + add/edit/delete + mark default.
  - Detection section: per-platform enabled + behavior (`auto-record` / `prompt`) + default org/backend.
  - Calendar section: per-provider org mapping + calendar-id.
  - Known contacts section: list + add/edit.
  - Daemon lifecycle: show status (running/stopped/uptime), restart button (POST to a new `/api/restart` endpoint that re-execs).
- `views/MeetingListView.ts:loadMeetings` — fetches `GET /api/config` for org-subfolder list, then filters files by `f.path.startsWith(subfolder)` for each. No more whole-vault scan.
- `views/SpeakerCorrectionModal.ts` — calls `getSpeakerClipUrl`, renders `<audio controls>` per speaker. Calls `getContacts()` for known-contacts dropdown.
- `main.ts` — replace silent `catch {}` in `readAuthToken`, `reconnect`, `file-open`, `activateView` with `Notice` + `notificationHistory.add("error", ...)`.
- `renameProcessor.ts` — same: errors surface.

**Extension:**

- `extension/options.html` + `options.js` — add "Connect" button. Instructs user to open "Pair browser extension…" from the daemon tray first, then click Connect. Calls `GET http://127.0.0.1:9847/bootstrap/token`; on 403, shows "Pairing not open — open it from the Recap tray icon". Stores successful result in `chrome.storage.local`.
- `extension/background.js` — reads token from storage, sends `Authorization: Bearer <token>` on all `/api/meeting-detected` + `/api/meeting-ended` POSTs. If 401, clears stored token and badge goes red prompting reconnect.

**Acceptance criteria:**

- Plugin notification history renders daemon journal backfill (entries from before plugin startup) plus live events (WebSocket).
- Settings UI round-trips actual daemon config for the agreed fields (change an org subfolder in the UI → daemon YAML updates on disk → daemon picks up changes after restart).
- Speaker correction can play sample clips for each SPEAKER_XX label, and shows known contacts as a suggestion list.
- Extension sends authenticated requests; daemon rejects unauthenticated on `/api/*` paths; badge reflects connection state honestly.
- `MeetingListView` only iterates files under configured org subfolders. (On a 10k-note vault, load time should be sub-100ms.)
- No `catch {}` or `catch (e) {}` block swallows an error silently. Every catch either surfaces via Notice or journals via `notificationHistory.add`.

---

## Phase 5 — Honesty Pass

**Owner:** one agent, starts after Phase 4 lands (mostly cleanup sweep).
**Write scope:** broad but shallow. Scattered small changes.

**Goals:**

- Remove remaining code that advertises features that don't work.
- Delete deprecated scaffolding.
- Tighten type safety where Phases 1-3 have made it possible.

**Specific changes:**

- Delete dead `_meeting_detected` + `_meeting_ended` handlers in `server.py` (if not already done in Phase 3 — double-check).
- Delete `extension_port_start` + `extension_port_end` from `DaemonPortConfig`; remove from config YAML fixtures.
- Delete `recap/config.py` reference in MANIFEST if any stale pointers remain.
- Grep for `# type: ignore` and remove each one where the underlying type is now correct.
- Grep for `object` type hints in `MeetingDetector.__init__` etc. — replace with concrete types now that Phase 3 has given us a `Daemon` service class.
- Remove `"implemented": False` + any similar placeholders.
- Review all `except Exception:` blocks for bare-swallow patterns missed in Phase 4.
- Update MANIFEST.md to reflect current structure.
- Update README claims to match reality.

**Acceptance criteria:**

- `autostart` is gone from code, API, plugin UI, and docs. (Already handled in Phase 3 but re-verify here.)
- Dead handlers and deprecated config fields are removed.
- No endpoint returns fake metadata like `implemented: false` or hardcoded `daemon_uptime: 0`.
- No UI advertises unfinished features as if they work.
- Type hacks and casts added only to paper over bad boundaries are reduced or removed. Remaining `# type: ignore` must have an inline comment explaining why.
- Docs stop claiming features that are still deferred.

---

## Phase 6 — Test Hardening

**Owner:** one agent, starts after Phase 5 lands.
**Write scope:** `tests/*`, plus any test utilities needed.

**Goals:**

- Prove contracts with real integration tests.
- Delete tests that only prove mocks work.

**Specific changes:**

- `tests/test_pipeline.py` — rewrite the tests that patch `write_meeting_note` to use a real tmp vault and assert on actual file content. Delete tests that only assert `pipeline-status: complete` via mocked write.
- New `tests/test_e2e_pipeline.py` — fixture-audio → run_pipeline → assert canonical frontmatter fully present, body has summary/key-points/action-items, recording-index updated, event-journal has `pipeline_completed` entry.
- New `tests/test_signal_backend_routing.py` — pass `RecordingMetadata.llm_backend="ollama"` → run_pipeline → assert ollama subprocess was invoked (patch `subprocess.run`, assert on argv).
- `tests/test_event_index.py` — already added in Phase 2; Phase 6 adds edge cases (corrupted index file → rebuild; concurrent modifications).
- New `tests/test_extension_auth.py` — `/api/meeting-detected` rejects no auth; accepts valid token; `/bootstrap/token` serves only during bootstrap window, only from localhost.
- Delete `tests/test_daemon_server.py` tests that only assert response shape with full mocks (keep the ones that exercise real handlers).
- Add a coverage gate: `uv run pytest --cov=recap --cov-fail-under=70`.

**Acceptance criteria:**

- There is a true end-to-end pipeline test using a real tmp vault and real file outputs.
- There is a test proving calendar-seeded note upsert produces full canonical frontmatter.
- There is a test proving Signal backend choice changes pipeline execution config.
- There are real tests for event-index lifecycle.
- There are tests for extension auth on the finalized protocol.
- Over-mocked tests that only prove mocks work are deleted or rewritten.
- The final suite still passes cleanly after removing fake-comfort tests. Coverage ≥ 70% over `recap/`.

---

## Final Integration Pass

**Owner:** solo (no delegation).

**Manual smoke checklist:**

- Scheduled calendar meeting creates a note; recording attaches to the same note; pipeline completes; canonical frontmatter is correct (all fields populated, `org` is slug, `org-subfolder` is path).
- Signal popup choice changes backend and survives through processing (verify by inspecting the analyze subprocess invocation in the log).
- Rename queue updates links correctly (trigger a calendar event time change; observe the note rename and the event index update).
- Plugin shows history that includes events from before plugin startup (close Obsidian, generate daemon events, reopen; events appear).
- Extension recording trigger works with auth (disconnect in extension options → daemon rejects → badge red; reconnect → works).

**Automated gates:**

- `uv run pytest -q` passes.
- `npm run build` in `obsidian-recap/` passes.
- `cd extension && ...` any build/lint passes.

**Review:**

- Codex runs the review rubric (see §Review Blockers) against the final diff.
- Every user-visible claim in README and architecture spec can be traced to actual behavior in code.

---

## Review Blockers

Any of these blocks merge:

- Any place where `org_subfolder` leaks into frontmatter `org` or API identity.
- Any user choice that is collected and ignored (backend, detection behavior, org selection, etc.).
- Any remaining placeholder status field (`daemon_uptime: 0`, `errors: []`, `implemented: false`).
- Any remaining hot-path markdown scan for event-id lookup.
- Any silent failure in plugin UX (bare `catch {}` with no surfacing).
- Any test that mocks the exact contract being claimed as fixed.
- Any `# type: ignore` without a justification comment.
- Any reference to `autostart` outside of git history.

---

## Execution Notes

- **Phase 0 is this document.** Approval + commit = Phase 0 done.
- **Phase ordering is strict.** Phase 2 depends on the artifact shape from Phase 1. Phase 3 depends on contracts from Phases 1+2. Phase 4 depends on the extension auth protocol finalized in Phase 3. Phases 5+6 clean up after.
- **Per-phase implementation plans are generated just-in-time** at the start of each phase via the `writing-plans` skill. Don't generate all six up front.
- **Single write-owner per phase.** No phase shares a file with another phase (except `artifacts.py` between Phases 1 and 2, resolved by sequencing).
- **Intermediate broken states are OK.** Nothing ships until the integration pass.
- **Agents read this doc before starting.** Each phase's acceptance criteria IS the definition of done for that agent.
- **Baseline commit for this batch: `a9b9418187507101d13bda0ebefd0484b0211d7a`.** All work builds on that HEAD.

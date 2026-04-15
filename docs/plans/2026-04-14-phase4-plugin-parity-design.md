# Phase 4: Plugin Parity + Extension — Design

**Date:** 2026-04-14
**Status:** Design approved; implementation plan to follow via `superpowers:writing-plans`.
**Baseline:** commit `9f5cf3b` (Phase 3 complete + Codex review fixes), 477 tests passing.
**Parent design:** `docs/plans/2026-04-14-fix-everything-design.md` §Phase 4.

## Goals

Close the Phase 3 transitional gaps and build the missing plugin surface:

1. **Extension on Bearer end-to-end** — pair via tray, send `Authorization: Bearer <token>` on `/api/meeting-detected` + `/api/meeting-ended`. Delete the transitional unauthenticated legacy routes.
2. **Plugin notification history as thin renderer** — daemon journal is the source of truth; plugin reads via `GET /api/events` (backfill) + WebSocket `journal_entry` frames (live).
3. **Settings UI buildout** — orgs, detection rules, calendar mapping, known contacts, daemon lifecycle. Plugin can read and update daemon config via `/api/config` (sanitized GET, ruamel round-trip PATCH).
4. **Speaker correction audio preview** — daemon serves MP3 clips per speaker via `/api/recordings/<stem>/clip`; plugin modal renders `<audio controls>` inline.
5. **Vault scan narrowing** — `MeetingListView` filters by configured org subfolders; no more whole-vault scan.
6. **Silent-catch elimination** — every `catch {}` in plugin code becomes `Notice` + `console.error`; no error vanishes.

Non-goals (deferred to Phase 5+):
- `/api/restart` endpoint (user tray-quits and relaunches).
- JS test runner for plugin (manual acceptance checklist instead).
- Backwards pagination of `/api/events` (notification history caps at 100 recent entries).
- Hot-reload of daemon config (PATCH writes YAML; user restarts).

## Scope

**Tests:** 477 → ~520 expected (integration + per-feature units).

**Writes:**
- Daemon: `recap/daemon/server.py`, `recap/daemon/events.py`, `recap/daemon/config.py`, `recap/daemon/api_config.py` (new), `recap/daemon/service.py`, `pyproject.toml` (+ruamel.yaml).
- Plugin: `obsidian-recap/src/api.ts`, `notificationHistory.ts`, `main.ts`, `renameProcessor.ts`, `settings.ts`, `views/SpeakerCorrectionModal.ts`, `views/MeetingListView.ts`.
- Extension: `extension/options.html`, `options.js`, `background.js`.
- Tests: `tests/test_phase4_integration.py` (new), `tests/test_api_config.py` (new), `tests/test_api_events.py` (new), `tests/test_clip_endpoint.py` (new); updates to `tests/test_daemon_server.py` and `tests/test_event_journal.py`.
- Docs: `docs/handoffs/2026-04-XX-phase4-plugin-manual-acceptance.md`, `MANIFEST.md`.

---

## Section 1: Task Groups

**17 tasks in 5 groups.** Ordering: observability vertical slice + extension auth land first; legacy route deletion follows immediately to close the Phase 3 transitional gap.

### Group 1 — Observability vertical slice + extension auth (5 tasks)

1. **Daemon `/api/events?since=&limit=`** — journal backfill endpoint. Bearer-required. Parses `since` via `datetime.fromisoformat`, filters entries where `parsed(entry["ts"]) > parsed(since)`, caps at `limit`, returns ascending by ts. Malformed `since` or non-int `limit` → 400.
2. **Plugin `api.ts`** — new methods `tailEvents(since?, limit?)` + `onEvent(handler)` with `journal_entry` WS subscription. Update `DaemonStatus` type to match daemon's current shape (adds `uptime_seconds`, `recent_errors`; keeps legacy `daemon_uptime`/`errors` for compat). Pure client-side contract cleanup.
3. **Plugin `notificationHistory.ts`** — daemon-backed refactor. Public API: `load()` tails last 100, `subscribe()` listens for `journal_entry` WS events, `render()` combines live + backfill. Remove in-memory store; remove `add()` method. `main.ts:295` stops synthesizing notifications from `state_change` events.
4. **Extension `options.html` + `options.js`** — Daemon URL field (default `http://localhost:9847`, loopback-only validation, normalized on save: trim + strip trailing `/`); Connect button fetches `/bootstrap/token` (1s timeout); stores `recapAuth = {token, baseUrl, pairedAt}`; handles 200/403/404 with user-facing messages; listens to `chrome.storage.onChanged` for cross-context sync; when `baseUrl` changes, clears `token` and `pairedAt`.
5. **Extension `background.js`** — `authReady` promise populated at startup from `chrome.storage.local.get("recapAuth")`; subscribes to `chrome.storage.onChanged`; `notifyRecap()` awaits `authReady` before first call; sends `Authorization: Bearer <token>` on `/api/meeting-detected` + `/api/meeting-ended`; 401 clears stored token, sets badge red with "AUTH" text; reads `cachedAuth.baseUrl` for every fetch (including `/health`).

### Group 2 — Prove auth, kill legacy (2 tasks)

6. **Daemon — delete transitional routes.** Lands immediately after Group 1 is verified (extension sends Bearer successfully). Removes `/meeting-detected` + `/meeting-ended` unauth route registrations, the "Transitional: remove in Phase 4" comment block, and `TestLegacyMeetingRoutesStillWork` tests. Updates MANIFEST `server.py` note.
7. **Plugin `main.ts` + `renameProcessor.ts`** — silent-catch elimination per §2.5. Every `catch {}` / `catch (e) {}` / log-only catch becomes `new Notice("Recap: <action> failed — <msg>"); console.error("Recap:", e);`. Plugin-local errors do NOT write to daemon journal (§0.4 invariant).

### Group 3 — Config API + settings UI (4 tasks)

8. **Daemon `recap/daemon/api_config.py` (new) + `/api/config` GET** — explicit `ApiConfig` dataclass hierarchy (allowlist, not deny-list scrub). Translation functions: `load_yaml_doc`, `yaml_doc_to_api_config`, `apply_api_patch_to_yaml_doc`, `validate_yaml_doc`. `DaemonConfig.config_path` + `DaemonConfig.config_lock` (threading.Lock) move to `Daemon` instance. New pure parser `parse_daemon_config_dict(raw) -> DaemonConfig` in `config.py`; `load_daemon_config()` delegates to it.
9. **Daemon `/api/config` PATCH** — under `Daemon.config_lock`. Validates unknown top-level AND nested keys → 400. Whole-list replacement for `orgs` / `known_contacts` (never element-wise merge). ruamel round-trip preserves comments; mutates `CommentedMap` in place; dumps to `config.yaml.tmp` via stream (not `write_text(yaml.dump(...))`); `os.replace()` atomic rename. Post-mutation validation via `parse_daemon_config_dict(dict(doc))`; failure → 400 without writing. Emits `config_updated` journal event with `payload={"changed_keys": [...]}` (keys only, no values). Response includes `{"restart_required": true}`.
10. **Plugin `settings.ts` pt.1 — orgs section.** List/add/edit/delete/mark default. Single `orgs[].default` flag is writable; `default_org` derived on GET. PATCH sends the whole orgs list on save.
11. **Plugin `settings.ts` pt.2 — detection + calendar + known contacts + daemon lifecycle.** Detection rules per platform (enabled, behavior, default_org, default_backend). Calendar providers (enabled, calendar_id, org). Known contacts (name, aliases, email) as editable list. Daemon lifecycle panel shows state/uptime from `/api/status`; "Restart daemon" surfaces a Notice instructing tray-quit + relaunch (no restart endpoint built).

### Group 4 — Feature parity (4 tasks)

12. **Daemon `/api/recordings/<stem>/clip?speaker=&duration=`** — stem validation (regex `[A-Za-z0-9._-]+`, reject `..`, `/`, `\`). Resolves `audio_path = daemon.config.recordings_path / f"{stem}.flac"`; transcript via `artifacts.transcript_path(audio_path)`; iterates `TranscriptResult.utterances` for first match on `speaker`. ffmpeg via `asyncio.create_subprocess_exec` with 96kbps mono. Cache at `<recordings_path>/<stem>.clips/<label>_<duration>s.mp3`. Missing audio/transcript/speaker → 404 each with specific error message. ffmpeg non-zero → 500 + `clip_extraction_failed` journal event.
13. **Plugin `SpeakerCorrectionModal.ts`** — `<audio controls>` per SPEAKER_XX label, `src` = `getSpeakerClipUrl(recordingPath.stem, speaker)`. Known-contacts dropdown sources from `/api/config`.`known_contacts`. Loading/error states for failed clip fetches.
14. **Plugin `MeetingListView.ts`** — on load: `GET /api/config` → extract org subfolder list → filter `this.app.vault.getMarkdownFiles()` by `f.path.startsWith(subfolder)` for each configured org. Falls back to whole-vault scan if `/api/config` unreachable, with a Notice. Target: sub-100ms on a 10k-note vault.
15. **Plugin `api.ts` DaemonStatus type sync** — Already covered in Task 2 above, but verify at this point: the plugin's `DaemonStatus` interface matches what `server.py:58-107` actually returns. If any gaps remain (e.g., `state`/`recording` shape drift), align here.

### Group 5 — Integration + docs (2 tasks)

16. **`tests/test_phase4_integration.py`** — contract integration (Python only). Pairing → `GET /bootstrap/token` → Bearer `/api/meeting-detected` → journal tail shows event → `GET /api/events?since=...` backfills correctly → WS connect receives live `journal_entry` frame. `/api/config` GET + PATCH round-trip. Clip endpoint smoke test (skipped if ffmpeg unavailable in test env). Plugin-side verification is manual per the handoff checklist — no JS test runner is stood up in Phase 4.
17. **MANIFEST update + manual acceptance checklist** — commit `docs/handoffs/2026-04-XX-phase4-plugin-manual-acceptance.md` with click-path checklist (pair extension, trigger meeting, verify notification history, edit config via settings UI, play speaker clip, verify filtered vault scan). Update `MANIFEST.md` to reflect new daemon module (`api_config.py`), new endpoints, plugin refactors, extension auth wiring. Remove legacy-route caveats.

**Dependencies:**
- Group 1 internal: Task 1 (`/api/events`) unblocks Tasks 2-3 (plugin notification refactor). Tasks 4-5 (extension) can land in parallel.
- Group 2: Task 6 (legacy route deletion) lands **immediately** after Group 1 extension tasks verified. Task 7 (plugin silent-catch) is independent of Task 6 — can land concurrently.
- Group 3: Task 8 (`/api/config` GET) unblocks Tasks 10-11 (settings UI). Task 9 (PATCH) can land between 10 and 11.
- Group 4: Tasks 12-13 (clip endpoint + modal) couple; Task 14 (list narrowing) independent; Task 15 (type sync) trivial.
- Group 5: Tasks 16-17 are closeout.

---

## Section 2: Technical Decisions

### 2.1 Extension token storage + refresh contract

**Storage:** `chrome.storage.local.recapAuth = {token: string, baseUrl: string, pairedAt: number}`. No expiry field — daemon's `auth_token` persists for daemon lifetime; staleness detected reactively via 401.

**`options.js` pairing flow:**
- Daemon URL input, default `http://localhost:9847`. Loopback-only validation (`hostname in {localhost, 127.0.0.1, ::1}`). Normalize on save: trim + strip trailing `/`.
- Connect button: `fetch(${baseUrl}/bootstrap/token)` with 1s timeout, no auth header.
- 200 → store `recapAuth`. 404 → "Open Recap tray, click 'Pair browser extension…', try again." 403 → "Pairing rejected (non-loopback)." Timeout → "Daemon unreachable."
- Disconnect → `chrome.storage.local.remove("recapAuth")`.
- When `baseUrl` changes (user edits + saves), clear `token` and `pairedAt` but keep new `baseUrl`. Force re-pair.
- Listens to `chrome.storage.onChanged` for `recapAuth` so UI updates if background clears token on 401.

**`background.js`:**
- Module-level `authReady: Promise<void>` initialized at service worker startup from `chrome.storage.local.get("recapAuth")`. `notifyRecap()` `await`s `authReady` before first call. Closes the MV3 service-worker wake-up race.
- `cachedAuth` updated on `chrome.storage.onChanged` for `recapAuth` key.
- Endpoint migration: `/meeting-detected` → `/api/meeting-detected`; same for ended.
- Sends `Authorization: Bearer ${cachedAuth.token}` when token present. No token → skip call, badge red.
- 401 → `chrome.storage.local.remove("recapAuth")` (cascades via onChanged); badge red + "AUTH"; console log prompts re-pair.
- `/health` stays unauth; uses `cachedAuth?.baseUrl ?? "http://localhost:9847"` fallback so health check works pre-pairing.

### 2.2 `/api/events` semantics

**Signature:** `GET /api/events?since=<RFC3339>&limit=<int>` (Bearer).

**Params:**
- `since` — optional; if present, return entries where `parsed_datetime(entry["ts"]) > parsed_datetime(since)`. Parsing via `datetime.fromisoformat` (accepts both second and microsecond precision, any offset).
- `limit` — optional, default 100. Parse via `int()` wrapped in try/except → 400 on failure. Clamp to `[1, 500]` silently after successful parse.

**Response:** `{"entries": [...]}`, ascending by `ts`. Filter happens in the handler; `EventJournal.tail()` stays unchanged. Malformed journal lines are skipped (already the case).

**Precision fix:** `EventJournal.append()` drops `timespec="seconds"` kwarg → defaults to microseconds (RFC3339 with fractional). Practically eliminates same-second collision for `since` filtering. Legacy second-precision entries still parse and sort correctly via `datetime.fromisoformat`.

**Plugin consumption:**
1. On mount: `tailEvents(undefined, 100)` → render ascending, optionally `.reverse()` for newest-first UI.
2. On `journal_entry` WS frame: append to scrollback (order-preserving; WS frames are emitted after append, so monotonic).
3. On WS reconnect: `tailEvents(lastSeenTs, 500)` for gap fill.

### 2.3 `/api/config` GET + PATCH

**API DTO module (`recap/daemon/api_config.py`, new):**

```python
@dataclass
class ApiOrgConfig:
    name: str
    subfolder: str
    default: bool

@dataclass
class ApiDetectionRule:
    enabled: bool
    behavior: str               # "auto-record" | "prompt"
    default_org: Optional[str]
    default_backend: Optional[str]

@dataclass
class ApiCalendarProvider:
    enabled: bool
    calendar_id: Optional[str]
    org: Optional[str]

@dataclass
class ApiKnownContact:
    name: str
    aliases: list[str]
    email: Optional[str]

@dataclass
class ApiConfig:
    vault_path: str
    recordings_path: str
    user_name: Optional[str]
    plugin_port: int
    orgs: list[ApiOrgConfig]
    default_org: Optional[str]  # derived on GET; NOT writable
    detection: dict[str, ApiDetectionRule]
    calendar: dict[str, ApiCalendarProvider]
    known_contacts: list[ApiKnownContact]
    recording_silence_timeout_minutes: int
    recording_max_duration_hours: float
    logging_retention_days: int
```

**Writable sources of truth:** `orgs[].default` is writable; `default_org` is derived on GET (the first org with `default=True`). PATCH of `default_org` → 400 `{"error": "default_org is read-only; set orgs[i].default instead"}`.

**Four pure functions in `api_config.py`:**
- `load_yaml_doc(path: Path) -> CommentedMap` — ruamel round-trip load.
- `yaml_doc_to_api_config(doc: CommentedMap) -> ApiConfig` — explicit field extraction, ignores keys not in allowlist.
- `apply_api_patch_to_yaml_doc(doc: CommentedMap, patch: dict) -> None` — mutates ruamel doc **in place**. Scalars: `doc[key] = value`. Lists: `doc[key].clear(); doc[key].extend(new)` preserving ruamel types. Nested dicts (`detection`, `calendar`): per-key scalar replacement, preserving sibling keys and comments.
- `validate_yaml_doc(doc: CommentedMap) -> DaemonConfig` — coerces through `parse_daemon_config_dict(dict(doc))`. Raises `ValueError` with field-specific message on failure.

**New `config.py` function:** `parse_daemon_config_dict(raw: dict) -> DaemonConfig` — pure parser, no file I/O. Existing `load_daemon_config(path)` delegates: `parse_daemon_config_dict(yaml.safe_load(path.read_text()))`.

**Daemon state:** `Daemon.config_path: Path` + `Daemon.config_lock: threading.Lock`, populated in `__init__`. Replaces any module-level globals.

**PATCH handler:**
```python
async def _api_config_patch(request):
    daemon = request.app["daemon"]
    body = await request.json()
    if not isinstance(body, dict):
        return web.json_response({"error": "body must be a JSON object"}, 400)

    # Recursive strict key validation
    unknown = _find_unknown_keys(body, ApiConfig)
    if unknown:
        return web.json_response({"error": f"unknown fields: {unknown}"}, 400)

    with daemon.config_lock:
        doc = load_yaml_doc(daemon.config_path)
        apply_api_patch_to_yaml_doc(doc, body)
        try:
            validate_yaml_doc(doc)
        except ValueError as e:
            return web.json_response({"error": str(e)}, 400)

        tmp = daemon.config_path.with_suffix(".yaml.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            yaml_rt.dump(doc, f)   # ruamel stream dump
        os.replace(tmp, daemon.config_path)

    daemon.emit_event("info", "config_updated",
                      f"Config PATCHed (keys: {sorted(body.keys())})",
                      payload={"changed_keys": sorted(body.keys())})
    return web.json_response({"status": "ok", "restart_required": True})
```

**`_find_unknown_keys`** walks the body recursively against `ApiConfig`'s nested dataclass shape. Top-level, `detection.<platform>`, `calendar.<provider>`, `orgs[i]`, `known_contacts[i]` — all are strictly validated. Unknown nested key → 400 with the full dotted path.

**New dep:** `ruamel.yaml` (added to `pyproject.toml` under `[project.dependencies]` — it's a production dep now, not just a dev tool).

### 2.4 Audio clip endpoint

**Signature:** `GET /api/recordings/<stem>/clip?speaker=<label>&duration=<seconds>` (Bearer).

**Stem validation:** regex `^[A-Za-z0-9._-]+$`. Reject `..`, `/`, `\`, or any character outside the set → 400.

**Resolution:**
- `audio_path = daemon.config.recordings_path / f"{stem}.flac"`. Missing → 404.
- `transcript_path(audio_path)` from `recap/artifacts.py:104` → sibling `.transcript.json`. Missing → 404.
- Parse as `TranscriptResult`; iterate `utterances` (NOT `segments`); find first where `utterance.speaker == label`. None found → 404 `{"error": "speaker not found in transcript"}`.
- Clip window: `start..min(start + duration, utterance.end)` — bounded by utterance end.

**Parameters:**
- `speaker` — required; diarization label string.
- `duration` — optional int seconds, default 5, valid `[1, 30]`. Out of range → 400.

**Cache:** `<recordings_path>/<stem>.clips/<label>_<duration>s.mp3`. Cache hit → `FileResponse`. Cache miss → ffmpeg:

```
ffmpeg -y -ss <start> -t <clip_duration> -i <audio_path> \
  -acodec libmp3lame -b:a 96k -ar 22050 <cache_path>
```

Via `asyncio.create_subprocess_exec`. Non-zero exit → 500 + `clip_extraction_failed` journal event with `{"stem", "speaker", "returncode"}`.

**No automatic cache invalidation** in Phase 4. Documented: "delete `<stem>.clips/` to force regeneration after speaker relabel."

### 2.5 Silent-catch policy

**Invariant:** plugin NEVER writes to daemon journal (§0.4). `notificationHistory.add(...)` does not exist after Task 3's refactor.

**Standard replacement pattern:**
```typescript
try {
    await riskyOperation();
} catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    new Notice(`Recap: <action description> failed — ${msg}`);
    console.error("Recap:", e);
}
```

**Two error layers:**
- **Plugin-local failures** (reading auth token, reconnecting WS, opening files, rendering views, renameProcessor hiccups): `Notice + console.error`. Not journaled, not stored.
- **Daemon-side failures**: already journaled by Phase 3 (Task 11). Plugin's refactored `notificationHistory` renders them via WS subscription + `/api/events` backfill.

**Result for user:** errors appear in Obsidian toasts (plugin-side) AND in the notification history panel (daemon-side). No silent vanishing; no cross-contamination.

**Target sites (from grep of current plugin):**
- `main.ts:289` (silent status-refresh catch)
- `main.ts` — `readAuthToken`, `reconnect`, file-open / activateView handlers
- `renameProcessor.ts` throughout
- Any `api.ts` fetch/WS error paths missing user surface

### 2.6 Testing approach

**Automated (Python):**
- `tests/test_phase4_integration.py` — full contract: pair → Bearer → journal → events backfill → WS live → config PATCH round-trip.
- `tests/test_api_events.py` — unit: since/limit parsing, ascending order, microsecond precision, malformed params.
- `tests/test_api_config.py` — unit: GET sanitization, PATCH validation (unknown keys at all depths), ruamel comment preservation, atomic write on failure, list whole-replacement.
- `tests/test_clip_endpoint.py` — unit tests mock `asyncio.create_subprocess_exec` for non-zero exit, transcript missing, speaker missing, cache hit, stem validation. **One** integration-style test that invokes real ffmpeg with `pytest.importorskip` or a `shutil.which("ffmpeg") is None` skip guard — skipped in CI-without-ffmpeg.

**Manual (plugin + extension):**
- `docs/handoffs/2026-04-XX-phase4-plugin-manual-acceptance.md` — click-path checklist committed at Task 17. Covers: pair extension, trigger meeting detection, verify notification history populates (both backfill and live), edit an org via settings UI, verify `config.yaml` round-tripped with comments, play a speaker clip, verify MeetingListView loads <100ms on a populated vault.

**No JS test runner in Phase 4.** Standing up Jest/Vitest with Obsidian mocks is ~half a day and buys little for Phase 4's scope. Phase 5+ can revisit if plugin test gaps hurt.

---

## Acceptance Criteria

- [ ] Extension pairs successfully from tray → options → Connect; 401 clears token and prompts re-pair.
- [ ] All `/api/meeting-detected` + `/api/meeting-ended` traffic is Bearer-authenticated end-to-end. Legacy unauth routes deleted.
- [ ] Plugin notification history shows both backfill (entries from before Obsidian opened) and live events (WebSocket).
- [ ] Settings UI round-trips `orgs`, `detection`, `calendar`, `known_contacts`. Editing a field in UI updates `config.yaml` on disk with comments preserved.
- [ ] Speaker correction modal plays MP3 clips per SPEAKER_XX label. Known contacts dropdown populated from `/api/config`.
- [ ] `MeetingListView` only iterates files under configured org subfolders. Sub-100ms load on a 10k-note vault.
- [ ] Zero `catch {}` or `catch (e) {}` blocks in plugin code swallow an error without `Notice` + console.
- [ ] Python integration test (`test_phase4_integration.py`) passes end-to-end.
- [ ] Manual acceptance checklist committed and all items verified by user before Phase 4 merge.

## Post-Phase Verification

| Check | Expected |
|---|---|
| `uv run pytest -q` | all pass (~520) |
| `grep -rn "catch {}\|catch (e) {}" obsidian-recap/src/` | 0 hits |
| `grep -rn "'/meeting-detected'\|'/meeting-ended'" recap/daemon/server.py` | 0 hits (only `/api/...` variants) |
| `grep -n "class ApiConfig" recap/daemon/api_config.py` | 1 hit |
| `grep -n "ruamel.yaml" pyproject.toml` | 1 hit |
| Plugin manual checklist | all items ✓ |

## Handoff to Phase 5

Phase 5 (Honesty Pass + cleanup) picks up:
- Remaining `except Exception:` swallow patterns missed in Phase 4.
- Deleting deprecated scaffolding identified during Phase 4 (TBD list from Phase 4 reviewers).
- Tightening type safety where Phases 1-4 made it possible.
- Potentially: JS test runner for plugin if manual acceptance proves inadequate.
- Potentially: backwards pagination for `/api/events` if notification scrollback needs grow.

Phase 4 does NOT touch Phase 2 frozen code (EventIndex, OrgConfig.resolve_subfolder, resolve_note_path, to_vault_relative). Phase 3's transitional shapes (`callbacks` dict in `Daemon.start`, dual status keys) are reviewed for closure; remaining transitional shapes stay deferred to Phase 5.

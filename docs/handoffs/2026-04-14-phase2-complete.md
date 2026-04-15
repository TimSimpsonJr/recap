# Handoff: Recap Phase 2 Complete, Phase 3 Ready

**Date:** 2026-04-14
**Project:** Recap (obsidian-pivot branch)
**Session duration:** full day, one conversation

---

## What We Did

Executed Phase 2 in full via `superpowers:subagent-driven-development`: 10 planned tasks + 7 review-driven follow-up commits (17 commits total), each task gated by spec-compliance review and code-quality review. Codex re-reviewed Phase 2 at the end and green-lit it after one cross-folder stale-heal fix (commit `f27fa2b`). Drafted the Phase 3 plan (`docs/plans/2026-04-14-phase3-runtime-foundation.md`, 13 tasks, 1588 lines). Did not start Phase 3 execution.

Phase 2 closed three things:

1. **Calendar-side org bifurcation** — killed `sync.py:org_subfolder()` hardcode; `write_calendar_note` and `should_update_note` take `OrgConfig`; calendar frontmatter carries `org-subfolder:` from creation; scheduler logs+skips on unknown org slug; `update_calendar_note` backfills `org-subfolder` on pre-canonical notes.

2. **Persistent `EventIndex`** (new `recap/daemon/calendar/index.py`) — schema-v1 JSON at `<vault>/_Recap/.recap/event-index.json`; `pathlib.PurePosixPath` end-to-end (forward slash on every OS, symmetric persist/load); thread-safe immediate-persist; graceful load-failure handling (corrupt JSON + unknown schema version both warn and treat as empty); hooked into both write paths (`upsert_note`, `write_calendar_note`); `find_note_by_event_id` consults index → stale-lookup warns + falls back to narrow scan → heals stale entry on scan hit (`rename()` preserves `org`) or misses → widens to `vault_path.rglob("Meetings/*.md")` on cross-folder moves → on still-miss `remove()`s the stale entry.

3. **Vault-relative `note_path`** (Codex's deferred Phase 1 P2) — `recap/artifacts.py:resolve_note_path` (read; legacy absolute + vault-relative) and `to_vault_relative` (write; forward-slash normalized); all write sites migrated; legacy absolute paths migrate on next save. Consolidated the pre-existing `sync.py:_to_vault_relative` into the canonical helper.

Plus full daemon-service-graph wiring: one `EventIndex` per process owned by `__main__.py`, **unconditional startup rebuild** (Codex 2026-04-14 lock-in), **no scheduler-tick rebuild** (same lock-in), threaded through scheduler, detector, pipeline, vault via constructors + `run_pipeline` kwarg. `should_update_note` accepts the index too (closed the last O(n) gap). End-to-end integration test at `tests/test_phase2_integration.py` verifies calendar-sync → pipeline → index consistency.

## Decisions Made

- **Phase 3 is a pure runtime-foundation phase** — `Daemon` service class retires `_loop_holder`/`_app_holder`; `EventJournal` backs real `/api/status` and plugin notification history; Signal popup becomes async; AudioCapture monkey-patch dies; extension auth is explicit tray-initiated one-shot pairing; `autostart.py` deleted; detector's `_org_subfolder` hand-join retired (Phase 2 carryover).

- **EventIndex rebuild policy locked (Codex 2026-04-14)**: startup rebuild is UNCONDITIONAL (not gated on file existence — must survive a stale or corrupt persisted index); NO scheduler-tick rebuild (normal write paths keep the index warm; Phase 4's rename endpoint will handle Obsidian-side drift); on stale lookup, warn + fall back to scan. This is encoded in `docs/plans/2026-04-14-phase3-runtime-foundation.md` Task 2 (`Daemon.start_services_only_for_test()` + `Daemon.start()`): the rebuild moves from `__main__.py` into `Daemon.start()` but stays unconditional.

- **EventIndex stores `pathlib.PurePosixPath`** — forward-slash on every OS, symmetric persist+load. `WindowsPath / PurePosixPath` composes correctly to `WindowsPath` on Windows (empirically verified). Consumers use `vault_path / entry.path` without wrapping. `str(entry.path)` always returns forward-slash form (good for logging, comparison, JSON).

- **`find_note_by_event_id` is index-first with dual-fallback heal** — narrow `search_path.glob("*.md")` is the normal scan fallback (caller-scoped org's meetings dir). On a heal path only (stale index entry), if the narrow scan misses, widen to `vault_path.rglob("Meetings/*.md")` to catch cross-folder moves. Non-stale lookups still hit the narrow fast path. `rename()` preserves `org`; `remove()` if both scans miss.

- **Calendar-owned vs pipeline-owned frontmatter** — Phase 1's `_CALENDAR_OWNED_KEYS` contract holds end-to-end: calendar writes `time`, `calendar-source`, `event-id`, `meeting-link` as identity; pipeline writes `pipeline-status`, `type`, `recording`, `companies`, etc. via `build_canonical_frontmatter`. The calendar-side frontmatter dict now also carries `org-subfolder: <raw_string>` so scheduled-but-unrecorded notes are in canonical shape from creation.

- **`write_meeting_note` lives in `vault.py`, not `pipeline/`** — `MANIFEST.md` was corrected for this attribution (the `build_canonical_frontmatter` is called from `write_meeting_note`, which the pipeline invokes; the function itself lives in vault).

- **Detector `_org_subfolder` stays until Phase 3 Task 5** — `MANIFEST.md` Key Relationships explicitly flags this as a Phase 3 cleanup target (scheduler and sync.py go through `resolve_subfolder`, detector still hand-joins `org_config.subfolder`). Phase 3 Task 5 fixes it in the same commit as the async Signal popup since both touch `detector.py`.

## Current State

**Branch:** `obsidian-pivot`.
**Baseline before Phase 2:** `8c78911` (Phase 2 plan committed), `dcc9787` (handoff), `411aca4` (my plan update for Codex Task 8 lock-in).
**HEAD at end of session:** `feabf8c` (Phase 3 plan committed).
**Phase 2 commit range:** `411aca4..f27fa2b` (17 commits: 10 task commits + 7 review-driven follow-ups).
**Test suite:** 386 passing (up from 342 pre-Phase-2). `uv run pytest -q` at 33 seconds.
**Worktree state:** `uv.lock` and `docs/reviews/` are modified/untracked in the working tree but intentionally NOT staged (pre-existing from before the session).

**Key files from Phase 2:**

- `recap/daemon/calendar/index.py` — `EventIndex` (new), `IndexEntry` dataclass (`PurePosixPath`).
- `recap/daemon/calendar/sync.py` — `write_calendar_note(event, vault_path, org_config, *, event_index=None)`; `should_update_note` takes `event_index`; `update_calendar_note(..., org_config=None)` backfills; `find_note_by_event_id(..., vault_path, event_index)` with self-heal + cross-folder widen scan.
- `recap/daemon/calendar/scheduler.py` — uses `org_by_slug` + `resolve_subfolder`; passes `event_index` to sync calls; warns+skips on unknown slug.
- `recap/daemon/recorder/detector.py` — receives `event_index` via ctor; `_find_calendar_note` returns vault-relative; **`_org_subfolder` still hand-joins (Phase 3 Task 5)**.
- `recap/daemon/__main__.py` — constructs `EventIndex` singleton; unconditional startup rebuild; threads through scheduler, detector, `_make_process_recording`.
- `recap/pipeline/__init__.py` — `_resolve_note_path(metadata, recording_metadata, meetings_dir, vault_path, event_index)` (pure resolver, no mutation); `run_pipeline(..., event_index=None)`; uses `to_vault_relative`/`resolve_note_path` at all note_path write sites.
- `recap/vault.py` — `upsert_note(..., event_index=None, vault_path=None)`; `_update_index_if_applicable` helper with debug logging on mismatched kwargs / outside-vault; `write_meeting_note` threads kwargs.
- `recap/artifacts.py` — `resolve_note_path(str, vault_path) -> Path`, `to_vault_relative(Path, vault_path) -> str`.
- `recap/daemon/config.py` — `OrgConfig.resolve_subfolder(vault_path) -> Path`, `DaemonConfig.org_by_slug(slug) -> OrgConfig | None`.

**Plan + handoff docs committed:**

- `docs/plans/2026-04-14-fix-everything-design.md` (Phase 0 contract freeze + all six phases sketched — unchanged from Phase 1)
- `docs/plans/2026-04-14-phase1-data-contracts.md` (complete, committed earlier)
- `docs/plans/2026-04-14-phase2-org-and-event-index.md` (complete + the commit `411aca4` Task 8 lock-in)
- `docs/plans/2026-04-14-phase3-runtime-foundation.md` (new, 13 tasks, ready to execute)
- `docs/handoffs/2026-04-14-fix-everything-phase1.md` (Phase 1 handoff)
- `docs/handoffs/2026-04-14-phase2-complete.md` (this file)

**Codex approval status:** Phase 2 approved. Codex: "Phase 2 is fully green from my side and ready to hand off into Phase 3 planning."

## What Remains

In order:

1. **Execute Phase 3** — see `docs/plans/2026-04-14-phase3-runtime-foundation.md`. 13 tasks. Foundational: `EventJournal` → `Daemon` service class → shrink `__main__.py`. Recorder-side: `AudioCapture.on_chunk` + async Signal popup + detector awaitable callback + retire detector `_org_subfolder`. Server: real `/api/status` + journal WebSocket broadcast, `/api/*` Bearer auth migration, dead-route cleanup. Auth: `PairingWindow` + `/bootstrap/token` + tray menu. Misc: `/api/index/rename`, delete `autostart.py`, notifications → journal. Integration test + MANIFEST last.

2. **Codex re-review after Phase 3** — same cadence as Phases 1 and 2. Hand off a summary of commits + acceptance-criteria status. No Phase 4 work until Codex greenlights.

3. **Execute Phase 4** — plugin settings UI buildout, daemon-owned notification history (plugin renders over `/api/events` + WebSocket), speaker correction audio preview, extension auth wiring (consume `/bootstrap/token`, send Bearer), rename processor POSTs to `/api/index/rename`, narrow `MeetingListView` to configured subfolders, kill silent `catch {}` blocks, remove transitional unauth `/meeting-detected` routes.

4. **Execute Phase 5** — honesty pass (remove deprecated fields, `implemented: false` placeholders).

5. **Execute Phase 6** — test contract hardening.

6. **Final integration pass + Codex review** — before merging `obsidian-pivot` to main.

Blocked on: nothing. All phases can proceed once Codex greenlights the preceding phase.

## Open Questions

- **Token scope for `/bootstrap/token`** — Phase 3 Task 8 explicitly defers the scoped-vs-full-token decision to implementation time (§0.5). If the auth middleware accepts a simple allow-list check, issue a scoped extension token (authorized only for `/api/meeting-detected` + `/api/meeting-ended`). Otherwise issue the full daemon token; explicit pairing + loopback-only + one-shot + journaling are the primary defense. Decision recorded in the Task 8 commit message.

- **Transitional unauthenticated `/meeting-detected` route** — Phase 3 Task 7 keeps the legacy unauth endpoint as a bridge (§0.5: "during Phase 3 implementation, the daemon supports both authenticated and unauthenticated endpoints briefly so the extension isn't broken mid-refactor"). Phase 4 removes it once the extension consumes the Bearer token. Do NOT remove earlier.

- **`llm_backend` → `llm_backend_override` rename** — cosmetically cleaner per Codex. Not urgent. Phase 3 Task 5 is the natural fold-in point if it stays small (Signal popup plumbing). If it ripples, defer to Phase 5.

## Context to Reload

- **Design doc is source of truth.** `docs/plans/2026-04-14-fix-everything-design.md`. Every phase's acceptance criteria traces back to a section there. §0.4 (event journal schema) and §0.5 (extension auth protocol) are especially load-bearing for Phase 3.

- **Execution skill:** `superpowers:subagent-driven-development`. Two-stage review per task (spec-compliance then code-quality via `superpowers:code-reviewer` agent type) is NOT optional. After all tasks, one final phase-level review.

- **Per-task implementer prompts** should include: full plan text for the task, baseline SHA, scope guardrails (what NOT to touch), self-review criteria. Skill-template files are at `C:\Users\tim\.claude\plugins\cache\superpowers-marketplace\superpowers\4.3.1\skills\subagent-driven-development\*.md`.

- **Commit discipline:** Conventional Commits always. One task = one logical commit (Phase 2 had ~1.7 commits per task average due to review-driven follow-ups, which is healthy). Never stage `uv.lock` or `docs/reviews/` — pre-existing untracked state from before the session.

- **Test running:** `uv run pytest -q` for the full suite. Takes ~33 seconds. Test count should only go up.

- **No `write_meeting_note` or `upsert_note` mocks.** If a test wants to verify frontmatter output, it uses a real tmp vault. Phase 1's hard rule, still enforced.

- **Codex review cadence:** after each phase's execution, hand off a summary of commits + acceptance criteria status to Codex. Don't merge or move on until Codex greenlights.

- **Phase 2 carryovers flagged in Phase 3 plan:** detector `_org_subfolder` (Task 5).

- **Phase 2 Codex lock-ins to preserve through Phase 3:**
  - Unconditional startup rebuild of EventIndex (now in `Daemon.start()`, not gated on file existence).
  - No scheduler-tick rebuild.
  - Stale lookup warns + dual-fallback scan (narrow then widen on heal).

- **Windows environment note:** Git will emit LF→CRLF warnings on every commit. They're cosmetic. Files committed with LF endings as intended.

- **User's global CLAUDE.md:** NEVER use `EnterPlanMode` — use the `brainstorming` skill instead. Prose-craft is not needed for internal docs.

- **Key SHAs for the branch:**
  - `a9b9418` — pre-work baseline (start of Phase 1 session).
  - `881f0db` — Phase 1 final fix.
  - `8c78911` — Phase 2 plan committed.
  - `dcc9787` — Phase 1 handoff.
  - `411aca4` — Codex Task 8 lock-in applied to Phase 2 plan.
  - `f27fa2b` — Phase 2 complete (cross-folder stale-heal fix).
  - `feabf8c` — Phase 3 plan committed (HEAD at handoff write time).

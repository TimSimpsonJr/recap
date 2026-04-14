# Handoff: Recap Fix-Everything Phase 1

**Date:** 2026-04-14
**Project:** Recap (obsidian-pivot branch)
**Session duration:** ~full day, one conversation

---

## What We Did

Started by roasting the codebase from two angles (Claude + Codex), which surfaced four silent data-integrity bugs plus a lot of architectural debt on the `obsidian-pivot` branch. Drove the findings through the brainstorming skill to produce a six-phase fix plan with explicit contract freeze (Phase 0), then executed Phase 1 in full via subagent-driven-development: 13 planned tasks + 4 follow-up commits, each gated by spec-compliance and code-quality review. Codex re-reviewed Phase 1 at the end and green-lit it after two P1 follow-up fixes. Phase 2 plan is written and committed. Did not start Phase 2 execution.

Phase 1 fixed:
- Calendar-seeded notes silently losing canonical frontmatter (recording, duration, type, tags, companies) — the most severe bug, Codex's #1.
- Frontmatter `org` being a folder path instead of a slug — Codex's #2.
- Signal popup backend choice being collected and ignored — Codex's #3 (data path + caller plumbing).
- Two `PipelineConfig` classes with identical names but incompatible shapes.
- Tests mocking the contract they claimed to verify.

Plus two bugs caught during final review and fixed before declaring Phase 1 done:
- `upsert_note` would crash on notes containing a marker but no frontmatter (a 5th case the initial design missed).
- `RecordingMetadata.llm_backend` defaulted to `"claude"` (truthy), which regressed the pre-Phase-1 behavior of respecting `org_config.llm_backend`. Changed to `Optional[str]` with `None` default.

## Decisions Made

- **6-phase sequenced plan over vertical slices or big-bang rebuild** — Phase 1 fixes contracts, Phase 2 does org/event-index, Phase 3 runtime, Phase 4 plugin+extension, Phase 5 honesty pass, Phase 6 test hardening. Plus Phase 0 contract freeze up front.
- **Contract freeze committed before any code changes** — `docs/plans/2026-04-14-fix-everything-design.md` locks canonical note shape (§0.1), org_slug vs org_subfolder (§0.2), RecordingMetadata shape (§0.3), daemon event journal (§0.4), extension auth (§0.5), PipelineSettings vs PipelineRuntimeConfig naming (§0.6). All phases reference this doc as source of truth.
- **Rename, don't merge, the two `PipelineConfig`s** — they're legitimately different concepts (persisted YAML settings vs per-run runtime config). Renamed to `PipelineSettings` and `PipelineRuntimeConfig` respectively. Codex's suggestion, correct call.
- **Extracted `build_runtime_config` into its own module** (`recap/daemon/runtime_config.py`) during Task 10. Plan said modify in-place, but importing `__main__.py` in tests pulls `pystray`. Extraction is also a Phase 3 prerequisite, so we brought it forward cheaply.
- **Autostart deleted, not stubbed, not implemented** — per the design doc decision. Less decorative surface area is honest.
- **Notification history is daemon-owned JSONL, not plugin-owned** — the plugin can't satisfy "history while Obsidian closed" if it owns the journal. Locked into contract for Phase 4.
- **Extension auth uses explicit tray-initiated one-shot pairing window**, not a silent startup window. Loopback-only, no CORS, journaled. Deferred implementation to Phase 3.
- **`llm_backend` default is `Optional[str] = None`**, not `str = "claude"`. Final reviewer caught that truthy defaults silently masked org defaults. `None` = "use org default"; explicit value = "override from popup/metadata."
- **`note_path` vault-relative normalization deferred to Phase 2** — Codex's P2 finding. Phase 2 Task 7 makes it explicit. Legacy absolute paths still resolve via `resolve_note_path(str, vault_path)` helper.
- **CLI `--org` still doubles as slug and subfolder** — plan explicitly allowed it ("CLI is for solo use"). Flagged for follow-up; not urgent since the daemon path is correct.

## Current State

**Branch:** `obsidian-pivot`.
**Baseline before session:** `a9b9418` (pre-work).
**HEAD at end of session:** `8c78911` (Phase 2 plan committed).
**Total commits in this session:** 22.
**Test suite:** 342 passing (up from 320 pre-session). `uv run pytest -q` at 33-34 seconds.
**Worktree state:** `uv.lock` and `docs/reviews/` are modified/untracked in the working tree but intentionally NOT staged (pre-existing, unrelated to this work).

**Key files from Phase 1:**
- `recap/vault.py` — `build_canonical_frontmatter`, `upsert_note` (5 cases), `_merge_frontmatter` with `_CALENDAR_OWNED_KEYS`, `write_meeting_note` (now a thin delegator).
- `recap/artifacts.py` — `RecordingMetadata` with `llm_backend: str | None = None`.
- `recap/daemon/runtime_config.py` — new module, `build_runtime_config`.
- `recap/daemon/signal_metadata.py` — new module, `build_signal_metadata` (extracted from `__main__.py` callback).
- `recap/daemon/config.py` — `PipelineSettings` (renamed from `PipelineConfig`).
- `recap/pipeline/__init__.py` — `PipelineRuntimeConfig` (renamed), `run_pipeline` takes `org_slug` + `org_subfolder` separately.

**Plan + handoff docs committed:**
- `docs/plans/2026-04-14-fix-everything-design.md` (Phase 0 contract freeze, all six phases sketched)
- `docs/plans/2026-04-14-phase1-data-contracts.md` (the 13-task plan, fully executed)
- `docs/plans/2026-04-14-phase2-org-and-event-index.md` (the next plan, ready to execute)

**Codex approval status:** Phase 1 approved after the two P1 follow-ups landed. Codex explicitly said "Phase 2 looks clear to start."

## What Remains

In order:

1. **Execute Phase 2** — see `docs/plans/2026-04-14-phase2-org-and-event-index.md`. 10 tasks. Owns `recap/daemon/config.py` (helpers), `recap/daemon/calendar/*` (kills hardcode, adds `EventIndex`), `recap/pipeline/__init__.py` (index-backed resolver + vault-relative note_path), `recap/daemon/__main__.py` + `detector.py` (wire index into service graph).
2. **Get Codex to re-review Phase 2** before Phase 3 starts. Same cadence as Phase 1: hand off a summary of commits + acceptance-criteria status.
3. **Execute Phase 3** — Daemon service class, kill `_loop_holder`/`_app_holder`, Signal popup truly async, kill `AudioCapture` monkey-patching with public `on_chunk` callback, extension bootstrap-token pairing, delete `autostart.py` and `/api/autostart`. Consider renaming `llm_backend` → `llm_backend_override` per Codex.
4. **Execute Phase 4** — plugin settings UI buildout, daemon-owned notification history (plugin renders), speaker correction audio preview, extension auth wiring, narrow `MeetingListView` to configured subfolders, kill silent `catch {}` blocks.
5. **Execute Phase 5** — honesty pass (remove deprecated fields, `implemented: false` placeholders, etc.).
6. **Execute Phase 6** — test contract hardening.
7. **Final integration pass + Codex review** — before merging `obsidian-pivot` to main.

Blocked on: nothing. All phases can proceed once Codex greenlights the preceding phase.

## Open Questions

- **Scheduler-driven index rebuild vs rename-endpoint-only?** Phase 2 Task 8 calls out two approaches for keeping the `EventIndex` consistent across out-of-band renames: (a) rebuild on every scheduler sync tick, or (b) rely on `upsert_note` hook + Phase 4's `/api/index/rename` endpoint. Plan recommends (b) with a startup rebuild as the only maintenance operation. Confirm with Codex or user before Phase 2 execution if preference changes.
- **Participant merge semantics** — Codex flagged that canonical-wins on `participants` narrows a rich calendar invitee list down to whatever analysis saw. Not a bug, but a design sharp edge. If Phase 3 or later needs union semantics, it's an explicit contract change not a merge-rule tweak.
- **`llm_backend_override` rename** — cosmetically cleaner than `llm_backend`. Not urgent. Fold into Phase 3 when Signal popup plumbing converges with extension + armed paths.

## Context to Reload

- **Design doc is source of truth.** `docs/plans/2026-04-14-fix-everything-design.md`. Every phase's acceptance criteria traces back to a section there.
- **Execution skill:** `superpowers:subagent-driven-development`. It invokes `superpowers:using-git-worktrees` as a no-op since we're already on `obsidian-pivot` (a feature branch). Implementer per task, then spec-compliance reviewer, then code-quality reviewer via `superpowers:code-reviewer` agent type. Two-stage review is not optional.
- **Per-task implementer prompts** should include: full plan text for the task, SHA context, scope guardrails (what NOT to touch), self-review criteria. Skill-template files are at `C:\Users\tim\.claude\plugins\cache\superpowers-marketplace\superpowers\4.3.1\skills\subagent-driven-development\*.md`.
- **Commit discipline:** Conventional Commits always. Each task is one commit. Never stage `uv.lock` or `docs/reviews/` — they're pre-existing untracked state from before the session.
- **Test running:** `uv run pytest -q` for the full suite. Takes ~33 seconds. Test count should only go up.
- **No `write_meeting_note` or `upsert_note` mocks.** If a test wants to verify frontmatter output, it uses a real tmp vault. This was Codex's test-quality fix and is now a hard rule.
- **Codex review cadence:** after each phase's execution, hand off a summary of commits + acceptance criteria status to Codex. Don't merge or move on until Codex greenlights.
- **`_loop_holder` / `_app_holder` stay until Phase 3.** Multiple Phase 2 changes (scheduler, detector) will need to read `self._config.vault_path`, etc. — do NOT try to refactor the service graph in Phase 2.
- **Baseline commit for the entire batch:** `a9b9418`. HEAD on the branch at session end: `8c78911`.
- **Windows environment note:** Git will emit LF→CRLF warnings on every commit. They're cosmetic. Files committed with LF endings as intended.
- **User's global CLAUDE.md:** NEVER use `EnterPlanMode` — use the `brainstorming` skill instead.
- **Prose-craft is not needed here** — internal docs, no external consumption.

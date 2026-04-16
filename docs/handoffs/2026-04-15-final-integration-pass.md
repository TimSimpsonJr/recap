# Final Integration Pass — manual smoke checklist

Parent design: `docs/plans/2026-04-14-fix-everything-design.md` §Final Integration Pass (lines 417-438).

All automated gates and Review Blockers are verified (see the bottom section). This checklist is the five live-system scenarios that can only be proved on real hardware with real accounts — it is the last gate before shipping Phases 1-6.

**Prereqs on the machine you run this on:**
- Windows 11 + NVIDIA RTX 4070 (or compatible CUDA 12.6-capable card) + SSD.
- `ffmpeg` + `ffprobe` on PATH.
- Obsidian with the `obsidian-recap` plugin installed from `obsidian-recap/`.
- Chrome or Edge with the `extension/` folder loaded unpacked.
- Google Calendar OAuth authorized in the daemon (at least one calendar with a scheduled meeting).
- Claude CLI authenticated (`claude` command works).

**How to record results:** mark each bullet `[x]` when you've verified it, `[~]` if partial, `[F]` if it fails. Leave notes inline. File a follow-up issue for any `F` before `git merge` to `master`.

---

## 1. Calendar → recording → pipeline → canonical note

The golden path the whole system exists to deliver.

- [ ] Create a calendar event (Google or Zoho) in a calendar that's synced into Recap — org slug set via `calendars.<provider>.org` in `config.yaml`.
- [ ] Wait for the sync interval (default 15 min) OR restart the daemon to force an immediate sync.
- [ ] Open the Obsidian vault → `<org-subfolder>/Meetings/` — a stub note exists with frontmatter `event-id: <calendar id>`, `pipeline-status: pending`, scheduled date/time, `platform: calendar`.
- [ ] Join the meeting on a browser tab the extension recognizes (Google Meet, Teams, Zoho, etc.); extension badge flips to green **ON**.
- [ ] Daemon picks up the meeting (watch the tray notification / log). Recording starts.
- [ ] End the meeting; daemon stops recording, pipeline runs.
- [ ] After pipeline completes (transcribe → diarize → analyze → write → convert), re-open the meeting note.
- [ ] Frontmatter is canonical: `title`, `date`, `org` (SLUG, not subfolder), `org-subfolder` (path), `platform`, `participants`, `companies`, `duration`, `type`, `tags`, `pipeline-status: complete`, `recording: <stem>.m4a` (or `.flac` if archive-format is flac).
- [ ] The calendar-seeded fields survived the upsert: same `event-id`, same scheduled time, unchanged calendar metadata.
- [ ] The note exists at exactly ONE path (`<org-subfolder>/Meetings/<title>.md`) — no duplicate from calendar vs pipeline slug mismatch.
- [ ] Body has `## Summary`, `## Key Points`, `## Action Items` (plus any others the analysis produced).

## 2. Signal backend choice survives end-to-end

- [ ] Trigger a manual recording via the Signal popup (or any flow that surfaces the backend selector).
- [ ] Select `ollama` as the backend.
- [ ] Finish the recording; let the pipeline run.
- [ ] Tail the daemon log (or the recording's `.status.json`) during analyze stage → confirm the subprocess command starts with `ollama run <model>`, NOT `claude --print`.
- [ ] Confirm the resulting note's analysis content was produced by ollama (vs. Claude's usual phrasing).
- [ ] Repeat with backend `claude`; confirm the command flipped back to `claude --print`.

## 3. Rename queue on calendar time change

- [ ] Reschedule the same calendar event you created in (1) — move it by one day.
- [ ] Wait for the next calendar sync OR force-trigger.
- [ ] Confirm the daemon journal emitted `rename_queued` with old path + new path.
- [ ] Plugin `RenameProcessor` picks up the queue on its next cycle.
- [ ] Note is renamed on disk; wikilinks elsewhere in the vault are updated (Obsidian's `fileManager.renameFile` does this automatically).
- [ ] EventIndex updated: `event-index.json` now points at the new path.
- [ ] `rename-queue.json` is empty / removed after processing.

## 4. Notification history includes events from before plugin startup

- [ ] Close Obsidian entirely (kill the process if needed).
- [ ] With the daemon still running, emit at least two events: e.g. start and stop a recording, or trigger a pipeline run.
- [ ] Confirm `_Recap/.recap/events.jsonl` has new entries with timestamps from the window Obsidian was closed.
- [ ] Reopen Obsidian.
- [ ] Run the "Recap: View notification history" command.
- [ ] The modal backfills from `/api/events` and shows the pre-startup entries (up to 100 most recent).
- [ ] Trigger one more event while Obsidian is open — it streams in via WebSocket without needing a refresh.

## 5. Extension auth enforcement

- [ ] Confirm badge is green **ON** (daemon reachable + paired).
- [ ] Open extension options → **Disconnect** → badge flips to grey (or "AUTH"). `chrome.storage.local.recapAuth` is cleared.
- [ ] Join a meeting URL → extension tries to POST `/api/meeting-detected` → daemon responds 401 (check daemon log) → extension console logs `"Recap: 401; clearing stored token"` (already cleared, no-op), badge stays AUTH/red.
- [ ] Right-click tray icon → **Pair browser extension…** → options page **Connect** → 200 response → `recapAuth` repopulated → badge flips to green **ON**.
- [ ] Join another meeting URL → daemon receives `/api/meeting-detected` 200 with Bearer; recording triggers.
- [ ] Manually delete `_Recap/.recap/auth-token` (or rotate it) while daemon is running; restart daemon; extension's next POST → 401 → badge flips AUTH. User must re-pair.

---

## Automated gates (verified 2026-04-15)

| Gate | Result |
|---|---|
| `uv run pytest -q` | 570 passed, 3 skipped. Coverage gate 70% → actual 71.39%. |
| `cd obsidian-recap && npm run build` | clean; zero `tsc -noEmit` errors; esbuild production bundle builds. |
| Extension build/lint | N/A — pure MV3 JavaScript, no build step. Manual verification via Chrome's unpacked-extension loader. |

## Review Blockers (parent design §442-453; all pass)

| Blocker | Status | Notes |
|---|---|---|
| `org_subfolder` leaking into frontmatter `org` | PASS | 0 hits |
| User choice collected and ignored (backend, detection, org) | PASS | Tests §3 above verifies backend; detection/org flows live in settings.ts |
| Placeholder status fields (`daemon_uptime: 0`, `errors: []`, `implemented: false`) | PASS | 0 hits; removed in Phase 5 Tasks 1 + 3 |
| Hot-path markdown scan for event-id | PASS | EventIndex fast-path in place since Phase 2; 0 hits |
| Silent plugin catches (bare `catch {}`) | PASS | 0 hits; Phase 4 Task 7 + Phase 6 Task 5 enforced |
| Tests that mock the exact contract claimed as fixed | PASS | 0 hits on `patch.*write_meeting_note|upsert_note|EventIndex.add` |
| `# type: ignore` without justification | PASS | 15 surviving, all annotated in Phase 5 Task 4 |
| `autostart` references | PASS | Only the `TestAutoStartRouteIsGone` regression guard (retained by design) + a separate-feature docstring phrase (`auto-starting a recording`); no config, API, UI, or doc mentions |

## What to do after this checklist

- **All 5 scenarios pass:** ship. Use `superpowers:finishing-a-development-branch` to merge Phases 1-6 into `master`.
- **One scenario fails:** open a bug ticket referencing the specific step. If it's a small fix, do it inline on `obsidian-pivot`; if it's bigger, branch from `obsidian-pivot` into a focused fix branch and merge back before shipping.
- **Multiple scenarios fail:** pause. The parent design's "Intermediate broken states are OK" is about phase boundaries, not about shipping. File per-scenario tickets and decide whether the pass needs to be re-entered after fixes.

Follow-up items explicitly deferred from Phase 6 review (not blocking):
- M1: hoist `_make_silent_flac` from 3 test files to `tests/conftest.py`.
- M2: hoist `_PATCH_*` constants from 3 test files to `tests/conftest.py` or a module.
- M3: add `raising=True` to `tests/test_pairing.py:244` `monkeypatch.setattr` for consistency with `test_extension_auth.py`.
- M5: coverage cushion is 1.39pp; consider `.coveragerc` exclusions for entry-point scripts (`__main__.py`, `cli.py`, `tray.py`) to widen the margin.

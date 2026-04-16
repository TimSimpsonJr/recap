# Phase 5: Honesty Pass Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Delete dead scaffolding (extension port range, `/api/status` legacy mirror fields, `object`-typed detector params), tighten remaining type hacks, audit silent-swallow patterns left by Phase 4, and update MANIFEST + config example to match reality.

**Architecture:** Sweep-style cleanup — no new modules, no new endpoints. Each task is a scoped deletion + callers migrated in the same task; tests pulled forward to prove nothing else depends on what we removed.

**Tech Stack:** Python 3.10+, TypeScript (plugin), pytest, ruamel (unchanged from Phase 4).

**Read before starting:**
- `docs/plans/2026-04-14-fix-everything-design.md` §Phase 5 (lines 351-382) — parent design; acceptance criteria are load-bearing.
- `docs/plans/2026-04-14-phase4-plugin-parity.md` — Phase 4 ended at commit `4c2066c` with 552 tests passing, 3 skipped.

**Baseline commit:** `4c2066c`. Test suite at 552 passing + 3 skipped.

---

## Conventions for every task

- Commit style: Conventional Commits (`refactor:`, `fix:`, `chore:`, `docs:`).
- Never stage `uv.lock` or `docs/reviews/`.
- Run `uv run pytest -q` at the end of every Python-touching task. Regressions are real.
- Plugin TypeScript changes: run `cd obsidian-recap && npm run build` to catch tsc errors before committing.
- Migrate every call site in the task that introduces the change — no half-migrated state.
- For each `# type: ignore` or `except Exception:` you keep, the task must add a one-line comment justifying it; anything unjustified after this phase is a regression.

---

## Task 1: Delete dead daemon-port fields (`extension_port_*`, `auto_start`)

**Context:** Phase 4 finalized extension pairing on the single `plugin-port` + Bearer token, making `extension_port_start` / `extension_port_end` obsolete. `auto_start` is also dead — declared on `DaemonPortConfig` and parsed from `daemon.auto-start` in YAML, but nothing in `recap/`, `obsidian-recap/`, or `extension/` reads it (verified via grep). The parent design §Phase 5 acceptance says "`autostart` is gone from code, API, plugin UI, and docs" — delete the field alongside the port range so all three claims become true.

**Files:**
- Modify: `recap/daemon/config.py` (drop three fields from `DaemonPortConfig` + three `_parse` call-site lines)
- Modify: `config.example.yaml` (remove the two `extension-port-*` keys and the `auto-start: false` key)
- Verify: no surviving references in the repo after the change

**Step 1: Confirm scope**

```bash
grep -rn "extension_port_start\|extension_port_end\|extension-port-start\|extension-port-end\|auto_start\|auto-start\|autostart" \
    recap/ obsidian-recap/src/ extension/ tests/ config.example.yaml
```

Expected hits: `recap/daemon/config.py` (3 field defs + 3 `.get()` calls) and `config.example.yaml` (3 keys). The `"auto-starting a recording"` string in `recap/daemon/server.py` is the `_meeting_detected_api` docstring — a different feature (extension-triggered recording start). Leave it alone. Any hit outside the expected files widens the task.

**Step 2: Strip the fields in `DaemonPortConfig`**

In `recap/daemon/config.py` around line 88, reduce the dataclass to:

```python
@dataclass
class DaemonPortConfig:
    plugin_port: int = 9847
```

In the `parse_daemon_config_dict` block that builds `daemon_ports` (around line 258), drop the `extension-port-start`, `extension-port-end`, and `auto-start` lines. The builder should only set `plugin_port`.

**Step 3: Remove from `config.example.yaml`**

Under the `daemon:` block, remove:
```yaml
  extension-port-start: 17839
  extension-port-end: 17845
  auto-start: false
```

Only `plugin-port` remains in that section.

**Step 4: Run pytest + grep again**

```bash
uv run pytest -q
grep -rn "extension_port_start\|extension_port_end\|extension-port-start\|extension-port-end\|auto_start\|auto-start\|autostart" \
    recap/ obsidian-recap/src/ extension/ tests/ config.example.yaml
```

Expected: pytest passes; grep returns zero hits (the `"auto-starting a recording"` docstring is a different phrase and the grep pattern doesn't match it).

**Step 5: Commit**

```bash
git add recap/daemon/config.py config.example.yaml
git commit -m "refactor: delete dead daemon-port fields (extension_port_*, auto_start)"
```

---

## Task 2: Replace `object` type hints in `MeetingDetector`

**Context:** `MeetingDetector.__init__` takes `config: object, recorder: object` — Phase 3 added concrete `DaemonConfig` and `Recorder` types but the detector was never migrated. This forces four `# type: ignore[no-any-return]` inside detector methods that the parent plan flags for removal.

**Files:**
- Modify: `recap/daemon/recorder/detector.py` (constructor signature + remove resulting `# type: ignore` annotations where the IDE now knows the type)

**Step 1: Confirm the ignore annotations**

```bash
grep -n "# type: ignore\[no-any-return\]" recap/daemon/recorder/detector.py
```

Expected: lines 75, 81, 84, 98.

**Step 2: Narrow the constructor types**

```python
# Top of file, under TYPE_CHECKING import:
if TYPE_CHECKING:
    from recap.daemon.config import DaemonConfig
    from recap.daemon.recorder.recorder import Recorder

class MeetingDetector:
    def __init__(
        self,
        config: "DaemonConfig",
        recorder: "Recorder",
        ...
    ):
```

Keep the quoted strings if a real import would create a cycle (the detector is imported by `recorder.py`'s typing path). Test passes → real type is correct; test fails → fall back to concrete import.

**Step 3: Strip now-unnecessary `# type: ignore[no-any-return]` annotations**

Each of the four flagged lines returns a typed value (`self._config.detection` is a `DetectionConfig`, `app_cfg.default_org` is `Optional[str]`, `default_org.name` is `str`, matched is a concrete type). Remove the `# type: ignore[no-any-return]` suffix; keep the code identical otherwise.

**Step 4: Run pytest + mypy-equivalent**

```bash
uv run pytest tests/test_meeting_detector.py -v
uv run pytest -q
```

If your local mypy or pyright setup flags new errors, fix them before committing. Otherwise, pytest pass + existing CI type-check are sufficient.

**Step 5: Commit**

```bash
git add recap/daemon/recorder/detector.py
git commit -m "refactor: MeetingDetector uses concrete config/recorder types"
```

---

## Task 3: Drop legacy `/api/status` mirror fields (`daemon_uptime`, `errors`)

**Context:** Phase 4 Task 15 grep proved no plugin code consumes `status.daemon_uptime` or `status.errors`. Only `status.uptime_seconds` (the canonical field) and `status.last_calendar_sync` are used. Keeping the legacy fields is exactly the "fake metadata" Phase 5 targets. Remove them from the server response and the plugin type.

**Files:**
- Modify: `recap/daemon/server.py` (both `_api_status` branches — around lines 102 and 122)
- Modify: `obsidian-recap/src/api.ts` (drop legacy members from `DaemonStatus`)
- Modify: `tests/test_daemon_server.py` (drop any assertion checking `daemon_uptime` / `errors` presence)

**Step 1: Confirm no other Python call sites rely on them**

```bash
grep -rn "daemon_uptime\|\"errors\":" recap/ tests/ --include="*.py"
```

Expected hits: `recap/daemon/server.py` (two response bodies), `tests/test_daemon_server.py` (TestApiStatusReal tests). Anything else means the task scope widens.

**Step 2: Strip the mirror keys from the response bodies**

In `recap/daemon/server.py`, both `web.json_response` calls in `_api_status` drop `daemon_uptime` and `errors`. Keep `uptime_seconds` + `recent_errors` (the canonical names).

**Step 3: Update plugin `DaemonStatus`**

In `obsidian-recap/src/api.ts`:

```typescript
export interface DaemonStatus {
    state: "idle" | "armed" | "detected" | "recording" | "processing";
    recording: { path: string; org: string } | null;
    last_calendar_sync: string | null;
    uptime_seconds: number;
    recent_errors: DaemonEvent[];
}
```

Delete the "Legacy (kept for back-compat…)" comment + the `daemon_uptime` and `errors` lines. The grep from Task 15 proved no consumers; re-run it to be sure nothing was added since:

```bash
grep -rn "\.daemon_uptime\|\.errors\b" obsidian-recap/src --include="*.ts"
```

Expected: zero hits.

**Step 4: Update tests**

In `tests/test_daemon_server.py`, find assertions in `TestApiStatusReal` referencing `daemon_uptime` or `errors` as keys of the status body and replace them with the canonical names. The tests should still exercise the same behavior — just via `uptime_seconds` and `recent_errors`.

**Step 5: Run full suites**

```bash
uv run pytest -q
cd obsidian-recap && npm run build
```

Both clean.

**Step 6: Commit**

```bash
git add recap/daemon/server.py obsidian-recap/src/api.ts tests/test_daemon_server.py
git commit -m "refactor: drop /api/status legacy mirror fields (daemon_uptime, errors)"
```

---

## Task 4: Audit `# type: ignore` — remove obsolete, justify the rest

**Context:** After Task 2, many of the remaining `# type: ignore` comments are for optional-dependency import guards (`keyring`, `pyaudio`, `win32gui`, `uiautomation`, `nemo`) that are genuinely unavoidable without runtime checks. Phase 5 acceptance says "remaining `# type: ignore` must have an inline comment explaining why." Go one by one.

**Files:**
- Modify: every file with a `# type: ignore` that doesn't have a justifying comment on the same or adjacent line. Produce a categorized report first; then fix.

**Step 1: Enumerate**

```bash
grep -rn "type: ignore" recap/ --include="*.py" > /tmp/type-ignore-audit.txt
cat /tmp/type-ignore-audit.txt
```

Expected: roughly 20 hits. The Phase 4 baseline in `recap/daemon/calendar/oauth.py`, `credentials.py`, `recorder/audio.py`, `recorder/detection.py`, `recorder/enrichment.py`, `streaming/diarizer.py` are optional-dep guards; keep but justify. The detector ones Task 2 handled.

**Step 2: Categorize each hit**

For every line in the audit:

- **Optional-dep import shim** (`import x  # type: ignore[import-not-found]` followed by `except Exception: x = None  # type: ignore[assignment]`): keep. Add an inline comment above the try block explaining "optional dependency; stub falls back to None" if one isn't there already.
- **Arg-type on external library call** (e.g. `mgr.refresh_token(refresh_tok)  # type: ignore[arg-type]`): if the library has stubs now (check `.venv/Lib/site-packages/<lib>-stubs/`), remove the ignore. Otherwise, keep with an inline comment "authlib returns Any; cast at boundary".
- **Union-attr on third-party objects** (uiautomation's `GetChildren`): keep with comment.
- **no-any-return on our own code**: remove — this means our types are wrong and need fixing upstream.

**Step 3: Apply changes**

For each ignore kept, add a same-line trailing comment or a single-line comment the line above explaining _why_:

```python
# keyring is optional on Linux dev environments; stub when missing.
try:
    import keyring  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - exercised in dependency-light environments
    keyring = None  # type: ignore[assignment]
```

**Step 4: Verify every surviving ignore has a justification**

```bash
# Each hit should have a comment within 2 lines above or on the same line
# explaining the ignore. Manual spot-check; no automated grep catches this.
grep -B2 "type: ignore" recap/ -r --include="*.py" | less
```

**Step 5: Run pytest**

```bash
uv run pytest -q
```

**Step 6: Commit**

```bash
git add recap/
git commit -m "refactor: justify or remove every # type: ignore in recap/"
```

---

## Task 5: Audit `except Exception:` — keep justified, fix silent swallows

**Context:** Phase 4 Task 7 eliminated silent catches in the plugin. Phase 5's parent design says "Review all `except Exception:` blocks for bare-swallow patterns missed in Phase 4" — specifically on the Python side. Many are legitimate (import guards, journal write fallbacks, best-effort cleanup); some are not.

**Files:**
- Modify: every file with an `except Exception:` that silently swallows (no log, no journal, no re-raise) OR that swallows with only a log when a journal entry would actually help.

**Step 1: Enumerate**

```bash
grep -rn "except Exception:" recap/ --include="*.py" > /tmp/except-audit.txt
cat /tmp/except-audit.txt
```

Expected: roughly 20 hits across `daemon/calendar/`, `daemon/recorder/`, `daemon/credentials.py`, `daemon/events.py`, `daemon/notifications.py`.

**Step 2: Classify each**

For each hit, read the surrounding 10 lines and decide:

- **Import guard** (`except Exception:  # pragma: no cover - depends on local env`): keep as-is.
- **Journal write fallback** (`events.py:103` inside `emit_event`): keep — if the journal itself breaks, we can't journal the failure. The existing `logger.exception` is the right call.
- **Best-effort cleanup** (e.g., deleting a partial file, closing a handle): keep, but ensure there's a `logger.debug` or `logger.warning` with context so the silent-fail isn't truly silent.
- **Real error path** (e.g., a calendar API call that failed mid-sync): must `logger.exception` with a message that names the operation. If not already the case, fix.

**Step 3: Fix real silent swallows**

For any hit that currently does nothing (or just `pass`), add:

```python
except Exception as e:
    logger.exception("recap: <operation-name> failed")
    # Optional: emit_event if the daemon has a journal handle here.
```

Do NOT convert best-effort cleanup patterns into user-facing errors — those are correct as-is, but add a log line if one isn't present.

**Step 4: Run pytest**

```bash
uv run pytest -q
```

**Step 5: Commit**

```bash
git add recap/
git commit -m "refactor: every except Exception in recap/ logs or is annotated"
```

---

## Task 6: Verify `autostart` / `implemented: False` / legacy routes are gone

**Context:** Parent design calls for re-verifying Phase 3/4 claims. Two specific claims to re-verify here:

1. The unauth legacy routes `POST /meeting-detected` and `POST /meeting-ended` were deleted in Phase 4 Task 6 (commit `efca30f`). Parent design §Phase 5 specifically asks us to "double-check" this. This task re-runs the grep that would catch any accidental re-introduction — it is not re-doing the deletion.
2. `autostart` disappeared entirely in Task 1 of this plan (the field on `DaemonPortConfig` and the `auto-start` key in `config.example.yaml`). This task re-greps after Task 1 lands.

Belt-and-suspenders only; if these are clean the task commits nothing.

**Files:** none modified if greps are clean; if any hits appear, the scope widens into a targeted fix task.

**Step 1: `autostart` sweep**

```bash
grep -rn "autostart\|auto_start\|auto-start" recap/ obsidian-recap/src/ extension/ tests/ --include="*.py" --include="*.ts" --include="*.js"
```

Expected after Task 1: zero hits. The `"auto-starting a recording"` docstring in `server.py` uses a different phrase (hyphen + gerund) that this pattern won't match.

**Step 2: Legacy route re-verify**

```bash
grep -n "add_post.*'/meeting-detected'\|add_post.*'/meeting-ended'\|add_post(\"/meeting-detected\"\|add_post(\"/meeting-ended\"" \
    recap/daemon/server.py
```

Expected: zero hits. Only `/api/meeting-detected` and `/api/meeting-ended` should be registered (per Phase 4 Task 6 regression test `TestLegacyRoutesDeleted` in `tests/test_daemon_server.py`).

**Step 3: Placeholder metadata**

```bash
grep -rn "\"implemented\": False\|implemented=False" recap/ --include="*.py"
```

Expected: zero hits.

**Step 4: TODO count signal**

```bash
grep -rn "# TODO\|# FIXME\|# XXX" recap/ --include="*.py" | wc -l
```

Report the count. Phase 5 doesn't delete TODOs, but a dramatic spike since Phase 3 baseline is a signal worth raising.

**Step 5: If any hits from Steps 1-3, migrate**

Case-by-case; in most repos after Phases 1-4 these greps are clean. Commit only if changes.

```bash
git add -- <touched files>
git commit -m "refactor: purge residual autostart/legacy-route/implemented references"
```

If no changes, skip the commit.

---

## Task 7: MANIFEST + README honesty pass

**Context:** MANIFEST was last touched for Phase 4 (commit `4c2066c`). Walk it against the current repo and fix any stale pointers. README is outside the plugin/daemon read path but users see it first — fact-check the feature claims.

Parent design §Phase 5 calls out one stale pointer specifically: any `recap/config.py` reference in MANIFEST. That file does not exist in this repo (the daemon's config lives at `recap/daemon/config.py`). The broader MANIFEST audit below would catch it, but this task lists it explicitly so the fix isn't buried in a generic sweep.

**Files:**
- Modify: `MANIFEST.md`
- Modify: `README.md` (if claims are false)

**Step 1: Explicit check for the `recap/config.py` pointer**

```bash
grep -n "recap/config\.py\|recap\.config\b" MANIFEST.md
```

Expected: zero hits. If any line mentions `recap/config.py`, replace it with `recap/daemon/config.py` or drop the bullet (the structure block already covers `daemon/config.py` at the correct path).

**Step 2: Broader MANIFEST path audit**

```bash
# Every path mentioned in MANIFEST must exist
awk '/^  [a-z_]/ {print $1}' MANIFEST.md | xargs -I{} ls {} 2>&1 | grep "No such file"
```

Any output means MANIFEST references a path that no longer exists; fix the annotation or drop the line.

**Step 3: Read README line-by-line**

```bash
cat README.md | less
```

For every feature claim, ask: does this work today? If not, rephrase ("planned") or delete. Especially scrutinize:
- "Runs on Linux" (we are Windows-only — plan constraints.md is explicit)
- "Uses Anthropic API" / "Uses OpenAI" (we use Claude CLI — plan constraints.md is explicit)
- Any screenshot or command example that doesn't match the current CLI flags.

**Step 4: Commit**

```bash
git add MANIFEST.md README.md
git commit -m "docs: Phase 5 MANIFEST + README honesty pass"
```

---

## Post-Phase Verification

| Command | Expected |
|---|---|
| `uv run pytest -q` | all pass (552+, 3 skipped) |
| `grep -rn "extension_port_start\|extension_port_end\|auto_start\|auto-start\|autostart" recap/ obsidian-recap/src/ extension/ tests/ config.example.yaml` | 0 hits |
| `grep -n "daemon_uptime\|\"errors\":" recap/daemon/server.py` | 0 hits |
| `grep -rn "\.daemon_uptime\|\.errors\b" obsidian-recap/src --include="*.ts"` | 0 hits |
| `grep -n "add_post.*/meeting-detected\|add_post.*/meeting-ended" recap/daemon/server.py` | only `/api/meeting-*` |
| `grep -n "recap/config\.py" MANIFEST.md` | 0 hits |
| `grep -rn "type: ignore" recap/ --include="*.py"` | every hit has adjacent justifying comment |
| `cd obsidian-recap && npm run build` | zero tsc errors |

**Acceptance criteria** (from parent design §Phase 5):

- [ ] `autostart` gone from code, API, plugin UI, docs (re-verified clean).
- [ ] Dead handlers + deprecated config fields removed.
- [ ] No endpoint returns fake metadata (`implemented: false`, legacy `daemon_uptime: 0`).
- [ ] No UI advertises unfinished features.
- [ ] Every surviving `# type: ignore` has an inline justification.
- [ ] Docs (MANIFEST + README) stop claiming features that don't work.

---

## Handoff to Phase 6

Phase 6 (Test Hardening) picks up:

- Rewrite over-mocked `tests/test_pipeline.py` cases to use real tmp vaults.
- Add `tests/test_e2e_pipeline.py`: fixture audio → `run_pipeline` → assert canonical frontmatter + body.
- Add `tests/test_signal_backend_routing.py`: `llm_backend="ollama"` → assert ollama subprocess invoked.
- Add `tests/test_extension_auth.py`: finalized Bearer protocol coverage.
- Add coverage gate: `uv run pytest --cov=recap --cov-fail-under=70`.

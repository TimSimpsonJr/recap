# Daemon Autostart — Design

**Issue:** [#31](https://github.com/TimSimpsonJr/recap/issues/31)
**Status:** Design approved; ready for implementation plan.
**Related:** [#27](https://github.com/TimSimpsonJr/recap/issues/27) parallel track; neither depends on the other.

---

## Problem

Today the user has to run `uv run python -m recap.launcher config.yaml` manually before opening Obsidian. If they forget, the plugin shows "Daemon offline" and every command fails silently. There is no in-tree autostart mechanism: `recap.launcher` is a watchdog supervisor that restarts the daemon on crash, but nothing invokes the launcher in the first place.

## Goals and non-goals

**Goals**
1. When Obsidian opens, the plugin starts the daemon automatically if it is not already running.
2. Daemon keeps running after Obsidian closes (so a second open doesn't fight a still-running daemon, and the tray stays responsive).
3. First-time setup is explicit — user configures launch settings once, autostart takes over thereafter.
4. No daemon-side API changes. Everything new lives in the plugin.

**Non-goals**
- OS-level scheduled task (login-time autostart regardless of Obsidian). Tracked as a future follow-up.
- Auto-capturing launch metadata from a running daemon's `/api/status`. Deferred to a follow-up issue; first-time users can't benefit from it (daemon hasn't run yet), so shipping structured settings is the right first move.
- Cross-Obsidian-instance coordination (multiple vaults opening at once). Port-bind collision handles this degenerately; no explicit coordination.
- "Daemon running when Obsidian is closed" stays a gap. OS scheduler (future) closes it.

## Architecture

### What the plugin spawns
The **launcher** ([launcher.py](../../recap/launcher.py)), not the daemon directly. The launcher is already the production-shaped entrypoint: it forks `python -m recap.daemon` as a child, sets `RECAP_MANAGED=1` ([launcher.py:97](../../recap/launcher.py)), and that env flag enables `managed/can_restart` in `/api/status` ([server.py:85-104](../../recap/daemon/server.py), [service.py:96](../../recap/daemon/service.py)). Spawning the daemon directly would bypass the supervisor and disable the restart handshake.

Daemon becomes a grandchild of Obsidian: `Obsidian → launcher (detached) → daemon`. Detach + unref on the launcher means both survive Obsidian close.

### Spawn contract
Node `child_process.spawn(exe, args, opts)` where:
- `opts.cwd = settings.launcherCwd`
- `opts.env = { ...process.env, RECAP_LAUNCHER_LOG: resolvedLogPath }`
- `opts.detached = true`
- `opts.stdio = 'ignore'`
- `opts.windowsHide = true`

Followed immediately by `child.unref()` so Node doesn't keep Obsidian alive waiting on it.

### `launcher.log` placement
Default: `{vault}/_Recap/.recap/launcher.log`. This matches the existing runtime-state convention in the repo — plugin already reads `_Recap/.recap/auth-token`, rename processor watches `_Recap/.recap/rename-queue.json`, daemon preflight creates `_Recap/.recap/auth-token`. One control directory, not two.

Overridable via the `launcherLogPath` setting. Never defaults to Obsidian's cwd (which on Windows is typically the Electron binary directory — wrong).

## Plugin settings schema

Additive to `RecapSettings` in [settings.ts:11](../../obsidian-recap/src/settings.ts):

```typescript
interface DaemonLaunchSettings {
  autostartEnabled: boolean;         // default: true
  launcherExecutable: string;        // default: ""
  launcherArgs: string[];            // default: []
  launcherCwd: string;               // default: ""
  launcherLogPath: string;           // default: "" → resolves to {vault}/_Recap/.recap/launcher.log
}
```

**Why structured, not a shell string:** Windows paths with spaces (`C:\Program Files\...`) and composite commands like `uv run python -m recap.launcher config.yaml` make shlex-parsing fragile. Structured fields let the user specify exactly what they mean (`executable = "uv"`, `args = ["run", "python", "-m", "recap.launcher", "config.yaml"]`), with no quoting ambiguity at the plugin layer.

### Settings UI

New "Daemon launch" section in the existing settings tab:

| Field | Type | Help |
|---|---|---|
| Auto-start daemon with Obsidian | toggle | default on; false suppresses both auto-spawn AND the "not configured" notice |
| Launcher executable | text | full path or binary-on-PATH name. Example: `uv` or `C:\Python312\python.exe` |
| Launcher arguments | text area, one per line | example: `run`, `python`, `-m`, `recap.launcher`, `config.yaml` |
| Working directory | text | usually the Recap repo root. Example: `C:\Users\tim\Documents\Projects\recap` |
| Launcher log path | text (optional) | default: `{vault}/_Recap/.recap/launcher.log` |
| **Button** "Start daemon now" | action | manual retry; jumps directly to spawn step |

Validation is soft: warn on `fs.access(launcherExecutable)` failure but don't block save — user may fill fields before installing Python.

## State machine (plugin onload)

```
1. Probe GET /health with 2s timeout.
   ├─ success → rehydrateClient() + existing connect path. Done.
   └─ fail → continue to step 2

2. Read autostartEnabled.
   ├─ false → status-bar "Daemon offline". No notice. Done.
   └─ true → continue to step 3

3. Check launch settings configured (executable + args + cwd all non-empty).
   ├─ no → one-time notice "Recap launcher not configured. Open Settings → Recap → Daemon launch."
   │       status-bar "Daemon offline". Done (unless user clicks "Start daemon now").
   └─ yes → continue to step 4

4. Spawn launcher detached. Register 'error' and 'exit' listeners; start a 15s overall timer.
   ├─ 'error' event (ENOENT/EACCES/etc.) → notice: "Recap launcher failed: {code} {message}". Done.
   ├─ 'exit' event BEFORE /health success → notice: "Recap launcher exited with code {code} before daemon started.
   │                                        launcher.log may not have been created if the launcher module itself failed.
   │                                        Verify launcherCwd and launcherExecutable in settings."
   └─ 'spawn' event fires → begin polling (step 5). Keep 'exit' listener active through step 5.

5. Poll GET /health every 500ms until success, 'exit', or 15s overall timeout.
   ├─ success → rehydrateClient() + existing connect path. Log "daemon spawned by plugin pid={pid}".
   ├─ 'exit' → same handling as step 4 'exit'.
   └─ timeout with no exit → notice: "Recap daemon started (launcher pid={pid}) but didn't respond within 15s.
                             Check {launcherLogPath}." status-bar "Daemon offline". Done.

Manual "Start daemon now" button: skips steps 1–3, jumps to step 4.
```

### Why track `exit` during the poll window
A common misconfiguration — wrong `launcherCwd` for `uv run` invocations, missing `config.yaml` relative path resolution, Python environment mismatch — causes the detached child to die before the Python launcher module even imports. In that case `launcher.log` never exists, and telling the user to "check launcher.log" is a dead end. Surfacing the exit code separately gives them an actionable signal.

### Why no retry after failure
If spawn fails or the daemon times out, plugin does not retry on the same onload. Reasoning: the failure is almost always configuration (wrong path, missing Python, etc.), and retrying without user action just repeats the same failure. Manual "Start daemon now" button exists for after-the-fix retry without an Obsidian reload.

## Auth token rehydration

The Codex catch that saved this design: [main.ts:54-63](../../obsidian-recap/src/main.ts) reads `_Recap/.recap/auth-token` once at onload and builds `this.client`. On first successful plugin-spawned start, the token file doesn't exist at onload — so without explicit rehydration, `/health` would flip green but `this.client` would remain null. Plugin would look connected but commands would silently fail.

**Fix:** `async rehydrateClient()` helper:
1. Re-read `_Recap/.recap/auth-token`.
2. If missing, retry twice with 500ms spacing (daemon writes the token shortly after binding the port).
3. If still missing after retries, notice: "Daemon running but auth token not found. Re-pair via tray menu."
4. If present, construct `new DaemonClient(baseUrl, token)`, assign to `this.client`.
5. Call existing `getStatus()` + WebSocket connect path.

State machine steps 1 and 5 both call `rehydrateClient()` on success. Step 1 is effectively idempotent when the token hasn't changed (same token, same client), but the call is cheap and the symmetry is worth it.

## Error handling

| Case | Behaviour |
|---|---|
| Spawn ENOENT (executable not found) | Notice with path. Status offline. No retry. |
| Spawn EACCES (permission denied) | Notice with path. Status offline. No retry. |
| Spawn succeeds but child exits before daemon binds | Notice with exit code + "launcher.log may not exist" caveat. Status offline. |
| Spawn + daemon bind OK but auth token missing after 2 retries | Notice: "Daemon running but auth token not found at {path}. Re-pair via tray menu." Daemon stays running; status shows partial state. |
| Port already bound by unrelated process | Daemon exits with port-bind error → 'exit' event → exit-before-success notice. |
| `autostartEnabled` toggled off mid-session | No effect until next onload. |
| Multiple Obsidian windows open simultaneously | Both probe `/health`; first one to spawn wins the race; second one sees /health succeed and skips spawn. |
| Windows detached + stdio:'ignore' edge case | Verified during implementation: child still fires 'exit' event to parent process while parent is alive. If Obsidian closes first, child is truly orphaned (that's the point). |

## Testing

### Manual acceptance (checklist in `docs/handoffs/`)
1. Fresh plugin install, no settings → notice appears once, status offline, no spawn attempt.
2. Configure settings → reload plugin → daemon starts, status green within 15s.
3. Kill daemon while Obsidian open → reload plugin → daemon restarts automatically.
4. Toggle `autostartEnabled` off → reload → status stays offline, no notice, no spawn.
5. Click "Start daemon now" with bad executable path → notice with ENOENT, actionable.
6. Click "Start daemon now" with wrong cwd → child exits quickly → notice mentions possible pre-launch failure.
7. Close Obsidian with daemon running → daemon survives (verify via `tasklist | findstr python` on Windows).
8. Reopen Obsidian → `/health` succeeds immediately, no respawn log entry.
9. Open two Obsidian vaults simultaneously → one spawns, other sees running daemon.
10. Delete auth token file, then spawn via "Start daemon now" → rehydrateClient retries, eventually shows re-pair notice.

### Automated (plugin TS tests)
- `daemonLauncher.spec.ts`:
  - /health success path (probe only, no spawn)
  - /health fail + settings configured (spawns, polls, succeeds)
  - /health fail + settings NOT configured (notice, no spawn)
  - Spawn 'error' event (ENOENT) → notice, no poll
  - 'exit' event during poll window → exit-specific notice
  - 15s poll timeout without exit → timeout notice with log path
  - `autostartEnabled: false` → no spawn, no notice
  - Manual "Start daemon now" bypasses steps 1–3
- `authRehydration.spec.ts`:
  - Token present on first read → single read, client built
  - Token missing on first read, present on second → retry, client built
  - Token missing after 2 retries → notice emitted
  - `DaemonClient` constructed with correct baseUrl + token

### Integration
No existing Obsidian plugin harness in-repo. Plugin tests are unit-level. Manual acceptance is the integration test for now.

## Migration and rollout

- Additive settings — existing installs get `autostartEnabled: true` but launch fields default to empty, so first onload after upgrade shows the "not configured" notice. Intentional: user opts in explicitly with their specific Python environment.
- No daemon changes. No version bump on server side. No breaking changes to plugin-daemon contract.
- README update: after the "installing the plugin" section, add a short "Configure Daemon launch in plugin settings so Recap starts automatically" paragraph with an example structured-settings block for `uv`-based setups.

## Open questions

None at design-approval time. Implementation plan (next step via `writing-plans` skill) will break this into ordered tasks with tests.

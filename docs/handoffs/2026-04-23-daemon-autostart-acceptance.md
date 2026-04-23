# Daemon Autostart â€” Manual Acceptance Checklist

Run through every scenario on Windows before opening the PR for #31. Tick each when verified.

## Pre-flight

- [ ] `cd obsidian-recap && npm test` â€” all green
- [ ] `cd obsidian-recap && npm run build` â€” no TypeScript errors
- [ ] Plugin loaded in an Obsidian install with a test vault

## Scenarios

- [ ] **Fresh install, no settings.** First plugin load â†’ notice "Recap launcher not configured..." appears once, status bar shows offline, no spawn attempt in Task Manager.
- [ ] **Configure and reload.** Fill in launch fields (executable, args, cwd), reload plugin â†’ daemon starts within 15s, status bar goes online, no lingering "offline" notice.
- [ ] **Daemon already running.** Start daemon manually (`uv run python -m recap.launcher config.yaml`) BEFORE opening Obsidian, then load plugin â†’ status goes green, no spawn attempt (confirm via Task Manager: only one python.exe tree, the manually-started one).
- [ ] **Kill daemon while Obsidian open.** `taskkill /pid <launcher-pid> /t /f`, then close+reopen Obsidian â†’ plugin respawns daemon. Verify a *new* pid in Task Manager.
- [ ] **Toggle autostart off.** Disable "Auto-start daemon with Obsidian", reload plugin while daemon is down â†’ status stays offline, no spawn attempt, NO notice (silent).
- [ ] **Bad executable path.** Set launcherExecutable to `nonexistent`, click "Start daemon now" â†’ notice with ENOENT. Status offline.
- [ ] **Bad working directory.** Set launcherCwd to a path without `config.yaml` â†’ notice describes exit code + "launcher.log may not exist" caveat.
- [ ] **Close Obsidian with daemon running.** Close Obsidian, confirm launcher + daemon still running in Task Manager. Open Obsidian â†’ probe succeeds immediately, no respawn.
- [ ] **Multiple Obsidian windows.** Open two Obsidian vaults with the plugin simultaneously â†’ one spawns, the other sees running daemon via /health. No port-bind collision notice.
- [ ] **Missing auth token after spawn.** With launch settings valid but auth token file missing or stale (delete `_Recap/.recap/auth-token`), click "Start daemon now" â†’ rehydrateClient retries, eventually surfaces "Daemon running but auth token not found... Re-pair via tray menu."
- [ ] **15s poll timeout.** Point launcherArgs at a command that does NOT bind port 9847 (e.g. `python -c "import time; time.sleep(60)"`) â†’ after 15s, notice mentions the log path and pid. Status offline.

## Cleanup before committing

- [ ] Kill any orphan launcher/daemon processes spawned during testing.
- [ ] Revert test vault's plugin settings to defaults.

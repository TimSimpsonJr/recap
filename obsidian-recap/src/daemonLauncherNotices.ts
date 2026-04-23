/**
 * Map LauncherOutcome -> (notice text, status bar state, rehydrate flag).
 *
 * Kept pure so tests don't need Obsidian's Notice/StatusBar APIs.
 * main.ts translates the returned LauncherNotice into the actual
 * Obsidian API calls.
 */
import type { LauncherOutcome } from "./daemonLauncher";

export interface LauncherNotice {
  /** null = no Notice emitted (used for DISABLED and happy paths). */
  notice: string | null;
  /** true = caller sets status bar offline. */
  statusBarOffline: boolean;
  /** true = caller should invoke rehydrateClient(). */
  shouldRehydrate: boolean;
}

/**
 * Translate a terminal LauncherOutcome into the three side-effect
 * decisions the plugin needs to make: whether to show a Notice, how
 * to set the status bar, and whether to trigger rehydrateClient().
 *
 * Pure function: no Obsidian imports, no I/O. All seven outcome kinds
 * from {@link LauncherOutcome} are handled.
 */
export function noticeForOutcome(
  outcome: LauncherOutcome,
): LauncherNotice {
  switch (outcome.kind) {
    case "ALREADY_RUNNING":
      return { notice: null, statusBarOffline: false, shouldRehydrate: true };
    case "DISABLED":
      return { notice: null, statusBarOffline: true, shouldRehydrate: false };
    case "NOT_CONFIGURED":
      return {
        notice: "Recap launcher not configured. Open Settings -> Recap -> Daemon launch.",
        statusBarOffline: true,
        shouldRehydrate: false,
      };
    case "SPAWN_ERROR":
      return {
        notice: `Recap launcher failed to start: ${outcome.code ?? "error"} ${outcome.message}`,
        statusBarOffline: true,
        shouldRehydrate: false,
      };
    case "EARLY_EXIT": {
      const codeStr = outcome.exitCode !== null ? String(outcome.exitCode) : "killed";
      return {
        notice: (
          `Recap launcher exited with code ${codeStr} before daemon started. ` +
          "launcher.log may not exist if the launcher module itself failed. " +
          "Verify launcherCwd and launcherExecutable in settings."
        ),
        statusBarOffline: true,
        shouldRehydrate: false,
      };
    }
    case "POLL_TIMEOUT":
      return {
        notice: (
          `Recap daemon started (launcher pid=${outcome.pid ?? "?"}) but didn't ` +
          `respond within 15s. Check ${outcome.logPath || "launcher.log"}.`
        ),
        statusBarOffline: true,
        shouldRehydrate: false,
      };
    case "SPAWNED_AND_READY":
      return { notice: null, statusBarOffline: false, shouldRehydrate: true };
  }
}

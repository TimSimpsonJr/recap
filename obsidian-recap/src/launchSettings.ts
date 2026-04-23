/**
 * Structured launch settings for plugin-driven daemon autostart.
 *
 * Kept as its own module so tests and the launcher state machine
 * can import defaults without pulling the whole Obsidian plugin
 * entrypoint.
 */
export interface DaemonLaunchSettings {
  autostartEnabled: boolean;
  /** Executable path or binary on PATH (e.g. "uv", "C:\\Python\\python.exe"). */
  launcherExecutable: string;
  /** Argv for the executable. E.g. ["run", "python", "-m", "recap.launcher", "config.yaml"]. */
  launcherArgs: string[];
  /** Working directory for the spawned launcher. Typically the Recap repo root. */
  launcherCwd: string;
  /** Absolute path for launcher.log. Empty string -> resolves to {vault}/_Recap/.recap/launcher.log. */
  launcherLogPath: string;
}

export const DEFAULT_LAUNCH_SETTINGS: DaemonLaunchSettings = {
  autostartEnabled: true,
  launcherExecutable: "",
  launcherArgs: [],
  launcherCwd: "",
  launcherLogPath: "",
};

/**
 * Daemon launcher state machine for plugin-driven autostart (#31).
 *
 * This module provides the building blocks the plugin's onload flow
 * uses to start the daemon automatically when it isn't already running.
 * Each function is parameterized on its side-effecting deps so the
 * state machine can be unit-tested without real network or processes.
 */

/** Injected fetch for testability. */
export type FetchLike = typeof fetch;

/**
 * Probe GET {baseUrl}/health within the given timeout.
 *
 * Returns true on 2xx, false on network error / timeout / non-OK status.
 * The /health endpoint is unauthenticated on the daemon side, so no
 * auth token is needed to ask "is it up?".
 */
export async function probeHealth(
  baseUrl: string,
  timeoutMs: number,
  fetchImpl: FetchLike = fetch,
): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetchImpl(`${baseUrl}/health`, {
      method: "GET",
      signal: controller.signal,
    });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

import type { ChildProcess, SpawnOptions } from "child_process";

export interface SpawnParams {
  executable: string;
  args: string[];
  cwd: string;
  env: Record<string, string>;
}

export type LaunchResult =
  | { kind: "SPAWNED"; child: ChildProcess; pid: number | undefined }
  | { kind: "ERROR"; code: string | undefined; message: string };

/** Injected spawn for testability. */
export type SpawnLike = (
  cmd: string, args: string[], opts: SpawnOptions,
) => ChildProcess;

/**
 * Spawn the launcher detached. Resolves to SPAWNED when the child
 * enters the runnable state, or ERROR on pre-run failure (ENOENT,
 * EACCES, etc.). Caller is responsible for listening to 'exit' on
 * the returned child during the poll window (see pollUntilReady).
 *
 * Uses detached:true + stdio:'ignore' + windowsHide:true + unref()
 * so the child survives Obsidian close. The parent merges
 * `process.env` with caller-provided `env` so RECAP_LAUNCHER_LOG
 * (or any future env var) lands alongside inherited values.
 */
export function spawnLauncher(
  params: SpawnParams,
  spawnFn: SpawnLike,
): Promise<LaunchResult> {
  return new Promise((resolve) => {
    const opts: SpawnOptions = {
      cwd: params.cwd,
      env: { ...process.env, ...params.env },
      detached: true,
      stdio: "ignore",
      windowsHide: true,
    };
    const child = spawnFn(params.executable, params.args, opts);

    const onSpawn = () => {
      child.removeListener("error", onError);
      child.unref();
      resolve({ kind: "SPAWNED", child, pid: child.pid });
    };
    const onError = (err: NodeJS.ErrnoException) => {
      child.removeListener("spawn", onSpawn);
      resolve({
        kind: "ERROR",
        code: err.code,
        message: err.message || "spawn failed",
      });
    };

    child.once("spawn", onSpawn);
    child.once("error", onError);
  });
}

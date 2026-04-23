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

export interface PollParams {
  baseUrl: string;
  child: ChildProcess;
  intervalMs?: number;
  totalMs?: number;
  fetchImpl?: FetchLike;
}

export type PollResult =
  | { kind: "READY" }
  | { kind: "EXITED"; exitCode: number | null; signal: NodeJS.Signals | null }
  | { kind: "TIMEOUT" };

const DEFAULT_POLL_INTERVAL_MS = 500;
const DEFAULT_POLL_TOTAL_MS = 15000;
const PROBE_TIMEOUT_MS = 2000;

/**
 * Poll GET {baseUrl}/health until success, child exit, or overall
 * timeout. Each individual probe has a 2s fetch timeout; outer loop
 * retries every {intervalMs} until {totalMs} elapses.
 *
 * Concurrently listens for the child's 'exit' event so a pre-launcher
 * failure (wrong cwd, bad args, Python crash before port bind) returns
 * EXITED rather than waiting out the full poll window.
 */
export function pollUntilReady(params: PollParams): Promise<PollResult> {
  const {
    baseUrl, child,
    intervalMs = DEFAULT_POLL_INTERVAL_MS,
    totalMs = DEFAULT_POLL_TOTAL_MS,
    fetchImpl = fetch,
  } = params;

  return new Promise((resolve) => {
    let settled = false;
    const startedAt = Date.now();

    const finish = (result: PollResult) => {
      if (settled) return;
      settled = true;
      child.removeListener("exit", onExit);
      resolve(result);
    };
    const onExit = (code: number | null, signal: NodeJS.Signals | null) => {
      finish({ kind: "EXITED", exitCode: code, signal });
    };
    child.once("exit", onExit);

    const tick = async () => {
      if (settled) return;
      if (Date.now() - startedAt > totalMs) {
        finish({ kind: "TIMEOUT" });
        return;
      }
      const ok = await probeHealth(baseUrl, PROBE_TIMEOUT_MS, fetchImpl);
      if (settled) return;
      if (ok) {
        finish({ kind: "READY" });
        return;
      }
      setTimeout(tick, intervalMs);
    };
    tick();
  });
}

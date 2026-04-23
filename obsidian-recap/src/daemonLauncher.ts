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

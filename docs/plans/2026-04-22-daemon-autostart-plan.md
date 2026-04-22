# Daemon Autostart Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** When the plugin loads and the daemon is not running, the plugin spawns `recap.launcher` detached so the daemon starts automatically. No daemon-side API changes.

**Architecture:** New `DaemonLauncher` module in the plugin owns the probe-spawn-poll state machine. Plugin settings gain structured launch fields (executable, args, cwd, log path) plus an `autostartEnabled` toggle. `main.ts.onload` calls the launcher, and a new `rehydrateClient()` helper re-reads the auth token after a fresh spawn so the plugin doesn't stay in a "daemon up, client null" limbo.

**Tech Stack:** TypeScript, Obsidian plugin SDK, Node `child_process`, `vitest` for unit tests. No new dependencies.

**Design doc:** [docs/plans/2026-04-22-daemon-autostart-design.md](./2026-04-22-daemon-autostart-design.md)

**Branch:** `feat/31-daemon-autostart` (design doc committed at 412a979)

**Convention:** Each task is TDD where possible (state machine + auth helper are testable; Obsidian/Electron spawn integration relies on a manual acceptance checklist). Conventional Commits format.

---

## Task 1: Extend plugin settings schema

**Files:**
- Modify: `obsidian-recap/src/main.ts:12-18` (RecapSettings + DEFAULT_SETTINGS)

**Context:** `RecapSettings` today only has `daemonUrl`. Add five fields for daemon launch.

### Step 1: Write failing type-level test

Since this is a pure interface change, "test" is the TypeScript compile. Add a minimal runtime check via vitest:

Create `obsidian-recap/src/launchSettings.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { DEFAULT_LAUNCH_SETTINGS } from "./launchSettings";

describe("DEFAULT_LAUNCH_SETTINGS", () => {
  it("defaults autostartEnabled to true", () => {
    expect(DEFAULT_LAUNCH_SETTINGS.autostartEnabled).toBe(true);
  });
  it("defaults launch fields to empty string / empty array", () => {
    expect(DEFAULT_LAUNCH_SETTINGS.launcherExecutable).toBe("");
    expect(DEFAULT_LAUNCH_SETTINGS.launcherArgs).toEqual([]);
    expect(DEFAULT_LAUNCH_SETTINGS.launcherCwd).toBe("");
    expect(DEFAULT_LAUNCH_SETTINGS.launcherLogPath).toBe("");
  });
});
```

### Step 2: Run test to verify it fails

Run: `cd obsidian-recap && npm test -- launchSettings`

Expected: FAIL — module does not exist yet.

### Step 3: Write minimal implementation

Create `obsidian-recap/src/launchSettings.ts`:

```typescript
/**
 * Structured launch settings for plugin-driven daemon autostart.
 *
 * Kept as its own module so tests can import the defaults without
 * pulling the whole Obsidian plugin entrypoint.
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
```

Modify `obsidian-recap/src/main.ts`:

```typescript
import { DaemonLaunchSettings, DEFAULT_LAUNCH_SETTINGS } from "./launchSettings";

interface RecapSettings extends DaemonLaunchSettings {
  daemonUrl: string;
}

const DEFAULT_SETTINGS: RecapSettings = {
  daemonUrl: "http://127.0.0.1:9847",
  ...DEFAULT_LAUNCH_SETTINGS,
};
```

### Step 4: Run tests + type-check

Run: `cd obsidian-recap && npm test -- launchSettings`
Expected: PASS.

Run: `cd obsidian-recap && npm run build`
Expected: type check + build succeeds.

### Step 5: Commit

```bash
git add obsidian-recap/src/launchSettings.ts obsidian-recap/src/launchSettings.test.ts obsidian-recap/src/main.ts
git commit -m "feat(plugin): structured daemon launch settings schema

Adds DaemonLaunchSettings interface with autostartEnabled,
launcherExecutable, launcherArgs, launcherCwd, launcherLogPath.
Merged into RecapSettings with sensible defaults (autostart on,
launch fields empty so first-run shows a configuration notice
rather than silently trying to spawn nothing).

Kept in its own module so the launcher state machine can import
without pulling in the main plugin class."
```

---

## Task 2: Auth token rehydration helper

**Files:**
- Modify: `obsidian-recap/src/main.ts:426-438` (promote `readAuthToken` from private to callable; add `rehydrateClient`)

**Context:** [main.ts:54-63](../../obsidian-recap/src/main.ts) reads the auth token once at onload. After a plugin-spawned daemon binds the port, the token file appears AFTER this read — so the plugin sees `/health` up but `this.client` is null. `rehydrateClient()` re-reads the token (with small retry) and rebuilds the client.

### Step 1: Write the failing test

Create `obsidian-recap/src/rehydrateClient.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";

// Shape-only mock for the vault adapter.
interface MockAdapter {
  exists: (p: string) => Promise<boolean>;
  read: (p: string) => Promise<string>;
}

// Extracted helper under test (not yet on `main`, will move there).
// For the test we import from a module where it will live.
async function readAuthTokenWithRetry(
  adapter: MockAdapter,
  path: string,
  maxAttempts = 3,
  delayMs = 50,
): Promise<string> {
  for (let i = 0; i < maxAttempts; i++) {
    if (await adapter.exists(path)) {
      const raw = await adapter.read(path);
      return raw.trim();
    }
    if (i < maxAttempts - 1) {
      await new Promise(r => setTimeout(r, delayMs));
    }
  }
  return "";
}

describe("readAuthTokenWithRetry", () => {
  it("returns token on first attempt when file exists", async () => {
    const adapter: MockAdapter = {
      exists: vi.fn().mockResolvedValue(true),
      read: vi.fn().mockResolvedValue("abc123\n"),
    };
    const token = await readAuthTokenWithRetry(adapter, "_Recap/.recap/auth-token");
    expect(token).toBe("abc123");
    expect(adapter.exists).toHaveBeenCalledTimes(1);
  });

  it("retries when file not yet present, returns token on later attempt", async () => {
    let attempts = 0;
    const adapter: MockAdapter = {
      exists: vi.fn().mockImplementation(async () => ++attempts >= 2),
      read: vi.fn().mockResolvedValue("newtoken\n"),
    };
    const token = await readAuthTokenWithRetry(
      adapter, "_Recap/.recap/auth-token", 3, 1,
    );
    expect(token).toBe("newtoken");
    expect(attempts).toBe(2);
  });

  it("returns empty string after max attempts if file never appears", async () => {
    const adapter: MockAdapter = {
      exists: vi.fn().mockResolvedValue(false),
      read: vi.fn(),
    };
    const token = await readAuthTokenWithRetry(
      adapter, "_Recap/.recap/auth-token", 3, 1,
    );
    expect(token).toBe("");
    expect(adapter.exists).toHaveBeenCalledTimes(3);
    expect(adapter.read).not.toHaveBeenCalled();
  });
});
```

### Step 2: Run test to verify it fails

Run: `cd obsidian-recap && npm test -- rehydrateClient`

Expected: FAIL — helper is only in the test file, but the test imports/redefines it locally. The failure is a logic error if the helper is wrong. Actually this test can pass on its own — what we need is to move the helper out of the test file.

Real failure condition: we need to refactor the plugin so the retry helper exists in a module we can import. Let me restructure: write the test importing from a new module `authToken.ts`, which fails until we create it.

Rewrite the test to import from the module that will exist:

```typescript
import { readAuthTokenWithRetry } from "./authToken";
```

Run: `cd obsidian-recap && npm test -- rehydrateClient`
Expected: FAIL — `Cannot find module './authToken'`.

### Step 3: Write minimal implementation

Create `obsidian-recap/src/authToken.ts`:

```typescript
/**
 * Read `_Recap/.recap/auth-token` with small retry.
 *
 * Needed because plugin-spawned daemons write the token *after* the
 * plugin's initial onload read. The retry lets a fresh spawn's token
 * file appear without forcing a plugin reload.
 */
export interface VaultLike {
  exists: (path: string) => Promise<boolean>;
  read: (path: string) => Promise<string>;
}

export const AUTH_TOKEN_PATH = "_Recap/.recap/auth-token";

export async function readAuthTokenWithRetry(
  adapter: VaultLike,
  path: string = AUTH_TOKEN_PATH,
  maxAttempts: number = 3,
  delayMs: number = 500,
): Promise<string> {
  for (let i = 0; i < maxAttempts; i++) {
    if (await adapter.exists(path)) {
      const raw = await adapter.read(path);
      return raw.trim();
    }
    if (i < maxAttempts - 1) {
      await new Promise(r => setTimeout(r, delayMs));
    }
  }
  return "";
}
```

### Step 4: Run test to verify it passes

Run: `cd obsidian-recap && npm test -- rehydrateClient`
Expected: all three tests PASS.

### Step 5: Refactor `main.ts` to use the helper

Replace the private `readAuthToken` method in `main.ts:426` with:

```typescript
private async readAuthToken(): Promise<string> {
    try {
        return await readAuthTokenWithRetry(this.app.vault.adapter, AUTH_TOKEN_PATH, 1);
    } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        new Notice(`Recap: could not read auth token — ${msg}`);
        console.error("Recap:", e);
        return "";
    }
}
```

Add a new `rehydrateClient()` method:

```typescript
/**
 * Re-read the auth token, rebuild DaemonClient, and reconnect.
 *
 * Used after a plugin-spawned daemon start (token file appears AFTER
 * onload's initial read). Retries a few times because the daemon
 * writes the token shortly after binding the port.
 */
async rehydrateClient(): Promise<boolean> {
    const token = await readAuthTokenWithRetry(this.app.vault.adapter);
    if (!token) {
        new Notice(
            `Recap: daemon running but auth token not found at ${AUTH_TOKEN_PATH}. ` +
            "Re-pair via tray menu."
        );
        return false;
    }
    this.client?.disconnectWebSocket();
    this.notificationHistory.detach();
    this.client = new DaemonClient(this.settings.daemonUrl, token);
    this.notificationHistory.setClient(this.client);
    this.connectWebSocket();
    try {
        const status = await this.client.getStatus();
        this.lastKnownState = status.state;
        this.statusBar?.updateState(status.state, status.recording?.org);
        return true;
    } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        new Notice(`Recap: post-spawn status fetch failed — ${msg}`);
        this.statusBar?.setOffline();
        return false;
    }
}
```

Add the import at the top of `main.ts`:

```typescript
import { readAuthTokenWithRetry, AUTH_TOKEN_PATH } from "./authToken";
```

### Step 6: Build + smoke test

Run: `cd obsidian-recap && npm run build`
Expected: type-check passes, esbuild produces `main.js`.

Run: `cd obsidian-recap && npm test`
Expected: all tests pass (existing + new).

### Step 7: Commit

```bash
git add obsidian-recap/src/authToken.ts obsidian-recap/src/rehydrateClient.test.ts obsidian-recap/src/main.ts
git commit -m "feat(plugin): rehydrateClient helper for post-spawn auth flow

Extracts readAuthTokenWithRetry to its own module with small
retry (needed after plugin-spawned daemon starts: token file
appears after onload's first read).

Adds RecapPlugin.rehydrateClient() that re-reads the token,
rebuilds DaemonClient, and reconnects WebSocket + status feed.
Called by the launcher state machine after a successful spawn."
```

---

## Task 3: DaemonLauncher module — probe

**Files:**
- Create: `obsidian-recap/src/daemonLauncher.ts`
- Create: `obsidian-recap/src/daemonLauncher.test.ts`

**Context:** First responsibility of the launcher module: quick `/health` probe so the plugin can tell whether the daemon is already running before attempting a spawn.

### Step 1: Write the failing test

```typescript
import { describe, it, expect, vi } from "vitest";
import { probeHealth } from "./daemonLauncher";

describe("probeHealth", () => {
  it("returns true when /health responds 200 within timeout", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ status: "ok" }),
    });
    const ok = await probeHealth("http://127.0.0.1:9847", 2000, fetchMock);
    expect(ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:9847/health",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("returns false when fetch throws", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("ECONNREFUSED"));
    const ok = await probeHealth("http://127.0.0.1:9847", 2000, fetchMock);
    expect(ok).toBe(false);
  });

  it("returns false on non-OK status", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false, status: 500,
    });
    const ok = await probeHealth("http://127.0.0.1:9847", 2000, fetchMock);
    expect(ok).toBe(false);
  });

  it("returns false on timeout", async () => {
    const fetchMock = vi.fn().mockImplementation(
      (_url: string, opts: { signal: AbortSignal }) =>
        new Promise((_, reject) => {
          opts.signal.addEventListener("abort", () =>
            reject(new Error("aborted"))
          );
        }),
    );
    const ok = await probeHealth("http://127.0.0.1:9847", 50, fetchMock);
    expect(ok).toBe(false);
  });
});
```

### Step 2: Run test to verify it fails

Run: `cd obsidian-recap && npm test -- daemonLauncher`
Expected: FAIL — module does not exist.

### Step 3: Write minimal implementation

Create `obsidian-recap/src/daemonLauncher.ts`:

```typescript
/**
 * Daemon launcher state machine for plugin-driven autostart (#31).
 */

/** Injected fetch for testability. */
export type FetchLike = typeof fetch;

/**
 * Probe GET {baseUrl}/health within the given timeout.
 * Returns true on 2xx, false on network error / timeout / non-OK.
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
```

### Step 4: Run tests to verify they pass

Run: `cd obsidian-recap && npm test -- daemonLauncher`
Expected: all four tests PASS.

### Step 5: Commit

```bash
git add obsidian-recap/src/daemonLauncher.ts obsidian-recap/src/daemonLauncher.test.ts
git commit -m "feat(plugin): probeHealth for daemon autostart state machine

Single-shot /health check with AbortController timeout; returns
a plain boolean. Pure function parameterized on fetchImpl so the
state-machine tests can mock it with vitest without touching
real network."
```

---

## Task 4: DaemonLauncher module — spawn

**Files:**
- Modify: `obsidian-recap/src/daemonLauncher.ts` (add spawn)
- Modify: `obsidian-recap/src/daemonLauncher.test.ts`

**Context:** Detached spawn with `child_process.spawn`, listening for `spawn` / `error` / `exit` events. Return a handle the caller can await + a cancel signal.

### Step 1: Write the failing test

Append to `obsidian-recap/src/daemonLauncher.test.ts`:

```typescript
import { spawnLauncher, LaunchResult } from "./daemonLauncher";
import { EventEmitter } from "events";

// Minimal child-process test double.
class FakeChild extends EventEmitter {
  pid: number | undefined = 12345;
  killed = false;
  unref = vi.fn();
  kill(_sig?: string) { this.killed = true; return true; }
}

describe("spawnLauncher", () => {
  it("resolves with SPAWNED + pid after 'spawn' event", async () => {
    const fake = new FakeChild();
    const spawnFn = vi.fn().mockReturnValue(fake);
    const promise = spawnLauncher(
      { executable: "uv", args: ["run", "-m", "recap.launcher"],
        cwd: "C:\\repo", env: {} },
      spawnFn,
    );
    // Fire 'spawn' asynchronously.
    queueMicrotask(() => fake.emit("spawn"));
    const result = await promise;
    expect(result.kind).toBe("SPAWNED");
    if (result.kind === "SPAWNED") {
      expect(result.pid).toBe(12345);
      expect(fake.unref).toHaveBeenCalled();
    }
    expect(spawnFn).toHaveBeenCalledWith(
      "uv",
      ["run", "-m", "recap.launcher"],
      expect.objectContaining({
        cwd: "C:\\repo",
        detached: true,
        stdio: "ignore",
        windowsHide: true,
      }),
    );
  });

  it("resolves with ERROR on 'error' event (ENOENT/EACCES/etc.)", async () => {
    const fake = new FakeChild();
    const spawnFn = vi.fn().mockReturnValue(fake);
    const promise = spawnLauncher(
      { executable: "missing", args: [], cwd: ".", env: {} },
      spawnFn,
    );
    queueMicrotask(() => {
      const err = new Error("spawn missing ENOENT");
      (err as NodeJS.ErrnoException).code = "ENOENT";
      fake.emit("error", err);
    });
    const result = await promise;
    expect(result.kind).toBe("ERROR");
    if (result.kind === "ERROR") {
      expect(result.code).toBe("ENOENT");
      expect(result.message).toContain("ENOENT");
    }
  });

  it("passes RECAP_LAUNCHER_LOG env var", async () => {
    const fake = new FakeChild();
    const spawnFn = vi.fn().mockReturnValue(fake);
    spawnLauncher(
      {
        executable: "uv", args: ["run"], cwd: ".",
        env: { RECAP_LAUNCHER_LOG: "/vault/_Recap/.recap/launcher.log" },
      },
      spawnFn,
    );
    queueMicrotask(() => fake.emit("spawn"));
    expect(spawnFn).toHaveBeenCalledWith(
      "uv", ["run"],
      expect.objectContaining({
        env: expect.objectContaining({
          RECAP_LAUNCHER_LOG: "/vault/_Recap/.recap/launcher.log",
        }),
      }),
    );
  });
});
```

### Step 2: Run tests to verify they fail

Run: `cd obsidian-recap && npm test -- daemonLauncher`
Expected: FAIL on the three new tests — `spawnLauncher` doesn't exist.

### Step 3: Write minimal implementation

Append to `obsidian-recap/src/daemonLauncher.ts`:

```typescript
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
 * the returned child during the poll window.
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
```

Add the import for `ChildProcess`-free parts at the top (already done above).

### Step 4: Run tests to verify they pass

Run: `cd obsidian-recap && npm test -- daemonLauncher`
Expected: all spawn tests PASS.

### Step 5: Commit

```bash
git add obsidian-recap/src/daemonLauncher.ts obsidian-recap/src/daemonLauncher.test.ts
git commit -m "feat(plugin): spawnLauncher with detached/unref semantics

Wraps Node's child_process.spawn with:
- detached=true, stdio='ignore', windowsHide=true
- unref() so the child can survive Obsidian close
- SPAWNED vs ERROR result enum (ENOENT/EACCES surface as ERROR,
  not a crash)
- process.env inheritance with caller-provided env merged on top
  (so RECAP_LAUNCHER_LOG lands where we want it)

Injected spawnFn keeps the tests decoupled from real processes."
```

---

## Task 5: DaemonLauncher module — poll-until-ready with exit watching

**Files:**
- Modify: `obsidian-recap/src/daemonLauncher.ts` (add `pollUntilReady`)
- Modify: `obsidian-recap/src/daemonLauncher.test.ts`

**Context:** After a SPAWNED, poll `/health` every 500ms up to 15s. Listen for child `exit` concurrently so a pre-launch failure (wrong cwd, bad args) surfaces distinctly from a post-launch timeout.

### Step 1: Write the failing test

```typescript
import { pollUntilReady, PollResult } from "./daemonLauncher";

describe("pollUntilReady", () => {
  it("returns READY when /health succeeds within window", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 500 })
      .mockResolvedValueOnce({ ok: false, status: 500 })
      .mockResolvedValue({ ok: true, status: 200 });
    const fakeChild = new FakeChild();
    const result = await pollUntilReady({
      baseUrl: "http://127.0.0.1:9847",
      child: fakeChild as unknown as any,
      intervalMs: 10,
      totalMs: 1000,
      fetchImpl: fetchMock,
    });
    expect(result.kind).toBe("READY");
    // At least 3 fetches attempted.
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(3);
  });

  it("returns EXITED when child emits 'exit' before /health succeeds", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false });
    const fakeChild = new FakeChild();
    const promise = pollUntilReady({
      baseUrl: "http://127.0.0.1:9847",
      child: fakeChild as unknown as any,
      intervalMs: 10,
      totalMs: 5000,
      fetchImpl: fetchMock,
    });
    queueMicrotask(() => fakeChild.emit("exit", 2, null));
    const result = await promise;
    expect(result.kind).toBe("EXITED");
    if (result.kind === "EXITED") {
      expect(result.exitCode).toBe(2);
    }
  });

  it("returns TIMEOUT when /health never succeeds and child stays alive", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false });
    const fakeChild = new FakeChild();
    const result = await pollUntilReady({
      baseUrl: "http://127.0.0.1:9847",
      child: fakeChild as unknown as any,
      intervalMs: 10,
      totalMs: 50,
      fetchImpl: fetchMock,
    });
    expect(result.kind).toBe("TIMEOUT");
  });
});
```

### Step 2: Run tests to verify they fail

Run: `cd obsidian-recap && npm test -- daemonLauncher`
Expected: FAIL — `pollUntilReady` not exported.

### Step 3: Write minimal implementation

Append to `obsidian-recap/src/daemonLauncher.ts`:

```typescript
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
    // Kick off first probe immediately.
    tick();
  });
}
```

### Step 4: Run tests to verify they pass

Run: `cd obsidian-recap && npm test -- daemonLauncher`
Expected: all three poll tests PASS. (May need `vi.useFakeTimers()` to avoid real setTimeouts blowing up the timeout test; if so, wrap the describe in `beforeEach(() => vi.useFakeTimers())` and use `vi.advanceTimersByTime`.)

### Step 5: Commit

```bash
git add obsidian-recap/src/daemonLauncher.ts obsidian-recap/src/daemonLauncher.test.ts
git commit -m "feat(plugin): pollUntilReady with concurrent exit watching

Polls /health every 500ms (default) up to 15s, returning READY
on success, EXITED with exit code/signal if the child dies first,
or TIMEOUT if neither happens.

Concurrent 'exit' listener means wrong launcherCwd / bad args
(which cause the child to die before launcher.log is created)
get a distinct error channel instead of being lost to the
generic timeout case."
```

---

## Task 6: DaemonLauncher module — top-level `runLauncherStateMachine`

**Files:**
- Modify: `obsidian-recap/src/daemonLauncher.ts` (add orchestrator)
- Modify: `obsidian-recap/src/daemonLauncher.test.ts`

**Context:** The state machine in the design doc — probe, then settings check, then spawn, then poll. Returns a discriminated union that the caller (`main.ts`) maps to notices + status-bar state + `rehydrateClient()` calls.

### Step 1: Write the failing test

```typescript
import { runLauncherStateMachine, LauncherOutcome } from "./daemonLauncher";
import { DaemonLaunchSettings } from "./launchSettings";

const _settings = (over: Partial<DaemonLaunchSettings> = {}): DaemonLaunchSettings => ({
  autostartEnabled: true,
  launcherExecutable: "uv",
  launcherArgs: ["run", "-m", "recap.launcher", "config.yaml"],
  launcherCwd: "C:\\repo",
  launcherLogPath: "C:\\vault\\_Recap\\.recap\\launcher.log",
  ...over,
});

describe("runLauncherStateMachine", () => {
  it("returns ALREADY_RUNNING when /health already succeeds", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    const outcome = await runLauncherStateMachine({
      baseUrl: "http://127.0.0.1:9847",
      settings: _settings(),
      spawnFn: vi.fn(),
      fetchImpl: fetchMock,
    });
    expect(outcome.kind).toBe("ALREADY_RUNNING");
  });

  it("returns DISABLED when autostartEnabled=false and /health fails", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false });
    const outcome = await runLauncherStateMachine({
      baseUrl: "http://127.0.0.1:9847",
      settings: _settings({ autostartEnabled: false }),
      spawnFn: vi.fn(),
      fetchImpl: fetchMock,
    });
    expect(outcome.kind).toBe("DISABLED");
  });

  it("returns NOT_CONFIGURED when launch fields are empty", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false });
    const outcome = await runLauncherStateMachine({
      baseUrl: "http://127.0.0.1:9847",
      settings: _settings({ launcherExecutable: "", launcherArgs: [] }),
      spawnFn: vi.fn(),
      fetchImpl: fetchMock,
    });
    expect(outcome.kind).toBe("NOT_CONFIGURED");
  });

  it("returns SPAWNED_AND_READY on successful end-to-end path", async () => {
    let callCount = 0;
    const fetchMock = vi.fn().mockImplementation(async () => {
      callCount++;
      // First probe (pre-spawn) fails; later probes after spawn succeed.
      return { ok: callCount > 1 };
    });
    const fake = new FakeChild();
    const spawnFn = vi.fn().mockReturnValue(fake);
    const promise = runLauncherStateMachine({
      baseUrl: "http://127.0.0.1:9847",
      settings: _settings(),
      spawnFn,
      fetchImpl: fetchMock,
      intervalMs: 10,
      totalMs: 1000,
    });
    queueMicrotask(() => fake.emit("spawn"));
    const outcome = await promise;
    expect(outcome.kind).toBe("SPAWNED_AND_READY");
    if (outcome.kind === "SPAWNED_AND_READY") {
      expect(outcome.pid).toBe(12345);
    }
  });

  it("returns SPAWN_ERROR on ENOENT", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false });
    const fake = new FakeChild();
    const spawnFn = vi.fn().mockReturnValue(fake);
    const promise = runLauncherStateMachine({
      baseUrl: "http://127.0.0.1:9847",
      settings: _settings({ launcherExecutable: "nonexistent" }),
      spawnFn, fetchImpl: fetchMock,
    });
    queueMicrotask(() => {
      const err = new Error("spawn nonexistent ENOENT");
      (err as NodeJS.ErrnoException).code = "ENOENT";
      fake.emit("error", err);
    });
    const outcome = await promise;
    expect(outcome.kind).toBe("SPAWN_ERROR");
    if (outcome.kind === "SPAWN_ERROR") {
      expect(outcome.code).toBe("ENOENT");
    }
  });

  it("returns EARLY_EXIT on child exit before /health succeeds", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false });
    const fake = new FakeChild();
    const spawnFn = vi.fn().mockReturnValue(fake);
    const promise = runLauncherStateMachine({
      baseUrl: "http://127.0.0.1:9847",
      settings: _settings(),
      spawnFn, fetchImpl: fetchMock,
      intervalMs: 10, totalMs: 5000,
    });
    queueMicrotask(() => fake.emit("spawn"));
    // Short delay, then exit.
    setTimeout(() => fake.emit("exit", 2, null), 20);
    const outcome = await promise;
    expect(outcome.kind).toBe("EARLY_EXIT");
  });

  it("returns POLL_TIMEOUT when /health never succeeds and child stays alive", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false });
    const fake = new FakeChild();
    const spawnFn = vi.fn().mockReturnValue(fake);
    const promise = runLauncherStateMachine({
      baseUrl: "http://127.0.0.1:9847",
      settings: _settings(),
      spawnFn, fetchImpl: fetchMock,
      intervalMs: 10, totalMs: 50,
    });
    queueMicrotask(() => fake.emit("spawn"));
    const outcome = await promise;
    expect(outcome.kind).toBe("POLL_TIMEOUT");
  });
});
```

### Step 2: Run tests to verify they fail

Run: `cd obsidian-recap && npm test -- daemonLauncher`
Expected: FAIL on the seven new state-machine tests.

### Step 3: Write minimal implementation

Append to `obsidian-recap/src/daemonLauncher.ts`:

```typescript
import type { DaemonLaunchSettings } from "./launchSettings";

export type LauncherOutcome =
  | { kind: "ALREADY_RUNNING" }
  | { kind: "DISABLED" }
  | { kind: "NOT_CONFIGURED" }
  | { kind: "SPAWN_ERROR"; code: string | undefined; message: string }
  | { kind: "EARLY_EXIT"; exitCode: number | null; signal: NodeJS.Signals | null }
  | { kind: "POLL_TIMEOUT"; pid: number | undefined; logPath: string }
  | { kind: "SPAWNED_AND_READY"; pid: number | undefined };

export interface RunParams {
  baseUrl: string;
  settings: DaemonLaunchSettings;
  /** Injectable for testing. */
  spawnFn: SpawnLike;
  fetchImpl?: FetchLike;
  intervalMs?: number;
  totalMs?: number;
  /** Only used when SPAWN happens and settings.launcherLogPath is empty. */
  defaultLogPath?: string;
}

const INITIAL_PROBE_TIMEOUT_MS = 2000;

function isConfigured(s: DaemonLaunchSettings): boolean {
  return (
    s.launcherExecutable.trim() !== "" &&
    s.launcherArgs.length > 0 &&
    s.launcherCwd.trim() !== ""
  );
}

export async function runLauncherStateMachine(
  params: RunParams,
): Promise<LauncherOutcome> {
  const {
    baseUrl, settings, spawnFn,
    fetchImpl = fetch, intervalMs, totalMs,
    defaultLogPath = "",
  } = params;

  // Step 1: probe.
  if (await probeHealth(baseUrl, INITIAL_PROBE_TIMEOUT_MS, fetchImpl)) {
    return { kind: "ALREADY_RUNNING" };
  }

  // Step 2: autostart toggle.
  if (!settings.autostartEnabled) return { kind: "DISABLED" };

  // Step 3: configuration check.
  if (!isConfigured(settings)) return { kind: "NOT_CONFIGURED" };

  // Step 4: spawn.
  const logPath = settings.launcherLogPath || defaultLogPath;
  const spawnResult = await spawnLauncher(
    {
      executable: settings.launcherExecutable,
      args: settings.launcherArgs,
      cwd: settings.launcherCwd,
      env: logPath ? { RECAP_LAUNCHER_LOG: logPath } : {},
    },
    spawnFn,
  );
  if (spawnResult.kind === "ERROR") {
    return {
      kind: "SPAWN_ERROR",
      code: spawnResult.code,
      message: spawnResult.message,
    };
  }

  // Step 5: poll.
  const pollResult = await pollUntilReady({
    baseUrl, child: spawnResult.child,
    intervalMs, totalMs, fetchImpl,
  });
  if (pollResult.kind === "READY") {
    return { kind: "SPAWNED_AND_READY", pid: spawnResult.pid };
  }
  if (pollResult.kind === "EXITED") {
    return {
      kind: "EARLY_EXIT",
      exitCode: pollResult.exitCode,
      signal: pollResult.signal,
    };
  }
  return { kind: "POLL_TIMEOUT", pid: spawnResult.pid, logPath };
}
```

### Step 4: Run all tests

Run: `cd obsidian-recap && npm test -- daemonLauncher`
Expected: all tests PASS.

### Step 5: Commit

```bash
git add obsidian-recap/src/daemonLauncher.ts obsidian-recap/src/daemonLauncher.test.ts
git commit -m "feat(plugin): runLauncherStateMachine orchestrator

Ties probeHealth + spawnLauncher + pollUntilReady into the
design-doc state machine with seven terminal outcomes:
ALREADY_RUNNING, DISABLED, NOT_CONFIGURED, SPAWN_ERROR,
EARLY_EXIT, POLL_TIMEOUT, SPAWNED_AND_READY.

Caller (main.ts onload) pattern-matches the outcome and
maps to Obsidian notices + status-bar state +
rehydrateClient() calls.

EARLY_EXIT is separate from POLL_TIMEOUT so the user knows
when to expect launcher.log vs when they hit a pre-launcher
failure (wrong cwd, bad args, etc.)."
```

---

## Task 7: Wire state machine into `main.ts.onload`

**Files:**
- Modify: `obsidian-recap/src/main.ts` (onload, add `startDaemonNow` method)

**Context:** Replace the current onload flow that assumes daemon is already running. After load settings + read token, invoke the state machine and branch on outcome.

### Step 1: Write a small integration-smoke test at the plugin boundary

Since `main.ts` imports Obsidian APIs that are hard to mock in vitest, rely on manual acceptance (Task 10) for the full onload verification. But add a tiny module-level test that the outcome-to-notice mapping function is sane.

Extract the mapping to a pure helper first, then test it. Create `obsidian-recap/src/daemonLauncherNotices.ts`:

```typescript
import type { LauncherOutcome } from "./daemonLauncher";

export interface LauncherNotice {
  // null = don't show a Notice (used for DISABLED and SPAWNED_AND_READY).
  notice: string | null;
  statusBarOffline: boolean;
  // true = caller should call rehydrateClient after this outcome.
  shouldRehydrate: boolean;
}

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
        notice: "Recap launcher not configured. Open Settings → Recap → Daemon launch.",
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
```

Create `obsidian-recap/src/daemonLauncherNotices.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { noticeForOutcome } from "./daemonLauncherNotices";

describe("noticeForOutcome", () => {
  it("ALREADY_RUNNING: no notice, status online, rehydrate", () => {
    const n = noticeForOutcome({ kind: "ALREADY_RUNNING" });
    expect(n.notice).toBeNull();
    expect(n.statusBarOffline).toBe(false);
    expect(n.shouldRehydrate).toBe(true);
  });
  it("DISABLED: silent offline, no rehydrate (per design doc)", () => {
    const n = noticeForOutcome({ kind: "DISABLED" });
    expect(n.notice).toBeNull();
    expect(n.statusBarOffline).toBe(true);
    expect(n.shouldRehydrate).toBe(false);
  });
  it("NOT_CONFIGURED: notice mentions settings path", () => {
    const n = noticeForOutcome({ kind: "NOT_CONFIGURED" });
    expect(n.notice).toContain("Settings");
    expect(n.notice).toContain("Daemon launch");
  });
  it("SPAWN_ERROR: notice includes code", () => {
    const n = noticeForOutcome({
      kind: "SPAWN_ERROR", code: "ENOENT", message: "spawn x ENOENT",
    });
    expect(n.notice).toContain("ENOENT");
  });
  it("EARLY_EXIT: notice mentions exit code and pre-launch caveat", () => {
    const n = noticeForOutcome({
      kind: "EARLY_EXIT", exitCode: 2, signal: null,
    });
    expect(n.notice).toContain("code 2");
    expect(n.notice).toContain("launcher.log may not exist");
  });
  it("POLL_TIMEOUT: notice mentions log path", () => {
    const n = noticeForOutcome({
      kind: "POLL_TIMEOUT", pid: 123, logPath: "/v/launcher.log",
    });
    expect(n.notice).toContain("/v/launcher.log");
    expect(n.notice).toContain("pid=123");
  });
  it("SPAWNED_AND_READY: no notice, rehydrate", () => {
    const n = noticeForOutcome({ kind: "SPAWNED_AND_READY", pid: 123 });
    expect(n.notice).toBeNull();
    expect(n.shouldRehydrate).toBe(true);
  });
});
```

### Step 2: Run test to verify it fails

Run: `cd obsidian-recap && npm test -- daemonLauncherNotices`
Expected: FAIL until the module is created. (We just wrote both files; write just the test first, run, see failure.)

### Step 3: Write the implementation (already above) + run tests

Run: `cd obsidian-recap && npm test -- daemonLauncherNotices`
Expected: all tests PASS.

### Step 4: Wire into `main.ts`

Modify `onload` in `obsidian-recap/src/main.ts`. Add near the top of the file:

```typescript
import { spawn } from "child_process";
import { runLauncherStateMachine } from "./daemonLauncher";
import { noticeForOutcome } from "./daemonLauncherNotices";
```

Replace the auth-token read block (lines 54-63) and the subsequent WebSocket block (lines 73-89) with:

```typescript
// Default launcher log path if the setting is empty.
const defaultLogPath = (this.app.vault.adapter as any).getFullPath?.(
  "_Recap/.recap/launcher.log",
) ?? "_Recap/.recap/launcher.log";

const outcome = await runLauncherStateMachine({
  baseUrl: this.settings.daemonUrl,
  settings: this.settings,
  spawnFn: spawn as any,
  defaultLogPath,
});
const notice = noticeForOutcome(outcome);
if (notice.notice) new Notice(notice.notice);

const statusBarEl = this.addStatusBarItem();
this.statusBar = new RecapStatusBar(statusBarEl);

if (notice.statusBarOffline) {
  this.statusBar.setOffline();
}
if (notice.shouldRehydrate) {
  await this.rehydrateClient();
}
```

Remove the original "Read auth token from vault" block and the `this.client` construction block — `rehydrateClient()` now owns that lifecycle.

Add a "Start daemon now" command:

```typescript
this.addCommand({
  id: "start-daemon-now",
  name: "Start daemon now",
  callback: async () => {
    const outcome = await runLauncherStateMachine({
      baseUrl: this.settings.daemonUrl,
      settings: { ...this.settings, autostartEnabled: true },
      spawnFn: spawn as any,
      defaultLogPath,
    });
    const n = noticeForOutcome(outcome);
    if (n.notice) new Notice(n.notice);
    if (n.statusBarOffline) this.statusBar?.setOffline();
    if (n.shouldRehydrate) await this.rehydrateClient();
  },
});
```

### Step 5: Build

Run: `cd obsidian-recap && npm run build`
Expected: build succeeds.

Run: `cd obsidian-recap && npm test`
Expected: all tests PASS.

### Step 6: Commit

```bash
git add obsidian-recap/src/daemonLauncherNotices.ts obsidian-recap/src/daemonLauncherNotices.test.ts obsidian-recap/src/main.ts
git commit -m "feat(plugin): wire launcher state machine into plugin onload

onload now runs the probe/spawn/poll state machine before
building DaemonClient. Each terminal outcome maps to a notice +
status-bar state + optional rehydrateClient() call via a pure
helper (easy to unit-test).

Adds 'Start daemon now' command for manual retry without
an Obsidian reload (bypasses probe + autostart gate; always
attempts spawn)."
```

---

## Task 8: Settings UI — daemon launch section

**Files:**
- Modify: `obsidian-recap/src/settings.ts` (add new "Daemon launch" section)

**Context:** Reuse Obsidian's `Setting` helper. Fields are: autostart toggle, executable, args (one-per-line textarea), cwd, log path, "Start daemon now" button.

### Step 1: Write no vitest (UI is Obsidian-dependent)

Manual acceptance — no automated test for settings UI. Implementation-only task.

### Step 2: Add section to `display()` in `settings.ts`

After `containerEl.createEl("h3", { text: "Daemon lifecycle" });` block, add:

```typescript
containerEl.createEl("h3", { text: "Daemon launch" });
const launchContainer = containerEl.createDiv({
  cls: "recap-settings-launch",
});
this.renderLaunchSection(launchContainer);
```

Implement `renderLaunchSection` as a new method on `RecapSettingTab`:

```typescript
private renderLaunchSection(el: HTMLElement): void {
  new Setting(el)
    .setName("Auto-start daemon with Obsidian")
    .setDesc("When enabled, the plugin will start the daemon if it's not already running.")
    .addToggle(t => t
      .setValue(this.plugin.settings.autostartEnabled)
      .onChange(async (v) => {
        this.plugin.settings.autostartEnabled = v;
        await this.plugin.saveSettings();
      }),
    );

  new Setting(el)
    .setName("Launcher executable")
    .setDesc("Full path to Python/uv executable or a binary name on PATH (e.g. \"uv\").")
    .addText(t => t
      .setPlaceholder("uv")
      .setValue(this.plugin.settings.launcherExecutable)
      .onChange(async (v) => {
        this.plugin.settings.launcherExecutable = v.trim();
        await this.plugin.saveSettings();
      }),
    );

  new Setting(el)
    .setName("Launcher arguments")
    .setDesc("One argument per line. Typical: run / python / -m / recap.launcher / config.yaml")
    .addTextArea(t => t
      .setPlaceholder("run\npython\n-m\nrecap.launcher\nconfig.yaml")
      .setValue(this.plugin.settings.launcherArgs.join("\n"))
      .onChange(async (v) => {
        this.plugin.settings.launcherArgs = v.split("\n")
          .map(s => s.trim()).filter(s => s.length > 0);
        await this.plugin.saveSettings();
      })
      .inputEl.rows = 6,
    );

  new Setting(el)
    .setName("Working directory")
    .setDesc("Typically the Recap repo root. Used as the cwd for the spawned launcher.")
    .addText(t => t
      .setPlaceholder("C:\\Users\\you\\Documents\\Projects\\recap")
      .setValue(this.plugin.settings.launcherCwd)
      .onChange(async (v) => {
        this.plugin.settings.launcherCwd = v.trim();
        await this.plugin.saveSettings();
      }),
    );

  new Setting(el)
    .setName("Launcher log path")
    .setDesc("Absolute path for launcher.log. Leave blank to use {vault}/_Recap/.recap/launcher.log.")
    .addText(t => t
      .setPlaceholder("(default)")
      .setValue(this.plugin.settings.launcherLogPath)
      .onChange(async (v) => {
        this.plugin.settings.launcherLogPath = v.trim();
        await this.plugin.saveSettings();
      }),
    );

  new Setting(el)
    .setName("Start daemon now")
    .setDesc("Spawn the launcher using the current settings without waiting for an Obsidian reload.")
    .addButton(b => b
      .setButtonText("Start daemon now")
      .setCta()
      .onClick(async () => {
        const cmd = (this.app as any).commands?.findCommand("obsidian-recap:start-daemon-now");
        if (cmd) {
          (this.app as any).commands.executeCommand(cmd);
        } else {
          new Notice("Recap: 'Start daemon now' command not registered. Reload plugin.");
        }
      }),
    );
}
```

### Step 3: Build + manual smoke

Run: `cd obsidian-recap && npm run build`
Expected: build succeeds.

Open plugin settings in a dev Obsidian install, confirm the new section renders.

### Step 4: Commit

```bash
git add obsidian-recap/src/settings.ts
git commit -m "feat(plugin): settings UI for daemon launch configuration

Adds 'Daemon launch' section with:
- Auto-start toggle (default on)
- Executable path (text)
- Arguments (textarea, one per line)
- Working directory (text)
- Launcher log path (text, optional; defaults to vault-local)
- 'Start daemon now' button (delegates to the registered command)

Structured fields avoid the shell-parsing fragility that a single
command string would introduce for Windows paths with spaces and
'uv run ...' style invocations."
```

---

## Task 9: Default log-path plumbing + vault-rooted resolution

**Files:**
- Modify: `obsidian-recap/src/main.ts` (refine `defaultLogPath` computation)

**Context:** The draft in Task 7 uses `getFullPath` which is Obsidian-internal API. Harden it with a fallback so the log path is always an absolute-or-useful string even if that API is absent.

### Step 1: Extract helper with test

Create `obsidian-recap/src/vaultPaths.ts`:

```typescript
/**
 * Resolve a vault-relative path to whatever concrete string the
 * platform gives us (absolute path on FileSystemAdapter, the relative
 * path otherwise). Used for passing log file paths to detached child
 * processes that don't share the plugin's vault rooting.
 */
export function vaultRelativeToConcrete(
  adapter: unknown,
  vaultRelative: string,
): string {
  const getFullPath = (adapter as { getFullPath?: (p: string) => string })
    .getFullPath;
  if (typeof getFullPath === "function") {
    try {
      return getFullPath.call(adapter, vaultRelative);
    } catch {
      // Fall through.
    }
  }
  return vaultRelative;
}
```

Create `obsidian-recap/src/vaultPaths.test.ts`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { vaultRelativeToConcrete } from "./vaultPaths";

describe("vaultRelativeToConcrete", () => {
  it("returns adapter.getFullPath(path) when available", () => {
    const adapter = { getFullPath: vi.fn().mockReturnValue("C:\\v\\x.log") };
    const p = vaultRelativeToConcrete(adapter, "_Recap/.recap/x.log");
    expect(p).toBe("C:\\v\\x.log");
    expect(adapter.getFullPath).toHaveBeenCalledWith("_Recap/.recap/x.log");
  });

  it("falls back to input when adapter has no getFullPath", () => {
    const p = vaultRelativeToConcrete({}, "_Recap/.recap/x.log");
    expect(p).toBe("_Recap/.recap/x.log");
  });

  it("falls back when getFullPath throws", () => {
    const adapter = {
      getFullPath: vi.fn().mockImplementation(() => { throw new Error(); }),
    };
    const p = vaultRelativeToConcrete(adapter, "x.log");
    expect(p).toBe("x.log");
  });
});
```

### Step 2: Run tests, implement, re-run

Run: `cd obsidian-recap && npm test -- vaultPaths`
Expected: 3 tests PASS.

### Step 3: Use in `main.ts`

Replace the `defaultLogPath` assignment in `onload` (Task 7) with:

```typescript
import { vaultRelativeToConcrete } from "./vaultPaths";

const defaultLogPath = vaultRelativeToConcrete(
  this.app.vault.adapter,
  "_Recap/.recap/launcher.log",
);
```

Repeat the same change in the `start-daemon-now` command callback.

### Step 4: Build + test

Run: `cd obsidian-recap && npm run build && npm test`
Expected: all pass.

### Step 5: Commit

```bash
git add obsidian-recap/src/vaultPaths.ts obsidian-recap/src/vaultPaths.test.ts obsidian-recap/src/main.ts
git commit -m "feat(plugin): safe absolute path resolution for launcher log

Wraps Obsidian's adapter.getFullPath (internal API, may not
exist on all platforms/versions) with a fallback that returns
the vault-relative path unchanged. Called from onload +
start-daemon-now so the spawned launcher receives a concrete
path for RECAP_LAUNCHER_LOG."
```

---

## Task 10: Manual acceptance checklist

**Files:**
- Create: `docs/handoffs/2026-04-22-daemon-autostart-acceptance.md`

**Context:** The UI integration is hard to automate. Capture the hand-test checklist that must pass before opening a PR.

### Step 1: Write the checklist

Create `docs/handoffs/2026-04-22-daemon-autostart-acceptance.md`:

```markdown
# Daemon Autostart — Manual Acceptance Checklist

Run through every scenario on Windows before opening the PR for #31. Tick each when verified.

## Pre-flight

- [ ] `cd obsidian-recap && npm test` — all green
- [ ] `cd obsidian-recap && npm run build` — no TypeScript errors
- [ ] Plugin loaded in an Obsidian install with a test vault

## Scenarios

- [ ] **Fresh install, no settings.** First plugin load → notice "Recap launcher not configured..." appears once, status bar shows offline, no spawn attempt in Task Manager.
- [ ] **Configure and reload.** Fill in launch fields, reload plugin → daemon starts within 15s, status bar goes online, no lingering "offline" notice.
- [ ] **Daemon already running.** Start daemon manually (`uv run python -m recap.launcher config.yaml`), then load plugin → status goes green, no spawn attempt (confirm via Task Manager: only one python.exe tree).
- [ ] **Kill daemon while Obsidian open.** `taskkill /pid <launcher-pid> /t /f`, then close+reopen Obsidian → plugin respawns daemon. Verify a *new* pid in Task Manager.
- [ ] **Toggle autostart off.** Disable "Auto-start daemon with Obsidian", reload plugin while daemon is down → status stays offline, no spawn attempt, NO notice (silent).
- [ ] **Bad executable path.** Set launcherExecutable to `nonexistent`, click "Start daemon now" → notice with ENOENT. Status offline.
- [ ] **Bad working directory.** Set launcherCwd to a path without `config.yaml` → notice describes exit code + "launcher.log may not exist" caveat.
- [ ] **Close Obsidian with daemon running.** Close Obsidian, confirm launcher + daemon still running in Task Manager. Open Obsidian → probe succeeds immediately, no respawn.
- [ ] **Multiple Obsidian windows.** Open two Obsidian vaults with the plugin simultaneously → one spawns, the other sees running daemon via /health. No port-bind collision notice.
- [ ] **Missing auth token after spawn.** With launch settings valid but auth token file missing or stale (delete `_Recap/.recap/auth-token`), click "Start daemon now" → rehydrateClient retries, eventually surfaces "Daemon running but auth token not found... Re-pair via tray menu."
- [ ] **15s poll timeout.** Point launcherArgs at a command that does NOT bind port 9847 (e.g. `python -c "import time; time.sleep(60)"`) → after 15s, notice mentions the log path and pid. Status offline.

## Cleanup before committing

- [ ] Kill any orphan launcher/daemon processes spawned during testing.
- [ ] Revert test vault's plugin settings to defaults.
```

### Step 2: Commit

```bash
git add docs/handoffs/2026-04-22-daemon-autostart-acceptance.md
git commit -m "docs(handoffs): manual acceptance checklist for daemon autostart"
```

---

## Task 11: MANIFEST update

**Files:**
- Modify: `MANIFEST.md`

### Step 1: Update the structure tree

Add/update lines under `obsidian-recap/`:

- `src/main.ts / api.ts / settings.ts` → append to description: `+ launcher autostart state machine wired into onload`.
- Add new lines:
  - `src/daemonLauncher.ts / daemonLauncherNotices.ts` — probe/spawn/poll state machine (probeHealth, spawnLauncher, pollUntilReady, runLauncherStateMachine) + outcome → (notice, statusBar, rehydrate) mapping
  - `src/authToken.ts` — read `_Recap/.recap/auth-token` with small retry (used by rehydrateClient after plugin-spawned daemon starts)
  - `src/launchSettings.ts` — DaemonLaunchSettings interface + DEFAULT_LAUNCH_SETTINGS
  - `src/vaultPaths.ts` — vault-relative path resolution with getFullPath fallback

Add a Key Relationships bullet:

```markdown
- **Plugin-driven daemon autostart (#31):** onload invokes `runLauncherStateMachine` which probes `/health`, checks `autostartEnabled`, spawns `recap.launcher` detached with `{cwd, args, env.RECAP_LAUNCHER_LOG}` from settings, polls `/health` up to 15s while concurrently listening for child `exit`, then calls `rehydrateClient()` on success. All Python-side code is unchanged — launcher keeps its supervisor role and `managed/can_restart` contract.
```

### Step 2: Commit

```bash
git add MANIFEST.md
git commit -m "docs(manifest): plugin-driven daemon autostart (#31)"
```

### Step 3: Open PR

```bash
git push -u origin feat/31-daemon-autostart
gh pr create --title "feat(#31): plugin-driven daemon autostart" --body "Implements the approved design at docs/plans/2026-04-22-daemon-autostart-design.md. Fixes #31. Task breakdown at docs/plans/2026-04-22-daemon-autostart-plan.md. Manual acceptance checklist at docs/handoffs/2026-04-22-daemon-autostart-acceptance.md."
```

---

## Rollback and safety notes

- Each commit is its own atomic change. Revert the main.ts wiring commit (Task 7) to fall back to the pre-#31 always-offline behavior without disturbing the helpers.
- No daemon-side changes → no plugin/server version mismatch concerns.
- Detached+unref is the specific contract that keeps the daemon alive across Obsidian close; verify in manual acceptance (scenario 8) rather than trusting docs.

## Verification after merge

- Fresh Obsidian install + plugin install: no notices on first open until the user configures settings.
- Configure settings, reload, verify daemon starts.
- Kill the daemon while Obsidian is open, reload plugin, verify autospawn.
- Close Obsidian, confirm daemon survives.
- Verify `/api/status` still returns `managed: true, can_restart: true` — that's the supervisor-contract regression check.

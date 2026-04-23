import { describe, it, expect, vi } from "vitest";
import { EventEmitter } from "events";
import { probeHealth, spawnLauncher, LaunchResult, pollUntilReady, PollResult, runLauncherStateMachine, LauncherOutcome } from "./daemonLauncher";
import { DaemonLaunchSettings } from "./launchSettings";

describe("probeHealth", () => {
  it("returns true when /health responds 200 within timeout", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ status: "ok" }),
    });
    const ok = await probeHealth("http://127.0.0.1:9847", 2000, fetchMock as any);
    expect(ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:9847/health",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("returns false when fetch throws", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("ECONNREFUSED"));
    const ok = await probeHealth("http://127.0.0.1:9847", 2000, fetchMock as any);
    expect(ok).toBe(false);
  });

  it("returns false on non-OK status", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false, status: 500,
    });
    const ok = await probeHealth("http://127.0.0.1:9847", 2000, fetchMock as any);
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
    const ok = await probeHealth("http://127.0.0.1:9847", 50, fetchMock as any);
    expect(ok).toBe(false);
  });
});

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
      spawnFn as any,
    );
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

  it("resolves with ERROR on 'error' event", async () => {
    const fake = new FakeChild();
    const spawnFn = vi.fn().mockReturnValue(fake);
    const promise = spawnLauncher(
      { executable: "missing", args: [], cwd: ".", env: {} },
      spawnFn as any,
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

  it("passes RECAP_LAUNCHER_LOG env var through to spawn options", async () => {
    const fake = new FakeChild();
    const spawnFn = vi.fn().mockReturnValue(fake);
    spawnLauncher(
      {
        executable: "uv", args: ["run"], cwd: ".",
        env: { RECAP_LAUNCHER_LOG: "/vault/_Recap/.recap/launcher.log" },
      },
      spawnFn as any,
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

describe("pollUntilReady", () => {
  it("returns READY when /health succeeds within window", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 500 })
      .mockResolvedValueOnce({ ok: false, status: 500 })
      .mockResolvedValue({ ok: true, status: 200 });
    const fakeChild = new FakeChild();
    const result = await pollUntilReady({
      baseUrl: "http://127.0.0.1:9847",
      child: fakeChild as any,
      intervalMs: 10,
      totalMs: 1000,
      fetchImpl: fetchMock as any,
    });
    expect(result.kind).toBe("READY");
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(3);
  });

  it("returns EXITED when child emits 'exit' before /health succeeds", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false });
    const fakeChild = new FakeChild();
    const promise = pollUntilReady({
      baseUrl: "http://127.0.0.1:9847",
      child: fakeChild as any,
      intervalMs: 10,
      totalMs: 5000,
      fetchImpl: fetchMock as any,
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
      child: fakeChild as any,
      intervalMs: 10,
      totalMs: 50,
      fetchImpl: fetchMock as any,
    });
    expect(result.kind).toBe("TIMEOUT");
  });
});

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
      spawnFn: vi.fn() as any,
      fetchImpl: fetchMock as any,
    });
    expect(outcome.kind).toBe("ALREADY_RUNNING");
  });

  it("returns DISABLED when autostartEnabled=false and /health fails", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false });
    const outcome = await runLauncherStateMachine({
      baseUrl: "http://127.0.0.1:9847",
      settings: _settings({ autostartEnabled: false }),
      spawnFn: vi.fn() as any,
      fetchImpl: fetchMock as any,
    });
    expect(outcome.kind).toBe("DISABLED");
  });

  it("returns NOT_CONFIGURED when launch fields are empty", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false });
    const outcome = await runLauncherStateMachine({
      baseUrl: "http://127.0.0.1:9847",
      settings: _settings({ launcherExecutable: "", launcherArgs: [] }),
      spawnFn: vi.fn() as any,
      fetchImpl: fetchMock as any,
    });
    expect(outcome.kind).toBe("NOT_CONFIGURED");
  });

  it("returns SPAWNED_AND_READY on successful end-to-end path", async () => {
    let callCount = 0;
    const fetchMock = vi.fn().mockImplementation(async () => {
      callCount++;
      return { ok: callCount > 1 };  // first probe fails, later succeed
    });
    const fake = new FakeChild();
    const spawnFn = vi.fn().mockReturnValue(fake);
    const promise = runLauncherStateMachine({
      baseUrl: "http://127.0.0.1:9847",
      settings: _settings(),
      spawnFn: spawnFn as any,
      fetchImpl: fetchMock as any,
      intervalMs: 10,
      totalMs: 1000,
    });
    // setTimeout(..., 0) (not queueMicrotask) so the orchestrator's initial
    // probeHealth await chain drains and spawnLauncher registers its listeners
    // before the event fires.
    setTimeout(() => fake.emit("spawn"), 0);
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
      spawnFn: spawnFn as any,
      fetchImpl: fetchMock as any,
    });
    setTimeout(() => {
      const err = new Error("spawn nonexistent ENOENT");
      (err as NodeJS.ErrnoException).code = "ENOENT";
      fake.emit("error", err);
    }, 0);
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
      spawnFn: spawnFn as any,
      fetchImpl: fetchMock as any,
      intervalMs: 10,
      totalMs: 5000,
    });
    setTimeout(() => fake.emit("spawn"), 0);
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
      spawnFn: spawnFn as any,
      fetchImpl: fetchMock as any,
      intervalMs: 10,
      totalMs: 50,
    });
    setTimeout(() => fake.emit("spawn"), 0);
    const outcome = await promise;
    expect(outcome.kind).toBe("POLL_TIMEOUT");
  });
});

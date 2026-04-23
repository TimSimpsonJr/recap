import { describe, it, expect, vi } from "vitest";
import { EventEmitter } from "events";
import { probeHealth, spawnLauncher, LaunchResult } from "./daemonLauncher";

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

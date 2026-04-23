import { describe, it, expect } from "vitest";
import { noticeForOutcome } from "./daemonLauncherNotices";

describe("noticeForOutcome", () => {
  it("ALREADY_RUNNING: no notice, status online, rehydrate", () => {
    const n = noticeForOutcome({ kind: "ALREADY_RUNNING" });
    expect(n.notice).toBeNull();
    expect(n.statusBarOffline).toBe(false);
    expect(n.shouldRehydrate).toBe(true);
  });
  it("DISABLED: silent offline, no rehydrate", () => {
    const n = noticeForOutcome({ kind: "DISABLED" });
    expect(n.notice).toBeNull();
    expect(n.statusBarOffline).toBe(true);
    expect(n.shouldRehydrate).toBe(false);
  });
  it("NOT_CONFIGURED: notice mentions settings path", () => {
    const n = noticeForOutcome({ kind: "NOT_CONFIGURED" });
    expect(n.notice).toContain("Settings");
    expect(n.notice).toContain("Daemon launch");
    expect(n.statusBarOffline).toBe(true);
    expect(n.shouldRehydrate).toBe(false);
  });
  it("SPAWN_ERROR: notice includes code", () => {
    const n = noticeForOutcome({
      kind: "SPAWN_ERROR", code: "ENOENT", message: "spawn x ENOENT",
    });
    expect(n.notice).toContain("ENOENT");
    expect(n.statusBarOffline).toBe(true);
    expect(n.shouldRehydrate).toBe(false);
  });
  it("EARLY_EXIT: notice mentions exit code and pre-launch caveat", () => {
    const n = noticeForOutcome({
      kind: "EARLY_EXIT", exitCode: 2, signal: null,
    });
    expect(n.notice).toContain("code 2");
    expect(n.notice).toContain("launcher.log may not exist");
    expect(n.statusBarOffline).toBe(true);
  });
  it("POLL_TIMEOUT: notice mentions log path and pid", () => {
    const n = noticeForOutcome({
      kind: "POLL_TIMEOUT", pid: 123, logPath: "/v/launcher.log",
    });
    expect(n.notice).toContain("/v/launcher.log");
    expect(n.notice).toContain("pid=123");
    expect(n.statusBarOffline).toBe(true);
    expect(n.shouldRehydrate).toBe(false);
  });
  it("SPAWNED_AND_READY: no notice, rehydrate", () => {
    const n = noticeForOutcome({ kind: "SPAWNED_AND_READY", pid: 123 });
    expect(n.notice).toBeNull();
    expect(n.statusBarOffline).toBe(false);
    expect(n.shouldRehydrate).toBe(true);
  });
});

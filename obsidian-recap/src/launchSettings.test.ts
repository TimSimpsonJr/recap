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

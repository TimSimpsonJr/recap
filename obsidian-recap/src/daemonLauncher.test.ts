import { describe, it, expect, vi } from "vitest";
import { probeHealth } from "./daemonLauncher";

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

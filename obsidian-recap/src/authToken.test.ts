import { describe, it, expect, vi } from "vitest";
import { readAuthTokenWithRetry } from "./authToken";

interface MockAdapter {
  exists: (p: string) => Promise<boolean>;
  read: (p: string) => Promise<string>;
}

describe("readAuthTokenWithRetry", () => {
  it("returns token on first attempt when file exists", async () => {
    const adapter: MockAdapter = {
      exists: vi.fn().mockResolvedValue(true),
      read: vi.fn().mockResolvedValue("abc123\n"),
    };
    const token = await readAuthTokenWithRetry(
      adapter, "_Recap/.recap/auth-token", 3, 1,
    );
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

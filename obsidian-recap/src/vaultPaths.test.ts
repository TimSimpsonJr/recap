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
      getFullPath: vi.fn().mockImplementation(() => { throw new Error("boom"); }),
    };
    const p = vaultRelativeToConcrete(adapter, "x.log");
    expect(p).toBe("x.log");
  });
});

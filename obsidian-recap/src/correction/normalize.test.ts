import {describe, it, expect} from "vitest";
import {normalize} from "./normalize";

describe("normalize", () => {
    it("casefolds", () => expect(normalize("Alice")).toBe("alice"));
    it("strips whitespace", () => expect(normalize("  Alice  ")).toBe("alice"));
    it("collapses internal whitespace",
       () => expect(normalize("Sean  Mooney")).toBe("sean mooney"));
    it("strips periods and commas", () => {
        expect(normalize("Sean M.")).toBe("sean m");
        expect(normalize("J.D.")).toBe("jd");
    });
    it("empty returns empty", () => {
        expect(normalize("")).toBe("");
        expect(normalize("   ")).toBe("");
    });
});

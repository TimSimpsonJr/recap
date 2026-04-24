import {describe, it, expect} from "vitest";
import {resolve, ResolutionContext} from "./resolve";

const emptyCtx: ResolutionContext = {
    knownContacts: [], peopleNames: [], companyNames: [], meetingParticipants: [],
};

describe("resolve", () => {
    it("empty typed → ineligible", () => {
        expect(resolve("", emptyCtx).kind).toBe("ineligible");
    });

    it("exact match on known_contact name", () => {
        const r = resolve("Alice", {
            ...emptyCtx,
            knownContacts: [{name: "Alice", display_name: "Alice"}],
        });
        expect(r).toEqual({kind: "link_to_existing", canonical_name: "Alice", requires_contact_create: false});
    });

    it("exact match on alias returns canonical name", () => {
        const r = resolve("Sean M.", {
            ...emptyCtx,
            knownContacts: [{
                name: "Sean Mooney", display_name: "Sean Mooney",
                aliases: ["Sean M."],
            }],
        });
        expect(r).toMatchObject({kind: "link_to_existing", canonical_name: "Sean Mooney"});
    });

    it("near-match initial-aware: 'Sean M.' → Sean Mooney suggestion", () => {
        const r = resolve("Sean M.", {
            ...emptyCtx,
            knownContacts: [{name: "Sean Mooney", display_name: "Sean Mooney"}],
        });
        expect(r.kind).toBe("near_match_ambiguous");
        if (r.kind === "near_match_ambiguous") {
            expect(r.suggestion).toBe("Sean Mooney");
        }
    });

    it("different first token rejects near-match", () => {
        const r = resolve("Sena", {
            ...emptyCtx,
            knownContacts: [{name: "Sean Mooney", display_name: "Sean Mooney"}],
        });
        expect(r.kind).not.toBe("near_match_ambiguous");
    });

    it("parenthetical strip-and-retry links to Sean", () => {
        const r = resolve("Sean (dev team)", {
            ...emptyCtx,
            knownContacts: [{name: "Sean", display_name: "Sean"}],
        });
        expect(r).toMatchObject({kind: "link_to_existing", canonical_name: "Sean"});
    });

    it("ineligible: SPEAKER_00", () => {
        expect(resolve("SPEAKER_00", emptyCtx).kind).toBe("ineligible");
    });

    it("ineligible: Unknown Speaker 1", () => {
        expect(resolve("Unknown Speaker 1", emptyCtx).kind).toBe("ineligible");
    });

    it("ineligible: company collision", () => {
        const r = resolve("DisburseCloud", {
            ...emptyCtx,
            companyNames: ["DisburseCloud"],
        });
        expect(r.kind).toBe("ineligible");
    });

    it("ineligible: multi-person form", () => {
        expect(resolve("Ed/Ellen", emptyCtx).kind).toBe("ineligible");
    });

    it("People-note-only match: requires_contact_create=true", () => {
        const r = resolve("Alice", {
            ...emptyCtx,
            peopleNames: ["Alice"],
        });
        expect(r).toEqual({
            kind: "link_to_existing",
            canonical_name: "Alice",
            requires_contact_create: true,
            email: undefined,
        });
    });

    it("email-first precedence", () => {
        const r = resolve("Nickname", {
            ...emptyCtx,
            knownContacts: [{name: "Sean Mooney", display_name: "Sean Mooney", email: "sean@x.com"}],
            meetingParticipants: [{name: "Nickname", email: "sean@x.com"}],
        });
        expect(r).toMatchObject({kind: "link_to_existing", canonical_name: "Sean Mooney"});
    });

    it("create new when nothing matches and eligible", () => {
        const r = resolve("Brand New Person", emptyCtx);
        expect(r.kind).toBe("create_new_contact");
    });

    it("skipNearMatch surfaces ineligibility (company collision)", () => {
        // Without skipNearMatch this would return near_match_ambiguous
        // (typed "Sean" is an initial-aware prefix of "Sean Mooney").
        // With skipNearMatch, the near-match layer is bypassed and the
        // company-collision check in checkIneligibility fires.
        const r = resolve("Sean", {
            ...emptyCtx,
            knownContacts: [{name: "Sean Mooney", display_name: "Sean Mooney"}],
            companyNames: ["Sean"],
        }, {skipNearMatch: true});
        expect(r.kind).toBe("ineligible");
        if (r.kind === "ineligible") {
            expect(r.reason).toContain("Company");
        }
    });

    it("skipNearMatch allows legitimate create", () => {
        // Non-near-match typed name flows straight to create_new_contact
        // even when knownContacts exist.
        const r = resolve("Totally New Person", {
            ...emptyCtx,
            knownContacts: [{name: "Sean Mooney", display_name: "Sean Mooney"}],
        }, {skipNearMatch: true});
        expect(r.kind).toBe("create_new_contact");
    });
});

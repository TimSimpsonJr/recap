// obsidian-recap/src/correction/resolve.ts
import {normalize} from "./normalize";

export interface KnownContact {
    name: string;
    display_name: string;
    aliases?: string[];
    email?: string | null;
}

export interface Participant {
    name: string;
    email?: string | null;
}

export interface ResolutionContext {
    knownContacts: KnownContact[];
    peopleNames: string[];
    companyNames: string[];
    meetingParticipants: Participant[];
}

export type ResolutionPlan =
    | {kind: "link_to_existing"; canonical_name: string; requires_contact_create: boolean; email?: string}
    | {kind: "create_new_contact"; name: string; email?: string}
    | {kind: "near_match_ambiguous"; suggestion: string; typed: string}
    | {kind: "ineligible"; reason: string; typed: string};

const SPEAKER_ID_RE = /^SPEAKER_\d+$/;
const UNKNOWN_RE = /^(UNKNOWN|Unknown Speaker.*)$/i;
const PARENTHETICAL_RE = /\([^)]+\)/;

export function resolve(typed: string, ctx: ResolutionContext): ResolutionPlan {
    const normalized = normalize(typed);
    if (!normalized) return {kind: "ineligible", reason: "empty", typed};

    const linked = tryMatches(typed, normalized, ctx);
    if (linked) return linked;

    const stripped = typed.replace(PARENTHETICAL_RE, "").trim();
    if (stripped !== typed && normalize(stripped)) {
        const retried = tryMatches(stripped, normalize(stripped), ctx);
        if (retried) return retried;
    }

    const near = findNearMatch(normalized, ctx);
    if (near) return {kind: "near_match_ambiguous", suggestion: near, typed};

    const ineligibility = checkIneligibility(typed, normalized, ctx);
    if (ineligibility) return ineligibility;

    const participant = ctx.meetingParticipants.find(
        p => normalize(p.name) === normalized && p.email,
    );
    return {kind: "create_new_contact", name: typed, email: participant?.email ?? undefined};
}

function tryMatches(typed: string, normalized: string, ctx: ResolutionContext): ResolutionPlan | null {
    // (a) Email-first
    const participant = ctx.meetingParticipants.find(
        p => normalize(p.name) === normalized && p.email,
    );
    if (participant?.email) {
        const byEmail = ctx.knownContacts.find(
            c => c.email?.toLowerCase() === participant.email!.toLowerCase(),
        );
        if (byEmail) return {
            kind: "link_to_existing",
            canonical_name: byEmail.name,
            requires_contact_create: false,
        };
    }

    // (b) Exact known_contact match
    for (const c of ctx.knownContacts) {
        const candidates = [c.name, c.display_name, ...(c.aliases || [])];
        for (const cand of candidates) {
            if (cand && normalize(cand) === normalized) {
                return {
                    kind: "link_to_existing",
                    canonical_name: c.name,
                    requires_contact_create: false,
                };
            }
        }
    }

    // (c) Exact People note basename match
    const peopleMatch = ctx.peopleNames.find(n => normalize(n) === normalized);
    if (peopleMatch) {
        return {
            kind: "link_to_existing",
            canonical_name: peopleMatch,
            requires_contact_create: true,
            email: participant?.email ?? undefined,
        };
    }
    return null;
}

function findNearMatch(normalizedTyped: string, ctx: ResolutionContext): string | null {
    const typedTokens = normalizedTyped.split(" ").filter(Boolean);
    if (typedTokens.length === 0) return null;

    const candidates: Array<{canonical: string; names: string[]}> = [
        ...ctx.knownContacts.map(c => ({
            canonical: c.name,
            names: [c.name, c.display_name, ...(c.aliases || [])].filter(Boolean) as string[],
        })),
        ...ctx.peopleNames.map(n => ({canonical: n, names: [n]})),
    ];

    for (const cand of candidates) {
        for (const candName of cand.names) {
            if (initialAwareMatch(typedTokens, normalize(candName).split(" ").filter(Boolean))) {
                return cand.canonical;
            }
        }
    }
    return null;
}

function initialAwareMatch(typed: string[], candidate: string[]): boolean {
    if (typed.length === 0 || candidate.length === 0) return false;
    if (typed[0] !== candidate[0]) return false;  // first token must match exactly
    if (typed.length > candidate.length) return false;  // typed can't have more tokens
    if (typed.length === candidate.length && typed.every((t, i) => t === candidate[i])) {
        return false;  // exact match is handled upstream; don't suggest it as near
    }
    for (let i = 1; i < typed.length; i++) {
        const t = typed[i];
        const c = candidate[i];
        if (t === c) continue;
        if (t.length === 1 && c.startsWith(t)) continue;  // initial match
        return false;
    }
    return true;
}

function checkIneligibility(typed: string, normalized: string, ctx: ResolutionContext): ResolutionPlan | null {
    const s = typed.trim();
    if (!s) return {kind: "ineligible", reason: "empty", typed};
    if (SPEAKER_ID_RE.test(s)) return {kind: "ineligible", reason: "SPEAKER_XX", typed};
    if (UNKNOWN_RE.test(s)) return {kind: "ineligible", reason: "Unknown Speaker", typed};
    if (PARENTHETICAL_RE.test(s)) return {kind: "ineligible", reason: "parenthetical", typed};
    if (s.includes("/")) return {kind: "ineligible", reason: "multi-person (contains /)", typed};
    if (ctx.companyNames.some(c => normalize(c) === normalized)) {
        return {kind: "ineligible", reason: "matches Company note", typed};
    }
    return null;
}

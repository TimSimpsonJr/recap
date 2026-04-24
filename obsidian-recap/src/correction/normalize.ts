// obsidian-recap/src/correction/normalize.ts
// Must match recap/identity.py _normalize() exactly.

const MULTI_WS = /\s+/g;
const STRIP_PUNCT = /[.,]/g;

export function normalize(text: string): string {
    let s = text.trim();
    if (!s) return "";
    s = s.replace(STRIP_PUNCT, "");
    s = s.replace(MULTI_WS, " ");
    return s.toLowerCase().trim();
}

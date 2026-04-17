export function formatDate(dateStr: string): string {
    if (!dateStr) return "";
    // Parse "YYYY-MM-DD" in LOCAL time rather than letting the Date
    // constructor interpret it as UTC midnight -- the latter renders as
    // the previous day for any user west of UTC (e.g. Eastern time turns
    // 2026-04-17 into "Apr 16, 2026"). Fall back to the raw Date for any
    // other shape we might receive from older frontmatter.
    const isoDateMatch = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    let d: Date;
    if (isoDateMatch) {
        const [, y, m, day] = isoDateMatch;
        d = new Date(Number(y), Number(m) - 1, Number(day));
    } else {
        d = new Date(dateStr);
    }
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

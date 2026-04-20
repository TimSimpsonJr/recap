# Meetings Three-Tab Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Split the Recap Meetings sidebar into Today / Upcoming / Past tabs with a "Now" divider and per-tab filters.

**Architecture:** `MeetingListView` keeps owning vault subscriptions, daemon state, meetings cache, and `activeTab` + per-tab `filterState`. Pure derive functions in `src/lib/` filter + sort + decorate the meetings per tab and return plain row arrays; a single thin renderer converts those arrays to DOM.

**Tech Stack:** TypeScript, Obsidian plugin API, esbuild, **vitest for unit tests (new)**.

**Design reference:** `docs/plans/2026-04-20-meetings-tabs-design.md`

**Deploy path for every manual-test step:**

```
cd obsidian-recap
npm run build
cp main.js /c/Users/tim/recap-test-vault/.obsidian/plugins/recap/main.js
cp styles.css /c/Users/tim/recap-test-vault/.obsidian/plugins/recap/styles.css
```

Then in Obsidian: Ctrl+P → "Reload app without saving".

---

## Task 1: Add vitest

**Files:**
- Modify: `obsidian-recap/package.json`
- Create: `obsidian-recap/vitest.config.ts`

**Step 1:** `cd obsidian-recap && npm install --save-dev vitest@^1.6.0`

**Step 2:** Add to `package.json` under `"scripts"`:

    "test": "vitest run",
    "test:watch": "vitest"

**Step 3:** Create `vitest.config.ts` with a minimal config: `include: ["src/**/*.test.ts"]`, `environment: "node"`.

**Step 4:** Run `npm test`. Expected: "No test files found" or similar — vitest starts cleanly.

**Step 5:** Commit:

    git add obsidian-recap/package.json obsidian-recap/package-lock.json obsidian-recap/vitest.config.ts
    git commit -m "chore(plugin): add vitest for TS unit tests"

---

## Task 2: `meetingTime.ts` — TDD

**Files:**
- Create: `obsidian-recap/src/lib/meetingTime.ts`
- Create: `obsidian-recap/src/lib/meetingTime.test.ts`

**Step 1:** Write the test file first. Tests to cover:
- `parseMeetingTime("14:00-15:00")` returns `{ start: "14:00", end: "15:00", allDay: false }`
- `parseMeetingTime(undefined)`, `""`, `"garbage"`, `"14:00"` (missing end) all return `{ start: "00:00", end: "23:59", allDay: true }`
- `todayIsoDate(new Date(2026, 3, 20, 14, 30))` returns `"2026-04-20"` (local tz, NOT UTC — regression guard)
- `todayIsoDate(new Date(2026, 3, 20, 22, 0))` returns `"2026-04-20"` (late-evening local doesn't flip to UTC next day)
- `isSameLocalDay(a, b)` true within same local day, false across local midnight

**Step 2:** Run `npm test`. Expected: FAIL (module not found).

**Step 3:** Create `meetingTime.ts`. Exports:
- `interface ParsedMeetingTime { start: string; end: string; allDay: boolean; }`
- `parseMeetingTime(raw: string | undefined | null): ParsedMeetingTime`
  - Use regex `/^(\d{2}):(\d{2})-(\d{2}):(\d{2})$/` against trimmed input
  - Any miss returns the all-day sentinel
- `todayIsoDate(now: Date = new Date()): string` — builds YYYY-MM-DD from `getFullYear/getMonth+1/getDate`, NOT `toISOString` (which would return UTC)
- `isSameLocalDay(a: Date, b: Date): boolean` — compares year/month/date components

**Step 4:** Run `npm test`. Expected: 7 tests pass.

**Step 5:** `npx tsc -noEmit -skipLibCheck`. Expected: exit 0.

**Step 6:** Commit:

    git add obsidian-recap/src/lib/meetingTime.ts obsidian-recap/src/lib/meetingTime.test.ts
    git commit -m "feat(plugin): add meetingTime helpers"

---

## Task 3: `deriveMeetings.ts` — TDD

**Files:**
- Create: `obsidian-recap/src/lib/deriveMeetings.ts`
- Create: `obsidian-recap/src/lib/deriveMeetings.test.ts`
- Modify: `obsidian-recap/src/components/MeetingRow.ts` (add `time`, `companies` to `MeetingData`; add optional `isPast` to `renderMeetingRow`)

**Step 1:** Update `MeetingRow.ts` first (the tests import `MeetingData`):
- Add `time: string;` and `companies: string[];` to `MeetingData`.
- Change `renderMeetingRow` signature to accept optional `opts?: { isPast?: boolean }`.
- When `opts.isPast` is true, add class `recap-meeting-row-past` to the row element.

**Step 2:** Write the test file. Use a frozen `NOW = new Date(2026, 3, 20, 14, 30)` and `TODAY = "2026-04-20"`. Write a helper `meeting(partial)` that spreads defaults over `MeetingData`. Cover:
- `deriveTodayMeetings`: empty input → empty rows, null divider.
- Only keeps today's rows (filters yesterday + tomorrow).
- Ascending sort by start time.
- Marks `isPast` correctly for past / in-progress / future relative to NOW.
- `nowDividerIndex` equals the index of the first non-past row when there's a mix.
- Divider is `null` when all rows are past.
- Divider is `null` when all rows are future/current.
- All-day rows (empty `time`) sort to the top and are never marked past.
- Search filter is case-insensitive across title + participants.
- `deriveUpcomingMeetings`: keeps `date > today`, ascending by date then start time.
- `deriveUpcomingMeetings`: org filter applies.
- `derivePastMeetings`: keeps `date < today`, descending.
- `derivePastMeetings`: company filter applies (`"all"` keeps everything).
- `derivePastMeetings`: status filter applies.

**Step 3:** Run `npm test`. Expected: FAIL (module not found).

**Step 4:** Create `deriveMeetings.ts`. Exports:
- `type Tab = "today" | "upcoming" | "past"`
- `interface TabFilterState { org: string; status: string; company: string; search: string; }`
- `interface DecoratedRow extends MeetingData { isPast: boolean; }`
- `interface TodayDeriveResult { rows: DecoratedRow[]; nowDividerIndex: number | null; }`
- `deriveTodayMeetings(meetings, now, filter): TodayDeriveResult`
- `deriveUpcomingMeetings(meetings, now, filter): DecoratedRow[]`
- `derivePastMeetings(meetings, now, filter): DecoratedRow[]`

Internals:
- `minutesSinceMidnight(hhmm)` helper.
- `isRowPast(m, now)` → `parseMeetingTime(m.time).allDay === false && parsedEnd < nowMin`.
- Shared filter predicates: `matchesOrg`, `matchesCompany`, `matchesStatus`, `matchesSearch`. Each returns `true` when the filter is `"all"` / empty.
- Today sort: ascending by `parseMeetingTime(m.time).start`.
- Upcoming sort: `date` ascending, then start-time ascending.
- Past sort: `date` descending, then start-time descending.
- Today divider: `firstNonPast = rows.findIndex(r => !r.isPast)`. Divider = `firstNonPast` if `firstNonPast > 0 && rows.some(r => r.isPast)`, else `null`.

**Step 5:** Run `npm test`. Expected: all tests pass (17 total with Task 2).

**Step 6:** `npx tsc -noEmit -skipLibCheck`. Expected: exit 0.

**Step 7:** Commit:

    git add obsidian-recap/src/lib/deriveMeetings.ts obsidian-recap/src/lib/deriveMeetings.test.ts obsidian-recap/src/components/MeetingRow.ts
    git commit -m "feat(plugin): add pure derive functions for meeting tabs"

---

## Task 4: `TabStrip` component

**Files:**
- Create: `obsidian-recap/src/components/TabStrip.ts`

**Step 1:** Create the file. Class `TabStrip` with:
- Constructor `(parent: HTMLElement, initial: Tab, onChange: (tab: Tab) => void)`.
- Creates a `.recap-tab-strip` div containing three `.recap-tab-button` divs labeled "Today", "Upcoming", "Past".
- Active button gets class `is-active`.
- On click, if clicked tab differs from current: swap classes, store new active, call `onChange`.
- `setActive(tab: Tab): void` public method for external overrides if needed.

**Step 2:** `npx tsc -noEmit -skipLibCheck`. Expected: exit 0.

**Step 3:** Commit:

    git add obsidian-recap/src/components/TabStrip.ts
    git commit -m "feat(plugin): add TabStrip component"

---

## Task 5: `NowDivider` component

**Files:**
- Create: `obsidian-recap/src/components/NowDivider.ts`

**Step 1:** Create the file. Exports `renderNowDivider(container: HTMLElement, now: Date = new Date()): HTMLElement`. Creates a div with class `recap-now-divider` and text `Now · HH:MM`.

**Step 2:** `npx tsc -noEmit -skipLibCheck`. Expected: exit 0.

**Step 3:** Commit:

    git add obsidian-recap/src/components/NowDivider.ts
    git commit -m "feat(plugin): add NowDivider component"

---

## Task 6: Tab-aware `FilterBar`

**Files:**
- Modify: `obsidian-recap/src/components/FilterBar.ts`

**Step 1:** Replace contents. New shape:
- `FilterState` gains `company: string` field.
- Export `EMPTY_FILTER_STATE = { org: "all", status: "all", company: "all", search: "" }`.
- Constructor: `(parent, tabMode: Tab, orgs: string[], companies: string[], initialState: FilterState, onChange)`.
- `render()` builds the bar based on `tabMode`:
  - Today: search only.
  - Upcoming: org + search.
  - Past: org + company + status + search.
- Public `setTabMode(tab, state, orgs, companies)` re-renders the bar without discarding state.

**Step 2:** `npx tsc -noEmit -skipLibCheck`. Expected: FAIL. `MeetingListView.ts` still calls the old signature. That's Task 7.

**Step 3:** Commit:

    git add obsidian-recap/src/components/FilterBar.ts
    git commit -m "feat(plugin): make FilterBar tab-aware"

---

## Task 7: Wire `MeetingListView`

**Files:**
- Modify: `obsidian-recap/src/views/MeetingListView.ts`

**Step 1:** Update imports at the top of the file:

    import { TabStrip } from "../components/TabStrip";
    import { renderNowDivider } from "../components/NowDivider";
    import { FilterBar, FilterState, EMPTY_FILTER_STATE } from "../components/FilterBar";
    import {
        Tab,
        deriveTodayMeetings,
        deriveUpcomingMeetings,
        derivePastMeetings,
        DecoratedRow,
    } from "../lib/deriveMeetings";

**Step 2:** Replace these class fields:
- Remove: `private filteredMeetings: MeetingData[] = [];`
- Remove: `private filterState: FilterState | null = null;`
- Add:

      private activeTab: Tab = "today";
      private filterStates: Record<Tab, FilterState> = {
          today: { ...EMPTY_FILTER_STATE },
          upcoming: { ...EMPTY_FILTER_STATE },
          past: { ...EMPTY_FILTER_STATE },
      };
      private tabStrip: TabStrip | null = null;
      private filterBar: FilterBar | null = null;
      private filterSlot: HTMLElement | null = null;

**Step 3:** In `loadMeetings`, update the `this.meetings.push({...})` block to include `time: frontmatter.time || ""` and `companies: this.parseParticipants(frontmatter.companies || [])`. The existing `parseParticipants` strips wikilink brackets, which is also what companies need.

Also remove the existing `this.meetings.sort(...)` and `this.filteredMeetings = [...this.meetings]` at the bottom of `loadMeetings` — sorting is now each derive function's job.

**Step 4:** In `onOpen`, replace the FilterBar construction:

Before:

    new FilterBar(container, orgs, (state) => {
        this.applyFilters(state);
    });

After (in this order: filterSlot first, then TabStrip above it so flexbox/CSS lands cleanly):

    this.tabStrip = new TabStrip(container, this.activeTab, (tab) => {
        this.activeTab = tab;
        this.refreshFilterBar();
        this.renderMeetings();
    });
    this.filterSlot = container.createDiv({ cls: "recap-filter-slot" });
    this.refreshFilterBar();

**Step 5:** Add helper methods on the class:

    private refreshFilterBar(): void {
        const orgs = [...new Set(this.meetings.map(m => m.org).filter(Boolean))];
        const companies = [...new Set(
            this.meetings.flatMap(m => m.companies).filter(Boolean),
        )].sort();
        const state = this.filterStates[this.activeTab];
        if (this.filterSlot === null) return;
        this.filterSlot.empty();
        this.filterBar = new FilterBar(
            this.filterSlot, this.activeTab, orgs, companies, state,
            (next) => {
                this.filterStates[this.activeTab] = next;
                this.renderMeetings();
            },
        );
    }

    private openMeeting(path: string): void {
        const file = this.app.vault.getAbstractFileByPath(path);
        if (file instanceof TFile) {
            this.app.workspace.getLeaf(false).openFile(file);
        }
    }

**Step 6:** Replace `renderMeetings` entirely:

    private renderMeetings(): void {
        if (!this.listContainer) return;
        this.listContainer.empty();
        const now = new Date();
        const state = this.filterStates[this.activeTab];

        if (this.activeTab === "today") {
            const { rows, nowDividerIndex } = deriveTodayMeetings(
                this.meetings, now, state,
            );
            this.renderRowsWithDivider(rows, nowDividerIndex, now);
            return;
        }
        const rows = this.activeTab === "upcoming"
            ? deriveUpcomingMeetings(this.meetings, now, state)
            : derivePastMeetings(this.meetings, now, state);
        this.renderRows(rows);
    }

    private renderRows(rows: DecoratedRow[]): void {
        if (!this.listContainer) return;
        if (rows.length === 0) {
            this.listContainer.createDiv({
                text: "No meetings found",
                cls: "recap-empty-state",
            });
            return;
        }
        for (const row of rows) {
            renderMeetingRow(
                this.listContainer, row,
                (path) => this.openMeeting(path),
                { isPast: row.isPast },
            );
        }
    }

    private renderRowsWithDivider(
        rows: DecoratedRow[],
        nowDividerIndex: number | null,
        now: Date,
    ): void {
        if (!this.listContainer) return;
        if (rows.length === 0) {
            this.listContainer.createDiv({
                text: "No meetings today",
                cls: "recap-empty-state",
            });
            return;
        }
        rows.forEach((row, i) => {
            if (nowDividerIndex !== null && i === nowDividerIndex) {
                renderNowDivider(this.listContainer!, now);
            }
            renderMeetingRow(
                this.listContainer!, row,
                (path) => this.openMeeting(path),
                { isPast: row.isPast },
            );
        });
    }

**Step 7:** Delete the old `applyFilters` method entirely, and any leftover `filterState` references.

**Step 8:** `npx tsc -noEmit -skipLibCheck`. Expected: exit 0.

**Step 9:** `npm test`. Expected: all 17 tests still pass.

**Step 10:** `npm run build`. Expected: `main.js` regenerates cleanly.

**Step 11:** Commit:

    git add obsidian-recap/src/views/MeetingListView.ts
    git commit -m "feat(plugin): wire Meetings view to three-tab layout"

---

## Task 8: CSS

**Files:**
- Modify: `obsidian-recap/styles.css`

**Step 1:** Append three CSS blocks to `styles.css`, using Obsidian CSS vars so the look tracks the active theme:

- `.recap-tab-strip` — horizontal flex, bottom 1px border (`--background-modifier-border`).
- `.recap-tab-button` — `--font-ui-small`, muted color, 2px transparent bottom border that becomes `--interactive-accent` on `.is-active`. Hover lifts color to `--text-normal`.
- `.recap-now-divider` — flex with `::before`/`::after` pseudo-elements creating the horizontal rule, `--interactive-accent` color, uppercase, `letter-spacing: 0.1em`.
- `.recap-meeting-row-past` — `opacity: 0.55`; hover lifts to `0.8`.

**Step 2:** Commit:

    git add obsidian-recap/styles.css
    git commit -m "style(plugin): CSS for tabs, Now divider, past-row dim"

---

## Task 9: Deploy + manual smoke

**Step 1:** Build + deploy:

    cd obsidian-recap
    npm run build
    cp main.js /c/Users/tim/recap-test-vault/.obsidian/plugins/recap/main.js
    cp styles.css /c/Users/tim/recap-test-vault/.obsidian/plugins/recap/styles.css

**Step 2:** Reload Obsidian (Ctrl+P → "Reload app without saving").

**Step 3:** Today tab: verify three-tab strip renders above filter bar, "Today" active with accent underline. Meetings list ascending by time. Past rows dimmed if mixed. Now divider appears at the past-to-future boundary only.

**Step 4:** Upcoming tab: filter bar shows `[All orgs] [Search]`. Future meetings, ascending.

**Step 5:** Past tab: filter bar shows `[All orgs] [All companies] [All status] [Search]`. Past meetings descending. Pick a company from the dropdown → results filter. Switch Today → Past → the company filter persists.

**Step 6:** Default check: close panel, re-open → "Today" is active (no persistence).

**Step 7:** If any last-second CSS or wiring fixups were needed, commit them separately with `fix(plugin): ...`.

---

## Rollback

If something breaks and reverting the whole range is safer than fixing forward:

    git revert <first-task-commit>..<last-task-commit>
    cd obsidian-recap && npm run build
    cp main.js /c/Users/tim/recap-test-vault/.obsidian/plugins/recap/main.js

Reload Obsidian. Vault data is untouched — no migration happened.

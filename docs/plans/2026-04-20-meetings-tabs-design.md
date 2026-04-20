# Recap Meetings sidebar — three-tab redesign

**Status:** approved design, ready for implementation plan.
**Date:** 2026-04-20
**Author:** Tim (brainstormed with Claude + Codex)

## Problem

The current Meetings sidebar (`MeetingListView`) is a flat, date-sorted list of every meeting note in the vault. There is no way to tell past meetings from upcoming ones at a glance — the 2026-04-23 meeting sits next to the 2026-04-17 meeting with no visual or structural distinction. When the user opens the panel they are almost always asking "what's next?" and the UI makes them read dates row by row to find out.

## Goals

- Surface the next meeting without scrolling or reading dates.
- Keep historical meetings accessible but out of the way when looking at the present.
- Make "which external company did we meet with last week?" answerable in seconds.

## Non-goals

- Multi-select filters.
- Participant-level filtering (the free-text search already covers it).
- Pagination or time-window limits on the Past tab.
- Persisting the active tab across sessions.

## Design

### Three tabs

| Tab | Contents | Sort |
|---|---|---|
| **Today** | meetings where `frontmatter.date == today's YYYY-MM-DD (local tz)` | ascending by start time |
| **Upcoming** | meetings where `date > today` | ascending by date then start time |
| **Past** | meetings where `date < today` | descending by date then start time |

Default tab is **Today** on every panel open. No persistence — if the user opens the panel at 2pm, Today is almost always the right starting view; remembering "you were on Past last time" is noise, not a feature.

### Today tab — "now" divider + dimming

Today is rendered as a single chronological list, ascending by start time. Each row is either "past" or "current/future":

- **past**: `parsedEnd < now` → rendered at opacity 0.55.
- **current**: `parsedStart <= now < parsedEnd` → rendered at full opacity.
- **future**: `parsedStart > now` → rendered at full opacity.

A "Now · HH:MM" divider row is inserted **before the first non-past row** — i.e. between the past chunk and the current/future chunk. The divider is **omitted** when all of today's meetings fall on the same side (all past, or all current/future), because there is no boundary to mark.

### Malformed / missing time

Meeting notes with a missing or unparsable `time` frontmatter field still need deterministic placement:

- `parseMeetingTime(undefined | "" | "garbage")` returns `{ start: "00:00", end: "23:59", allDay: true }`.
- `allDay` rows are treated as future until local midnight passes (`end < now` is false until 23:59, which only matters at day's end).
- `allDay` rows sort to the **top** of the day (start = 00:00) and are never dimmed within their own day.
- A single `console.warn` is emitted per malformed file per load so the user can fix the note if they care.

This keeps Today's list behavior well-defined even when manual notes have sloppy frontmatter.

### Filters per tab

`FilterBar` becomes tab-aware via a `tabMode` prop. Only the dropdowns relevant to the active tab are rendered:

- **Today**: free-text search only.
- **Upcoming**: org dropdown + free-text search.
- **Past**: org dropdown + **company dropdown** + status dropdown + free-text search.

The company dropdown's options are derived from the union of `frontmatter.companies` wikilinks across all meetings visible in the Past tab (stripped of `[[ ]]`, deduped, alphabetical).

Filter state is stored as `Map<Tab, FilterState>` in the view. Switching Past → Today → Past preserves the company filter the user set.

### Tab UI

Custom `TabStrip` component. Three text buttons in a horizontal row, bottom-aligned with a 1px border separator. The active tab has a 2px underline accent in `--accent-blue`. Hover lifts inactive tabs to full `--text` color. No icons. Matches Obsidian's native tab styling.

### Module layout

```
src/views/MeetingListView.ts        OWNER: vault subscribe, daemon state,
                                     meetings array, activeTab, filter state.
                                     Delegates rendering to derive + renderMeetingList.

src/components/TabStrip.ts          NEW. Three buttons, onChange(tab).
src/components/NowDivider.ts        NEW. Renders "Now · HH:MM" divider row.
src/components/FilterBar.ts         MODIFY. Add tabMode + companies props.
src/components/MeetingRow.ts        MODIFY. Accept optional isPast decorator.

src/lib/deriveMeetings.ts           NEW. Pure functions, no DOM:
                                    deriveTodayMeetings(meetings, now, filter)
                                      → { rows: DecoratedRow[], nowDividerIndex: number | null }
                                    deriveUpcomingMeetings(meetings, now, filter)
                                      → DecoratedRow[]
                                    derivePastMeetings(meetings, now, filter)
                                      → DecoratedRow[]

src/lib/meetingTime.ts              NEW. parseMeetingTime(raw: string | undefined)
                                      → { start: "HH:MM", end: "HH:MM", allDay: boolean }
                                    isSameLocalDay(date1, date2) → boolean
                                    todayIsoDate() → "YYYY-MM-DD"
```

`DecoratedRow = MeetingData & { isPast: boolean }`. Each derive function handles its own filter → sort → decorate pipeline and returns either a plain row array or, for Today, the array plus the index to insert the Now divider (or `null` to omit it).

`renderMeetingList(container, rows, nowDividerIndex)` is a single thin DOM walker. It loops rows, calls `renderMeetingRow(row, row.isPast)`, and inserts `NowDivider` when the loop index equals `nowDividerIndex`. No tab-specific branching in the renderer.

### State flow per render

1. Vault event fires → `MeetingListView.loadMeetings()` rebuilds the `meetings` cache.
2. View calls `renderActiveTab()` which dispatches on `activeTab`.
3. The appropriate derive function runs with `(meetings, now=Date.now(), filterState[activeTab])`.
4. The result is passed to `renderMeetingList`.

Tab switch:
1. `TabStrip.onChange(newTab)` → view updates `activeTab`.
2. View re-reads `filterState[newTab]` and re-renders the `FilterBar` with the new `tabMode`.
3. View calls `renderActiveTab()`.

No new vault subscriptions; no new daemon calls. The existing debounced reload pipeline is untouched.

## Testing

Logic risk lives in `deriveMeetings.ts` and `meetingTime.ts`. Everything else is thin UI glue.

**`meetingTime.ts`** — unit tests for:
- `parseMeetingTime("14:00-15:00")` → `{ start: "14:00", end: "15:00", allDay: false }`
- `parseMeetingTime("")` / `parseMeetingTime(undefined)` / `parseMeetingTime("garbage")` → `{ start: "00:00", end: "23:59", allDay: true }`
- `isSameLocalDay` across DST boundaries and UTC midnight.
- `todayIsoDate()` returns the local calendar date, not UTC.

**`deriveMeetings.ts`** — unit tests for:
- Today: empty / all past / all future / mixed. Verify `nowDividerIndex` is the index of the first non-past row, or `null` when all on one side.
- Today: `allDay` rows sort to the top and are not dimmed.
- Upcoming / Past: correct filtering by date, correct ascending / descending sort.
- Past: company filter restricts results; empty company dropdown selection returns everything.
- Search filter applies uniformly across tabs.

**`MeetingListView` wiring** — one smoke test:
- Stub the three derive functions. Click each tab button. Assert the right derive was called with the current meetings + filter state for that tab.

No tests for `TabStrip`, `NowDivider`, or the FilterBar tab-mode rendering — trivial DOM, not worth the ceremony.

## Migration

No data migration. Vault notes are unchanged. Plugin data.json schema unchanged (we're not persisting `activeTab`). This is a pure UI-layer change inside `obsidian-recap/`.

## Rollout

1. Land the pure libs + tests first.
2. Land `TabStrip` + `NowDivider` + `FilterBar` tab-mode changes.
3. Switch `MeetingListView.renderMeetings` to delegate to derive + renderMeetingList.
4. Manual test in the real vault (Today with past + future meetings, tab switching, filter persistence).
5. `npm run build` + copy to `.obsidian/plugins/recap/` and reload.

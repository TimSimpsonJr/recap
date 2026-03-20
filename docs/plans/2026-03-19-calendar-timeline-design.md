# Calendar Timeline Redesign

**Goal:** Replace the flat event list in the Calendar view with a proper timeline grid (day/week/month), similar to Zoho/Google Calendar.

**Closes:** GitHub issue #9

---

## Views

### Week View (default)

Seven-column CSS Grid with time axis on the left. Sunday through Saturday.

- **Business hours** (~7am–7pm): 60px row height
- **Off-hours** (before 7am, after 7pm): ~20px row height (compressed, not hidden)
- **Current time indicator**: red horizontal line with dot, positioned at the current minute
- **Auto-scroll**: on mount, scroll to current time (or first event of the day)
- **Events**: colored blocks positioned by start/end time, spanning their duration
- **Overlapping events**: split column width equally (side-by-side, like Google Calendar)
- **All-day events**: banner row above the time grid

### Day View

Single-column version of the week grid. Same time axis, compression, and event rendering. Shows one day at a time.

### Month View

Traditional month grid with event chips.

- Each cell shows truncated event names with color-coded left borders
- Blue = meeting, gold = recorded, green = auto-record enabled
- "+N more" overflow link when events exceed cell height
- Today highlighted with gold circle on date number
- Other-month days shown at reduced opacity
- Click a day to switch to day view for that date

### Responsive Behavior

Below 900px (narrow mode), auto-switch to day view. Week and month views are only available above that breakpoint.

---

## Navigation

- **View switcher**: Day / Week / Month toggle buttons in the header
- **Prev/Next arrows**: move by one day, week, or month depending on active view
- **Today button**: jump back to current date
- **Date label**: shows current range (e.g., "Mar 15 - 21, 2026" for week, "March 2026" for month, "Thu, Mar 19" for day)
- **Month view click**: clicking a day switches to day view for that date

---

## Event Interaction

### Popover (click event block)

Floating card near the clicked event with:
- Event title and time range
- Platform badge (Zoom/Meet/Teams/Zoho)
- Auto-record toggle dot (per-event, with "Enable/Disable all in series" for recurring)
- Meeting join link (opens URL)
- Recording link (if matched)
- Participant list (first 4, "+N more")
- "See details" button to open side panel

Dismissed on click outside or Escape.

### Side Panel (from "See details")

Slides in from the right side of the calendar view. Contains:
- Event title, time, platform
- Full participant list with clickable names (existing ParticipantPopover)
- Event description (with looksLikeMeetingInvite filter)
- Full briefing (reuses existing BriefingPanel component)
- Recording link
- Auto-record toggle

Close button or click outside to dismiss.

---

## Components

| Component | Responsibility |
|-----------|---------------|
| `CalendarView.svelte` | Top-level container: header (nav, view switcher, sync status), routes to active view |
| `WeekView.svelte` | 7-column CSS Grid with time axis, event block positioning, overlap layout |
| `DayView.svelte` | Single-column time grid (shares logic with WeekView) |
| `MonthView.svelte` | Month grid with event chips |
| `EventPopover.svelte` | Floating card on event click |
| `EventSidePanel.svelte` | Slide-in detail panel with briefing |
| `TimeGrid.svelte` | Shared time axis + grid rendering for day/week views (optional extraction) |

Existing components reused as-is:
- `BriefingPanel.svelte` — rendered inside EventSidePanel
- `ParticipantPopover.svelte` — triggered from participant names in popover/side panel

---

## Data Flow

No backend changes. All data comes from existing IPC commands:

- `syncCalendar()` — fetches 14 days from Zoho, writes cache
- `getUpcomingMeetings(hoursAhead)` — reads cache (used for initial load)
- `getCalendarMatches(recordingsDir)` — returns `{ eventId: meetingId }` map
- `setAutoRecord(eventId, bool)` / `setSeriesAutoRecord(seriesId, bool)` — toggle persistence
- `generateBriefing(...)` — briefing generation (called by BriefingPanel)

### Calendar Store (new)

Create `src/lib/stores/calendar.ts` to hold event state across tab switches. Currently, Calendar.svelte reloads from cache on every mount, making the app feel sluggish.

The store holds:
- `events: CalendarEvent[]` — full event list from cache
- `matches: Record<string, string>` — event-to-recording map
- `lastSynced: string | null` — cache timestamp
- `loaded: boolean` — whether initial load has completed

Behavior:
- **First load**: fetches from cache via IPC, sets `loaded = true`
- **Subsequent tab switches**: reads from store instantly (no IPC call, no loading state)
- **Background sync**: updates store reactively when sync completes
- **Manual "Sync Now"**: triggers sync, updates store on completion
- **Auto-record toggle**: updates the event in the store directly (optimistic)

View state (current date, active view mode) is local component state, not persisted.

Cache holds 14 days forward. Navigating outside the cache window shows empty cells (past meetings are accessible via the Meetings dashboard).

---

## Preserved Features

All existing Calendar features carry forward:

- Auto-record toggle (per-event and per-series for recurring)
- Briefing panel (topics, action items, context, relationship)
- Calendar-to-recording matching with link
- Participant display with clickable popover cards
- Platform badge detection (Zoom, Meet, Teams, Zoho)
- Meeting join link
- Sync status display + manual "Sync Now" button
- Empty state when Zoho not connected
- Loading and error states
- Window focus auto-sync (debounced 15 min)
- Recurring series indicator with bulk toggle

---

## Visual Style

- Inline styles using existing CSS custom properties (var(--bg), var(--surface), etc.)
- Event block colors: blue (meeting), gold (recorded), green (auto-record)
- Event blocks have 3px left border + translucent background matching their color
- Dark theme throughout (Recap Dark palette)
- No new CSS dependencies or frameworks

---

## Out of Scope

- Drag-to-create/drag-to-resize events (read-only calendar)
- Multi-calendar color coding
- Mini calendar sidebar date picker
- Persisting view preference across sessions
- Expanding cache window for backward navigation

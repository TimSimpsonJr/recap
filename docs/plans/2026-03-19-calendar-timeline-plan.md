# Calendar Timeline Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the flat Calendar event list with a day/week/month timeline grid, with event popover and side panel interactions.

**Architecture:** New calendar store for persistent state across tab switches. CalendarView container routes to WeekView (default), DayView, or MonthView. Event clicks open a popover; "See details" opens a slide-in side panel with full briefing. Existing BriefingPanel and ParticipantPopover components reused as-is.

**Tech Stack:** Svelte 5 (runes), CSS Grid, native JS Date, existing Tauri IPC commands (no backend changes)

**Design doc:** `docs/plans/2026-03-19-calendar-timeline-design.md`

---

### Task 1: Calendar Store

Create `src/lib/stores/calendar.ts` — a Svelte writable store that holds calendar event state across tab switches, eliminating the sluggish reload on every Calendar tab open.

**Files:**
- Create: `src/lib/stores/calendar.ts`

**Context:**
- Follow the pattern in `src/lib/stores/meetings.ts` — writable store with typed state interface
- Use Svelte 5 runes are NOT used in store files (they use `writable()` from `svelte/store`)
- The store wraps existing IPC calls from `src/lib/tauri.ts`: `syncCalendar`, `getUpcomingMeetings`, `getCalendarMatches`, `getCalendarLastSynced`, `setAutoRecord`, `setSeriesAutoRecord`, `fetchCalendarEvents`
- Events are `CalendarEvent[]` from `src/lib/tauri.ts`
- Recording matches are `Record<string, string>` — `{ eventId: meetingId }`
- Settings store provides `recordingsFolder` needed by `getCalendarMatches`

**Implementation:**

```typescript
import { writable, get } from "svelte/store";
import { settings } from "./settings";
import {
  syncCalendar,
  getUpcomingMeetings,
  getCalendarMatches,
  getCalendarLastSynced,
  fetchCalendarEvents,
  setAutoRecord,
  setSeriesAutoRecord,
  type CalendarEvent,
} from "../tauri";

export interface CalendarState {
  events: CalendarEvent[];
  matches: Record<string, string>;
  lastSynced: string | null;
  loaded: boolean;
  loading: boolean;
  syncing: boolean;
  error: string | null;
}

const initial: CalendarState = {
  events: [],
  matches: {},
  lastSynced: null,
  loaded: false,
  loading: false,
  syncing: false,
  error: null,
};

export const calendarStore = writable<CalendarState>({ ...initial });

/** Load events from cache. Only triggers IPC on first call; subsequent calls are no-ops. */
export async function loadCalendarEvents(force = false) {
  const state = get(calendarStore);
  if (state.loaded && !force) return;
  if (state.loading) return;

  calendarStore.update((s) => ({ ...s, loading: true, error: null }));

  try {
    const lastSynced = await getCalendarLastSynced();
    const events = await getUpcomingMeetings(168);

    // Also fetch past events
    const now = new Date();
    const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
    let pastEvents: CalendarEvent[] = [];
    try {
      const allPast = await fetchCalendarEvents(
        thirtyDaysAgo.toISOString(),
        now.toISOString()
      );
      pastEvents = allPast.filter(
        (e) => new Date(e.start).getTime() < now.getTime()
      );
    } catch (err) {
      console.warn("Failed to load past events:", err);
    }

    // Merge upcoming + past, deduplicate by id
    const allEvents = [...events];
    for (const pe of pastEvents) {
      if (!allEvents.some((e) => e.id === pe.id)) {
        allEvents.push(pe);
      }
    }

    // Load recording matches
    let matches: Record<string, string> = {};
    try {
      const s = get(settings);
      if (s.recordingsFolder) {
        matches = await getCalendarMatches(s.recordingsFolder);
      }
    } catch (err) {
      console.warn("Failed to load calendar matches:", err);
    }

    calendarStore.set({
      events: allEvents,
      matches,
      lastSynced,
      loaded: true,
      loading: false,
      syncing: false,
      error: null,
    });
  } catch (err) {
    calendarStore.update((s) => ({
      ...s,
      loading: false,
      error: String(err),
    }));
  }
}

/** Trigger a full sync from Zoho, then reload events. */
export async function syncCalendarEvents() {
  calendarStore.update((s) => ({ ...s, syncing: true }));
  try {
    const cache = await syncCalendar();
    calendarStore.update((s) => ({
      ...s,
      lastSynced: cache.last_synced,
      error: null,
    }));
  } catch (err) {
    calendarStore.update((s) => ({
      ...s,
      syncing: false,
      error: String(err),
    }));
    console.error("Calendar sync failed:", err);
  }
  // Reload events from cache after sync
  await loadCalendarEvents(true);
}

/** Toggle auto-record for a single event. Optimistic update. */
export async function toggleEventAutoRecord(eventId: string) {
  const state = get(calendarStore);
  const event = state.events.find((e) => e.id === eventId);
  if (!event) return;

  const newValue = !event.auto_record;

  // Optimistic update
  calendarStore.update((s) => ({
    ...s,
    events: s.events.map((e) =>
      e.id === eventId ? { ...e, auto_record: newValue } : e
    ),
  }));

  try {
    await setAutoRecord(eventId, newValue);
  } catch (err) {
    // Revert on failure
    calendarStore.update((s) => ({
      ...s,
      events: s.events.map((e) =>
        e.id === eventId ? { ...e, auto_record: !newValue } : e
      ),
    }));
    console.error("Failed to toggle auto-record:", err);
  }
}

/** Toggle auto-record for all events in a recurring series. Optimistic update. */
export async function toggleSeriesAutoRecord(seriesId: string) {
  const state = get(calendarStore);
  const sample = state.events.find((e) => e.recurring_series_id === seriesId);
  if (!sample) return;

  const newValue = !sample.auto_record;

  // Optimistic update
  calendarStore.update((s) => ({
    ...s,
    events: s.events.map((e) =>
      e.recurring_series_id === seriesId
        ? { ...e, auto_record: newValue }
        : e
    ),
  }));

  try {
    await setSeriesAutoRecord(seriesId, newValue);
  } catch (err) {
    // Revert on failure
    calendarStore.update((s) => ({
      ...s,
      events: s.events.map((e) =>
        e.recurring_series_id === seriesId
          ? { ...e, auto_record: !newValue }
          : e
      ),
    }));
    console.error("Failed to toggle series auto-record:", err);
  }
}
```

**Commit:** `feat: add calendar store for persistent event state`

---

### Task 2: Date Utility Helpers

Create `src/lib/calendar-utils.ts` — pure functions for date math, time formatting, and event layout calculations used by all three views.

**Files:**
- Create: `src/lib/calendar-utils.ts`

**Context:**
- No external dependencies — native JS Date only
- These functions are used by WeekView, DayView, and MonthView
- Business hours: 7am–7pm (60px row height), off-hours: 20px row height
- `CalendarEvent` has `start` and `end` as ISO 8601 strings

**Implementation:**

```typescript
import type { CalendarEvent } from "./tauri";

// ─── Date helpers ───────────────────────────────────────────────

/** Get the Sunday that starts the week containing `date`. */
export function weekStart(date: Date): Date {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - d.getDay());
  return d;
}

/** Get the Saturday that ends the week containing `date`. */
export function weekEnd(date: Date): Date {
  const d = weekStart(date);
  d.setDate(d.getDate() + 6);
  d.setHours(23, 59, 59, 999);
  return d;
}

/** Get the first day of the month containing `date`. */
export function monthStart(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

/** Get the last day of the month containing `date`. */
export function monthEnd(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth() + 1, 0, 23, 59, 59, 999);
}

/** Add N days to a date. */
export function addDays(date: Date, n: number): Date {
  const d = new Date(date);
  d.setDate(d.getDate() + n);
  return d;
}

/** Check if two dates are the same calendar day. */
export function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

/** Check if a date is today. */
export function isToday(date: Date): boolean {
  return isSameDay(date, new Date());
}

/** Format date for header: "Thu, Mar 19" */
export function formatDayHeader(date: Date): string {
  return date.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

/** Format date range for week header: "Mar 15 - 21, 2026" */
export function formatWeekRange(start: Date): string {
  const end = addDays(start, 6);
  const sameMonth = start.getMonth() === end.getMonth();
  if (sameMonth) {
    return `${start.toLocaleDateString(undefined, { month: "short" })} ${start.getDate()} - ${end.getDate()}, ${end.getFullYear()}`;
  }
  return `${start.toLocaleDateString(undefined, { month: "short" })} ${start.getDate()} - ${end.toLocaleDateString(undefined, { month: "short" })} ${end.getDate()}, ${end.getFullYear()}`;
}

/** Format month header: "March 2026" */
export function formatMonthHeader(date: Date): string {
  return date.toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
}

/** Format time: "2:30 PM" */
export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Format time range: "2:30 PM – 3:30 PM" */
export function formatTimeRange(start: string, end: string): string {
  return `${formatTime(start)} – ${formatTime(end)}`;
}

/** Relative time: "5 min ago", "2h ago" */
export function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

/** Platform label: "zoom" → "Zoom" */
export function platformLabel(platform: string): string {
  switch (platform) {
    case "zoom": return "Zoom";
    case "google_meet": return "Meet";
    case "teams": return "Teams";
    case "zoho_meet": return "Zoho";
    default: return platform;
  }
}

// ─── Time grid layout ───────────────────────────────────────────

/** Business hours: 7am to 7pm (0-indexed). */
export const BUSINESS_START = 7;
export const BUSINESS_END = 19;

/** Row heights in pixels. */
export const BUSINESS_HOUR_HEIGHT = 60;
export const OFF_HOUR_HEIGHT = 20;

/** Get the Y offset in pixels for a given hour (0-23). */
export function hourToY(hour: number): number {
  let y = 0;
  for (let h = 0; h < hour; h++) {
    y += h >= BUSINESS_START && h < BUSINESS_END
      ? BUSINESS_HOUR_HEIGHT
      : OFF_HOUR_HEIGHT;
  }
  return y;
}

/** Get the Y offset for a specific time (hour + fractional minutes). */
export function timeToY(date: Date): number {
  const hour = date.getHours();
  const minuteFraction = date.getMinutes() / 60;
  const baseY = hourToY(hour);
  const rowHeight =
    hour >= BUSINESS_START && hour < BUSINESS_END
      ? BUSINESS_HOUR_HEIGHT
      : OFF_HOUR_HEIGHT;
  return baseY + minuteFraction * rowHeight;
}

/** Total height of the 24-hour grid. */
export function totalGridHeight(): number {
  return hourToY(24);
}

/** Get the row height for a given hour. */
export function hourHeight(hour: number): number {
  return hour >= BUSINESS_START && hour < BUSINESS_END
    ? BUSINESS_HOUR_HEIGHT
    : OFF_HOUR_HEIGHT;
}

// ─── Event positioning ──────────────────────────────────────────

export interface PositionedEvent {
  event: CalendarEvent;
  top: number;
  height: number;
  left: number;       // 0-1 fraction of column width
  width: number;      // 0-1 fraction of column width
  column: number;     // which overlap column (0-indexed)
  totalColumns: number;
}

/** Check if an event spans all day (or is missing end time). */
export function isAllDay(event: CalendarEvent): boolean {
  const start = new Date(event.start);
  const end = new Date(event.end);
  return (
    start.getHours() === 0 &&
    start.getMinutes() === 0 &&
    end.getHours() === 0 &&
    end.getMinutes() === 0 &&
    end.getTime() - start.getTime() >= 24 * 60 * 60 * 1000
  );
}

/**
 * Position events within a single day column.
 * Returns positioned events with top/height/left/width for rendering.
 * Handles overlapping events by splitting column width equally.
 */
export function layoutEventsForDay(
  events: CalendarEvent[],
  day: Date
): PositionedEvent[] {
  // Filter to timed events on this day (exclude all-day)
  const timed = events.filter((e) => {
    if (isAllDay(e)) return false;
    const start = new Date(e.start);
    return isSameDay(start, day);
  });

  if (timed.length === 0) return [];

  // Sort by start time, then by duration (longer first)
  const sorted = [...timed].sort((a, b) => {
    const diff = new Date(a.start).getTime() - new Date(b.start).getTime();
    if (diff !== 0) return diff;
    // Longer events first
    const durA =
      new Date(a.end).getTime() - new Date(a.start).getTime();
    const durB =
      new Date(b.end).getTime() - new Date(b.start).getTime();
    return durB - durA;
  });

  // Assign overlap columns using a greedy algorithm
  const columns: { end: number; events: CalendarEvent[] }[] = [];

  for (const event of sorted) {
    const startTime = new Date(event.start).getTime();
    // Find first column where this event doesn't overlap
    let placed = false;
    for (const col of columns) {
      if (startTime >= col.end) {
        col.end = new Date(event.end).getTime();
        col.events.push(event);
        placed = true;
        break;
      }
    }
    if (!placed) {
      columns.push({
        end: new Date(event.end).getTime(),
        events: [event],
      });
    }
  }

  // Build column index lookup
  const eventColumn = new Map<string, number>();
  for (let i = 0; i < columns.length; i++) {
    for (const event of columns[i].events) {
      eventColumn.set(event.id, i);
    }
  }

  // For each event, find how many columns overlap with it at its peak
  // For simplicity, use the total column count at the event's start time
  const totalCols = columns.length;

  return sorted.map((event) => {
    const start = new Date(event.start);
    const end = new Date(event.end);
    const top = timeToY(start);
    const bottom = timeToY(end);
    const col = eventColumn.get(event.id) ?? 0;

    return {
      event,
      top,
      height: Math.max(bottom - top, 20), // minimum 20px
      left: col / totalCols,
      width: 1 / totalCols,
      column: col,
      totalColumns: totalCols,
    };
  });
}

/**
 * Get all-day events for a given day.
 */
export function getAllDayEvents(
  events: CalendarEvent[],
  day: Date
): CalendarEvent[] {
  return events.filter((e) => {
    if (!isAllDay(e)) return false;
    const start = new Date(e.start);
    const end = new Date(e.end);
    // All-day event spans this day
    return day.getTime() >= start.getTime() && day.getTime() < end.getTime();
  });
}

/**
 * Get events for a specific day (for month view chips).
 */
export function getEventsForDay(
  events: CalendarEvent[],
  day: Date
): CalendarEvent[] {
  return events.filter((e) => {
    const start = new Date(e.start);
    return isSameDay(start, day);
  });
}

/**
 * Get the color class for an event based on its status.
 * Returns "gold" (recorded), "green" (auto-record), or "blue" (default meeting).
 */
export function eventColor(
  event: CalendarEvent,
  matches: Record<string, string>
): "blue" | "gold" | "green" {
  if (matches[event.id]) return "gold";
  if (event.auto_record) return "green";
  return "blue";
}

/**
 * CSS color values for event block rendering.
 */
export const EVENT_COLORS = {
  blue: {
    bg: "rgba(77, 156, 245, 0.2)",
    border: "var(--blue)",
    text: "var(--blue)",
  },
  gold: {
    bg: "rgba(196, 168, 77, 0.2)",
    border: "var(--gold)",
    text: "var(--gold)",
  },
  green: {
    bg: "rgba(75, 170, 85, 0.15)",
    border: "var(--green)",
    text: "var(--green)",
  },
} as const;
```

**Commit:** `feat: add calendar date utils and event layout helpers`

---

### Task 3: CalendarView Container

Replace `src/routes/Calendar.svelte` with the new `CalendarView` container that holds the header (navigation, view switcher, sync status) and routes to the active view. This task creates the shell with the header only — views are plugged in by subsequent tasks.

**Files:**
- Modify: `src/routes/Calendar.svelte` (full rewrite)

**Context:**
- This replaces the entire current Calendar.svelte (676 lines)
- Uses the new `calendarStore` from Task 1
- Uses helpers from `calendar-utils.ts` from Task 2
- View state (`currentDate`, `viewMode`) is local component state
- Must preserve: Zoho not-connected empty state, loading state, error banner, sync button
- Narrow mode (<900px) forces day view
- The `credentials` store from `src/lib/stores/credentials.ts` provides `zoho.status`
- Navigation: Today button, prev/next arrows, date range label, Day/Week/Month switcher
- Participant popover state stays here (rendered outside the views)

**Implementation:**

```svelte
<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { get } from "svelte/store";
  import { credentials } from "../lib/stores/credentials";
  import {
    calendarStore,
    loadCalendarEvents,
    syncCalendarEvents,
  } from "../lib/stores/calendar";
  import {
    weekStart,
    addDays,
    monthStart,
    formatDayHeader,
    formatWeekRange,
    formatMonthHeader,
    relativeTime,
  } from "../lib/calendar-utils";
  import ParticipantPopover from "../lib/components/ParticipantPopover.svelte";
  import WeekView from "../lib/components/calendar/WeekView.svelte";
  import DayView from "../lib/components/calendar/DayView.svelte";
  import MonthView from "../lib/components/calendar/MonthView.svelte";

  type ViewMode = "day" | "week" | "month";

  let viewMode: ViewMode = $state("week");
  let currentDate = $state(new Date());
  let windowWidth = $state(window.innerWidth);
  let narrow = $derived(windowWidth < 900);

  // Force day view on narrow screens
  let effectiveView = $derived(narrow ? "day" : viewMode);

  let zohoConnected = $state(false);

  let popoverParticipant: {
    name: string;
    email: string | null;
    rect: DOMRect;
  } | null = $state(null);

  function handleResize() {
    windowWidth = window.innerWidth;
  }

  function openPopover(name: string, email: string | null, rect: DOMRect) {
    popoverParticipant = { name, email, rect };
  }

  function closePopover() {
    popoverParticipant = null;
  }

  // Navigation
  function goToday() {
    currentDate = new Date();
  }

  function goPrev() {
    switch (effectiveView) {
      case "day":
        currentDate = addDays(currentDate, -1);
        break;
      case "week":
        currentDate = addDays(currentDate, -7);
        break;
      case "month":
        currentDate = new Date(
          currentDate.getFullYear(),
          currentDate.getMonth() - 1,
          1
        );
        break;
    }
  }

  function goNext() {
    switch (effectiveView) {
      case "day":
        currentDate = addDays(currentDate, 1);
        break;
      case "week":
        currentDate = addDays(currentDate, 7);
        break;
      case "month":
        currentDate = new Date(
          currentDate.getFullYear(),
          currentDate.getMonth() + 1,
          1
        );
        break;
    }
  }

  function switchToDay(date: Date) {
    currentDate = date;
    viewMode = "day";
  }

  let dateLabel = $derived.by(() => {
    switch (effectiveView) {
      case "day":
        return formatDayHeader(currentDate);
      case "week":
        return formatWeekRange(weekStart(currentDate));
      case "month":
        return formatMonthHeader(currentDate);
    }
  });

  onDestroy(() => {
    window.removeEventListener("resize", handleResize);
  });

  onMount(async () => {
    window.addEventListener("resize", handleResize);

    const unsub = credentials.subscribe((creds) => {
      zohoConnected = creds.zoho.status === "connected";
    });

    // Load events (no-op if already loaded)
    await loadCalendarEvents();

    // Background sync if connected and cache is stale
    if (zohoConnected) {
      const state = get(calendarStore);
      const needsSync =
        !state.lastSynced ||
        Date.now() - new Date(state.lastSynced).getTime() > 15 * 60 * 1000;
      if (needsSync) {
        syncCalendarEvents();
      }
    }

    return () => unsub();
  });
</script>

<div
  class="h-full overflow-y-auto"
  style="font-family: 'DM Sans', sans-serif; padding: {narrow
    ? '24px 16px'
    : '32px 40px'}; overflow-x: hidden; display: flex; flex-direction: column;"
>
  <!-- Header -->
  <div
    style="display: flex; align-items: center; gap: 12px; margin-bottom: 20px; flex-shrink: 0;"
  >
    <!-- Today button -->
    <button
      onclick={goToday}
      style="
        padding: 4px 14px;
        font-size: 13px;
        font-family: 'DM Sans', sans-serif;
        border-radius: 4px;
        border: 1px solid var(--border);
        background: var(--surface);
        color: var(--text-secondary);
        cursor: pointer;
      "
    >Today</button>

    <!-- Prev/Next -->
    <div style="display: flex; gap: 2px;">
      <button
        onclick={goPrev}
        style="
          width: 28px;
          height: 28px;
          border-radius: 4px;
          border: 1px solid var(--border);
          background: var(--surface);
          color: var(--text-muted);
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 14px;
        "
      >&lsaquo;</button>
      <button
        onclick={goNext}
        style="
          width: 28px;
          height: 28px;
          border-radius: 4px;
          border: 1px solid var(--border);
          background: var(--surface);
          color: var(--text-muted);
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 14px;
        "
      >&rsaquo;</button>
    </div>

    <!-- Date label -->
    <span style="font-size: 16px; font-weight: 600; color: var(--text);">
      {dateLabel}
    </span>

    <!-- Sync status -->
    {#if $calendarStore.lastSynced}
      <span style="font-size: 12px; color: var(--text-faint);">
        Synced {relativeTime($calendarStore.lastSynced)}
      </span>
    {/if}

    <!-- Right side: sync + view switcher -->
    <div style="margin-left: auto; display: flex; align-items: center; gap: 10px;">
      <button
        onclick={syncCalendarEvents}
        disabled={$calendarStore.syncing}
        style="
          padding: 4px 14px;
          font-size: 12px;
          font-family: 'DM Sans', sans-serif;
          border-radius: 4px;
          border: 1px solid var(--border);
          background: var(--surface);
          color: var(--text);
          cursor: {$calendarStore.syncing ? 'wait' : 'pointer'};
          opacity: {$calendarStore.syncing ? 0.6 : 1};
        "
      >
        {$calendarStore.syncing ? "Syncing..." : "Sync Now"}
      </button>

      {#if !narrow}
        <div
          style="display: flex; border: 1px solid var(--border); border-radius: 4px; overflow: hidden;"
        >
          {#each ["day", "week", "month"] as mode}
            <button
              onclick={() => (viewMode = mode as ViewMode)}
              style="
                background: {viewMode === mode ? 'var(--raised)' : 'var(--surface)'};
                border: none;
                border-right: {mode !== 'month' ? '1px solid var(--border)' : 'none'};
                color: {viewMode === mode ? 'var(--gold)' : 'var(--text-muted)'};
                padding: 4px 14px;
                font-size: 12px;
                font-family: 'DM Sans', sans-serif;
                cursor: pointer;
                text-transform: capitalize;
              "
            >{mode}</button>
          {/each}
        </div>
      {/if}
    </div>
  </div>

  <!-- Error banner -->
  {#if $calendarStore.error}
    <div
      style="
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 10px 16px;
        margin-bottom: 16px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        flex-shrink: 0;
      "
    >
      <div
        style="font-size: 13px; color: var(--text-muted); min-width: 0; overflow: hidden; text-overflow: ellipsis;"
      >
        <span style="color: var(--red); font-weight: 500;">Sync error:</span>
        {$calendarStore.error}
      </div>
      <button
        onclick={() => calendarStore.update((s) => ({ ...s, error: null }))}
        style="background:none;border:none;color:var(--text-faint);cursor:pointer;font-size:16px;padding:0 4px;flex-shrink:0;"
        aria-label="Dismiss"
      >&times;</button>
    </div>
  {/if}

  <!-- Content -->
  {#if !zohoConnected}
    <div
      style="display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 80px 20px; text-align: center;"
    >
      <div style="font-size: 15px; color: var(--text-muted); margin-bottom: 12px;">
        No calendar connected
      </div>
      <a
        href="#settings"
        style="font-size: 14px; color: var(--gold); text-decoration: none;"
      >Connect Zoho Calendar in Settings</a>
    </div>
  {:else if $calendarStore.loading && !$calendarStore.loaded}
    <div
      style="color: var(--text-faint); font-size: 14px; padding: 40px 0; text-align: center;"
    >
      Loading calendar events...
    </div>
  {:else if effectiveView === "week"}
    <WeekView
      events={$calendarStore.events}
      matches={$calendarStore.matches}
      {currentDate}
      onEventPopover={(event, rect) => {/* Task 6 */}}
      onOpenPopover={openPopover}
    />
  {:else if effectiveView === "day"}
    <DayView
      events={$calendarStore.events}
      matches={$calendarStore.matches}
      {currentDate}
      onEventPopover={(event, rect) => {/* Task 6 */}}
      onOpenPopover={openPopover}
    />
  {:else if effectiveView === "month"}
    <MonthView
      events={$calendarStore.events}
      matches={$calendarStore.matches}
      {currentDate}
      onDayClick={switchToDay}
    />
  {/if}
</div>

{#if popoverParticipant}
  <ParticipantPopover
    name={popoverParticipant.name}
    email={popoverParticipant.email}
    anchorRect={popoverParticipant.rect}
    onclose={closePopover}
  />
{/if}
```

Note: The `onEventPopover` callbacks are placeholders — Task 6 (EventPopover) will wire them up. For now, use no-op functions so the component compiles.

**Commit:** `feat: replace Calendar with CalendarView container`

---

### Task 4: WeekView Component

Create `src/lib/components/calendar/WeekView.svelte` — the primary view showing a 7-column CSS Grid with time axis, event blocks, and current time indicator.

**Files:**
- Create: `src/lib/components/calendar/WeekView.svelte`

**Context:**
- Uses `layoutEventsForDay`, `hourToY`, `timeToY`, `totalGridHeight`, `hourHeight`, `weekStart`, `addDays`, `isSameDay`, `isToday`, `eventColor`, `EVENT_COLORS`, `formatTime`, `getAllDayEvents` from `calendar-utils.ts`
- Events are positioned absolutely within each day column using the layout helpers
- Off-hours are compressed (20px vs 60px)
- Current time indicator: red line with dot, updates every minute
- All-day events banner above the grid
- Auto-scroll to current time on mount
- Each event block is clickable → calls `onEventPopover(event, rect)`
- Props: `events`, `matches`, `currentDate`, `onEventPopover`, `onOpenPopover`
- The event blocks show: title (truncated), time range. Color based on `eventColor()`.

**Key rendering approach:**
- Outer container: `position: relative; overflow-y: auto;` (scrollable)
- Time labels column: fixed 60px width
- Day columns: `flex: 1` or CSS Grid `1fr` each
- Each day column is `position: relative` — event blocks are `position: absolute` with `top`, `height`, `left`, `width` from `PositionedEvent`
- Time row backgrounds alternate with subtle border at each hour

The component should be approximately 200-250 lines. Focus on the grid structure, event block rendering, and current time indicator. Keep the all-day banner simple (just event titles in chips).

**Commit:** `feat: add WeekView calendar component`

---

### Task 5: DayView Component

Create `src/lib/components/calendar/DayView.svelte` — single-column version of the week time grid.

**Files:**
- Create: `src/lib/components/calendar/DayView.svelte`

**Context:**
- Same time axis and event rendering as WeekView, but single column
- Reuses same layout helpers from `calendar-utils.ts`
- Same props interface as WeekView
- Shows date header: "Thursday, March 19, 2026"
- Wider event blocks since there's only one column
- Same current time indicator, auto-scroll, all-day banner
- Should be simpler than WeekView (~120-150 lines) since there's no multi-column grid

**Commit:** `feat: add DayView calendar component`

---

### Task 6: MonthView Component

Create `src/lib/components/calendar/MonthView.svelte` — traditional month grid with event chips.

**Files:**
- Create: `src/lib/components/calendar/MonthView.svelte`

**Context:**
- Uses `monthStart`, `monthEnd`, `weekStart`, `addDays`, `isSameDay`, `isToday`, `getEventsForDay`, `eventColor`, `EVENT_COLORS`, `formatTime` from `calendar-utils.ts`
- 7-column CSS Grid, rows for each week
- Weekday header row (Sun–Sat)
- Each cell shows: day number, up to 3 event chips, "+N more" if overflow
- Event chips: truncated title, color-coded left border matching `eventColor()`
- Today: gold circle behind date number
- Other-month days: reduced opacity
- Click a day → calls `onDayClick(date)` (parent switches to day view)
- Click an event chip → calls `onEventPopover(event, rect)` (opens popover from parent)
- Props: `events`, `matches`, `currentDate`, `onDayClick`, `onEventPopover` (optional, for future)

**Commit:** `feat: add MonthView calendar component`

---

### Task 7: EventPopover Component

Create `src/lib/components/calendar/EventPopover.svelte` — floating card shown when clicking an event block in any view.

**Files:**
- Create: `src/lib/components/calendar/EventPopover.svelte`

**Context:**
- Similar pattern to existing `ParticipantPopover.svelte` — positioned near anchor, dismissed on click outside or Escape
- Shows: title, time range, platform badge, auto-record toggle, meeting join link (↗), recording link, participant list (first 4 + overflow), recurring series toggle, "See details →" button
- Uses `toggleEventAutoRecord`, `toggleSeriesAutoRecord` from calendar store
- Uses `platformLabel`, `formatTimeRange` from calendar-utils
- Uses `openUrl` from `@tauri-apps/plugin-opener` for meeting links
- "See details →" calls `onOpenSidePanel()` prop
- Participant names are clickable → calls `onOpenPopover(name, email, rect)` prop
- Positioning: below the clicked element, flip above if near viewport bottom (same logic as ParticipantPopover)
- Props: `event`, `matchedId`, `anchorRect`, `onClose`, `onOpenSidePanel`, `onOpenPopover`

**Commit:** `feat: add EventPopover for calendar event cards`

---

### Task 8: EventSidePanel Component

Create `src/lib/components/calendar/EventSidePanel.svelte` — slide-in panel from the right with full event details and briefing.

**Files:**
- Create: `src/lib/components/calendar/EventSidePanel.svelte`

**Context:**
- Slides in from right edge, ~400px wide, full height
- Semi-transparent backdrop (click to close)
- Close button (×) in top-right
- Content: event title, time range + date, platform badge, auto-record toggle, meeting join link, recording link, full participant list (all participants, each clickable → ParticipantPopover), event description (with `looksLikeMeetingInvite` filter from BriefingPanel), BriefingPanel component
- Props: `event`, `matchedId`, `onClose`, `onOpenPopover`
- Uses existing `BriefingPanel.svelte` — pass `eventId`, `title`, `participants`, `time`, `eventDescription`
- Uses `looksLikeMeetingInvite` logic — extract from BriefingPanel into calendar-utils or duplicate (it's 10 lines)
- Transition: slide in from right (CSS transform or Svelte transition)

**Commit:** `feat: add EventSidePanel with briefing integration`

---

### Task 9: Wire Up Event Interaction

Connect the popover and side panel to the CalendarView container and all three views.

**Files:**
- Modify: `src/routes/Calendar.svelte`

**Context:**
- Add state: `popoverEvent`, `sidePanelEvent` (which event is shown in each)
- Wire `onEventPopover` in WeekView/DayView/MonthView to set `popoverEvent`
- Wire EventPopover's `onOpenSidePanel` to set `sidePanelEvent` and close popover
- Wire EventSidePanel's `onClose` to clear `sidePanelEvent`
- Render EventPopover and EventSidePanel at the bottom of Calendar.svelte (outside views, so they overlay)
- Close popover when clicking a different event (replaces current popover)
- Close popover when navigating to a different date/view

**Commit:** `feat: wire event popover and side panel to calendar views`

---

### Task 10: Extract looksLikeMeetingInvite

Move the `looksLikeMeetingInvite` function from `BriefingPanel.svelte` into `calendar-utils.ts` so it can be used by both BriefingPanel and EventSidePanel without duplication.

**Files:**
- Modify: `src/lib/calendar-utils.ts` (add function)
- Modify: `src/lib/components/BriefingPanel.svelte` (import instead of inline)
- Use in: `src/lib/components/calendar/EventSidePanel.svelte` (import)

**Implementation:**

In `calendar-utils.ts`, add:
```typescript
/** Check if an event description looks like meeting invite boilerplate. */
export function looksLikeMeetingInvite(desc: string): boolean {
  const lower = desc.toLowerCase();
  const signals = [
    "join zoom", "zoom.us/j/", "meeting id:", "dial by your location",
    "join microsoft teams", "teams.microsoft.com", "click here to join",
    "meet.google.com/", "join with google meet",
    "zoho.com/meeting", "join meeting",
    "passcode:", "one tap mobile", "dial-in", "phone number",
  ];
  const hits = signals.filter((s) => lower.includes(s)).length;
  return hits >= 2;
}
```

In `BriefingPanel.svelte`, replace the inline function with:
```typescript
import { looksLikeMeetingInvite } from "../calendar-utils";
```

**Commit:** `refactor: extract looksLikeMeetingInvite to calendar-utils`

---

### Task 11: Cleanup and Polish

Final cleanup pass:
- Delete any dead code from old Calendar.svelte that wasn't carried forward
- Ensure the `@keyframes spin` for loading spinner is available (currently in BriefingPanel's `<style>` block — may need to add to CalendarView if used)
- Verify all empty states work: Zoho not connected, no events, loading
- Verify narrow mode auto-switches to day view
- Verify the mockup HTML files in `mockups/` are not accidentally committed (add to `.gitignore` or delete)

**Files:**
- Modify: `src/routes/Calendar.svelte` (any remaining cleanup)
- Modify: `.gitignore` (add `mockups/` if needed)

**Commit:** `chore: clean up calendar redesign, ignore mockups`

---

### Task 12: Manual Testing Checklist

No automated tests (frontend has no test framework). Verify manually:

- [ ] Week view renders 7 columns with time axis
- [ ] Events appear as colored blocks at correct times
- [ ] Overlapping events split column width
- [ ] Off-hours are compressed (smaller rows)
- [ ] Current time indicator shows and updates
- [ ] Auto-scroll to current time on mount
- [ ] All-day events show in banner above grid
- [ ] Day view shows single column
- [ ] Month view shows event chips with correct colors
- [ ] Month view "+N more" appears for busy days
- [ ] Click event → popover appears with correct info
- [ ] Popover: auto-record toggle works
- [ ] Popover: "See details →" opens side panel
- [ ] Side panel: shows full briefing (BriefingPanel)
- [ ] Side panel: participant names clickable → ParticipantPopover
- [ ] Side panel: event description filtered (no invite boilerplate)
- [ ] Navigation: prev/next moves by correct period
- [ ] Navigation: Today button jumps to current date
- [ ] View switcher: Day/Week/Month works
- [ ] Narrow mode (<900px): forces day view, hides switcher
- [ ] Tab switching: events don't reload (instant)
- [ ] Sync Now button works
- [ ] Error banner shows and dismisses
- [ ] Zoho not connected: shows empty state with Settings link
- [ ] Recording match links work (gold link icon → meeting detail)
- [ ] Meeting join links work (↗ opens URL)

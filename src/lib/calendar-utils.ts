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

/** Row height in pixels (uniform for all hours). */
export const HOUR_HEIGHT = 60;

/** Check if an hour falls within business hours. */
export function isBusinessHour(hour: number): boolean {
  return hour >= BUSINESS_START && hour < BUSINESS_END;
}

/** Get the Y offset in pixels for a given hour (0-23). */
export function hourToY(hour: number): number {
  return hour * HOUR_HEIGHT;
}

/** Get the Y offset for a specific time (hour + fractional minutes). */
export function timeToY(date: Date): number {
  const hour = date.getHours();
  const minuteFraction = date.getMinutes() / 60;
  return (hour + minuteFraction) * HOUR_HEIGHT;
}

/** Total height of the 24-hour grid. */
export function totalGridHeight(): number {
  return 24 * HOUR_HEIGHT;
}

/** Get the row height for a given hour. */
export function hourHeight(_hour: number): number {
  return HOUR_HEIGHT;
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

// ─── Description helpers ─────────────────────────────────────────

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

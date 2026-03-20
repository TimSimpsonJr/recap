import { writable, get } from "svelte/store";
import { listen } from "@tauri-apps/api/event";
import { settings } from "./settings";
import {
  syncCalendar,
  getUpcomingMeetings,
  getAllCachedEvents,
  getCalendarMatches,
  getCalendarLastSynced,
  fetchCalendarEvents,
  setAutoRecord,
  setSeriesAutoRecord,
  type CalendarEvent,
} from "../tauri";

// When background enrichment completes, patch participant data from the
// enriched cache into the current store (both past and upcoming events).
listen("calendar-enriched", async () => {
  try {
    const enriched = await getAllCachedEvents();
    const enrichedMap = new Map(enriched.map((e) => [e.id, e]));
    calendarStore.update((s) => ({
      ...s,
      events: s.events.map((e) => {
        const updated = enrichedMap.get(e.id);
        if (updated && updated.participants.length > e.participants.length) {
          return { ...e, participants: updated.participants };
        }
        return e;
      }),
    }));
  } catch (err) {
    console.warn("Failed to apply enriched participants:", err);
  }
});

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

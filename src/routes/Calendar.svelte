<script lang="ts">
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import { settings } from "../lib/stores/settings";
  import { credentials } from "../lib/stores/credentials";
  import {
    syncCalendar,
    getUpcomingMeetings,
    getCalendarMatches,
    getCalendarLastSynced,
    type CalendarEvent,
    type CalendarCache,
  } from "../lib/tauri";
  import BriefingPanel from "../lib/components/BriefingPanel.svelte";

  let upcoming: CalendarEvent[] = $state([]);
  let past: CalendarEvent[] = $state([]);
  let matches: Record<string, string> = $state({});
  let lastSynced: string | null = $state(null);
  let loading = $state(true);
  let syncing = $state(false);
  let error: string | null = $state(null);

  let zohoConnected = $state(false);
  let expandedEventId: string | null = $state(null);

  function toggleBriefing(eventId: string) {
    expandedEventId = expandedEventId === eventId ? null : eventId;
  }

  // Relative time formatting
  function relativeTime(iso: string): string {
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60_000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins} min ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  }

  function formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  }

  function formatTime(iso: string): string {
    return new Date(iso).toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    });
  }

  function formatTimeRange(start: string, end: string): string {
    return `${formatTime(start)} – ${formatTime(end)}`;
  }

  async function doSync() {
    syncing = true;
    try {
      const cache: CalendarCache = await syncCalendar();
      lastSynced = cache.last_synced;
      await loadEvents();
    } catch (err) {
      error = String(err);
      console.error("Calendar sync failed:", err);
    } finally {
      syncing = false;
    }
  }

  async function loadEvents() {
    const s = get(settings);
    try {
      // Upcoming: next 7 days
      upcoming = await getUpcomingMeetings(168);

      // Past: last 30 days — fetch via getUpcomingMeetings with negative trick won't work,
      // so we use fetchCalendarEvents for the past range
      const { fetchCalendarEvents } = await import("../lib/tauri");
      const now = new Date();
      const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
      const allPast = await fetchCalendarEvents(
        thirtyDaysAgo.toISOString(),
        now.toISOString()
      );
      // Filter to only past events and sort newest first
      past = allPast
        .filter((e) => new Date(e.start).getTime() < now.getTime())
        .sort((a, b) => new Date(b.start).getTime() - new Date(a.start).getTime());

      // Get recording matches
      if (s.recordingsFolder) {
        matches = await getCalendarMatches(s.recordingsFolder);
      }
    } catch (err) {
      error = String(err);
      console.error("Failed to load calendar events:", err);
    }
  }

  onMount(async () => {
    // Subscribe to credentials to track Zoho status reactively.
    // Svelte store .subscribe() calls the callback synchronously with the
    // current value, so zohoConnected is set before the if-check below.
    const unsub = credentials.subscribe((creds) => {
      zohoConnected = creds.zoho.status === "connected";
    });

    if (!zohoConnected) {
      loading = false;
      return;
    }

    try {
      // Read cached sync timestamp to decide whether to sync or just load
      lastSynced = await getCalendarLastSynced();

      if (lastSynced) {
        const diff = Date.now() - new Date(lastSynced).getTime();
        if (diff > 15 * 60 * 1000) {
          // Stale cache — sync (which loads events after syncing)
          await doSync();
        } else {
          // Fresh cache — just load events from cache
          await loadEvents();
        }
      } else {
        // No cache — sync now (which loads events after syncing)
        await doSync();
      }
    } catch (err) {
      error = String(err);
    } finally {
      loading = false;
    }

    return () => unsub();
  });
</script>

<div
  class="h-full overflow-y-auto"
  style="font-family: 'DM Sans', sans-serif; padding: 32px 40px;"
>
  <!-- Header -->
  <div style="display: flex; align-items: center; gap: 16px; margin-bottom: 28px;">
    <h1
      style="
        font-family: 'Source Serif 4', serif;
        font-size: 24px;
        font-weight: 700;
        color: var(--text);
        margin: 0;
      "
    >Calendar</h1>

    {#if lastSynced}
      <span style="font-size: 13px; color: var(--text-muted);">
        Synced {relativeTime(lastSynced)}
      </span>
    {/if}

    <button
      onclick={doSync}
      disabled={syncing}
      style="
        margin-left: auto;
        padding: 6px 16px;
        font-size: 13px;
        font-family: 'DM Sans', sans-serif;
        border-radius: 6px;
        border: 1px solid var(--border);
        background: var(--surface);
        color: var(--text);
        cursor: {syncing ? 'wait' : 'pointer'};
        opacity: {syncing ? 0.6 : 1};
      "
    >
      {syncing ? "Syncing..." : "Sync Now"}
    </button>
  </div>

  {#if !zohoConnected}
    <!-- Empty state: Zoho not connected -->
    <div
      style="
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 80px 20px;
        text-align: center;
      "
    >
      <div style="font-size: 15px; color: var(--text-muted); margin-bottom: 12px;">
        No calendar connected
      </div>
      <a
        href="#settings"
        style="
          font-size: 14px;
          color: var(--gold);
          text-decoration: none;
        "
      >Connect Zoho Calendar in Settings</a>
    </div>
  {:else if loading}
    <div style="color: var(--text-faint); font-size: 14px; padding: 40px 0; text-align: center;">
      Loading calendar events...
    </div>
  {:else if error}
    <div
      style="
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 24px;
        text-align: center;
      "
    >
      <div style="color: var(--text-muted); font-size: 14px; margin-bottom: 8px;">
        Failed to load calendar
      </div>
      <div style="color: var(--text-faint); font-size: 13px;">{error}</div>
    </div>
  {:else if upcoming.length === 0 && past.length === 0}
    <!-- Empty state: no events -->
    <div
      style="
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 80px 20px;
        text-align: center;
      "
    >
      <div style="font-size: 15px; color: var(--text-muted);">
        No calendar events found
      </div>
      <div style="font-size: 13px; color: var(--text-faint); margin-top: 8px;">
        Events from the past 30 days and next 7 days will appear here
      </div>
    </div>
  {:else}
    <!-- Upcoming meetings -->
    {#if upcoming.length > 0}
      <section style="margin-bottom: 36px;">
        <h2
          style="
            font-size: 14px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin: 0 0 12px 0;
          "
        >Upcoming</h2>

        <div style="display: flex; flex-direction: column; gap: 6px;">
          {#each upcoming as event}
            {@const matchedId = matches[event.id]}
            {@const isExpanded = expandedEventId === event.id}
            <div
              style="
                background: var(--surface);
                border: 1px solid {isExpanded ? 'var(--gold)' : 'var(--border)'};
                border-radius: 8px;
                overflow: hidden;
              "
            >
              <button
                onclick={() => toggleBriefing(event.id)}
                style="
                  width: 100%;
                  background: none;
                  border: none;
                  padding: 14px 18px;
                  display: flex;
                  align-items: center;
                  gap: 14px;
                  cursor: pointer;
                  text-align: left;
                  font-family: 'DM Sans', sans-serif;
                "
              >
                <div style="flex: 1; min-width: 0;">
                  <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 14.5px; font-weight: 500; color: var(--text);">
                      {event.title}
                    </span>
                    {#if matchedId}
                      <a
                        href="#meeting/{matchedId}"
                        title="View recording"
                        onclick={(e) => e.stopPropagation()}
                        style="
                          color: var(--gold);
                          text-decoration: none;
                          font-size: 14px;
                          flex-shrink: 0;
                        "
                      >&#x1F517;</a>
                    {/if}
                  </div>
                  <div style="font-size: 13px; color: var(--text-muted); margin-top: 3px;">
                    {formatDate(event.start)} &middot; {formatTimeRange(event.start, event.end)}
                  </div>
                  {#if event.participants.length > 0}
                    <div style="font-size: 12.5px; color: var(--text-faint); margin-top: 3px;">
                      {event.participants.map(p => p.name).join(", ")}
                    </div>
                  {/if}
                </div>
                <span
                  style="
                    color: var(--text-faint);
                    font-size: 12px;
                    flex-shrink: 0;
                    transform: rotate({isExpanded ? '180deg' : '0deg'});
                    transition: transform 0.15s ease;
                  "
                >&#9660;</span>
              </button>

              {#if isExpanded}
                <BriefingPanel
                  eventId={event.id}
                  title={event.title}
                  participants={event.participants.map(p => p.name)}
                  time={event.start}
                  eventDescription={event.description ?? undefined}
                />
              {/if}
            </div>
          {/each}
        </div>
      </section>
    {/if}

    <!-- Past events -->
    {#if past.length > 0}
      <section>
        <h2
          style="
            font-size: 14px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin: 0 0 12px 0;
          "
        >Past 30 Days</h2>

        <div style="display: flex; flex-direction: column; gap: 6px;">
          {#each past as event}
            {@const matchedId = matches[event.id]}
            <div
              style="
                background: var(--surface);
                border: 1px solid var(--border);
                border-radius: 8px;
                padding: 12px 18px;
                display: flex;
                align-items: center;
                gap: 14px;
                opacity: 0.85;
              "
            >
              <div style="flex: 1; min-width: 0;">
                <div style="display: flex; align-items: center; gap: 8px;">
                  <span style="font-size: 14px; font-weight: 500; color: var(--text);">
                    {event.title}
                  </span>
                  {#if matchedId}
                    <a
                      href="#meeting/{matchedId}"
                      title="View recording"
                      style="
                        color: var(--gold);
                        text-decoration: none;
                        font-size: 14px;
                        flex-shrink: 0;
                      "
                    >&#x1F517;</a>
                  {/if}
                </div>
                <div style="font-size: 13px; color: var(--text-muted); margin-top: 2px;">
                  {formatDate(event.start)} &middot; {formatTimeRange(event.start, event.end)}
                </div>
                {#if event.participants.length > 0}
                  <div style="font-size: 12.5px; color: var(--text-faint); margin-top: 2px;">
                    {event.participants.map(p => p.name).join(", ")}
                  </div>
                {/if}
              </div>
            </div>
          {/each}
        </div>
      </section>
    {/if}
  {/if}
</div>

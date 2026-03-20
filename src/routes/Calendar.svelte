<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { get } from "svelte/store";
  import { settings } from "../lib/stores/settings";
  import { credentials } from "../lib/stores/credentials";
  import {
    syncCalendar,
    getUpcomingMeetings,
    getCalendarMatches,
    getCalendarLastSynced,
    setAutoRecord,
    setSeriesAutoRecord,
    type CalendarEvent,
    type CalendarCache,
  } from "../lib/tauri";
  import BriefingPanel from "../lib/components/BriefingPanel.svelte";
  import ParticipantPopover from "../lib/components/ParticipantPopover.svelte";
  import { openUrl } from "@tauri-apps/plugin-opener";

  let upcoming: CalendarEvent[] = $state([]);
  let past: CalendarEvent[] = $state([]);
  let matches: Record<string, string> = $state({});
  let lastSynced: string | null = $state(null);
  let loading = $state(true);
  let syncing = $state(false);
  let error: string | null = $state(null);

  let zohoConnected = $state(false);
  let expandedEventId: string | null = $state(null);
  let windowWidth = $state(window.innerWidth);
  let narrow = $derived(windowWidth < 900);
  let popoverParticipant: { name: string; email: string | null; rect: DOMRect } | null = $state(null);
  let showAllParticipants: Record<string, boolean> = $state({});

  function handleResize() {
    windowWidth = window.innerWidth;
  }

  function openPopover(name: string, email: string | null, e: MouseEvent) {
    e.stopPropagation();
    const target = e.currentTarget as HTMLElement;
    popoverParticipant = { name, email, rect: target.getBoundingClientRect() };
  }

  function closePopover() {
    popoverParticipant = null;
  }

  function getVisibleParticipants(event: CalendarEvent): { name: string; email: string | null }[] {
    const s = get(settings);
    const userName = (s.userName || "").toLowerCase();
    const filtered = event.participants.filter(
      (p) => p.name.toLowerCase() !== userName
    );
    if (showAllParticipants[event.id]) return filtered;
    return filtered.slice(0, 4);
  }

  function getOverflowCount(event: CalendarEvent): number {
    const s = get(settings);
    const userName = (s.userName || "").toLowerCase();
    const total = event.participants.filter(
      (p) => p.name.toLowerCase() !== userName
    ).length;
    return Math.max(0, total - 4);
  }

  function openMeetingLink(url: string, e: MouseEvent) {
    e.stopPropagation();
    openUrl(url);
  }

  function toggleBriefing(eventId: string) {
    expandedEventId = expandedEventId === eventId ? null : eventId;
  }

  async function toggleAutoRecord(event: CalendarEvent) {
    const newValue = !event.auto_record;
    try {
      await setAutoRecord(event.id, newValue);
      // Update local state
      upcoming = upcoming.map(e =>
        e.id === event.id ? { ...e, auto_record: newValue } : e
      );
    } catch (err) {
      console.error("Failed to toggle auto-record:", err);
    }
  }

  async function toggleSeriesAutoRecord(event: CalendarEvent) {
    if (!event.recurring_series_id) return;
    const newValue = !event.auto_record;
    try {
      await setSeriesAutoRecord(event.recurring_series_id, newValue);
      // Update local state for all events in this series
      upcoming = upcoming.map(e =>
        e.recurring_series_id === event.recurring_series_id
          ? { ...e, auto_record: newValue }
          : e
      );
    } catch (err) {
      console.error("Failed to toggle series auto-record:", err);
    }
  }

  function platformLabel(platform: string): string {
    switch (platform) {
      case "zoom": return "Zoom";
      case "google_meet": return "Meet";
      case "teams": return "Teams";
      case "zoho_meet": return "Zoho";
      default: return platform;
    }
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
      error = null;
    } catch (err) {
      error = String(err);
      console.error("Calendar sync failed:", err);
    }
    // Always try to load cached events, even if sync failed
    await loadEvents();
    syncing = false;
  }

  async function loadEvents() {
    const s = get(settings);

    // Load upcoming from cache (doesn't hit API)
    try {
      upcoming = await getUpcomingMeetings(168);
    } catch (err) {
      console.warn("Failed to load upcoming events from cache:", err);
    }

    // Load past events (hits API — may fail independently)
    try {
      const { fetchCalendarEvents } = await import("../lib/tauri");
      const now = new Date();
      const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
      const allPast = await fetchCalendarEvents(
        thirtyDaysAgo.toISOString(),
        now.toISOString()
      );
      past = allPast
        .filter((e) => new Date(e.start).getTime() < now.getTime())
        .sort((a, b) => new Date(b.start).getTime() - new Date(a.start).getTime());
    } catch (err) {
      // Don't overwrite a sync error with a load error
      if (!error) error = String(err);
      console.warn("Failed to load past events:", err);
    }

    // Get recording matches
    try {
      if (s.recordingsFolder) {
        matches = await getCalendarMatches(s.recordingsFolder);
      }
    } catch (err) {
      console.warn("Failed to load calendar matches:", err);
    }
  }

  onDestroy(() => {
    window.removeEventListener("resize", handleResize);
  });

  onMount(async () => {
    window.addEventListener("resize", handleResize);
    // Subscribe to credentials to track Zoho status reactively.
    // Svelte store .subscribe() calls the callback synchronously with the
    // current value, so zohoConnected is set before the if-check below.
    const unsub = credentials.subscribe((creds) => {
      zohoConnected = creds.zoho.status === "connected";
    });

    try {
      // Always load cached events first so UI populates immediately
      lastSynced = await getCalendarLastSynced();
      await loadEvents();
    } catch (err) {
      console.warn("Failed to load cached events:", err);
    } finally {
      loading = false;
    }

    // Then sync in the background if connected and cache is stale
    if (zohoConnected) {
      const needsSync = !lastSynced || (Date.now() - new Date(lastSynced).getTime() > 15 * 60 * 1000);
      if (needsSync) {
        doSync();
      }
    }

    return () => unsub();
  });
</script>

<div
  class="h-full overflow-y-auto"
  style="font-family: 'DM Sans', sans-serif; padding: {narrow ? '24px 16px' : '32px 40px'}; overflow-x: hidden;"
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
  {:else}
    {#if error}
      <div
        style="
          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: 8px;
          padding: 12px 16px;
          margin-bottom: 20px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
        "
      >
        <div style="font-size: 13px; color: var(--text-muted); min-width: 0; overflow: hidden; text-overflow: ellipsis;">
          <span style="color: var(--red); font-weight: 500;">Sync error:</span> {error}
        </div>
        <button
          onclick={() => error = null}
          style="background:none;border:none;color:var(--text-faint);cursor:pointer;font-size:16px;padding:0 4px;flex-shrink:0;"
          aria-label="Dismiss"
        >&times;</button>
      </div>
    {/if}
    {#if upcoming.length === 0 && past.length === 0}
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
              <div
                style="
                  padding: 14px 18px;
                  display: flex;
                  align-items: center;
                  gap: 14px;
                "
              >
                <!-- Auto-record toggle dot -->
                <button
                  onclick={(e) => { e.stopPropagation(); toggleAutoRecord(event); }}
                  title={event.auto_record ? "Disable auto-record" : "Enable auto-record"}
                  style="
                    width: 14px;
                    height: 14px;
                    border-radius: 50%;
                    border: 2px solid {event.auto_record ? 'var(--gold)' : 'var(--text-muted)'};
                    background: {event.auto_record ? 'var(--gold)' : 'transparent'};
                    cursor: pointer;
                    flex-shrink: 0;
                    padding: 0;
                    transition: all 0.15s ease;
                  "
                ></button>

                <button
                  onclick={() => toggleBriefing(event.id)}
                  style="
                    flex: 1;
                    min-width: 0;
                    background: none;
                    border: none;
                    padding: 0;
                    cursor: pointer;
                    text-align: left;
                    font-family: 'DM Sans', sans-serif;
                  "
                >
                  <div style="display: flex; align-items: center; gap: 8px; min-width: 0;">
                    <span style="font-size: 14.5px; font-weight: 500; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0;">
                      {event.title}
                    </span>
                    {#if event.detected_platform}
                      <span
                        style="
                          font-size: 11px;
                          padding: 1px 6px;
                          border-radius: 4px;
                          background: var(--surface-hover, rgba(255,255,255,0.06));
                          color: var(--text-muted);
                          flex-shrink: 0;
                        "
                      >{platformLabel(event.detected_platform)}</span>
                    {/if}
                    {#if event.meeting_url}
                      <button
                        onclick={(e) => openMeetingLink(event.meeting_url!, e)}
                        title="Join meeting"
                        style="
                          background: none;
                          border: none;
                          padding: 0;
                          cursor: pointer;
                          font-size: 13px;
                          color: var(--blue, var(--gold));
                          flex-shrink: 0;
                        "
                      >↗</button>
                    {/if}
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
                    {#if event.recurring_series_id}
                      <span
                        role="button"
                        tabindex="0"
                        onclick={(e) => { e.stopPropagation(); toggleSeriesAutoRecord(event); }}
                        onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); toggleSeriesAutoRecord(event); } }}
                        style="
                          background: none;
                          border: none;
                          color: var(--gold);
                          font-size: 12px;
                          cursor: pointer;
                          padding: 0;
                          margin-left: 8px;
                          font-family: 'DM Sans', sans-serif;
                          text-decoration: underline;
                          text-underline-offset: 2px;
                        "
                      >{event.auto_record ? "Disable all in series" : "Enable all in series"}</span>
                    {/if}
                  </div>
                  {@const visible = getVisibleParticipants(event)}
                  {@const overflow = getOverflowCount(event)}
                  {#if visible.length > 0}
                    <div style="font-size: 12.5px; color: var(--text-faint); margin-top: 3px; display: flex; flex-wrap: wrap; gap: 0;">
                      {#each visible as participant, i}
                        <button
                          onclick={(e) => openPopover(participant.name, participant.email, e)}
                          style="
                            background: none;
                            border: none;
                            padding: 0;
                            cursor: pointer;
                            font-family: 'DM Sans', sans-serif;
                            font-size: 12.5px;
                            color: var(--text-faint);
                            text-decoration: underline;
                            text-decoration-color: transparent;
                            text-underline-offset: 2px;
                          "
                          onmouseenter={(e) => { (e.currentTarget as HTMLElement).style.textDecorationColor = 'var(--text-faint)'; }}
                          onmouseleave={(e) => { (e.currentTarget as HTMLElement).style.textDecorationColor = 'transparent'; }}
                        >{participant.name}{i < visible.length - 1 || overflow > 0 ? ',\u00A0' : ''}</button>
                      {/each}
                      {#if overflow > 0 && !showAllParticipants[event.id]}
                        <button
                          onclick={(e) => { e.stopPropagation(); showAllParticipants = { ...showAllParticipants, [event.id]: true }; }}
                          style="
                            background: none;
                            border: none;
                            padding: 0;
                            cursor: pointer;
                            font-family: 'DM Sans', sans-serif;
                            font-size: 12.5px;
                            color: var(--text-muted);
                          "
                        >+{overflow} more</button>
                      {/if}
                    </div>
                  {/if}
                </button>

                <span
                  onclick={() => toggleBriefing(event.id)}
                  role="button"
                  tabindex="0"
                  onkeydown={(e) => { if (e.key === 'Enter') toggleBriefing(event.id); }}
                  style="
                    color: var(--text-faint);
                    font-size: 12px;
                    flex-shrink: 0;
                    transform: rotate({isExpanded ? '180deg' : '0deg'});
                    transition: transform 0.15s ease;
                    cursor: pointer;
                  "
                >&#9660;</span>
              </div>

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
                <div style="display: flex; align-items: center; gap: 8px; min-width: 0;">
                  <span style="font-size: 14px; font-weight: 500; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0;">
                    {event.title}
                  </span>
                  {#if event.meeting_url}
                    <button
                      onclick={(e) => openMeetingLink(event.meeting_url!, e)}
                      title="Join meeting"
                      style="
                        background: none;
                        border: none;
                        padding: 0;
                        cursor: pointer;
                        font-size: 13px;
                        color: var(--blue, var(--gold));
                        flex-shrink: 0;
                      "
                    >↗</button>
                  {/if}
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
                {@const visible = getVisibleParticipants(event)}
                {@const overflow = getOverflowCount(event)}
                {#if visible.length > 0}
                  <div style="font-size: 12.5px; color: var(--text-faint); margin-top: 2px; display: flex; flex-wrap: wrap; gap: 0;">
                    {#each visible as participant, i}
                      <button
                        onclick={(e) => openPopover(participant.name, participant.email, e)}
                        style="
                          background: none;
                          border: none;
                          padding: 0;
                          cursor: pointer;
                          font-family: 'DM Sans', sans-serif;
                          font-size: 12.5px;
                          color: var(--text-faint);
                          text-decoration: underline;
                          text-decoration-color: transparent;
                          text-underline-offset: 2px;
                        "
                        onmouseenter={(e) => { (e.currentTarget as HTMLElement).style.textDecorationColor = 'var(--text-faint)'; }}
                        onmouseleave={(e) => { (e.currentTarget as HTMLElement).style.textDecorationColor = 'transparent'; }}
                      >{participant.name}{i < visible.length - 1 || overflow > 0 ? ',\u00A0' : ''}</button>
                    {/each}
                    {#if overflow > 0 && !showAllParticipants[event.id]}
                      <button
                        onclick={(e) => { e.stopPropagation(); showAllParticipants = { ...showAllParticipants, [event.id]: true }; }}
                        style="
                          background: none;
                          border: none;
                          padding: 0;
                          cursor: pointer;
                          font-family: 'DM Sans', sans-serif;
                          font-size: 12.5px;
                          color: var(--text-muted);
                        "
                      >+{overflow} more</button>
                    {/if}
                  </div>
                {/if}
              </div>
            </div>
          {/each}
        </div>
      </section>
    {/if}
  {/if}
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

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

  let unsub: (() => void) | undefined;

  onDestroy(() => {
    window.removeEventListener("resize", handleResize);
    unsub?.();
  });

  onMount(() => {
    window.addEventListener("resize", handleResize);

    unsub = credentials.subscribe((creds) => {
      zohoConnected = creds.zoho.status === "connected";
    });

    // Load events (no-op if already loaded), then background sync if stale
    loadCalendarEvents().then(() => {
      if (zohoConnected) {
        const state = get(calendarStore);
        const needsSync =
          !state.lastSynced ||
          Date.now() - new Date(state.lastSynced).getTime() > 15 * 60 * 1000;
        if (needsSync) {
          syncCalendarEvents();
        }
      }
    });
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
      onEventPopover={(event, rect) => {}}
      onOpenPopover={openPopover}
    />
  {:else if effectiveView === "day"}
    <DayView
      events={$calendarStore.events}
      matches={$calendarStore.matches}
      {currentDate}
      onEventPopover={(event, rect) => {}}
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

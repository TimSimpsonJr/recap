<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import type { CalendarEvent } from "../../tauri";
  import {
    isToday,
    hourToY,
    timeToY,
    totalGridHeight,
    hourHeight,
    layoutEventsForDay,
    getAllDayEvents,
    eventColor,
    EVENT_COLORS,
    formatTime,
    BUSINESS_START,
  } from "../../calendar-utils";

  interface Props {
    events: CalendarEvent[];
    matches: Record<string, string>;
    currentDate: Date;
    onEventPopover: (event: CalendarEvent, rect: DOMRect) => void;
    onOpenPopover: (name: string, email: string | null, rect: DOMRect) => void;
  }
  let { events, matches, currentDate, onEventPopover, onOpenPopover }: Props = $props();

  const hours = Array.from({ length: 24 }, (_, i) => i);

  let allDayEvents = $derived(getAllDayEvents(events, currentDate));
  let positionedEvents = $derived(layoutEventsForDay(events, currentDate));
  let showToday = $derived(isToday(currentDate));

  let nowY = $state(timeToY(new Date()));
  let gridContainer: HTMLDivElement | undefined = $state();
  let timer: ReturnType<typeof setInterval> | undefined;

  function formatHour(hour: number): string {
    if (hour === 0) return "12 AM";
    if (hour < 12) return `${hour} AM`;
    if (hour === 12) return "12 PM";
    return `${hour - 12} PM`;
  }

  function handleEventClick(event: CalendarEvent, e: MouseEvent) {
    const target = e.currentTarget as HTMLElement;
    onEventPopover(event, target.getBoundingClientRect());
  }

  onMount(() => {
    timer = setInterval(() => {
      nowY = timeToY(new Date());
    }, 60_000);

    if (gridContainer) {
      const now = new Date();
      const scrollTarget = now.getHours() < BUSINESS_START
        ? hourToY(BUSINESS_START) - 100
        : timeToY(now) - 100;
      gridContainer.scrollTop = Math.max(0, scrollTarget);
    }
  });

  onDestroy(() => {
    if (timer) clearInterval(timer);
  });
</script>

<div style="display: flex; flex-direction: column; flex: 1; min-height: 0;">
  <!-- All-day banner -->
  {#if allDayEvents.length > 0}
    <div style="display: flex; border-bottom: 1px solid var(--border); flex-shrink: 0;">
      <div style="width: 60px; flex-shrink: 0; padding: 4px 8px; font-size: 11px; color: var(--text-muted);">
        all-day
      </div>
      <div style="flex: 1; padding: 4px 6px; display: flex; flex-wrap: wrap; gap: 4px; border-left: 1px solid var(--border); min-height: 28px;">
        {#each allDayEvents as ev}
          {@const color = eventColor(ev, matches)}
          <button
            onclick={(e) => handleEventClick(ev, e)}
            style="
              background: {EVENT_COLORS[color].bg};
              border: none;
              border-left: 3px solid {EVENT_COLORS[color].border};
              color: {EVENT_COLORS[color].text};
              font-size: 11px;
              padding: 1px 6px;
              border-radius: 3px;
              cursor: pointer;
              white-space: nowrap;
              overflow: hidden;
              text-overflow: ellipsis;
              max-width: 100%;
              text-align: left;
            "
          >{ev.title}</button>
        {/each}
      </div>
    </div>
  {/if}

  <!-- Scrollable time grid -->
  <div bind:this={gridContainer} style="flex: 1; overflow-y: auto; min-height: 0;">
    <div style="display: flex; position: relative; height: {totalGridHeight()}px;">
      <!-- Time labels column -->
      <div style="width: 60px; position: relative; flex-shrink: 0;">
        {#each hours as hour}
          <div style="
            position: absolute;
            top: {hourToY(hour)}px;
            right: 8px;
            font-size: 11px;
            color: var(--text-muted);
            transform: translateY(-7px);
            white-space: nowrap;
          ">{formatHour(hour)}</div>
        {/each}
      </div>

      <!-- Single day column -->
      <div style="flex: 1; position: relative; border-left: 1px solid var(--border);">
        <!-- Hour grid lines -->
        {#each hours as hour}
          <div style="
            position: absolute;
            top: {hourToY(hour)}px;
            height: {hourHeight(hour)}px;
            width: 100%;
            border-bottom: 1px solid var(--border);
            box-sizing: border-box;
          "></div>
        {/each}

        <!-- Events -->
        {#each positionedEvents as pe}
          {@const color = eventColor(pe.event, matches)}
          <button
            onclick={(e) => handleEventClick(pe.event, e)}
            style="
              position: absolute;
              top: {pe.top}px;
              height: {pe.height}px;
              left: calc({pe.left * 100}% + 2px);
              width: calc({pe.width * 100}% - 4px);
              background: {EVENT_COLORS[color].bg};
              border: none;
              border-left: 3px solid {EVENT_COLORS[color].border};
              border-radius: 4px;
              overflow: hidden;
              cursor: pointer;
              padding: 2px 6px;
              text-align: left;
              z-index: 5;
              display: flex;
              flex-direction: column;
            "
          >
            <span style="
              font-size: 11px;
              font-weight: 600;
              color: {EVENT_COLORS[color].text};
              white-space: nowrap;
              overflow: hidden;
              text-overflow: ellipsis;
            ">{pe.event.title}</span>
            {#if pe.height > 30}
              <span style="
                font-size: 10px;
                color: var(--text-muted);
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
              ">{formatTime(pe.event.start)} – {formatTime(pe.event.end)}</span>
            {/if}
          </button>
        {/each}

        <!-- Now indicator -->
        {#if showToday}
          <div style="
            position: absolute;
            top: {nowY}px;
            left: 0;
            right: 0;
            border-top: 2px solid var(--red);
            z-index: 10;
            pointer-events: none;
          ">
            <div style="
              position: absolute;
              left: -4px;
              top: -5px;
              width: 8px;
              height: 8px;
              border-radius: 50%;
              background: var(--red);
            "></div>
          </div>
        {/if}
      </div>
    </div>
  </div>
</div>

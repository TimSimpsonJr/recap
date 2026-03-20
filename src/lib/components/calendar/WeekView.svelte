<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import type { CalendarEvent } from "../../tauri";
  import {
    weekStart,
    addDays,
    isSameDay,
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
    isBusinessHour,
    BUSINESS_START,
    HOUR_HEIGHT,
  } from "../../calendar-utils";

  interface Props {
    events: CalendarEvent[];
    matches: Record<string, string>;
    currentDate: Date;
    onEventPopover: (event: CalendarEvent, rect: DOMRect) => void;
    onOpenPopover: (name: string, email: string | null, rect: DOMRect) => void;
  }
  let { events, matches, currentDate, onEventPopover, onOpenPopover }: Props = $props();

  const DAY_ABBREVS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
  const hours = Array.from({ length: 24 }, (_, i) => i);
  const LABEL_OFFSET = 7; // px above grid line where label text sits

  let days = $derived(Array.from({ length: 7 }, (_, i) => addDays(weekStart(currentDate), i)));

  let hasAllDay = $derived(days.some((d) => getAllDayEvents(events, d).length > 0));

  let nowY = $state(timeToY(new Date()));
  let gridContainer: HTMLDivElement | undefined = $state();
  let headerEl: HTMLDivElement | undefined = $state();
  let timer: ReturnType<typeof setInterval> | undefined;

  let headerHeight = $state(53);
  let bottomEdgeHour = $state(-1);

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

  function handleScroll() {
    if (!gridContainer) return;
    const st = gridContainer.scrollTop;
    const ch = gridContainer.clientHeight;

    // Grid Y at the visible bottom edge
    const bottomGridY = st + ch - headerHeight;

    // Next hour line at or just past the visible bottom
    const nextHour = Math.ceil(bottomGridY / HOUR_HEIGHT);
    bottomEdgeHour = (nextHour >= 1 && nextHour <= 23) ? nextHour : -1;
  }

  onMount(() => {
    timer = setInterval(() => {
      nowY = timeToY(new Date());
    }, 60_000);

    if (headerEl) {
      headerHeight = headerEl.getBoundingClientRect().height;
    }

    if (gridContainer) {
      const now = new Date();
      const scrollTarget = now.getHours() < BUSINESS_START
        ? hourToY(BUSINESS_START) - 100
        : timeToY(now) - 100;
      gridContainer.scrollTop = Math.max(0, scrollTarget);
      gridContainer.addEventListener("scroll", handleScroll);
      handleScroll();
    }
  });

  onDestroy(() => {
    if (timer) clearInterval(timer);
    gridContainer?.removeEventListener("scroll", handleScroll);
  });
</script>

<div style="display: flex; flex-direction: column; flex: 1; min-height: 0; position: relative;">
  <!-- All-day banner -->
  {#if hasAllDay}
    <div style="display: flex; border-bottom: 1px solid var(--border); flex-shrink: 0;">
      <div style="width: 60px; flex-shrink: 0; padding: 4px 8px; font-size: 11px; color: var(--text-muted);">
        all-day
      </div>
      {#each days as day}
        <div style="flex: 1; padding: 4px 2px; display: flex; flex-wrap: wrap; gap: 2px; border-left: 1px solid var(--border); min-height: 28px;">
          {#each getAllDayEvents(events, day) as ev}
            {@const color = eventColor(ev, matches)}
            <button
              onclick={(e) => handleEventClick(ev, e)}
              style="
                background: {EVENT_COLORS[color].bg};
                border: none;
                border-left: 3px solid {EVENT_COLORS[color].border};
                color: {EVENT_COLORS[color].text};
                font-size: 11px;
                padding: 1px 4px;
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
      {/each}
    </div>
  {/if}

  <!-- Scrollable time grid -->
  <div bind:this={gridContainer} style="flex: 1; min-height: 0; overflow-y: auto;">
    <!-- Day headers row (sticky inside scroll container for alignment) -->
    <div bind:this={headerEl} style="display: flex; border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 20; background: var(--bg);">
      <div style="width: 60px; flex-shrink: 0;"></div>
      {#each days as day, i}
        <div style="
          flex: 1;
          text-align: center;
          padding: 8px 0 6px;
          border-left: 1px solid var(--border);
        ">
          <div style="font-size: 11px; color: var(--text-muted); letter-spacing: 0.5px;">{DAY_ABBREVS[i]}</div>
          <div style="
            font-size: 18px;
            font-weight: 600;
            margin-top: 2px;
            color: {isToday(day) ? 'var(--gold)' : 'var(--text)'};
          ">{day.getDate()}</div>
        </div>
      {/each}
    </div>

    <div style="display: flex; position: relative; height: {totalGridHeight()}px;">
      <!-- Time labels column — each hour in its own containing block for CSS sticky -->
      <div style="width: 60px; flex-shrink: 0; position: relative;">
        {#each hours as hour}
          <div style="height: {HOUR_HEIGHT}px;">
            <div style="
              position: sticky;
              top: {headerHeight + LABEL_OFFSET}px;
              bottom: 0;
              font-size: 11px;
              color: var(--text-muted);
              text-align: right;
              padding-right: 8px;
              transform: translateY(-{LABEL_OFFSET}px);
              background: var(--bg);
              width: fit-content;
              margin-left: auto;
              white-space: nowrap;
              z-index: 2;
            ">{formatHour(hour)}</div>
          </div>
        {/each}
        <!-- Midnight label at the very bottom of the grid -->
        <div style="
          position: absolute;
          top: {totalGridHeight()}px;
          right: 8px;
          font-size: 11px;
          color: var(--text-muted);
          transform: translateY(-{LABEL_OFFSET}px);
          white-space: nowrap;
        ">12 AM</div>
      </div>

      <!-- Day columns -->
      {#each days as day}
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
              background: {isBusinessHour(hour) ? 'transparent' : 'rgba(255, 255, 255, 0.03)'};
            "></div>
          {/each}

          <!-- Events -->
          {#each layoutEventsForDay(events, day) as pe}
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
                padding: 2px 4px;
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

          <!-- Now indicator (only on today's column) -->
          {#if isToday(day)}
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
      {/each}
    </div>
  </div>

  <!-- Bottom edge hour label (overlay) -->
  {#if bottomEdgeHour >= 0}
    <div style="
      position: absolute;
      bottom: 2px;
      left: 0;
      width: 52px;
      font-size: 11px;
      color: var(--text-muted);
      text-align: right;
      padding-right: 8px;
      background: var(--bg);
      z-index: 25;
      pointer-events: none;
    ">{formatHour(bottomEdgeHour)}</div>
  {/if}
</div>

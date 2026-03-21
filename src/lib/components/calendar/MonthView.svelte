<script lang="ts">
  import type { CalendarEvent } from "../../tauri";
  import {
    monthStart,
    monthEnd,
    weekStart,
    addDays,
    isSameDay,
    isToday,
    getEventsForDay,
    eventColor,
    EVENT_COLORS,
    formatTime,
  } from "../../calendar-utils";

  interface Props {
    events: CalendarEvent[];
    matches: Record<string, string>;
    currentDate: Date;
    onDayClick: (date: Date) => void;
  }
  let { events, matches, currentDate, onDayClick }: Props = $props();

  const WEEKDAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
  const MAX_CHIPS = 3;

  let gridDates = $derived.by(() => {
    const first = monthStart(currentDate);
    const last = monthEnd(currentDate);
    const gridStart = weekStart(first);
    const dates: Date[] = [];
    let d = new Date(gridStart);
    while (d <= last || d.getDay() !== 0) {
      dates.push(new Date(d));
      d = addDays(d, 1);
    }
    return dates;
  });

  function isOtherMonth(date: Date): boolean {
    return date.getMonth() !== currentDate.getMonth();
  }
</script>

<!-- Weekday header -->
<div style="display: grid; grid-template-columns: repeat(7, 1fr); border-bottom: 1px solid var(--border);">
  {#each WEEKDAYS as day}
    <span style="font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; padding: 8px 10px; text-align: right;">
      {day}
    </span>
  {/each}
</div>

<!-- Month grid -->
<div style="display: grid; grid-template-columns: repeat(7, 1fr);">
  {#each gridDates as date}
    {@const dayEvents = getEventsForDay(events, date)}
    {@const visibleEvents = dayEvents.slice(0, MAX_CHIPS)}
    {@const overflow = dayEvents.length - MAX_CHIPS}
    {@const today = isToday(date)}
    {@const otherMonth = isOtherMonth(date)}
    <button
      type="button"
      onclick={() => onDayClick(date)}
      style="
        border: 1px solid var(--border);
        border-top: none;
        border-left: {date.getDay() === 0 ? '1px solid var(--border)' : 'none'};
        min-height: 100px;
        padding: 4px;
        cursor: pointer;
        position: relative;
        overflow: hidden;
        background: {today ? 'var(--surface)' : 'transparent'};
        opacity: {otherMonth ? '0.35' : '1'};
        text-align: left;
        display: flex;
        flex-direction: column;
        font-family: inherit;
      "
    >
      <!-- Day number -->
      <div style="text-align: right; padding: 2px 4px; margin-bottom: 2px;">
        {#if today}
          <span style="
            display: inline-block;
            background: var(--gold);
            color: var(--bg);
            font-weight: 700;
            font-size: 12px;
            border-radius: 50%;
            width: 22px;
            height: 22px;
            line-height: 22px;
            text-align: center;
          ">{date.getDate()}</span>
        {:else}
          <span style="font-size: 13px; color: var(--text-secondary);">{date.getDate()}</span>
        {/if}
      </div>

      <!-- Event chips -->
      {#each visibleEvents as event}
        {@const color = eventColor(event, matches)}
        {@const colors = EVENT_COLORS[color]}
        <div style="
          font-size: 11px;
          padding: 2px 5px;
          border-radius: 3px;
          margin-bottom: 2px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          line-height: 1.4;
          background: {colors.bg};
          color: {colors.text};
          border-left: 3px solid {colors.border};
        ">
          {event.title}
        </div>
      {/each}

      <!-- Overflow indicator -->
      {#if overflow > 0}
        <div style="font-size: 10px; color: var(--text-muted); padding: 1px 5px;">
          +{overflow} more
        </div>
      {/if}
    </button>
  {/each}
</div>

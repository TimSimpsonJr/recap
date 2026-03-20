<script lang="ts">
  import type { CalendarEvent } from "../../tauri";
  interface Props {
    events: CalendarEvent[];
    matches: Record<string, string>;
    currentDate: Date;
    onDayClick: (date: Date) => void;
  }
  let { events, matches, currentDate, onDayClick }: Props = $props();
</script>
<div style="color: var(--text-muted); padding: 40px; text-align: center;">Month view placeholder</div>

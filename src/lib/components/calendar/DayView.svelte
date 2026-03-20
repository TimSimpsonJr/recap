<script lang="ts">
  import type { CalendarEvent } from "../../tauri";
  interface Props {
    events: CalendarEvent[];
    matches: Record<string, string>;
    currentDate: Date;
    onEventPopover: (event: CalendarEvent, rect: DOMRect) => void;
    onOpenPopover: (name: string, email: string | null, rect: DOMRect) => void;
  }
  let { events, matches, currentDate, onEventPopover, onOpenPopover }: Props = $props();
</script>
<div style="color: var(--text-muted); padding: 40px; text-align: center;">Day view placeholder</div>

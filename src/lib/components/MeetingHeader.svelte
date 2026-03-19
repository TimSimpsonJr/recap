<script lang="ts">
  import type { MeetingSummary } from "../tauri";

  interface Props {
    meeting: MeetingSummary;
    showBack?: boolean;
  }

  let { meeting, showBack = true }: Props = $props();

  let dateStr = $derived(
    new Date(meeting.date).toLocaleDateString("en-US", {
      weekday: "long",
      month: "long",
      day: "numeric",
      year: "numeric",
    })
  );

  let durationText = $derived.by(() => {
    if (!meeting.duration_seconds) return null;
    const m = Math.round(meeting.duration_seconds / 60);
    if (m < 60) return `${m} min`;
    const h = Math.floor(m / 60);
    const rem = m % 60;
    return rem > 0 ? `${h}h ${rem}m` : `${h}h`;
  });
</script>

<div>
  {#if showBack}
    <a
      href="#dashboard"
      style="
        font-family: 'DM Sans', sans-serif;
        font-size: 14px;
        color: var(--gold);
        text-decoration: none;
        display: inline-block;
        margin-bottom: 12px;
      "
      onmouseenter={(e) => { (e.currentTarget as HTMLElement).style.color = 'var(--gold-hover)'; }}
      onmouseleave={(e) => { (e.currentTarget as HTMLElement).style.color = 'var(--gold)'; }}
    >
      &larr; Back
    </a>
  {/if}

  <h1
    style="
      font-family: 'Source Serif 4', serif;
      font-size: 24px;
      font-weight: 700;
      color: var(--text);
      margin: 0 0 8px 0;
    "
  >
    {meeting.title}
  </h1>

  <div
    class="flex items-center flex-wrap"
    style="
      font-family: 'DM Sans', sans-serif;
      font-size: 13.5px;
      color: var(--text-muted);
      gap: 0;
    "
  >
    <span>{dateStr}</span>
    {#if meeting.platform}
      <span style="color: var(--border); margin: 0 6px;">&middot;</span>
      <span>{meeting.platform}</span>
    {/if}
    {#if durationText}
      <span style="color: var(--border); margin: 0 6px;">&middot;</span>
      <span>{durationText}</span>
    {/if}
    {#if meeting.participants.length}
      <span style="color: var(--border); margin: 0 6px;">&middot;</span>
      <span>{meeting.participants.join(", ")}</span>
    {/if}
  </div>
</div>

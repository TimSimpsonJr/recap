<script lang="ts">
  import type { MeetingSummary } from "../tauri";

  interface Props {
    meeting: MeetingSummary;
  }

  let { meeting }: Props = $props();

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
  <a
    href="#dashboard"
    style="
      font-family: 'DM Sans', sans-serif;
      font-size: 14px;
      color: #A8A078;
      text-decoration: none;
      display: inline-block;
      margin-bottom: 12px;
    "
    onmouseenter={(e) => { (e.currentTarget as HTMLElement).style.color = '#B8B088'; }}
    onmouseleave={(e) => { (e.currentTarget as HTMLElement).style.color = '#A8A078'; }}
  >
    &larr; Back
  </a>

  <h1
    style="
      font-family: 'Source Serif 4', serif;
      font-size: 24px;
      font-weight: 700;
      color: #D8D5CE;
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
      color: #78756E;
      gap: 0;
    "
  >
    <span>{dateStr}</span>
    {#if meeting.platform}
      <span style="color: #464440; margin: 0 6px;">&middot;</span>
      <span>{meeting.platform}</span>
    {/if}
    {#if durationText}
      <span style="color: #464440; margin: 0 6px;">&middot;</span>
      <span>{durationText}</span>
    {/if}
    {#if meeting.participants.length}
      <span style="color: #464440; margin: 0 6px;">&middot;</span>
      <span>{meeting.participants.join(", ")}</span>
    {/if}
  </div>
</div>

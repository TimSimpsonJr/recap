<script lang="ts">
  import type { MeetingSummary } from "../tauri";
  import PipelineStatusBadge from "./PipelineStatusBadge.svelte";

  interface Props {
    meeting: MeetingSummary;
    isSelected?: boolean;
    onSelect?: (id: string) => void;
  }

  let { meeting, isSelected = false, onSelect }: Props = $props();

  let durationText = $derived.by(() => {
    if (!meeting.duration_seconds) return null;
    const m = Math.round(meeting.duration_seconds / 60);
    if (m < 60) return `${m}m`;
    const h = Math.floor(m / 60);
    const rem = m % 60;
    return rem > 0 ? `${h}h ${rem}m` : `${h}h`;
  });

  let participantText = $derived.by(() => {
    if (!meeting.participants.length) return null;
    if (meeting.participants.length <= 2) return meeting.participants.join(", ");
    return `${meeting.participants[0]} +${meeting.participants.length - 1}`;
  });

  function handleClick(e: MouseEvent) {
    if (onSelect) {
      e.preventDefault();
      onSelect(meeting.id);
    }
  }
</script>

<a
  href="#meeting/{meeting.id}"
  class="block"
  onclick={handleClick}
  style="
    padding: 14px 16px;
    border-radius: 8px;
    background: {isSelected ? '#2B2B28' : '#242422'};
    text-decoration: none;
    transition: background 120ms ease, box-shadow 120ms ease;
    {isSelected ? 'box-shadow: inset 2px 0 0 #A8A078;' : ''}
  "
  onmouseenter={(e) => {
    if (!isSelected) {
      const el = e.currentTarget as HTMLElement;
      el.style.background = '#2B2B28';
      el.style.boxShadow = '0 1px 8px rgba(0,0,0,0.25)';
    }
  }}
  onmouseleave={(e) => {
    const el = e.currentTarget as HTMLElement;
    if (isSelected) {
      el.style.background = '#2B2B28';
      el.style.boxShadow = 'inset 2px 0 0 #A8A078';
    } else {
      el.style.background = '#242422';
      el.style.boxShadow = 'none';
    }
  }}
>
  <div class="flex items-start justify-between gap-3">
    <div class="min-w-0 flex-1">
      <h3
        style="
          font-family: 'Source Serif 4', serif;
          font-size: 16px;
          font-weight: 600;
          color: #D8D5CE;
          margin: 0 0 4px 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        "
      >
        {meeting.title}
      </h3>
      <div
        class="flex items-center gap-0 flex-wrap"
        style="
          font-family: 'DM Sans', sans-serif;
          font-size: 13.5px;
          color: #78756E;
        "
      >
        {#if meeting.platform}
          <span>{meeting.platform}</span>
        {/if}
        {#if durationText}
          <span style="color: #464440; margin: 0 6px;">&middot;</span>
          <span>{durationText}</span>
        {/if}
        {#if participantText}
          <span style="color: #464440; margin: 0 6px;">&middot;</span>
          <span>{participantText}</span>
        {/if}
      </div>
    </div>
    <PipelineStatusBadge status={meeting.pipeline_status} />
  </div>
</a>

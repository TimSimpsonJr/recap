<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { get } from "svelte/store";
  import { settings } from "../../stores/settings";
  import {
    toggleEventAutoRecord,
    toggleSeriesAutoRecord,
  } from "../../stores/calendar";
  import { openUrl } from "@tauri-apps/plugin-opener";
  import { platformLabel, formatTimeRange } from "../../calendar-utils";
  import type { CalendarEvent } from "../../tauri";

  interface Props {
    event: CalendarEvent;
    matchedId: string | null;
    anchorRect: DOMRect;
    onClose: () => void;
    onOpenSidePanel: () => void;
    onOpenPopover: (name: string, email: string | null, rect: DOMRect) => void;
  }

  let { event, matchedId, anchorRect, onClose, onOpenSidePanel, onOpenPopover }: Props = $props();

  let popoverEl: HTMLDivElement | undefined = $state();
  let top = $state(0);
  let left = $state(0);

  function updatePosition() {
    if (!popoverEl) return;
    const rect = popoverEl.getBoundingClientRect();
    const viewportH = window.innerHeight;
    const viewportW = window.innerWidth;

    let t = anchorRect.bottom + 6;
    let l = anchorRect.left;

    // Flip above if not enough space below
    if (t + rect.height > viewportH - 16) {
      t = anchorRect.top - rect.height - 6;
    }
    // Clamp horizontally
    if (l + rect.width > viewportW - 16) {
      l = viewportW - rect.width - 16;
    }
    if (l < 16) l = 16;

    top = t;
    left = l;
  }

  // Participants filtered to exclude current user
  let visibleParticipants = $derived.by(() => {
    const userName = get(settings).userName?.toLowerCase() ?? "";
    const filtered = event.participants.filter(
      (p) => p.name.toLowerCase() !== userName
    );
    return filtered;
  });

  let shownParticipants = $derived(visibleParticipants.slice(0, 4));
  let overflowCount = $derived(
    Math.max(0, visibleParticipants.length - 4)
  );

  // Dismiss handlers
  let handleKey: ((e: KeyboardEvent) => void) | null = null;
  let handleClick: ((e: MouseEvent) => void) | null = null;
  let clickTimeout: ReturnType<typeof setTimeout> | null = null;

  onMount(() => {
    requestAnimationFrame(updatePosition);

    handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);

    handleClick = (e: MouseEvent) => {
      if (popoverEl && !popoverEl.contains(e.target as Node)) {
        onClose();
      }
    };
    clickTimeout = setTimeout(() => {
      if (handleClick) window.addEventListener("click", handleClick);
    }, 0);
  });

  onDestroy(() => {
    if (handleKey) window.removeEventListener("keydown", handleKey);
    if (handleClick) window.removeEventListener("click", handleClick);
    if (clickTimeout) clearTimeout(clickTimeout);
  });

  function handleParticipantClick(
    p: { name: string; email: string | null },
    e: MouseEvent
  ) {
    const btn = e.currentTarget as HTMLElement;
    const rect = btn.getBoundingClientRect();
    onOpenPopover(p.name, p.email, rect);
  }
</script>

<div
  bind:this={popoverEl}
  style="
    position: fixed;
    top: {top}px;
    left: {left}px;
    min-width: 280px;
    max-width: 360px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 18px;
    z-index: 1000;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
    font-family: 'DM Sans', sans-serif;
  "
>
  <!-- Title -->
  <div style="font-size: 15px; font-weight: 700; color: var(--text);">
    {event.title}
  </div>

  <!-- Time range -->
  <div style="font-size: 13px; color: var(--text-muted); margin-top: 2px;">
    {formatTimeRange(event.start, event.end)}
  </div>

  <!-- Platform badge -->
  {#if event.detected_platform}
    <span
      style="
        display: inline-block;
        margin-top: 6px;
        padding: 2px 8px;
        font-size: 11px;
        font-weight: 600;
        color: var(--text-muted);
        background: var(--surface-hover, rgba(255,255,255,0.06));
        border: 1px solid var(--border);
        border-radius: 10px;
      "
    >{platformLabel(event.detected_platform)}</span>
  {/if}

  <!-- Divider -->
  <div style="border-top: 1px solid var(--border); margin: 10px 0;"></div>

  <!-- Action row -->
  <div style="display: flex; align-items: center; gap: 10px;">
    <!-- Auto-record toggle -->
    <button
      onclick={() => toggleEventAutoRecord(event.id)}
      title={event.auto_record ? "Disable auto-record" : "Enable auto-record"}
      style="
        width: 14px;
        height: 14px;
        border-radius: 50%;
        border: 2px solid {event.auto_record ? 'var(--gold)' : 'var(--text-muted)'};
        background: {event.auto_record ? 'var(--gold)' : 'transparent'};
        cursor: pointer;
        padding: 0;
        flex-shrink: 0;
      "
    ></button>

    <!-- Series toggle link -->
    {#if event.recurring_series_id}
      <button
        onclick={() => toggleSeriesAutoRecord(event.recurring_series_id!)}
        style="
          background: none;
          border: none;
          padding: 0;
          font-size: 11px;
          color: var(--text-muted);
          cursor: pointer;
          font-family: 'DM Sans', sans-serif;
          text-decoration: underline;
          text-underline-offset: 2px;
          text-decoration-color: var(--border);
        "
      >{event.auto_record ? "Disable" : "Enable"} all in series</button>
    {/if}

    <!-- Spacer -->
    <div style="flex: 1;"></div>

    <!-- Meeting join link -->
    {#if event.meeting_url}
      <button
        onclick={() => openUrl(event.meeting_url!)}
        title="Join meeting"
        style="
          background: none;
          border: none;
          padding: 0;
          font-size: 15px;
          cursor: pointer;
          color: var(--text-muted);
        "
      >&#8599;</button>
    {/if}

    <!-- Recording link -->
    {#if matchedId}
      <a
        href="#meeting/{matchedId}"
        title="View recording"
        style="
          font-size: 15px;
          color: var(--gold);
          text-decoration: none;
        "
      >&#128279;</a>
    {/if}
  </div>

  <!-- Participants -->
  {#if shownParticipants.length > 0}
    <div style="margin-top: 10px; display: flex; flex-wrap: wrap; gap: 4px;">
      {#each shownParticipants as p}
        <button
          onclick={(e) => handleParticipantClick(p, e)}
          style="
            background: none;
            border: none;
            padding: 2px 0;
            font-size: 13px;
            color: var(--text);
            cursor: pointer;
            font-family: 'DM Sans', sans-serif;
            text-decoration: underline;
            text-decoration-color: var(--border);
            text-underline-offset: 2px;
          "
        >{p.name}</button>
      {/each}
      {#if overflowCount > 0}
        <span style="font-size: 12px; color: var(--text-muted); align-self: center;">
          +{overflowCount} more
        </span>
      {/if}
    </div>
  {/if}

  <!-- See details -->
  <button
    onclick={onOpenSidePanel}
    style="
      display: block;
      margin-top: 10px;
      background: none;
      border: none;
      padding: 0;
      font-size: 13px;
      color: var(--gold);
      cursor: pointer;
      font-family: 'DM Sans', sans-serif;
    "
  >See details &#8594;</button>
</div>
